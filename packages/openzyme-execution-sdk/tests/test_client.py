from __future__ import annotations

from collections.abc import Callable
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import threading
import time

import pytest

from openzyme_execution_sdk import client


def test_control_socket_frame_limit_is_fixed_at_four_mibibytes() -> None:
    assert client.CONTROL_SOCKET_FRAME_MAX_BYTES == 4 * 1024 * 1024


@contextmanager
def _fake_control_server(
    tmp_path: Path,
    responder: Callable[[socket.socket, bytes], None],
):
    socket_path = tmp_path / "fake-control.sock"
    ready = threading.Event()
    requests: list[bytes] = []
    errors: list[BaseException] = []

    def serve() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
                server.bind(str(socket_path))
                server.listen(1)
                ready.set()
                conn, _ = server.accept()
                with conn:
                    payload = bytearray()
                    while b"\n" not in payload:
                        chunk = conn.recv(4096)
                        if not chunk:
                            break
                        payload.extend(chunk)
                    frame, delimiter, trailing = bytes(payload).partition(b"\n")
                    assert delimiter == b"\n"
                    assert not trailing.strip()
                    requests.append(frame)
                    responder(conn, frame)
        except BaseException as exc:  # pragma: no cover - asserted after join
            errors.append(exc)
            ready.set()

    worker = threading.Thread(target=serve, name="fake-control-server")
    worker.start()
    assert ready.wait(timeout=2.0)
    try:
        yield str(socket_path), requests
    finally:
        worker.join(timeout=5.0)
    assert worker.is_alive() is False
    assert errors == []


def test_control_client_transports_historical_r15_large_frame(
    tmp_path: Path,
) -> None:
    # Preserve the exact r15 framing-regression payload; this is not the corrected
    # r25 HMMER accession-count oracle.
    accessions = [f"A0A{i:07d}" for i in range(37_722)]
    response_padding = "result-" * 20_000

    def respond(conn: socket.socket, frame: bytes) -> None:
        request = json.loads(frame.decode("utf-8"))
        assert len(request["params"]["params"]["accessions"]) == 37_722
        response = json.dumps(
            {
                "jsonrpc": "2.0",
                "id": request["id"],
                "result": {
                    "accession_count": 37_722,
                    "padding": response_padding,
                },
            },
            sort_keys=True,
        ).encode("utf-8") + b"\n"
        assert len(response) > 64 * 1024
        for offset in range(0, len(response), 4093):
            conn.sendall(response[offset : offset + 4093])

    with _fake_control_server(tmp_path, respond) as (socket_path, requests):
        result = client.ControlClient(socket_path=socket_path).call(
            "s10.controlled_operation",
            {
                "schema_version": "s12.adapter_envelope.v1",
                "sdk_module": "bio",
                "function_name": "uniprot_fetch_entries",
                "route_policy_id": "bio.uniprot_fetch_entries.provider:v1",
                "params": {"accessions": accessions},
                "expected_outputs": {"kind": "uniprot_records"},
            },
        )

    assert len(requests) == 1
    assert 64 * 1024 < len(requests[0]) < client.CONTROL_SOCKET_FRAME_MAX_BYTES
    assert result == {"accession_count": 37_722, "padding": response_padding}


def test_control_client_rejects_oversized_request_before_connect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client, "CONTROL_SOCKET_FRAME_MAX_BYTES", 1024)

    with pytest.raises(client.PipelineSdkError) as error:
        client.ControlClient(socket_path=str(tmp_path / "absent.sock")).call(
            "s09.transport_smoke",
            {"padding": "x" * 2048},
        )

    assert error.value.error_code == "sandbox_transport_request_too_large"
    assert error.value.stage == "control_socket_request"
    assert error.value.retryable is False
    assert error.value.details["max_bytes"] == 1024
    assert error.value.details["size_bytes"] > 1024


def test_control_client_preserves_runtime_write_fence_contract(
    tmp_path: Path,
) -> None:
    def respond(conn: socket.socket, frame: bytes) -> None:
        request = json.loads(frame.decode("utf-8"))
        conn.sendall(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {
                        "message": (
                            "session runtime write was rejected because its lease "
                            "fence is no longer authoritative"
                        ),
                        "error_code": "runtime_write_fenced",
                        "stage": "session_runtime_write_fence",
                        "hint": "Fail closed for the current runtime attempt.",
                        "details": {
                            "boundary": "session_runtime_write_fence",
                            "disposition": "fail_closed",
                        },
                        "retryable": False,
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

    with _fake_control_server(tmp_path, respond) as (socket_path, _requests):
        with pytest.raises(client.PipelineSdkError) as error:
            client.ControlClient(socket_path=socket_path).call(
                "s09.transport_smoke",
                {},
            )

    assert error.value.error_code == "runtime_write_fenced"
    assert error.value.stage == "session_runtime_write_fence"
    assert error.value.retryable is False
    assert error.value.hint == "Fail closed for the current runtime attempt."
    assert error.value.details == {
        "boundary": "session_runtime_write_fence",
        "disposition": "fail_closed",
    }


def test_control_client_does_not_truthiness_coerce_retryable(
    tmp_path: Path,
) -> None:
    def respond(conn: socket.socket, frame: bytes) -> None:
        request = json.loads(frame.decode("utf-8"))
        conn.sendall(
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request["id"],
                    "error": {
                        "message": "adapter returned a malformed retryability field",
                        "error_code": "adapter_execution_failed",
                        "stage": "adapter_execution",
                        "retryable": "false",
                    },
                },
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

    with _fake_control_server(tmp_path, respond) as (socket_path, _requests):
        with pytest.raises(client.PipelineSdkError) as error:
            client.ControlClient(socket_path=socket_path).call(
                "s09.transport_smoke",
                {},
            )

    assert error.value.error_code == "adapter_execution_failed"
    assert error.value.stage == "adapter_execution"
    assert error.value.retryable is None


def test_control_client_rejects_recursive_request_before_connect(
    tmp_path: Path,
) -> None:
    recursive: dict[str, object] = {}
    recursive["self"] = recursive

    with pytest.raises(client.PipelineSdkError) as error:
        client.ControlClient(socket_path=str(tmp_path / "absent.sock")).call(
            "s09.transport_smoke",
            recursive,
        )

    assert error.value.error_code == "sandbox_transport_request_invalid"
    assert error.value.stage == "control_socket_request"
    assert error.value.retryable is False


def test_control_client_rejects_non_finite_request_before_connect(
    tmp_path: Path,
) -> None:
    with pytest.raises(client.PipelineSdkError) as error:
        client.ControlClient(socket_path=str(tmp_path / "absent.sock")).call(
            "s09.transport_smoke",
            {"value": float("nan")},
        )

    assert error.value.error_code == "sandbox_transport_request_invalid"
    assert error.value.stage == "control_socket_request"
    assert error.value.retryable is False


def test_control_client_rejects_oversized_response(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client, "CONTROL_SOCKET_FRAME_MAX_BYTES", 1024)

    def respond(conn: socket.socket, _frame: bytes) -> None:
        conn.sendall(b"x" * 1025)

    with _fake_control_server(tmp_path, respond) as (socket_path, _requests):
        with pytest.raises(client.PipelineSdkError) as error:
            client.ControlClient(socket_path=socket_path).call(
                "s09.transport_smoke",
                {},
            )

    assert error.value.error_code == "sandbox_transport_response_too_large"
    assert error.value.stage == "control_socket_response"
    assert error.value.retryable is False


def test_control_client_rejects_response_without_newline(
    tmp_path: Path,
) -> None:
    def respond(conn: socket.socket, frame: bytes) -> None:
        request = json.loads(frame.decode("utf-8"))
        conn.sendall(
            json.dumps(
                {"jsonrpc": "2.0", "id": request["id"], "result": {}},
                sort_keys=True,
            ).encode("utf-8")
        )

    with _fake_control_server(tmp_path, respond) as (socket_path, _requests):
        with pytest.raises(client.PipelineSdkError) as error:
            client.ControlClient(socket_path=socket_path).call(
                "s09.transport_smoke",
                {},
            )

    assert error.value.error_code == "sandbox_transport_response_invalid"
    assert error.value.stage == "control_socket_response"


def test_control_client_times_out_on_partial_response_that_remains_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client, "CONTROL_SOCKET_IO_TIMEOUT_SECONDS", 0.05)

    def respond(conn: socket.socket, _frame: bytes) -> None:
        conn.sendall(b'{"jsonrpc":"2.0"')
        assert conn.recv(1) == b""

    with _fake_control_server(tmp_path, respond) as (socket_path, _requests):
        with pytest.raises(client.PipelineSdkError) as error:
            client.ControlClient(socket_path=socket_path).call(
                "s09.transport_smoke",
                {},
            )

    assert error.value.error_code == "sandbox_transport_response_timeout"
    assert error.value.stage == "control_socket_response"
    assert error.value.retryable is False


def test_control_client_allows_delayed_first_response_byte(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(client, "CONTROL_SOCKET_IO_TIMEOUT_SECONDS", 0.05)

    def respond(conn: socket.socket, frame: bytes) -> None:
        request = json.loads(frame.decode("utf-8"))
        time.sleep(0.1)
        conn.sendall(
            json.dumps(
                {"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}},
                sort_keys=True,
            ).encode("utf-8")
            + b"\n"
        )

    with _fake_control_server(tmp_path, respond) as (socket_path, _requests):
        result = client.ControlClient(socket_path=socket_path).call(
            "s10.controlled_operation",
            {},
        )

    assert result == {"ok": True}


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff",
        b"{",
        b'{"jsonrpc":"2.0","id":' + b"9" * 5_000 + b',"result":{}}',
        b'{"jsonrpc":"2.0","id":' + b"[" * 20_000 + b"]" * 20_000 + b',"result":{}}',
        b"[]",
        json.dumps({"jsonrpc": "2.0", "id": "wrong", "result": {}}).encode("utf-8"),
        json.dumps({"jsonrpc": "1.0", "id": "rpc_expected", "result": {}}).encode("utf-8"),
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "rpc_expected",
                "result": {},
                "error": {},
            }
        ).encode("utf-8"),
        json.dumps({"jsonrpc": "2.0", "id": "rpc_expected"}).encode("utf-8"),
        b'{"jsonrpc":"2.0","id":"rpc_expected","result":{"value":NaN}}',
        b'{"jsonrpc":"2.0","id":"rpc_expected","result":{},"result":{}}',
    ],
)
def test_control_client_rejects_invalid_response_shape(payload: bytes) -> None:
    with pytest.raises(client.PipelineSdkError) as error:
        client.ControlClient._decode_response_frame(
            payload,
            request_id="rpc_expected",
        )

    assert error.value.error_code == "sandbox_transport_response_invalid"
    assert error.value.stage == "control_socket_response"
    assert error.value.retryable is False
