from __future__ import annotations

from contextlib import contextmanager
import hashlib
import json
from dataclasses import replace
from pathlib import Path
import socket
import subprocess
import tempfile
import threading
import time

import pytest

from openzyme_core import ArtifactBoundaryService
from openzyme_core import CoreRepositories
from openzyme_core import ContinuationDeliveryWorker
from openzyme_core import ControlledOperationExecutionTransitionService
from openzyme_core import ControlledOperationExecutionWorker
from openzyme_core import DurableRouteMaterializedResult
from openzyme_core import DurableRouteObservation
from openzyme_core import DurableRouteObservationKind
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SandboxRuntimeError
from openzyme_core import SandboxRuntimeService
from openzyme_core import SandboxWorkspaceService
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import RuntimeWriteFencingError
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import controlled_operation_artifact_set_digest
from openzyme_core import sandbox_image_record
from openzyme_core.sandbox_runtime import S12_ROUTE_POLICIES
from openzyme_core.sandbox_runtime import CONTROL_SOCKET_FRAME_MAX_BYTES
from openzyme_core.sandbox_runtime import EXEC_MAX_TIMEOUT_SECONDS
from openzyme_core.sandbox_runtime import EXEC_POLICY_VERSION
from openzyme_core.sandbox_runtime import _sanitize_toolchain_runtime_identity
from openzyme_core.sandbox_runtime import _structured_adapter_message
from openzyme_core.sandbox_runtime import _tool_success
from openzyme_core.sandbox_runtime import _ControlSocketServer
from openzyme_core.sandbox_runtime import register_sandbox_runtime_tools
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_runtime import PodmanContainerLease
from openzyme_runtime import ControlledOperationOwnerPolicy
from openzyme_runtime import ReliabilityRefactorSettings
from openzyme_runtime import ReliabilityShadowObserver
from openzyme_runtime import ShadowObservabilityMode


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:", check_same_thread=False)
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _digest_text(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _control_socket_server(tmp_path: Path, *, name: str) -> _ControlSocketServer:
    return _ControlSocketServer(
        socket_path=tmp_path / f"{name}.sock",
        repositories=_build_repositories(),
        session_id=f"sess_{name}",
        sandbox_workspace_id=f"sw_{name}",
        sandbox_run_id=f"srun_{name}",
        agent_id="agent:executor",
        source_snapshot_artifact_id="art_source",
        source_tree_digest=_digest_text("source"),
    )


def _send_control_socket_bytes(
    server: _ControlSocketServer,
    payload: bytes,
    *,
    chunk_bytes: int | None = None,
    shutdown_write: bool = False,
) -> dict[str, object]:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(5.0)
        client.connect(str(server.socket_path))
        if chunk_bytes is None:
            client.sendall(payload)
        else:
            for offset in range(0, len(payload), chunk_bytes):
                client.sendall(payload[offset : offset + chunk_bytes])
        if shutdown_write:
            client.shutdown(socket.SHUT_WR)
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(64 * 1024)
            if not chunk:
                break
            response.extend(chunk)
    frame, delimiter, trailing = bytes(response).partition(b"\n")
    assert delimiter == b"\n"
    assert not trailing.strip()
    decoded = json.loads(frame.decode("utf-8"))
    assert isinstance(decoded, dict)
    return decoded


def test_sandbox_exec_v2_timeout_bound_is_finite_and_authoritative(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    service = SandboxRuntimeService(
        repositories,
        workspace_root=tmp_path / "workspaces",
        log_root=tmp_path / "logs",
    )

    assert EXEC_MAX_TIMEOUT_SECONDS == 3_600
    assert EXEC_POLICY_VERSION == "s09.exec_policy.v2"
    assert CONTROL_SOCKET_FRAME_MAX_BYTES == 4 * 1024 * 1024
    assert service._bounded_timeout(EXEC_MAX_TIMEOUT_SECONDS) == 3_600
    with pytest.raises(SandboxRuntimeError) as error:
        service._bounded_timeout(EXEC_MAX_TIMEOUT_SECONDS + 1)

    assert error.value.error_code == "sandbox_resource_exceeded"
    assert "between 1 and 3600" in str(error.value)


def test_structured_adapter_message_rejects_private_machine_fields() -> None:
    message = _structured_adapter_message(
        {
            "code": "/home/operator/private-code",
            "stage": "sk-abcdefghijklmnop",
            "summary": "failed at /scratch/slurm/job-001/stderr",
            "details_ref": "storage://private/adapter.log",
            "safe_diagnostics": {"host_path": "/custom/private"},
        },
        default_code="adapter_result_unsuccessful",
    )

    assert message == {
        "code": "adapter_result_unsuccessful",
        "stage": "adapter_result",
        "retryable": False,
        "summary": "failed at [redacted-host-path]",
        "details_ref": "[redacted-private-locator]",
        "safe_diagnostics": {},
    }


def test_control_socket_error_envelope_rejects_private_machine_code(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class PrivateCodeError(RuntimeError):
        error_code = "sk-abcdefghijklmnop"
        hint = "inspect /tmp/private-hint"
        details = {"host_path": "/custom/private"}
        retryable = "false"

    def fail_transport(
        _server: _ControlSocketServer,
        _request: dict[str, object],
        _params: dict[str, object],
    ) -> dict[str, object]:
        raise PrivateCodeError("failed at /home/operator/private.sock")

    monkeypatch.setattr(
        _ControlSocketServer,
        "_handle_transport_smoke",
        fail_transport,
    )
    server = _ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        repositories=_build_repositories(),
        session_id="sess_001",
        sandbox_workspace_id="sw_001",
        sandbox_run_id="srun_001",
        agent_id="agent:executor",
        source_snapshot_artifact_id="art_source",
        source_tree_digest=_digest_text("source"),
    )

    response = server._handle(
        {"jsonrpc": "2.0", "id": "call_1", "method": "s09.transport_smoke"}
    )
    serialized = json.dumps(response, sort_keys=True)

    assert response["error"]["error_code"] == "sandbox_transport_error"
    assert response["error"]["retryable"] is None
    assert "/home/operator" not in serialized
    assert "/tmp/private-hint" not in serialized
    assert "sk-abcdefghijklmnop" not in serialized
    assert "host_path" not in serialized


def test_control_socket_runtime_write_fence_is_typed_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def reject_stale_write(
        _server: _ControlSocketServer,
        _request: dict[str, object],
        _params: dict[str, object],
    ) -> dict[str, object]:
        raise RuntimeWriteFencingError(
            "stale lease sk-abcdefghijklmnop rejected at /tmp/private-runtime.sock"
        )

    monkeypatch.setattr(
        _ControlSocketServer,
        "_handle_transport_smoke",
        reject_stale_write,
    )
    server = _ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        repositories=_build_repositories(),
        session_id="sess_001",
        sandbox_workspace_id="sw_001",
        sandbox_run_id="srun_001",
        agent_id="agent:executor",
        source_snapshot_artifact_id="art_source",
        source_tree_digest=_digest_text("source"),
    )

    response = server._handle(
        {"jsonrpc": "2.0", "id": "call_1", "method": "s09.transport_smoke"}
    )
    error = response["error"]
    serialized = json.dumps(response, sort_keys=True)

    assert error == {
        "message": (
            "session runtime write was rejected because its lease fence is no longer "
            "authoritative"
        ),
        "type": "RuntimeWriteFencingError",
        "error_code": "runtime_write_fenced",
        "hint": (
            "Fail closed for the current runtime attempt; acquire a fresh session "
            "runtime lease before any further write."
        ),
        "details": {
            "boundary": "session_runtime_write_fence",
            "disposition": "fail_closed",
        },
        "retryable": False,
    }
    assert "sk-abcdefghijklmnop" not in serialized
    assert "/tmp/private-runtime.sock" not in serialized


def test_control_socket_registers_nested_artifact_publisher_writer(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: list[dict[str, object]] = []

    @contextmanager
    def writer_scope(**kwargs):  # type: ignore[no-untyped-def]
        observed.append(dict(kwargs))
        yield None

    def register(
        _server: _ControlSocketServer,
        request: dict[str, object],
        method: str,
        params: dict[str, object],
    ) -> dict[str, object]:
        del method, params
        return {"jsonrpc": "2.0", "id": request["id"], "result": {"ok": True}}

    monkeypatch.setattr(_ControlSocketServer, "_handle_artifact_boundary", register)
    server = _control_socket_server(tmp_path, name="artifact_writer")
    server.mutation_writer_scope_factory = writer_scope

    registered = server._handle(
        {
            "jsonrpc": "2.0",
            "id": "register",
            "method": "artifacts.register",
            "params": {"path": "/workspace/output/result.csv"},
        }
    )
    fetched = server._handle(
        {
            "jsonrpc": "2.0",
            "id": "get",
            "method": "artifacts.get",
            "params": {"artifact_id": "art_result"},
        }
    )

    assert registered["result"] == {"ok": True}
    assert fetched["result"] == {"ok": True}
    assert observed == [
        {
            "session_id": "sess_artifact_writer",
            "owner_kind": MutationWriterKind.ARTIFACT_PUBLISHER,
            "owner_ref": (
                "sandbox-artifact-publisher:srun_artifact_writer:"
                "artifacts.register"
            ),
            "process_epoch": None,
        }
    ]


def test_control_socket_round_trips_frames_larger_than_one_recv(
    tmp_path: Path,
) -> None:
    server = _control_socket_server(tmp_path, name="large_frame")
    padding = "AOX-" * 30_000
    request = {
        "jsonrpc": "2.0",
        "id": "large_call",
        "method": "s09.transport_smoke",
        "params": {"artifact_read_summary": {"padding": padding}},
    }
    encoded = json.dumps(request, sort_keys=True).encode("utf-8") + b"\n"

    assert len(encoded) > 64 * 1024
    assert len(encoded) < CONTROL_SOCKET_FRAME_MAX_BYTES

    server.start()
    try:
        response = _send_control_socket_bytes(
            server,
            encoded,
            chunk_bytes=4093,
        )
        follow_up = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "follow_up",
                    "method": "s09.transport_smoke",
                    "params": {"call_identity": "still_alive"},
                }
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        server.stop()

    assert response["id"] == "large_call"
    assert response["result"]["artifact_read_summary"]["padding"] == padding
    assert len(json.dumps(response, sort_keys=True).encode("utf-8")) > 64 * 1024
    assert follow_up["result"]["call_identity"] == "still_alive"


@pytest.mark.parametrize(
    ("payload", "shutdown_write", "expected_response_id"),
    [
        (b'{"jsonrpc":"2.0","method":\xff}\n', False, None),
        (b'{"jsonrpc":"2.0",\n', False, None),
        (b'{"jsonrpc":"2.0","id":' + b"9" * 5_000 + b"}\n", False, None),
        (
            b'{"jsonrpc":"2.0","id":' + b"[" * 20_000 + b"]" * 20_000 + b"}\n",
            False,
            None,
        ),
        (b"[]\n", False, None),
        (
            b'{"jsonrpc":"2.0","id":"non_finite","method":"s09.transport_smoke",'
            b'"params":{"value":NaN}}\n',
            False,
            None,
        ),
        (
            b'{"jsonrpc":"2.0","id":"duplicate","method":"s09.transport_smoke",'
            b'"params":{},"params":{}}\n',
            False,
            None,
        ),
        (
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "bad_params",
                    "method": "s09.transport_smoke",
                    "params": [],
                }
            ).encode("utf-8")
            + b"\n",
            False,
            "bad_params",
        ),
        (b'{"jsonrpc":"2.0"}', True, None),
    ],
)
def test_control_socket_rejects_invalid_frame_and_remains_available(
    tmp_path: Path,
    payload: bytes,
    shutdown_write: bool,
    expected_response_id: str | None,
) -> None:
    server = _control_socket_server(
        tmp_path, name=f"invalid_{hashlib.sha256(payload).hexdigest()[:8]}"
    )
    server.start()
    try:
        response = _send_control_socket_bytes(
            server,
            payload,
            shutdown_write=shutdown_write,
        )
        follow_up = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "valid_after_invalid",
                    "method": "s09.transport_smoke",
                    "params": {},
                }
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        server.stop()

    assert response["error"]["error_code"] == "sandbox_transport_request_invalid"
    assert response["id"] == expected_response_id
    assert follow_up["id"] == "valid_after_invalid"
    assert follow_up["result"]["status"] == "ok"


def test_control_socket_bounds_request_id_and_error_envelope(
    tmp_path: Path,
) -> None:
    server = _control_socket_server(tmp_path, name="bounded_request_id")
    oversized_id = "x" * (CONTROL_SOCKET_FRAME_MAX_BYTES - 128)
    encoded = (
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": oversized_id,
                "method": "s09.transport_smoke",
                "params": {},
            },
            separators=(",", ":"),
        ).encode("utf-8")
        + b"\n"
    )
    assert len(encoded) <= CONTROL_SOCKET_FRAME_MAX_BYTES

    server.start()
    try:
        response = _send_control_socket_bytes(server, encoded)
        follow_up = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "valid_after_oversized_id",
                    "method": "s09.transport_smoke",
                    "params": {},
                }
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        server.stop()

    assert response["id"] is None
    assert response["error"]["error_code"] == "sandbox_transport_request_invalid"
    assert len(json.dumps(response, sort_keys=True).encode("utf-8")) <= (
        CONTROL_SOCKET_FRAME_MAX_BYTES
    )
    assert follow_up["result"]["status"] == "ok"


def test_control_socket_bounds_request_and_response_before_mutation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handled: list[str] = []

    def bounded_transport(
        _server: _ControlSocketServer,
        request: dict[str, object],
        params: dict[str, object],
    ) -> dict[str, object]:
        handled.append(str(request.get("id")))
        response_bytes = int(params.get("response_bytes") or 0)
        return {
            "jsonrpc": "2.0",
            "id": request.get("id"),
            "result": {"padding": "x" * response_bytes},
        }

    monkeypatch.setattr(
        "openzyme_core.sandbox_runtime.CONTROL_SOCKET_FRAME_MAX_BYTES",
        1024,
    )
    monkeypatch.setattr(
        _ControlSocketServer,
        "_handle_transport_smoke",
        bounded_transport,
    )
    server = _control_socket_server(tmp_path, name="bounded_frames")
    server.start()
    try:
        oversized_request = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "oversized_request",
                    "method": "s09.transport_smoke",
                    "params": {"padding": "x" * 2048},
                }
            ).encode("utf-8")
            + b"\n",
        )
        oversized_response = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "oversized_response",
                    "method": "s09.transport_smoke",
                    "params": {"response_bytes": 2048},
                }
            ).encode("utf-8")
            + b"\n",
        )
        valid_response = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "bounded_valid",
                    "method": "s09.transport_smoke",
                    "params": {"response_bytes": 16},
                }
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        server.stop()

    assert (
        oversized_request["error"]["error_code"]
        == "sandbox_transport_request_too_large"
    )
    assert "oversized_request" not in handled
    assert (
        oversized_response["error"]["error_code"]
        == "sandbox_transport_response_too_large"
    )
    assert handled == ["oversized_response", "bounded_valid"]
    assert valid_response["result"]["padding"] == "x" * 16


def test_control_socket_times_out_partial_frame_without_stopping_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_core.sandbox_runtime._CONTROL_SOCKET_IO_TIMEOUT_SECONDS",
        0.02,
    )
    server = _control_socket_server(tmp_path, name="partial_timeout")
    server.start()
    try:
        response = _send_control_socket_bytes(server, b'{"jsonrpc":')
        follow_up = _send_control_socket_bytes(
            server,
            json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": "valid_after_timeout",
                    "method": "s09.transport_smoke",
                    "params": {},
                }
            ).encode("utf-8")
            + b"\n",
        )
    finally:
        server.stop()

    assert response["error"]["error_code"] == "sandbox_transport_request_timeout"
    assert follow_up["result"]["status"] == "ok"


def test_control_socket_stop_waits_past_grace_for_blocking_handler(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler_started = threading.Event()
    release_handler = threading.Event()

    def blocking_transport(
        _server: _ControlSocketServer,
        request: dict[str, object],
        _params: dict[str, object],
    ) -> dict[str, object]:
        handler_started.set()
        if not release_handler.wait(timeout=10.0):
            raise AssertionError("test did not release blocking control handler")
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": {}}

    monkeypatch.setattr(
        _ControlSocketServer,
        "_handle_transport_smoke",
        blocking_transport,
    )
    server = _ControlSocketServer(
        socket_path=tmp_path / "blocking-control.sock",
        repositories=_build_repositories(),
        session_id="sess_blocking_stop",
        sandbox_workspace_id="sw_blocking_stop",
        sandbox_run_id="srun_blocking_stop",
        agent_id="agent:executor",
        source_snapshot_artifact_id="art_source",
        source_tree_digest=_digest_text("source"),
    )
    request_errors: list[BaseException] = []
    stop_errors: list[BaseException] = []
    stop_started = threading.Event()
    stop_done = threading.Event()

    def request() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.settimeout(5.0)
                client.connect(str(server.socket_path))
                client.sendall(
                    json.dumps(
                        {
                            "jsonrpc": "2.0",
                            "id": "blocking_call",
                            "method": "s09.transport_smoke",
                        }
                    ).encode("utf-8")
                    + b"\n"
                )
                client.recv(4096)
        except BaseException as exc:  # pragma: no cover - asserted below
            request_errors.append(exc)

    def stop() -> None:
        stop_started.set()
        try:
            server.stop()
        except BaseException as exc:  # pragma: no cover - asserted below
            stop_errors.append(exc)
        finally:
            stop_done.set()

    server.start()
    request_thread = threading.Thread(target=request, name="control-request")
    stop_thread = threading.Thread(target=stop, name="control-stop")
    try:
        request_thread.start()
        assert handler_started.wait(timeout=1.0)
        stop_thread.start()
        assert stop_started.wait(timeout=1.0)

        assert stop_done.wait(timeout=2.2) is False
        assert stop_thread.is_alive()
        assert server._thread is not None
        assert server._thread.is_alive()
    finally:
        release_handler.set()
        if stop_thread.ident is None:
            server.stop()
        stop_thread.join(timeout=3.0)
        request_thread.join(timeout=3.0)

    assert stop_done.is_set()
    assert stop_thread.is_alive() is False
    assert request_thread.is_alive() is False
    assert request_errors == []
    assert stop_errors == []
    assert server._thread is not None
    assert server._thread.is_alive() is False
    assert server.socket_path.exists() is False


def test_control_socket_start_failure_retires_created_worker(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    release_worker = threading.Event()
    worker_started = threading.Event()
    start_done = threading.Event()
    start_errors: list[BaseException] = []

    def blocked_serve(_server: _ControlSocketServer) -> None:
        worker_started.set()
        release_worker.wait()

    monkeypatch.setattr(_ControlSocketServer, "_serve", blocked_serve)
    monkeypatch.setattr(
        "openzyme_core.sandbox_runtime._CONTROL_SOCKET_START_ATTEMPTS",
        1,
    )
    monkeypatch.setattr(
        "openzyme_core.sandbox_runtime._CONTROL_SOCKET_START_POLL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        "openzyme_core.sandbox_runtime._CONTROL_SOCKET_STOP_GRACE_SECONDS",
        0.01,
    )
    server = _ControlSocketServer(
        socket_path=tmp_path / "never-started-control.sock",
        repositories=_build_repositories(),
        session_id="sess_start_failure",
        sandbox_workspace_id="sw_start_failure",
        sandbox_run_id="srun_start_failure",
        agent_id="agent:executor",
        source_snapshot_artifact_id="art_source",
        source_tree_digest=_digest_text("source"),
    )

    def start() -> None:
        try:
            server.start()
        except BaseException as exc:  # pragma: no cover - asserted below
            start_errors.append(exc)
        finally:
            start_done.set()

    start_thread = threading.Thread(target=start, name="control-start")
    start_thread.start()
    try:
        assert worker_started.wait(timeout=1.0)
        assert start_done.wait(timeout=0.05) is False
        assert server._thread is not None
        assert server._thread.is_alive()
    finally:
        release_worker.set()
        start_thread.join(timeout=2.0)

    assert start_done.is_set()
    assert start_thread.is_alive() is False
    assert server._thread is not None
    assert server._thread.is_alive() is False
    assert len(start_errors) == 1
    assert isinstance(start_errors[0], SandboxRuntimeError)
    assert start_errors[0].error_code == "sandbox_transport_unavailable"


@pytest.mark.parametrize("summary_execution_mode", [None, "sbatch"])
def test_toolchain_runtime_identity_requires_ssh_summary_execution_mode(
    summary_execution_mode: str | None,
) -> None:
    summary: dict[str, object] = {
        "toolchain_runtime_identity": {
            "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
            "attestation_scope": "same_ssh_login_shell_pre_exec",
            "execution_mode": "ssh",
            "tool_id": "bio_tools.mafft",
            "adapter_id": "bio_tools.mafft",
            "command_template_id": "bio_tools_mafft_sif_v1",
            "runner_contract_digest": "sha256:" + "a" * 64,
            "image_digest": "sha256:" + "b" * 64,
        }
    }
    if summary_execution_mode is not None:
        summary["execution_mode"] = summary_execution_mode

    sanitized = _sanitize_toolchain_runtime_identity(summary)

    assert "toolchain_runtime_identity" not in sanitized
    if summary_execution_mode is not None:
        assert sanitized["execution_mode"] == summary_execution_mode


def _seed_session(
    repositories: CoreRepositories, *, session_id: str = "sess_s09"
) -> Session:
    session = Session(
        session_id=session_id,
        project_id="proj_001",
        title="S09",
        objective="Sandbox file command runtime",
        status=SessionStatus.ACTIVE,
        created_at="2026-05-28T00:00:00+00:00",
        updated_at="2026-05-28T00:00:00+00:00",
    )
    repositories.sessions.save(session)
    return session


def _seed_executor(
    repositories: CoreRepositories,
    session: Session,
    *,
    agent_id: str = "agent:executor:runtime",
    member_id: str = "member_executor",
) -> AgentMember:
    agent = AgentMember(
        agent_id=agent_id,
        session_id=session.session_id,
        lane_id=None,
        task_id=None,
        name="executor",
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-28T00:01:00+00:00",
        updated_at="2026-05-28T00:01:00+00:00",
        member_id=member_id,
    )
    repositories.agents.save(agent)
    saved = repositories.agents.get(session.session_id, agent_id)
    assert saved is not None
    return saved


def _seed_workspace(
    repositories: CoreRepositories,
    tmp_path: Path,
) -> tuple[Session, AgentMember, SandboxWorkspaceRecord, Path]:
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:" + "9" * 64,
            image_digest="sha256:" + "9" * 64,
        )
    )
    workspace_root = tmp_path / "workspaces"
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=workspace_root,
    ).create_or_get(session_id=session.session_id, agent_member_id=agent.member_id)
    return session, agent, workspace, workspace_root


def _service(
    repositories: CoreRepositories,
    *,
    workspace_root: Path,
    log_root: Path,
    artifact_blob_root: Path | None = None,
    adapter_executor=None,
    hpc_fetch_executor=None,
    repository_scope_factory=None,
    reliability_shadow_observer=None,
    reliability_settings=None,
    durable_route_adapter_policy_ids=None,
) -> SandboxRuntimeService:
    return SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=artifact_blob_root,
        log_root=log_root,
        execution_backend="local",
        adapter_executor=adapter_executor,
        hpc_fetch_executor=hpc_fetch_executor,
        repository_scope_factory=repository_scope_factory,
        reliability_shadow_observer=reliability_shadow_observer,
        reliability_settings=reliability_settings,
        durable_route_adapter_policy_ids=dict(durable_route_adapter_policy_ids or {}),
    )


def test_sandbox_sdk_registration_uses_attempt_scoped_roots(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    blob_root = tmp_path / "attempt-blobs"
    service = _service(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=blob_root,
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/register_result.py",
        content=(
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "target = Path('output/result.json')\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_text('{\"status\":\"ok\"}\\n', encoding='utf-8')\n"
            "print(artifacts.register('/workspace/output/result.json', "
            "kind='result', format='json')['artifact']['artifact_id'])\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/register_result.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    artifacts = repositories.artifacts.list_by_session(session.session_id)
    result = next(item for item in artifacts if item.relative_path == "result.json")
    source_snapshot = repositories.artifacts.get(str(run.source_snapshot_artifact_id))
    assert source_snapshot is not None
    assert (
        workspace_root.resolve()
        in (workspace_root / workspace.sandbox_workspace_id).resolve().parents
    )
    assert blob_root.resolve() in Path(result.storage_uri).resolve().parents
    assert blob_root.resolve() in Path(source_snapshot.storage_uri).resolve().parents


def test_sandbox_sdk_registers_metadata_larger_than_control_frame_via_sidecar(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=tmp_path / "attempt-blobs",
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/register_large_metadata.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "target = Path('output/result.csv')\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_text('id,score\\nA,1\\n', encoding='utf-8')\n"
            "metadata = {\n"
            "    'contract_id': 'aox_sequence_length_join@2',\n"
            "    'identity_mappings': [\n"
            "        {\n"
            "            'requested_accession': f'A{index:05d}',\n"
            "            'primary_accession': f'A{index:05d}',\n"
            "            'padding': 'x' * 480,\n"
            "        }\n"
            "        for index in range(10000)\n"
            "    ],\n"
            "}\n"
            "response = artifacts.register(\n"
            "    '/workspace/output/result.csv',\n"
            "    kind='result',\n"
            "    format='csv',\n"
            "    metadata=metadata,\n"
            ")\n"
            "selected = artifacts.registered_artifact_ref(response)\n"
            "print(json.dumps({\n"
            "    'schema_id': response['schema_id'],\n"
            "    'artifact_keys': sorted(response['artifact']),\n"
            "    'selected': selected,\n"
            "    'metadata': response['artifact']['metadata'],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/register_large_metadata.py"],
        timeout_seconds=30,
    )

    assert run.status is SandboxRunStatus.COMPLETED, run.stderr_summary
    response = json.loads(str(run.stdout_summary))
    assert response["schema_id"] == "artifact_registration_response@2"
    assert response["artifact_keys"] == ["artifact_id", "metadata"]
    assert response["metadata"]["projection"] == "bounded_registration_summary"
    assert "identity_mappings" not in str(run.stdout_summary)
    result = next(
        item
        for item in repositories.artifacts.list_by_session(session.session_id)
        if item.relative_path == "result.csv"
    )
    persisted_metadata = dict(result.metadata or {})
    assert len(persisted_metadata["identity_mappings"]) == 10_000
    assert persisted_metadata["identity_mappings"][0]["padding"] == "x" * 480
    sidecars = list(
        (
            workspace_root
            / workspace.sandbox_workspace_id
            / "work"
            / ".openzyme"
            / "artifact-metadata"
        ).glob("*.json")
    )
    assert len(sidecars) == 1
    assert sidecars[0].stat().st_size > CONTROL_SOCKET_FRAME_MAX_BYTES


def test_sandbox_register_many_prevalidates_all_metadata_sidecars_before_mutation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=tmp_path / "attempt-blobs",
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/register_many_sidecars.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "Path('output/one.csv').write_text('id\\n1\\n', encoding='utf-8')\n"
            "Path('output/two.csv').write_text('id\\n2\\n', encoding='utf-8')\n"
            "transport = artifacts._metadata_transport({'padding': 'x' * 300000})\n"
            "descriptor = dict(transport['metadata_sidecar'])\n"
            "bad = dict(descriptor)\n"
            "bad['size_bytes'] += 1\n"
            "try:\n"
            "    call('artifacts.register_many', {'items': [\n"
            "        {'path': '/workspace/output/one.csv', 'kind': 'result', "
            "'format': 'csv', 'metadata_sidecar': descriptor},\n"
            "        {'path': '/workspace/output/two.csv', 'kind': 'result', "
            "'format': 'csv', 'metadata_sidecar': bad},\n"
            "    ]})\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({'error_code': exc.error_code}, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected sidecar prevalidation failure')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/register_many_sidecars.py"],
        timeout_seconds=30,
    )

    assert run.status is SandboxRunStatus.COMPLETED, run.stderr_summary
    assert json.loads(str(run.stdout_summary)) == {
        "error_code": "artifact_registration_metadata_sidecar_size_mismatch"
    }
    registered_paths = {
        item.relative_path
        for item in repositories.artifacts.list_by_session(session.session_id)
    }
    assert "one.csv" not in registered_paths
    assert "two.csv" not in registered_paths


def test_sandbox_raw_artifact_registration_rejects_invalid_kind_nonretryably(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=tmp_path / "attempt-blobs",
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/register_invalid_raw.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "try:\n"
            "    call('artifacts.register', {\n"
            "        'path': '/workspace/output/AOX_ref.hmm',\n"
            "        'kind': 'model',\n"
            "        'format': 'hmm',\n"
            "    })\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({\n"
            "        'error_code': exc.error_code,\n"
            "        'retryable': exc.retryable,\n"
            "    }, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected invalid kind failure')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/register_invalid_raw.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED, run.stderr_summary
    assert json.loads(str(run.stdout_summary)) == {
        "error_code": "artifact_kind_invalid",
        "retryable": False,
    }
    assert all(
        artifact.relative_path != "AOX_ref.hmm"
        for artifact in repositories.artifacts.list_by_session(session.session_id)
    )


def test_second_sandbox_exec_registration_binds_current_source_snapshot(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=tmp_path / "attempt-blobs",
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/pipeline.py",
        content="print('inspect')\n",
        create_dirs=True,
    )

    prior_run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/pipeline.py"],
        timeout_seconds=10,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/pipeline.py",
        content=(
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "target = Path('output/current.json')\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_text('{\"status\":\"current\"}\\n', encoding='utf-8')\n"
            "artifacts.register('/workspace/output/current.json', "
            "kind='result', format='json')\n"
        ),
    )

    current_run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/pipeline.py"],
        timeout_seconds=10,
    )

    assert prior_run.status is SandboxRunStatus.COMPLETED, prior_run.stderr_summary
    assert current_run.status is SandboxRunStatus.COMPLETED, current_run.stderr_summary
    assert (
        current_run.source_snapshot_artifact_id != prior_run.source_snapshot_artifact_id
    )
    artifact = next(
        item
        for item in repositories.artifacts.list_by_session(session.session_id)
        if item.relative_path == "current.json"
    )
    metadata = dict(artifact.metadata or {})
    assert (
        metadata["source_snapshot_artifact_id"]
        == current_run.source_snapshot_artifact_id
    )
    assert metadata["source_tree_digest"] == current_run.source_tree_digest
    assert (
        dict(metadata["provenance"])["source_snapshot_artifact_id"]
        == current_run.source_snapshot_artifact_id
    )


def test_sandbox_sdk_forwards_typed_zero_record_fasta_profile(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=tmp_path / "attempt-blobs",
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/register_empty.py",
        content=(
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts\n"
            "target = Path('output/target.fasta')\n"
            "target.parent.mkdir(parents=True, exist_ok=True)\n"
            "target.write_bytes(b'')\n"
            "print(artifacts.register(\n"
            "    '/workspace/output/target.fasta',\n"
            "    kind='sequence',\n"
            "    format='fasta',\n"
            "    validation_profile='fasta_zero_records@1',\n"
            "    metadata={\n"
            "        'empty_result_reason': 'no_candidates_after_length_filter',\n"
            "        'derivation_contract_id': 'aox_sequence_length_join@2',\n"
            "    },\n"
            ')["artifact"]["artifact_id"])\n'
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/register_empty.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    target = next(
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.relative_path == "target.fasta"
    )
    assert Path(target.storage_uri).read_bytes() == b""
    assert target.metadata["validation"] == {
        "status": "passed",
        "format": "fasta",
        "required_columns": [],
        "validation_profile": "fasta_zero_records@1",
        "empty_result_reason": "no_candidates_after_length_filter",
        "derivation_contract_id": "aox_sequence_length_join@2",
    }


def _wait_for_pending_approval(
    repositories: CoreRepositories,
    session_id: str,
) -> ApprovalRequest:
    for _ in range(100):
        pending_items = repositories.approvals.list_pending_by_session(session_id)
        if pending_items:
            return pending_items[0]
        time.sleep(0.05)
    raise AssertionError("expected pending approval")


def _wait_for_operation_with_approval(
    repositories: CoreRepositories,
    operation_id: str,
    approval_id: str,
) -> ControlledOperation:
    for _ in range(100):
        operation = repositories.controlled_operations.get(operation_id)
        if operation is not None and operation.approval_id == approval_id:
            return operation
        time.sleep(0.05)
    raise AssertionError("expected controlled operation to be linked to approval")


def _resolve_s10_approval(
    repositories: CoreRepositories,
    approval_id: str,
    *,
    decision: str,
) -> None:
    approval = repositories.approvals.get(approval_id)
    assert approval is not None
    status = (
        ApprovalRequestStatus.APPROVED
        if decision == "approved"
        else ApprovalRequestStatus.REJECTED
    )
    repositories.approvals.save(
        replace(
            approval,
            status=status,
            resolved_at="2026-05-28T00:05:00+00:00",
        )
    )
    repositories.continuation_states.resolve_for_approval(
        approval.approval_id,
        decision=decision,
    )


class _DurableProviderFixtureAdapter:
    route_policy_id = "bio.ncbi_fetch_proteins.provider:v1"
    selected_backend = "provider_http"
    adapter_policy_id = "test_durable_provider_adapter:v1"

    def __init__(self) -> None:
        self.dispatch_count = 0
        self.reconcile_count = 0

    def prepare_dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> str:
        del request
        digest = hashlib.sha256(
            f"{execution.execution_id}:{execution.dispatch_generation}".encode()
        ).hexdigest()[:24]
        return f"provider_req_{digest}"

    def dispatch(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        self.dispatch_count += 1
        assert execution.backend_handle_ref is not None
        return self._materialized(execution.backend_handle_ref)

    def poll(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        return self._materialized(str(execution.backend_handle_ref))

    def reconcile(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        self.reconcile_count += 1
        return self._materialized(str(execution.backend_handle_ref))

    def materialize(
        self,
        execution: ControlledOperationExecution,
        request: ControlledOperationDispatchRequest,
    ) -> DurableRouteObservation:
        del request
        return self._materialized(str(execution.backend_handle_ref))

    @staticmethod
    def _materialized(backend_handle_ref: str) -> DurableRouteObservation:
        return DurableRouteObservation(
            kind=DurableRouteObservationKind.RESULT_MATERIALIZED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=RetryEligibility.TERMINAL,
            backend_handle_ref=backend_handle_ref,
            safe_receipt_digest="sha256:" + "8" * 64,
            safe_summary="fixture provider result materialized",
            terminal_outcome=(ControlledOperationExecutionTerminalOutcome.SUCCEEDED),
            materialized_result=DurableRouteMaterializedResult(
                bounded_result_envelope={
                    "status": "succeeded",
                    "result_origin": "test_durable_provider_adapter",
                    "registered_artifact_ids": [],
                    "output_artifact_ids": [],
                    "bounded_summary": {
                        "status": "completed",
                        "records": 1,
                    },
                },
                artifact_set_digest=controlled_operation_artifact_set_digest(()),
                origin="test_durable_provider_adapter",
            ),
        )


def _approve_durable_operation(
    repositories: CoreRepositories,
    operation: ControlledOperation,
) -> ControlledOperationExecution:
    approval = repositories.approvals.get(str(operation.approval_id))
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    assert approval is not None
    assert execution is not None
    now = "2026-07-21T01:00:00+00:00"
    approved = replace(
        approval,
        status=ApprovalRequestStatus.APPROVED,
        resolved_at=now,
    )
    ready = replace(
        execution,
        lifecycle_state=ControlledOperationExecutionLifecycle.READY,
        state_version=execution.state_version + 1,
        updated_at=now,
    )
    event = ControlledOperationExecutionEvent(
        event_id=f"test_approval_{execution.execution_id}",
        execution_id=execution.execution_id,
        operation_id=execution.operation_id,
        session_id=execution.session_id,
        state_version=ready.state_version,
        dispatch_generation=ready.dispatch_generation,
        phase=ControlledOperationExecutionPhase.APPROVAL,
        previous_lifecycle_state=execution.lifecycle_state,
        lifecycle_state=ready.lifecycle_state,
        terminal_outcome=ready.terminal_outcome,
        effect_certainty=ready.effect_certainty,
        retry_eligibility=ready.retry_eligibility,
        fencing_token=ready.fencing_token,
        safe_summary="durable operation approved",
        created_at=now,
    )
    with repositories.atomic(prefix="test_durable_approval"):
        repositories.approvals.save(approved)
        repositories.continuation_states.resolve_for_approval(
            approval.approval_id,
            decision="approved",
        )
        ControlledOperationExecutionTransitionService(repositories).transition(
            execution=ready,
            event=event,
            expected_state_version=execution.state_version,
        )
    return ready


def test_sandbox_file_crud_records_audit_and_rejects_bad_patch(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )

    written = service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/tool.py",
        content="print('one')\n",
        create_dirs=True,
    )
    assert written["new_digest"] == _digest_text("print('one')\n")

    read = service.read_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/src/tool.py",
    )
    assert read["content"] == "print('one')\n"
    root_listing = service.list_files(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace",
    )
    assert [item["path"] for item in root_listing["items"]] == [
        "/workspace/logs",
        "/workspace/output",
        "/workspace/src",
        "/workspace/work",
    ]

    patch = (
        "--- /workspace/src/tool.py\n"
        "+++ /workspace/src/tool.py\n"
        "@@ -1 +1 @@\n"
        "-print('one')\n"
        "+print('two')\n"
    )
    patched = service.patch_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/tool.py",
        base_digest=str(written["new_digest"]),
        patch=patch,
    )
    assert patched["new_digest"] == _digest_text("print('two')\n")

    with pytest.raises(SandboxRuntimeError) as bad_patch:
        service.patch_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/tool.py",
            base_digest=str(patched["new_digest"]),
            patch=patch.replace("/workspace/src/tool.py", "/workspace/src/other.py"),
        )
    assert bad_patch.value.error_code == "sandbox_path_forbidden"

    deleted = service.delete_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/tool.py",
        expected_digest=str(patched["new_digest"]),
    )
    assert deleted["deleted"] is True
    audit = repositories.file_audit_entries.list_by_workspace(
        workspace.sandbox_workspace_id
    )
    assert [entry.operation for entry in audit] == ["write", "patch", "delete"]


def test_sandbox_file_mutations_reject_prospective_quota_overflow(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    repositories.sandbox_workspaces.save(
        replace(
            workspace,
            quota_summary={"limit_bytes": 8, "used_bytes": 0, "exceeded": False},
        )
    )

    with pytest.raises(SandboxRuntimeError) as write_error:
        service.write_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/too-large.txt",
            content="123456789",
            create_dirs=True,
        )

    assert write_error.value.error_code == "sandbox_quota_exceeded"
    assert write_error.value.details == {
        "limit_bytes": 8,
        "used_bytes": 0,
        "prospective_bytes": 9,
    }
    assert not (
        workspace_root / workspace.sandbox_workspace_id / "src" / "too-large.txt"
    ).exists()

    repositories.sandbox_workspaces.save(
        replace(
            repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
            or workspace,
            quota_summary={"limit_bytes": 12, "used_bytes": 0, "exceeded": False},
        )
    )
    written = service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/value.txt",
        content="small\n",
        create_dirs=True,
    )
    patch = (
        "--- /workspace/src/value.txt\n"
        "+++ /workspace/src/value.txt\n"
        "@@ -1 +1 @@\n"
        "-small\n"
        "+this is much larger\n"
    )
    with pytest.raises(SandboxRuntimeError) as patch_error:
        service.patch_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/value.txt",
            base_digest=str(written["new_digest"]),
            patch=patch,
        )
    assert patch_error.value.error_code == "sandbox_quota_exceeded"
    assert (
        workspace_root / workspace.sandbox_workspace_id / "src" / "value.txt"
    ).read_text(encoding="utf-8") == "small\n"


def test_sandbox_write_conflicts_with_active_exec(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    active = SandboxRunRecord(
        sandbox_run_id="srun_active",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/script.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        created_at="2026-05-28T00:02:00+00:00",
        updated_at="2026-05-28T00:02:00+00:00",
        changed_files_summary={},
    )
    repositories.sandbox_runs.save(active)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )

    with pytest.raises(SandboxRuntimeError) as exc_info:
        service.write_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/script.py",
            content="print('blocked')\n",
            create_dirs=True,
        )
    assert exc_info.value.error_code == "sandbox_run_conflict"


def test_sandbox_exec_snapshots_source_and_allows_output_registration(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/script.py",
        content=(
            "from pathlib import Path\n"
            "Path('output/result.txt').write_text('ok\\n', encoding='utf-8')\n"
            "print('ran')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/script.py"],
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert run.exit_code == 0
    assert run.source_snapshot_artifact_id
    assert run.source_tree_digest
    assert run.stdout_summary == "ran\n"
    assert run.stdout_metadata == {
        "raw_digest": _digest_text("ran\n"),
        "raw_size_bytes": 4,
        "truncated": False,
        "log_ref": None,
    }
    assert run.stderr_metadata == {
        "raw_digest": _digest_text(""),
        "raw_size_bytes": 0,
        "truncated": False,
        "log_ref": None,
    }
    assert run.changed_files_summary
    assert "output/result.txt" in run.changed_files_summary["added"]
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    assert refreshed.last_command_summary["sandbox_run_id"] == run.sandbox_run_id

    registered = ArtifactBoundaryService(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    ).register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.txt",
        kind="result",
        format="text",
    )
    assert (
        registered.artifact.metadata["source_snapshot_artifact_id"]
        == run.source_snapshot_artifact_id
    )


def test_sandbox_exec_tool_registers_exact_process_writer(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
    ).write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/process_writer.py",
        content="print('writer-covered')\n",
        create_dirs=True,
    )
    observed: list[dict[str, object]] = []

    @contextmanager
    def writer_scope(**kwargs):  # type: ignore[no-untyped-def]
        observed.append(dict(kwargs))
        yield None

    registry = ToolRegistry()
    register_sandbox_runtime_tools(registry, agent_id=agent.agent_id)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
        sandbox_workspace_root=workspace_root,
        mutation_writer_scope_factory=writer_scope,
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_process_writer",
            tool_name="sandbox.exec",
            arguments={
                "sandbox_workspace_id": workspace.sandbox_workspace_id,
                "argv": ["python", "src/process_writer.py"],
            },
        ),
    )

    assert result.ok is True
    assert len(observed) == 1
    assert observed[0]["session_id"] == session.session_id
    assert observed[0]["owner_kind"] is MutationWriterKind.SANDBOX_PROCESS
    assert observed[0]["owner_ref"] == "sandbox-exec:cadbd77f7f1a86e3"
    assert isinstance(observed[0]["process_epoch"], int)
    assert int(observed[0]["process_epoch"]) > 0


def test_sandbox_exec_marks_run_and_workspace_when_output_exceeds_disk_quota(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/fill.py",
        content=(
            "from pathlib import Path\n"
            "Path('output/large.txt').write_text('x' * 100, encoding='utf-8')\n"
        ),
        create_dirs=True,
    )
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    used_bytes = int((refreshed.quota_summary or {})["used_bytes"])
    repositories.sandbox_workspaces.save(
        replace(
            refreshed,
            quota_summary={
                "limit_bytes": used_bytes + 10,
                "used_bytes": used_bytes,
                "exceeded": False,
            },
        )
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/fill.py"],
    )

    assert run.status is SandboxRunStatus.RESOURCE_EXCEEDED
    assert run.error_code == "sandbox_quota_exceeded"
    exceeded_workspace = repositories.sandbox_workspaces.get(
        workspace.sandbox_workspace_id
    )
    assert exceeded_workspace is not None
    assert exceeded_workspace.status is SandboxWorkspaceStatus.QUOTA_EXCEEDED
    assert (exceeded_workspace.quota_summary or {})["exceeded"] is True
    with pytest.raises(SandboxRuntimeError) as blocked:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/fill.py"],
        )
    assert blocked.value.error_code == "sandbox_quota_exceeded"


def test_sandbox_exec_transport_smoke_returns_identity_binding(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/smoke.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s09.transport_smoke', {'call_identity': 'smoke_001'})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/smoke.py"],
    )

    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["sandbox_workspace_id"] == workspace.sandbox_workspace_id
    assert payload["sandbox_run_id"] == run.sandbox_run_id
    assert payload["source_snapshot_artifact_id"] == run.source_snapshot_artifact_id
    assert payload["call_identity"] == "smoke_001"


def test_control_socket_opens_thread_owned_repository_scope(tmp_path: Path) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "control-plane.sqlite3"))

    @contextmanager
    def open_repositories():
        with provider.connection_scope() as owned_scope:
            yield owned_scope.repositories

    with provider.connection_scope() as scope:
        repositories = scope.repositories
        session, agent, workspace, workspace_root = _seed_workspace(
            repositories,
            tmp_path,
        )
        service = _service(
            repositories,
            workspace_root=workspace_root,
            log_root=tmp_path / "logs",
            repository_scope_factory=open_repositories,
        )
        input_path = tmp_path / "thread-owned-input.txt"
        input_path.write_text("owned\n", encoding="utf-8")
        repositories.artifacts.save(
            SessionArtifactRecord(
                artifact_id="art_thread_owned",
                session_id=session.session_id,
                task_id=None,
                lane_id=None,
                run_id=None,
                invocation_id=None,
                storage_uri=str(input_path),
                relative_path="inputs/thread-owned.txt",
                kind=ArtifactKind.RESULT,
                metadata={"content_digest": _digest_text("owned\n")},
                created_at="2026-05-28T00:01:30+00:00",
            )
        )
        service.write_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/thread_owned.py",
            content=(
                "import json\n"
                "from openzyme_pipeline.client import call\n"
                "result = call('artifacts.get', {'artifact_id': 'art_thread_owned'})\n"
                "print(json.dumps(result, sort_keys=True))\n"
            ),
            create_dirs=True,
        )

        run = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/thread_owned.py"],
        )

        assert run.status is SandboxRunStatus.COMPLETED
        assert json.loads(str(run.stdout_summary))["artifact_id"] == "art_thread_owned"


def test_sandbox_exec_controlled_operation_approval_resumes_same_rpc(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    shadow_observer = ReliabilityShadowObserver(
        ReliabilityRefactorSettings(
            shadow_observability=ShadowObservabilityMode.SHADOW_V1
        )
    )
    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        reliability_shadow_observer=shadow_observer,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_approve_001',\n"
            "    'logical_operation_key': 'fake.controlled',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'provider_http',\n"
            "    'input_artifact_digests': ['artifact_a:sha256:input'],\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "    'result_summary': {'message': 'approved result'},\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        try:
            holder["run"] = service.exec_command(
                session_id=session.session_id,
                sandbox_workspace_id=workspace.sandbox_workspace_id,
                agent_id=agent.agent_id,
                argv=["python", "src/s10.py"],
                timeout_seconds=10,
            )
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            holder["error"] = exc

    thread = threading.Thread(target=_run)
    thread.start()
    pending = None
    for _ in range(100):
        pending_items = repositories.approvals.list_pending_by_session(
            session.session_id
        )
        if pending_items:
            pending = pending_items[0]
            break
        time.sleep(0.05)
    assert pending is not None
    assert pending.kind == "sdk_controlled_operation"
    operation = repositories.controlled_operations.get(str(pending.request_ref))
    assert operation is not None
    assert operation.status is ControlledOperationStatus.WAITING_APPROVAL
    assert operation.owner_mode is ControlledOperationOwnerMode.LEGACY_SYNC
    assert (
        repositories.controlled_operation_executions.get_by_operation_id(
            operation.operation_id
        )
        is None
    )
    continuation = repositories.continuation_states.get_by_operation_id(
        operation.operation_id
    )
    assert continuation is not None
    assert continuation.status is ContinuationStateStatus.WAITING_APPROVAL
    assert thread.is_alive()

    repositories.approvals.save(
        pending.__class__(
            approval_id=pending.approval_id,
            session_id=pending.session_id,
            task_id=pending.task_id,
            lane_id=pending.lane_id,
            kind=pending.kind,
            requested_action=pending.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=pending.request_ref,
            resolution_ref=pending.resolution_ref,
            created_at=pending.created_at,
            resolved_at="2026-05-28T00:05:00+00:00",
        )
    )
    repositories.continuation_states.resolve_for_approval(
        pending.approval_id, decision="approved"
    )
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in holder
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["approval_id"] == pending.approval_id
    assert payload["approval_state"] == "approved"
    assert payload["status"] == "completed"
    assert payload["result_summary"] == {"message": "approved result"}
    completed_operation = repositories.controlled_operations.get(operation.operation_id)
    completed_continuation = repositories.continuation_states.get(
        continuation.continuation_id
    )
    assert completed_operation is not None
    assert completed_operation.status is ControlledOperationStatus.COMPLETED
    assert completed_operation.owner_mode is ControlledOperationOwnerMode.LEGACY_SYNC
    assert (
        repositories.controlled_operation_executions.get_by_operation_id(
            operation.operation_id
        )
        is None
    )
    assert completed_continuation is not None
    assert completed_continuation.status is ContinuationStateStatus.COMPLETED
    assert (
        completed_continuation.claimed_by == f"sandbox-supervisor:{run.sandbox_run_id}"
    )
    shadow = shadow_observer.snapshot()
    assert len(shadow) == 1
    assert shadow[0]["kind"] == "approval_wait"
    assert shadow[0]["dimensions"]["resolution"] == "approved"
    assert operation.operation_id not in json.dumps(shadow, sort_keys=True)


def test_sandbox_exec_durable_route_admits_once_and_never_calls_legacy_adapter(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "attached-process.sqlite3"
    connection = connect_sqlite(str(database_path), check_same_thread=False)
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        scoped_connection = connect_sqlite(
            str(database_path),
            check_same_thread=False,
        )
        try:
            yield CoreRepositories.from_connection(scoped_connection)
        finally:
            scoped_connection.close()

    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    route_policy_id = "bio.ncbi_fetch_proteins.provider:v1"
    fixture_adapter = _DurableProviderFixtureAdapter()
    legacy_adapter_calls: list[str] = []

    def _legacy_adapter_executor(
        operation: ControlledOperation,
        envelope: dict[str, object],
    ) -> dict[str, object]:
        del envelope
        legacy_adapter_calls.append(operation.operation_id)
        raise AssertionError("durable owner reached the legacy adapter")

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_legacy_adapter_executor,
        reliability_settings=ReliabilityRefactorSettings(
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
            durable_execution_route_allowlist=(route_policy_id,),
        ),
        durable_route_adapter_policy_ids={
            route_policy_id: fixture_adapter.adapter_policy_id,
        },
        repository_scope_factory=repository_scope,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/durable_provider.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call, canonical_digest\n"
            "params = {'accessions': ['AAB57849.1']}\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'ncbi_fetch_proteins',\n"
            "    'idempotency_key': 'durable_provider_001',\n"
            "    'params_digest': canonical_digest(params),\n"
            "    'params': params,\n"
            "    'expected_outputs': {'kind': 'fasta'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/durable_provider.py"],
            timeout_seconds=10,
            originating_signal_id="signal_durable_provider",
            originating_tool_call_id="tool_call_durable_provider",
            originating_invocation_id="invocation_durable_provider",
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation.operation_id
    )
    continuation = repositories.continuation_states.get_by_operation_id(
        operation.operation_id
    )
    assert operation.owner_mode is ControlledOperationOwnerMode.DURABLE_ASYNC_V1
    assert execution is not None
    assert execution.lifecycle_state is (
        ControlledOperationExecutionLifecycle.AWAITING_APPROVAL
    )
    assert execution.adapter_policy_id == fixture_adapter.adapter_policy_id
    assert continuation is not None
    assert (
        repositories.controlled_operation_dispatch_requests.get_by_execution_id(
            execution.execution_id
        )
        is not None
    )
    assert (
        len(
            repositories.controlled_operation_execution_events.list_by_execution(
                execution.execution_id
            )
        )
        == 1
    )
    assert legacy_adapter_calls == []

    thread.join(timeout=5)
    assert not thread.is_alive()
    suspended_run = holder["run"]
    assert isinstance(suspended_run, SandboxRunRecord)
    assert suspended_run.status is SandboxRunStatus.RUNNING
    assert (suspended_run.compatibility or {})["suspension"]["status"] == (
        "suspended_waiting_approval"
    )

    ready = _approve_durable_operation(repositories, operation)

    worker = ControlledOperationExecutionWorker(
        repository_scope_factory=repository_scope,
        adapters={route_policy_id: fixture_adapter},
        worker_id="test:durable-provider",
    )
    assert worker.run_execution_once(ready.execution_id).action == "dispatch"
    assert worker.run_execution_once(ready.execution_id).action == "terminalize_result"
    assert service.live_process_registry is not None
    delivery_worker = ContinuationDeliveryWorker(
        repository_scope_factory=repository_scope,
        live_process_registry=service.live_process_registry,
        worker_id="test:continuation-delivery",
    )
    assert delivery_worker.run_once().action == "delivered"
    run = suspended_run
    for _ in range(100):
        current_run = repositories.sandbox_runs.get(run.sandbox_run_id)
        assert current_run is not None
        if current_run.status is not SandboxRunStatus.RUNNING:
            run = current_run
            break
        time.sleep(0.05)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["status"] == "completed"
    assert payload["result_summary"] == {"records": 1, "status": "completed"}
    assert fixture_adapter.dispatch_count == 1
    assert fixture_adapter.reconcile_count == 0
    assert legacy_adapter_calls == []
    completed = repositories.controlled_operations.get(operation.operation_id)
    assert completed is not None
    assert completed.owner_mode is ControlledOperationOwnerMode.DURABLE_ASYNC_V1
    assert completed.status is ControlledOperationStatus.COMPLETED
    assert completed.result_summary == {"records": 1, "status": "completed"}
    assert (completed.adapter_result_envelope or {})["bounded_summary"] == {
        "records": 1,
        "status": "completed",
    }
    owner_wakeups = [
        signal
        for signal in repositories.runtime_signals.list_by_session(session.session_id)
        if signal.reason is AgentRuntimeSignalReason.ENGINE_COMPLETED
        and signal.source_ref == continuation.continuation_id
    ]
    assert len(owner_wakeups) == 1
    assert delivery_worker.run_once().action == "idle"
    assert service.live_process_registry.active_count() == 0


def test_sandbox_exec_durable_route_without_exact_adapter_fails_closed(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    route_policy_id = "bio.ncbi_fetch_proteins.provider:v1"
    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        reliability_settings=ReliabilityRefactorSettings(
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
            durable_execution_route_allowlist=(route_policy_id,),
        ),
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/missing_durable_adapter.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call, canonical_digest\n"
            "params = {'accessions': ['AAB57849.1']}\n"
            "try:\n"
            "    call('s10.controlled_operation', {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "        'sdk_module': 'bio',\n"
            "        'function_name': 'ncbi_fetch_proteins',\n"
            "        'idempotency_key': 'durable_missing_adapter_001',\n"
            "        'params_digest': canonical_digest(params),\n"
            "        'params': params,\n"
            "        'expected_outputs': {'kind': 'fasta'},\n"
            "        'resource_estimate': {'requests': 1},\n"
            "    })\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({'error_code': exc.error_code}, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected durable adapter rejection')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/missing_durable_adapter.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "error_code": "durable_route_adapter_unavailable"
    }
    assert repositories.approvals.list_by_session(session.session_id) == []
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_timeout_excludes_pending_approval_wait(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_wait.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_wait_001',\n"
            "    'logical_operation_key': 'fake.wait_for_human',\n"
            "    'params_digest': 'sha256:params-wait',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "    'result_summary': {'message': 'approved after wait'},\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_wait.py"],
            timeout_seconds=2,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    time.sleep(2.25)
    assert thread.is_alive()
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["result_summary"] == {"message": "approved after wait"}


def test_sandbox_exec_controlled_operation_reject_returns_sdk_error(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_reject.py",
        content=(
            "from openzyme_pipeline.client import call\n"
            "call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_reject_001',\n"
            "    'logical_operation_key': 'fake.rejected',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'host_local_tool',\n"
            "    'expected_outputs_summary': {},\n"
            "    'resource_estimate': {},\n"
            "})\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_reject.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = None
    for _ in range(100):
        pending_items = repositories.approvals.list_pending_by_session(
            session.session_id
        )
        if pending_items:
            pending = pending_items[0]
            break
        time.sleep(0.05)
    assert pending is not None
    repositories.approvals.save(
        pending.__class__(
            approval_id=pending.approval_id,
            session_id=pending.session_id,
            task_id=pending.task_id,
            lane_id=pending.lane_id,
            kind=pending.kind,
            requested_action=pending.requested_action,
            status=ApprovalRequestStatus.REJECTED,
            request_ref=pending.request_ref,
            resolution_ref=pending.resolution_ref,
            created_at=pending.created_at,
            resolved_at="2026-05-28T00:06:00+00:00",
        )
    )
    repositories.continuation_states.resolve_for_approval(
        pending.approval_id, decision="rejected"
    )
    thread.join(timeout=5)
    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "PipelineSdkError" in str(run.stderr_summary)
    operation = repositories.controlled_operations.get(str(pending.request_ref))
    assert operation is not None
    assert operation.status is ControlledOperationStatus.FAILED
    assert operation.error_code == "approval_rejected"


def test_sandbox_exec_controlled_operation_detects_idempotency_digest_drift(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_drift.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "first = call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_drift_001',\n"
            "    'logical_operation_key': 'fake.drift',\n"
            "    'params_digest': 'sha256:params-a',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "})\n"
            "try:\n"
            "    call('s10.controlled_operation', {\n"
            "        'schema_version': 's10.supervised_rpc.v1',\n"
            "        'idempotency_key': 'op_drift_001',\n"
            "        'logical_operation_key': 'fake.drift',\n"
            "        'params_digest': 'sha256:params-b',\n"
            "        'backend_category': 'provider_http',\n"
            "        'expected_outputs_summary': {'kind': 'json'},\n"
            "        'resource_estimate': {'seconds': 1},\n"
            "    })\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({'first_status': first['status'], 'error_code': exc.error_code}, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected operation drift')\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_drift.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload == {
        "error_code": "operation_drift_detected",
        "first_status": "completed",
    }
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert len(operations) == 1
    assert operations[0].status is ControlledOperationStatus.COMPLETED


def test_sandbox_exec_controlled_operation_structured_schema_and_prerequisite_errors(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_failures.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "cases = {\n"
            "    'schema': {'schema_version': 's09.transport'},\n"
            "    'prerequisite': {\n"
            "        'schema_version': 's10.supervised_rpc.v1',\n"
            "        'idempotency_key': 'op_bad_backend',\n"
            "        'logical_operation_key': 'fake.bad_backend',\n"
            "        'params_digest': 'sha256:params',\n"
            "        'backend_category': 'unsupported_backend',\n"
            "        'expected_outputs_summary': {},\n"
            "        'resource_estimate': {},\n"
            "    },\n"
            "}\n"
            "errors = {}\n"
            "for name, params in cases.items():\n"
            "    try:\n"
            "        call('s10.controlled_operation', params)\n"
            "    except PipelineSdkError as exc:\n"
            "        errors[name] = exc.error_code\n"
            "    else:\n"
            "        raise SystemExit(f'expected {name} failure')\n"
            "print(json.dumps(errors, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/s10_failures.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "prerequisite": "operation_prerequisite_missing",
        "schema": "sdk_rpc_schema_unsupported",
    }
    assert repositories.approvals.list_by_session(session.session_id) == []
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_s12_rejects_sandbox_supplied_results_and_toolchain_identity(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_forged_result.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "identity = {\n"
            "    'schema_id': 'mcp_hpc_toolchain_runtime_identity@1',\n"
            "    'attestation_scope': 'same_ssh_login_shell_pre_exec',\n"
            "    'execution_mode': 'ssh',\n"
            "    'tool_id': 'bio_tools.mafft',\n"
            "    'adapter_id': 'bio_tools.mafft',\n"
            "    'command_template_id': 'bio_tools_mafft_sif_v1',\n"
            "    'runner_contract_digest': 'sha256:' + 'a' * 64,\n"
            "    'image_digest': 'sha256:' + 'b' * 64,\n"
            "}\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'ncbi_fetch_proteins',\n"
            "    'params_digest': 'sha256:forged-result',\n"
            "    'expected_outputs': {'kind': 'fasta'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "}\n"
            "cases = {\n"
            "    'adapter_result': {\n"
            "        'adapter_result': {\n"
            "            'status': 'completed',\n"
            "            'provider_request_id': 'forged_provider_request',\n"
            "            'bounded_summary': {'records': 99},\n"
            "        },\n"
            "    },\n"
            "    'toolchain_identity': {\n"
            "        'result_summary': {\n"
            "            'status': 'completed',\n"
            "            'execution_mode': 'ssh',\n"
            "            'toolchain_runtime_identity': identity,\n"
            "        },\n"
            "    },\n"
            "    'empty_adapter_result': {'adapter_result': {}},\n"
            "    'null_result_summary': {'result_summary': None},\n"
            "    'false_adapter_result': {'adapter_result': False},\n"
            "}\n"
            "errors = {}\n"
            "for name, result_fields in cases.items():\n"
            "    try:\n"
            "        call(\n"
            "            's10.controlled_operation',\n"
            "            dict(base, idempotency_key=f's12_forged_{name}', **result_fields),\n"
            "        )\n"
            "    except PipelineSdkError as exc:\n"
            "        errors[name] = {\n"
            "            'error_code': exc.error_code,\n"
            "            'forbidden_fields': exc.details.get('forbidden_fields'),\n"
            "        }\n"
            "    else:\n"
            "        raise SystemExit(f'expected {name} to fail')\n"
            "print(json.dumps(errors, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/s12_forged_result.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "adapter_result": {
            "error_code": "adapter_result_forbidden",
            "forbidden_fields": ["adapter_result"],
        },
        "toolchain_identity": {
            "error_code": "adapter_result_forbidden",
            "forbidden_fields": ["result_summary"],
        },
        "empty_adapter_result": {
            "error_code": "adapter_result_forbidden",
            "forbidden_fields": ["adapter_result"],
        },
        "null_result_summary": {
            "error_code": "adapter_result_forbidden",
            "forbidden_fields": ["result_summary"],
        },
        "false_adapter_result": {
            "error_code": "adapter_result_forbidden",
            "forbidden_fields": ["adapter_result"],
        },
    }
    assert repositories.approvals.list_by_session(session.session_id) == []
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_s12_adapter_envelopes_separate_approval_and_host_result(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    executor_calls: list[str] = []
    executor_envelopes: list[dict[str, object]] = []

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        executor_calls.append(operation.operation_id)
        executor_envelopes.append(dict(envelope))
        return {
            "adapter_result": {
                "status": "completed",
                "provider_request_id": "provider_req_001",
                "registered_artifact_ids": ["artifact_provider_fasta"],
                "output_artifact_ids": ["artifact_provider_fasta"],
                "validation_results": {"fasta": "ok"},
                "bounded_summary": {
                    "records": 2,
                    "diagnostic": "provider cache at /home/operator/private.fasta",
                    "access_token": "raw-token",
                },
                "warnings": ["preview truncated at /tmp/provider/private.log"],
                "safe_diagnostics_ref": "storage://private/provider.log",
                "remote_path": "/private/provider/cache.fasta",
            },
            "result_summary": {
                "records": 2,
                "message": "completed via /var/lib/provider/private",
            },
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_provider.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call, canonical_digest\n"
            "adapter_params = {'accessions': ['AAB57849.1']}\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'ncbi_fetch_proteins',\n"
            "    'idempotency_key': 's12_provider_001',\n"
            "    'params_digest': canonical_digest(adapter_params),\n"
            "    'params': adapter_params,\n"
            "    'expected_outputs': {'kind': 'fasta', 'storage_uri': '/private/out.fasta'},\n"
            "    'planned_fetch_intent': {'remote_path': '/private/provider/fetch'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "    '_host_validated_result_reuse': True,\n"
            "    'adapter_result_origin': 'host_adapter_executor',\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_provider.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    approval_envelope = operation.adapter_approval_envelope or {}
    assert (
        approval_envelope["adapter_envelope_schema_version"]
        == "s12.adapter_envelope.v1"
    )
    assert approval_envelope["approval_id"] == pending.approval_id
    assert approval_envelope["sdk_module"] == "bio"
    assert approval_envelope["function_name"] == "ncbi_fetch_proteins"
    assert approval_envelope["route_policy_id"] == "bio.ncbi_fetch_proteins.provider:v1"
    assert approval_envelope["selected_backend"] == "provider_http"
    assert approval_envelope["provider_config_digest"] == "provider_config:ncbi:v1"
    assert approval_envelope["expected_outputs"] == {"kind": "fasta"}
    assert approval_envelope["planned_fetch_intent"] == {}
    assert "storage_uri" not in json.dumps(approval_envelope, sort_keys=True)
    assert "remote_path" not in json.dumps(approval_envelope, sort_keys=True)
    for post_run_key in {
        "fetch_refs",
        "registered_artifact_ids",
        "output_artifact_ids",
        "backend_run_id",
        "provider_request_id",
    }:
        assert post_run_key not in approval_envelope
    assert operation.adapter_result_envelope == {}

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["schema_version"] == "s12.adapter_envelope.v1"
    assert payload["adapter_approval_envelope"] == approval_envelope
    result_envelope = payload["adapter_result_envelope"]
    assert result_envelope["status"] == "completed"
    assert result_envelope["result_origin"] == "host_adapter_executor"
    assert result_envelope["provider_request_id"] == "provider_req_001"
    assert result_envelope["registered_artifact_ids"] == ["artifact_provider_fasta"]
    assert result_envelope["bounded_summary"] == {
        "records": 2,
        "diagnostic": "provider cache at [redacted-host-path]",
    }
    assert result_envelope["safe_diagnostics_ref"] == "[redacted-private-locator]"
    assert result_envelope["warnings"] == [
        {
            "code": "adapter_warning",
            "stage": "adapter_result",
            "retryable": False,
            "summary": "preview truncated at [redacted-host-path]",
            "details_ref": None,
            "safe_diagnostics": None,
        }
    ]
    assert "remote_path" not in json.dumps(result_envelope, sort_keys=True)
    assert "raw-token" not in json.dumps(payload, sort_keys=True)
    assert payload["result_summary"] == {
        "records": 2,
        "message": "completed via [redacted-host-path]",
    }
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.adapter_result_envelope == result_envelope
    assert executor_calls == [operation.operation_id]
    assert len(executor_envelopes) == 1
    assert "_host_validated_result_reuse" not in executor_envelopes[0]
    assert "adapter_result_origin" not in executor_envelopes[0]
    assert persisted.input_artifact_ids == ()
    assert persisted.input_artifact_digests == ()


def test_sandbox_exec_preserves_typed_adapter_failure_for_pipeline_sdk(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )

    class TypedStagingFailure(RuntimeError):
        error_type = "hpc_staging_failed"
        message = "HPC input staging failed before tool execution."
        hint = "Retry only in a fresh attempt after checking runner connectivity."
        stage = "hpc_staging"
        retryable = True
        details = {
            "runner_failure": {
                "schema_id": "runner_failure@1",
                "run_id": "runner_attempt_001",
                "phase": "input_parent",
                "input_ordinal": 1,
                "content_digest": "sha256:" + "a" * 64,
                "returncode": 255,
                "timed_out": False,
                "elapsed_seconds": 60.25,
            },
            "remote_path": "/private/runner/input.fasta",
            "credential": "sk-private-runner-token",
        }

    adapter_calls: list[str] = []

    def _adapter_executor(
        _operation: ControlledOperation,
        _envelope: dict[str, object],
    ) -> dict[str, object]:
        adapter_calls.append(_operation.operation_id)
        raise TypedStagingFailure

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/typed_adapter_failure.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call, canonical_digest\n"
            "params = {'accessions': ['AAB57849.1']}\n"
            "try:\n"
            "    call('s10.controlled_operation', {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "        'sdk_module': 'bio',\n"
            "        'function_name': 'ncbi_fetch_proteins',\n"
            "        'idempotency_key': 'typed_adapter_failure_001',\n"
            "        'params_digest': canonical_digest(params),\n"
            "        'params': params,\n"
            "        'expected_outputs': {'kind': 'fasta'},\n"
            "        'resource_estimate': {'requests': 1},\n"
            "    })\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({\n"
            "        'error_code': exc.error_code,\n"
            "        'stage': exc.stage,\n"
            "        'retryable': exc.retryable,\n"
            "        'hint': exc.hint,\n"
            "        'details': exc.details,\n"
            "        'display_message': str(exc),\n"
            "    }, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected typed adapter failure')\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/typed_adapter_failure.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(
        repositories,
        pending.approval_id,
        decision="approved",
    )
    thread.join(timeout=5)

    assert thread.is_alive() is False
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED, run.stderr_summary
    payload = json.loads(str(run.stdout_summary))
    assert payload["error_code"] == "hpc_staging_failed"
    assert payload["stage"] == "hpc_staging"
    assert payload["retryable"] is True
    assert payload["hint"] == (
        "Retry only in a fresh attempt after checking runner connectivity."
    )
    assert "stage=hpc_staging" in payload["display_message"]
    assert "retryable=True" in payload["display_message"]
    assert payload["details"]["stage"] == "hpc_staging"
    assert payload["details"]["retryable"] is True
    assert payload["details"]["runner_failure"] == {
        "schema_id": "runner_failure@1",
        "run_id": "runner_attempt_001",
        "phase": "input_parent",
        "input_ordinal": 1,
        "content_digest": "sha256:" + "a" * 64,
        "returncode": 255,
        "timed_out": False,
        "elapsed_seconds": 60.25,
    }
    assert payload["details"]["operation_id"] == str(pending.request_ref)
    serialized = json.dumps(payload, sort_keys=True)
    assert "remote_path" not in serialized
    assert "/private/runner" not in serialized
    assert "credential" not in serialized
    assert "sk-private-runner-token" not in serialized
    operation = repositories.controlled_operations.get(str(pending.request_ref))
    assert operation is not None
    assert operation.status is ControlledOperationStatus.FAILED
    assert adapter_calls == [operation.operation_id]


def test_sandbox_exec_s12_rejects_unsuccessful_or_inconsistent_host_result(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    executor_calls: list[str] = []

    def _adapter_executor(
        operation: ControlledOperation,
        envelope: dict[str, object],
    ) -> dict[str, object]:
        del envelope
        executor_calls.append(operation.operation_id)
        if len(executor_calls) == 1:
            return {
                "adapter_result": {
                    "status": "failed",
                    "error": {
                        "code": "provider_contract_failed",
                        "message": "Provider response failed its contract.",
                    },
                },
                "result_summary": {"status": "failed"},
            }
        if len(executor_calls) == 3:
            return {
                "adapter_result": {
                    "status": "failed",
                    "error_code": "/home/operator/private-error-code",
                },
                "result_summary": {"status": "failed"},
            }
        return {
            "adapter_result": {
                "status": "succeeded",
                "bounded_summary": {"status": "failed"},
            },
            "result_summary": {"status": "failed"},
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_failed_host_result.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call, canonical_digest\n"
            "params = {'accessions': ['P12345']}\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.uniprot_fetch.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'uniprot_fetch',\n"
            "    'params_digest': canonical_digest(params),\n"
            "    'params': params,\n"
            "    'expected_outputs': {'kind': 'fasta'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "}\n"
            "errors = []\n"
            "for key in ('failed_status', 'inconsistent_summary', 'private_code'):\n"
            "    try:\n"
            "        call('s10.controlled_operation', dict(base, idempotency_key=key))\n"
            "    except PipelineSdkError as exc:\n"
            "        errors.append(exc.error_code)\n"
            "    else:\n"
            "        raise SystemExit('expected Host result failure')\n"
            "print(json.dumps(errors))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_failed_host_result.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(
        repositories,
        pending.approval_id,
        decision="approved",
    )
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == [
        "provider_contract_failed",
        "adapter_result_inconsistent",
        "adapter_result_unsuccessful",
    ]
    operations = repositories.controlled_operations.list_by_session(session.session_id)
    assert len(operations) == 3
    assert all(
        operation.status is ControlledOperationStatus.FAILED for operation in operations
    )
    assert {operation.error_code for operation in operations} == {
        "provider_contract_failed",
        "adapter_result_inconsistent",
        "adapter_result_unsuccessful",
    }
    assert all(operation.adapter_result_origin is None for operation in operations)
    assert all(not operation.adapter_result_envelope for operation in operations)
    assert len(repositories.approvals.list_by_session(session.session_id)) == 1
    assert len(executor_calls) == 3
    assert "/home/operator" not in json.dumps(
        [operation.to_dict() for operation in operations],
        sort_keys=True,
    )


def test_sandbox_exec_public_bio_sdk_uses_s12_controlled_operation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_sdk.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import bio\n"
            "result = bio.ncbi_fetch_proteins(\n"
            "    accessions=['AAB57849.1'],\n"
            "    output_dir='/workspace/output/bio/ncbi',\n"
            "    fields=['definition'],\n"
            ")\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    assert operation.adapter_envelope_schema_version == "s12.adapter_envelope.v1"
    assert operation.sdk_module == "bio"
    assert operation.function_name == "ncbi_fetch_proteins"
    assert operation.route_policy_id == "bio.ncbi_fetch_proteins.provider:v1"
    assert operation.selected_backend == "provider_http"
    assert operation.provider_config_digest == "provider_config:ncbi:v1"
    assert operation.expected_outputs_summary == {
        "output_dir": "/workspace/output/bio/ncbi"
    }

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "adapter_execution_unavailable" in run.stderr_summary
    assert "sandbox_transport_method_forbidden" not in run.stderr_summary
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.FAILED
    assert persisted.error_code == "adapter_execution_unavailable"


def test_sandbox_exec_public_bio_sdk_uses_adapter_executor_after_approval(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    calls: list[dict[str, object]] = []

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        calls.append(
            {
                "operation_id": operation.operation_id,
                "params": dict(envelope["adapter_params"]),
            }
        )
        return {
            "adapter_result": {
                "status": "succeeded",
                "provider_request_id": "provider_req_core",
                "registered_artifact_ids": ["artifact_provider_core"],
                "output_artifact_ids": ["artifact_provider_core"],
                "validation_results": {"artifact_provider_core": {"passed": True}},
                "bounded_summary": {"provider": "ncbi", "record_count": 1},
                "warnings": [],
            },
            "result_summary": {"provider": "ncbi", "record_count": 1},
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_sdk.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import bio\n"
            "result = bio.ncbi_fetch_proteins(\n"
            "    accessions=['AAB57849.1'],\n"
            "    output_dir='/workspace/output/bio/ncbi',\n"
            "    fields=['definition'],\n"
            ")\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert (
        payload["adapter_result_envelope"]["provider_request_id"] == "provider_req_core"
    )
    assert (
        payload["adapter_result_envelope"]["result_origin"] == "host_adapter_executor"
    )
    assert payload["adapter_result_envelope"]["registered_artifact_ids"] == [
        "artifact_provider_core"
    ]
    assert calls == [
        {
            "operation_id": operation.operation_id,
            "params": {
                "accessions": ["AAB57849.1"],
                "fields": ["definition"],
                "output_dir": "/workspace/output/bio/ncbi",
            },
        }
    ]
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.COMPLETED
    assert persisted.error_code is None


def test_sandbox_exec_public_rcsb_sdk_uses_s12_controlled_operation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    calls: list[dict[str, object]] = []
    manifest = {
        "artifact_id": "art_rcsb_6leh",
        "kind": "structure",
        "relative_path": "rcsb_pdb/6leh/provider_parsed/6LEH.pdb",
        "format": "pdb",
        "provider": "rcsb_pdb",
        "external_id": "6LEH",
        "content_digest": "sha256:rcsb-content",
        "sealed_digest": "sha256:rcsb-content",
        "provenance": {
            "provider": "rcsb_pdb",
            "external_id": "6LEH",
            "format": "pdb",
            "digest": "sha256:rcsb-content",
        },
    }

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        calls.append(
            {
                "operation_id": operation.operation_id,
                "params": dict(envelope["adapter_params"]),
            }
        )
        result_summary = {
            "provider": "rcsb_pdb",
            "pdb_id": "6LEH",
            "format": "pdb",
            "artifacts": [manifest],
        }
        return {
            "adapter_result": {
                "status": "succeeded",
                "provider_request_id": "provider_req_rcsb_core",
                "registered_artifact_ids": ["art_rcsb_6leh"],
                "output_artifact_ids": ["art_rcsb_6leh"],
                "validation_results": {"art_rcsb_6leh": {"passed": True}},
                "bounded_summary": result_summary,
                "warnings": [],
            },
            "result_summary": result_summary,
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_rcsb_sdk.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import rcsb_pdb\n"
            "result = rcsb_pdb.download_structure(\n"
            "    pdb_id='6LEH',\n"
            "    format='pdb',\n"
            "    output_dir='/workspace/output/rcsb_pdb/6leh',\n"
            ")\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_rcsb_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    assert operation.adapter_envelope_schema_version == "s12.adapter_envelope.v1"
    assert operation.sdk_module == "rcsb_pdb"
    assert operation.function_name == "download_structure"
    assert operation.route_policy_id == "rcsb_pdb.download_structure.provider:v1"
    assert operation.selected_backend == "provider_http"
    assert operation.provider_config_digest == "provider_config:rcsb_pdb:v1"
    assert operation.expected_outputs_summary == {
        "output_dir": "/workspace/output/rcsb_pdb/6leh"
    }

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    artifact = payload["result_summary"]["artifacts"][0]
    assert artifact["content_digest"] == "sha256:rcsb-content"
    assert artifact["sealed_digest"] == "sha256:rcsb-content"
    assert artifact["provenance"]["provider"] == "rcsb_pdb"
    assert "storage_uri" not in json.dumps(payload)
    assert "sandbox_transport_method_forbidden" not in run.stderr_summary
    assert calls == [
        {
            "operation_id": operation.operation_id,
            "params": {
                "pdb_id": "6LEH",
                "format": "pdb",
                "output_dir": "/workspace/output/rcsb_pdb/6leh",
            },
        }
    ]


def test_sandbox_exec_public_bio_tools_hpc_run_can_fetch_declared_outputs(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    adapter_calls: list[dict[str, object]] = []
    fetch_calls: list[dict[str, object]] = []
    safe_toolchain_identity = {
        "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
        "attestation_scope": "same_ssh_login_shell_pre_exec",
        "execution_mode": "ssh",
        "tool_id": "bio_tools.mafft",
        "adapter_id": "bio_tools.mafft",
        "command_template_id": "bio_tools_mafft_sif_v1",
        "runner_contract_digest": "sha256:" + "a" * 64,
        "image_digest": "sha256:" + "b" * 64,
    }

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        params = dict(envelope["adapter_params"])
        adapter_calls.append({"operation_id": operation.operation_id, "params": params})
        run_handle = {
            "kind": "hpc_run_handle",
            "run_id": "run_hpc_core",
            "runner_run_id": "runner_hpc_core",
            "status": "succeeded",
            "execution_mode": "ssh",
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "hpc_workspace_id": operation.hpc_workspace_id,
            "declared_outputs": list(params["expected_outputs"]),
            "summary": "bio_tools.mafft placement operation succeeded",
            "warnings": [],
            "toolchain_runtime_identity": {
                **safe_toolchain_identity,
                "sif_path": "/private/tool.sif",
                "command": ["apptainer", "exec", "/private/tool.sif"],
                "secret": "must-not-propagate",
            },
        }
        return {
            "adapter_result": {
                "status": "succeeded",
                "backend_run_id": "runner_hpc_core",
                "fetch_refs": [],
                "registered_artifact_ids": [],
                "output_artifact_ids": [],
                "bounded_summary": run_handle,
                "warnings": [],
            },
            "result_summary": run_handle,
        }

    def _hpc_fetch_executor(params: dict[str, object]) -> dict[str, object]:
        fetch_calls.append(dict(params))
        return {
            "kind": "hpc_fetch_result",
            "run_id": params["run_id"],
            "status": "succeeded",
            "registered_artifact_ids": ["artifact_alignment_core"],
            "fetch_refs": [
                {
                    "fetch_ref_id": "fetch_alignment_core",
                    "run_id": params["run_id"],
                    "declared_output_path": "bio_tools/mafft/alignment.fasta",
                    "registered_artifact_id": "artifact_alignment_core",
                    "output_digest": "sha256:alignment",
                }
            ],
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
        hpc_fetch_executor=_hpc_fetch_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_tools_fetch.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts, bio_tools, hpc\n"
            "path = Path('output/inputs/reference.fasta')\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text('>one\\nMSEQONE\\n>two\\nMSEQTWO\\n', encoding='utf-8')\n"
            "registered = artifacts.register('/workspace/output/inputs/reference.fasta', kind='sequence', format='fasta')\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "stage_ref = ws.stage_artifact(registered['artifact']['artifact_id'], workspace_path='inputs/reference.fasta')\n"
            "run = bio_tools.mafft(\n"
            "    input_fasta=stage_ref,\n"
            "    placement=ws,\n"
            "    expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence', 'format': 'fasta'}],\n"
            ")\n"
            "fetch = ws.fetch_outputs(run)\n"
            "print(json.dumps({'run': run, 'fetch': fetch}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_tools_fetch.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    assert operation.sandbox_run_id == run.sandbox_run_id
    assert operation.source_snapshot_artifact_id == run.source_snapshot_artifact_id
    assert operation.source_snapshot_digest == run.source_tree_digest
    input_artifact = repositories.artifacts.get(operation.input_artifact_ids[0])
    assert input_artifact is not None
    input_metadata = dict(input_artifact.metadata or {})
    assert (
        input_metadata["source_snapshot_artifact_id"] == run.source_snapshot_artifact_id
    )
    assert (
        dict(input_metadata["provenance"])["source_snapshot_artifact_id"]
        == run.source_snapshot_artifact_id
    )
    payload = json.loads(str(run.stdout_summary))
    assert payload["run"]["kind"] == "hpc_run_handle"
    assert payload["run"]["run_id"] == "run_hpc_core"
    assert payload["run"]["operation_id"] == operation.operation_id
    assert payload["run"]["toolchain_runtime_identity"] == safe_toolchain_identity
    assert "/private/tool.sif" not in json.dumps(payload["run"])
    assert "must-not-propagate" not in json.dumps(payload["run"])
    assert payload["fetch"]["registered_artifact_ids"] == ["artifact_alignment_core"]
    assert adapter_calls[0]["operation_id"] == operation.operation_id
    assert fetch_calls[0]["operation_id"] == operation.operation_id
    assert fetch_calls[0]["operation_digest"] == operation.operation_digest
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.COMPLETED
    assert persisted.result_summary is not None
    assert (
        persisted.result_summary["toolchain_runtime_identity"]
        == safe_toolchain_identity
    )
    assert persisted.adapter_result_envelope is not None
    assert persisted.adapter_result_envelope["registered_artifact_ids"] == [
        "artifact_alignment_core"
    ]
    assert (
        persisted.adapter_result_envelope["fetch_refs"][0]["fetch_ref_id"]
        == "fetch_alignment_core"
    )
    assert (
        persisted.adapter_result_envelope["bounded_summary"][
            "toolchain_runtime_identity"
        ]
        == safe_toolchain_identity
    )


def test_sandbox_exec_public_artifacts_hpc_and_bio_tools_sdk_use_control_socket(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_tools_sdk.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts, bio_tools, hpc\n"
            "path = Path('output/inputs/reference.fasta')\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text('>one\\nMSEQONE\\n>two\\nMSEQTWO\\n', encoding='utf-8')\n"
            "registered = artifacts.register('/workspace/output/inputs/reference.fasta', kind='sequence', format='fasta')\n"
            "artifact_id = registered['artifact']['artifact_id']\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "stage_ref = ws.stage_artifact(artifact_id, workspace_path='inputs/reference.fasta')\n"
            "result = bio_tools.mafft(\n"
            "    input_fasta=stage_ref,\n"
            "    placement=ws,\n"
            "    expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence', 'format': 'fasta'}],\n"
            ")\n"
            "print(json.dumps({'registered': registered, 'stage_ref': stage_ref, 'result': result}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_tools_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    assert operation.adapter_envelope_schema_version == "s12.adapter_envelope.v1"
    assert operation.sdk_module == "bio_tools"
    assert operation.function_name == "mafft"
    assert operation.route_policy_id == "bio_tools.mafft.hpc:v1"
    assert operation.selected_backend == "hpc"
    assert operation.placement == "hpc"
    assert operation.hpc_workspace_id
    assert len(operation.stage_refs) == 1
    assert operation.stage_refs[0]["kind"] == "hpc_stage_ref"
    assert operation.stage_refs[0]["artifact_id"]
    assert operation.planned_fetch_intent == {
        "declared_outputs": [
            {
                "path": "bio_tools/mafft/alignment.fasta",
                "kind": "sequence",
                "format": "fasta",
            }
        ]
    }

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "adapter_execution_unavailable" in run.stderr_summary
    registered_artifacts = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.relative_path == "inputs/reference.fasta"
    ]
    assert registered_artifacts
    assert "sandbox_transport_method_forbidden" not in run.stderr_summary
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.FAILED
    assert persisted.error_code == "adapter_execution_unavailable"


def test_sandbox_exec_public_structure_tools_fpocket_uses_controlled_operation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_fpocket_sdk.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts, hpc, structure_tools\n"
            "lines = ['HEADER    OPENZYME FPOCKET FIXTURE']\n"
            "atom_id = 1\n"
            "for residue in range(1, 17):\n"
            "    for atom_name in ('N', 'CA', 'C', 'O'):\n"
            "        lines.append(\n"
            "            f'ATOM  {atom_id:5d} {atom_name:^4s} ALA A{residue:4d}    '\n"
            "            f'{residue + atom_id / 100:8.3f}{residue + 1.0:8.3f}{residue + 2.0:8.3f}'\n"
            "            '  1.00 20.00           C'\n"
            "        )\n"
            "        atom_id += 1\n"
            "lines.append('END')\n"
            "path = Path('output/inputs/structure.pdb')\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text('\\n'.join(lines) + '\\n', encoding='utf-8')\n"
            "registered = artifacts.register('/workspace/output/inputs/structure.pdb', kind='structure', format='pdb')\n"
            "artifact_id = registered['artifact']['artifact_id']\n"
            "ws = hpc.workspace('fpocket')\n"
            "stage_ref = ws.stage_artifact(artifact_id, workspace_path='inputs/structure.pdb')\n"
            "result = structure_tools.fpocket(\n"
            "    structure=stage_ref,\n"
            "    placement=ws,\n"
            "    expected_outputs=[{'path': 'target_out', 'kind': 'directory', 'format': 'fpocket'}],\n"
            ")\n"
            "print(json.dumps({'registered': registered, 'stage_ref': stage_ref, 'result': result}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_fpocket_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    assert operation.adapter_envelope_schema_version == "s12.adapter_envelope.v1"
    assert operation.sdk_module == "structure_tools"
    assert operation.function_name == "fpocket"
    assert operation.route_policy_id == "structure_tools.fpocket.hpc:v1"
    assert operation.selected_backend == "hpc"
    assert operation.placement == "hpc"
    assert operation.hpc_workspace_id
    assert operation.input_artifact_ids
    assert operation.input_artifact_digests
    assert len(operation.stage_refs) == 1
    assert operation.stage_refs[0]["kind"] == "hpc_stage_ref"
    assert operation.stage_refs[0]["artifact_id"] == operation.input_artifact_ids[0]
    assert (
        operation.stage_refs[0]["artifact_digest"]
        == operation.input_artifact_digests[0]
    )
    assert operation.expected_outputs_summary == {
        "items": [{"path": "target_out", "kind": "directory", "format": "fpocket"}]
    }
    assert operation.planned_fetch_intent == {
        "declared_outputs": [
            {"path": "target_out", "kind": "directory", "format": "fpocket"}
        ]
    }

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "adapter_execution_unavailable" in run.stderr_summary
    assert "sandbox_transport_method_forbidden" not in run.stderr_summary


def test_sandbox_exec_public_hpc_fetch_outputs_fails_structured_without_run(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_hpc_fetch.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import hpc\n"
            "from openzyme_pipeline.client import PipelineSdkError\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "try:\n"
            "    ws.fetch_outputs({'run_id': 'run_missing'})\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({'error_code': exc.error_code, 'message': exc.message}, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected hpc.fetch_outputs to fail')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/public_hpc_fetch.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "error_code": "hpc_fetch_not_declared",
        "message": "hpc.fetch_outputs requires a completed Host-supervised HPC run with declared outputs",
    }
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_hpc_fetch_preserves_typed_failure_for_pipeline_sdk(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    fetch_calls: list[str] = []

    class TypedFetchFailure(RuntimeError):
        error_type = "hpc_staging_failed"
        message = "HPC output staging failed before transfer."
        hint = "Retry only in a fresh attempt after checking runner connectivity."
        stage = "hpc_staging"
        retryable = True
        details = {
            "runner_failure": {
                "schema_id": "runner_failure@1",
                "run_id": "runner_attempt_002",
                "phase": "input_parent",
                "input_ordinal": 1,
                "content_digest": "sha256:" + "b" * 64,
                "returncode": 255,
                "timed_out": False,
                "elapsed_seconds": 60.5,
            },
            "remote_path": "/private/runner/output.fasta",
        }

    def _hpc_fetch_executor(params: dict[str, object]) -> dict[str, object]:
        fetch_calls.append(str(params["run_id"]))
        raise TypedFetchFailure

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        hpc_fetch_executor=_hpc_fetch_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/typed_hpc_fetch_failure.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import hpc\n"
            "from openzyme_pipeline.client import PipelineSdkError\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "try:\n"
            "    ws.fetch_outputs({'run_id': 'run_staging_failed'})\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({\n"
            "        'error_code': exc.error_code,\n"
            "        'stage': exc.stage,\n"
            "        'retryable': exc.retryable,\n"
            "        'hint': exc.hint,\n"
            "        'details': exc.details,\n"
            "        'display_message': str(exc),\n"
            "    }, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected typed HPC fetch failure')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/typed_hpc_fetch_failure.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED, run.stderr_summary
    payload = json.loads(str(run.stdout_summary))
    assert payload["error_code"] == "hpc_staging_failed"
    assert payload["stage"] == "hpc_staging"
    assert payload["retryable"] is True
    assert payload["hint"] == (
        "Retry only in a fresh attempt after checking runner connectivity."
    )
    assert "stage=hpc_staging" in payload["display_message"]
    assert "retryable=True" in payload["display_message"]
    assert payload["details"]["run_id"] == "run_staging_failed"
    assert payload["details"]["operation_id"] is None
    assert payload["details"]["stage"] == "hpc_staging"
    assert payload["details"]["retryable"] is True
    assert payload["details"]["runner_failure"]["phase"] == "input_parent"
    serialized = json.dumps(payload, sort_keys=True)
    assert "remote_path" not in serialized
    assert "/private/runner" not in serialized
    assert fetch_calls == ["run_staging_failed"]
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_s12_route_policy_failures_do_not_create_operations(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_route_failures.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "cases = {\n"
            "    'missing_policy': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'idempotency_key': 's12_missing_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'unknown_policy': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio.unknown.provider:v1',\n"
            "        'idempotency_key': 's12_unknown_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'fixture': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'test.fixture_adapter:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'mafft',\n"
            "        'idempotency_key': 's12_fixture_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'prerequisite': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'test.prerequisite_missing:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'mafft',\n"
            "        'idempotency_key': 's12_prerequisite_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'disabled': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio_tools.hmmer_search_cli.disabled:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'hmmer_search_cli',\n"
            "        'idempotency_key': 's12_disabled_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'mismatch': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'mafft',\n"
            "        'idempotency_key': 's12_mismatch_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "}\n"
            "errors = {}\n"
            "for name, params in cases.items():\n"
            "    try:\n"
            "        call('s10.controlled_operation', params)\n"
            "    except PipelineSdkError as exc:\n"
            "        errors[name] = exc.error_code\n"
            "    else:\n"
            "        raise SystemExit(f'expected {name} failure')\n"
            "print(json.dumps(errors, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/s12_route_failures.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "disabled": "unsupported_in_s14",
        "fixture": "fixture_backend_forbidden",
        "mismatch": "adapter_schema_incompatible",
        "missing_policy": "route_policy_missing",
        "prerequisite": "operation_prerequisite_missing",
        "unknown_policy": "route_policy_missing",
    }
    assert repositories.approvals.list_by_session(session.session_id) == []
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_runtime_s14_bio_tool_route_policy_table_is_fail_closed() -> None:
    enabled = {
        "bio_tools.cdhit.hpc:v1": ("cdhit", "cdhit_4.8.1.hpc_apptainer_sif:v1"),
        "bio_tools.mafft.hpc:v1": ("mafft", "mafft_7.525.hpc_apptainer_sif:v1"),
        "bio_tools.hmmbuild.hpc:v1": (
            "hmmbuild",
            "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1",
        ),
        "bio_tools.hmmalign.hpc:v1": (
            "hmmalign",
            "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1",
        ),
    }
    for route_policy_id, (function_name, toolchain_id) in enabled.items():
        policy = S12_ROUTE_POLICIES[route_policy_id]
        assert policy["sdk_module"] == "bio_tools"
        assert policy["function_name"] == function_name
        assert policy["selected_backend"] == "hpc"
        assert policy["backend_category"] == "hpc_runner"
        assert policy["runtime_packaging_id"] == "hpc_apptainer_sif.aox_hmm_2026_05_30"
        assert policy["toolchain_id"] == toolchain_id
        assert policy["status"] == "ok"
        assert policy["evidence_ref"]
        assert policy["parameter_inventory_ref"]

    disabled = S12_ROUTE_POLICIES["bio_tools.hmmer_search_cli.disabled:v1"]
    assert disabled["sdk_module"] == "bio_tools"
    assert disabled["function_name"] == "hmmer_search_cli"
    assert disabled["selected_backend"] == "disabled"
    assert disabled["status"] == "disabled"
    assert disabled["error_code"] == "unsupported_in_s14"


def test_sandbox_exec_s12_hpc_requires_explicit_placement_stage_and_fetch_intent(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        del operation, envelope
        return {
            "adapter_result": {
                "status": "completed",
                "backend_run_id": "slurm_123",
                "fetch_refs": [
                    {
                        "fetch_ref_id": "fetch_alignment",
                        "remote_path": "hpc://private/out",
                    }
                ],
                "registered_artifact_ids": ["artifact_alignment"],
                "validation_results": {"alignment": "ok"},
                "bounded_summary": {"outputs": 1},
            },
            "result_summary": {"outputs": 1},
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    input_digest = "sha256:" + "a" * 64
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_hpc.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call, canonical_digest\n"
            "stage_ref = {\n"
            "    'kind': 'hpc_stage_ref',\n"
            "    'stage_ref_id': 'stage_input_001',\n"
            "    'hpc_workspace_id': 'hpcws_s12',\n"
            "    'artifact_id': 'artifact_input_fasta',\n"
            f"    'artifact_digest': '{input_digest}',\n"
            "    'workspace_relative_path': 'inputs/query.fasta',\n"
            "    'remote_path': 'hpc://private/input.fasta',\n"
            "}\n"
            "fetch_intent = {\n"
            "    'declared_outputs': [\n"
            "        {'path': 'outputs/alignment.fasta', 'format': 'fasta', 'remote_path': 'hpc://private/out'}\n"
            "    ],\n"
            "    'remote_path': 'hpc://private/run',\n"
            "}\n"
            "adapter_params = {'input_fasta': stage_ref}\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio_tools.mafft.hpc:v1',\n"
            "    'sdk_module': 'bio_tools',\n"
            "    'function_name': 'mafft',\n"
            "    'params_digest': canonical_digest(adapter_params),\n"
            "    'params': adapter_params,\n"
            "    'input_artifact_ids': ['artifact_input_fasta'],\n"
            f"    'input_artifact_digests': ['{input_digest}'],\n"
            "    'expected_outputs': [{'path': 'outputs/alignment.fasta'}],\n"
            "    'resource_estimate': {'walltime_minutes': 5},\n"
            "}\n"
            "errors = {}\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(\n"
            "        base,\n"
            "        idempotency_key='s12_hpc_missing_placement',\n"
            "        hpc_workspace_id='hpcws_s12',\n"
            "        stage_refs=[stage_ref],\n"
            "        planned_fetch_intent=fetch_intent,\n"
            "    ))\n"
            "except PipelineSdkError as exc:\n"
            "    errors['missing_placement'] = exc.error_code\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(\n"
            "        base,\n"
            "        idempotency_key='s12_hpc_bad_path',\n"
            "        placement='hpc',\n"
            "        hpc_workspace_id='hpcws_s12',\n"
            "        stage_refs=[dict(stage_ref, workspace_relative_path='/remote/input.fasta')],\n"
            "        planned_fetch_intent=fetch_intent,\n"
            "    ))\n"
            "except PipelineSdkError as exc:\n"
            "    errors['bad_stage_path'] = exc.error_code\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(\n"
            "        base,\n"
            "        idempotency_key='s12_hpc_empty_approved_inputs',\n"
            "        placement='hpc',\n"
            "        hpc_workspace_id='hpcws_s12',\n"
            "        input_artifact_ids=[],\n"
            "        input_artifact_digests=[],\n"
            "        stage_refs=[stage_ref],\n"
            "        planned_fetch_intent=fetch_intent,\n"
            "    ))\n"
            "except PipelineSdkError as exc:\n"
            "    errors['empty_approved_inputs'] = exc.error_code\n"
            "try:\n"
            "    changed_params = {'input_fasta': dict(stage_ref, artifact_id='artifact_other')}\n"
            "    call('s10.controlled_operation', dict(\n"
            "        base,\n"
            "        idempotency_key='s12_hpc_param_ref_mismatch',\n"
            "        params=changed_params,\n"
            "        params_digest=canonical_digest(changed_params),\n"
            "        placement='hpc',\n"
            "        hpc_workspace_id='hpcws_s12',\n"
            "        stage_refs=[stage_ref],\n"
            "        planned_fetch_intent=fetch_intent,\n"
            "    ))\n"
            "except PipelineSdkError as exc:\n"
            "    errors['param_ref_mismatch'] = exc.error_code\n"
            "result = call('s10.controlled_operation', dict(\n"
            "    base,\n"
            "    idempotency_key='s12_hpc_valid',\n"
            "    placement='hpc',\n"
            "    hpc_workspace_id='hpcws_s12',\n"
            "    stage_refs=[stage_ref],\n"
            "    planned_fetch_intent=fetch_intent,\n"
            "))\n"
            "print(json.dumps({'errors': errors, 'result': result}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_hpc.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    approval_envelope = operation.adapter_approval_envelope or {}
    assert approval_envelope["placement"] == "hpc"
    assert approval_envelope["hpc_workspace_id"] == "hpcws_s12"
    assert approval_envelope["stage_refs"] == [
        {
            "kind": "hpc_stage_ref",
            "stage_ref_id": "stage_input_001",
            "hpc_workspace_id": "hpcws_s12",
            "artifact_id": "artifact_input_fasta",
            "artifact_digest": input_digest,
            "workspace_relative_path": "inputs/query.fasta",
        }
    ]
    assert approval_envelope["planned_fetch_intent"] == {
        "declared_outputs": [{"path": "outputs/alignment.fasta", "format": "fasta"}]
    }
    assert "fetch_refs" not in approval_envelope
    assert "remote_path" not in json.dumps(approval_envelope, sort_keys=True)

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["errors"] == {
        "bad_stage_path": "hpc_stage_path_invalid",
        "empty_approved_inputs": "adapter_input_binding_mismatch",
        "missing_placement": "hpc_workspace_forbidden",
        "param_ref_mismatch": "adapter_input_binding_mismatch",
    }
    result_envelope = payload["result"]["adapter_result_envelope"]
    assert result_envelope["backend_run_id"] == "slurm_123"
    assert result_envelope["registered_artifact_ids"] == ["artifact_alignment"]
    assert result_envelope["bounded_summary"] == {"outputs": 1}
    assert "remote_path" not in json.dumps(result_envelope, sort_keys=True)
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert len(operations) == 1
    assert operations[0].operation_id == operation.operation_id


def test_sandbox_exec_s12_reuses_only_host_persisted_result_without_second_executor(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    executor_calls: list[str] = []

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        del envelope
        executor_calls.append(operation.operation_id)
        return {
            "adapter_result": {
                "status": "completed",
                "provider_request_id": "provider_req_host",
                "bounded_summary": {"records": 1},
            },
            "result_summary": {"records": 1},
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_drift.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call, canonical_digest\n"
            "adapter_params = {'accessions': ['P12345']}\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.uniprot_fetch.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'uniprot_fetch',\n"
            "    'params_digest': canonical_digest(adapter_params),\n"
            "    'params': adapter_params,\n"
            "    'expected_outputs': {'kind': 'fasta'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "}\n"
            "first = call(\n"
            "    's10.controlled_operation',\n"
            "    dict(base, idempotency_key='s12_reuse_a'),\n"
            ")\n"
            "second = call(\n"
            "    's10.controlled_operation',\n"
            "    dict(base, idempotency_key='s12_reuse_b'),\n"
            ")\n"
            "try:\n"
            "    changed_params = {'accessions': ['Q99999']}\n"
            "    call(\n"
            "        's10.controlled_operation',\n"
            "        dict(\n"
            "            base,\n"
            "            idempotency_key='s12_reuse_a',\n"
            "            params=changed_params,\n"
            "            params_digest=canonical_digest(changed_params),\n"
            "        ),\n"
            "    )\n"
            "except PipelineSdkError as exc:\n"
            "    drift_error = exc.error_code\n"
            "else:\n"
            "    raise SystemExit('expected S12 digest drift')\n"
            "print(json.dumps({\n"
            "    'drift_error': drift_error,\n"
            "    'first_operation': first['operation_id'],\n"
            "    'second_operation': second['operation_id'],\n"
            "    'second_provider_request_id': second['adapter_result_envelope']['provider_request_id'],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_drift.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["drift_error"] == "operation_drift_detected"
    assert payload["first_operation"] != payload["second_operation"]
    assert payload["second_provider_request_id"] == "provider_req_host"
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert len(operations) == 2
    assert len(repositories.approvals.list_by_session(session.session_id)) == 1
    assert executor_calls == [payload["first_operation"]]
    assert {operation.operation_digest for operation in operations} == {
        operations[0].operation_digest
    }
    for operation in operations:
        assert operation.adapter_result_envelope is not None
        assert (
            operation.adapter_result_envelope["provider_request_id"]
            == "provider_req_host"
        )
        assert (
            operation.adapter_result_envelope["result_origin"]
            == "host_adapter_executor"
        )


def test_sandbox_exec_s12_untrusted_legacy_result_requires_fresh_approval(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "legacy-result-reuse.sqlite3"
    service_connection = connect_sqlite(
        str(database_path),
        check_same_thread=False,
    )
    apply_sqlite_migrations(service_connection)
    repositories = CoreRepositories.from_connection(service_connection)

    @contextmanager
    def repository_scope():  # type: ignore[no-untyped-def]
        connection = connect_sqlite(str(database_path), check_same_thread=False)
        try:
            yield CoreRepositories.from_connection(connection)
        finally:
            connection.close()

    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    executor_calls: list[str] = []

    def _adapter_executor(
        operation: ControlledOperation, envelope: dict[str, object]
    ) -> dict[str, object]:
        del envelope
        executor_calls.append(operation.operation_id)
        request_id = f"provider_req_host_{len(executor_calls)}"
        return {
            "adapter_result": {
                "status": "completed",
                "provider_request_id": request_id,
                "bounded_summary": {"records": 1},
            },
            "result_summary": {"records": 1},
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
        repository_scope_factory=repository_scope,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_legacy_reuse.py",
        content=(
            "import json\n"
            "import time\n"
            "from openzyme_pipeline.client import call, canonical_digest\n"
            "adapter_params = {'accessions': ['P12345']}\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.uniprot_fetch.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'uniprot_fetch',\n"
            "    'params_digest': canonical_digest(adapter_params),\n"
            "    'params': adapter_params,\n"
            "    'expected_outputs': {'kind': 'fasta'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "}\n"
            "first = call(\n"
            "    's10.controlled_operation',\n"
            "    dict(base, idempotency_key='s12_legacy_reuse_a'),\n"
            ")\n"
            "time.sleep(1.0)\n"
            "try:\n"
            "    call(\n"
            "        's10.controlled_operation',\n"
            "        dict(base, idempotency_key='s12_legacy_reuse_a'),\n"
            "    )\n"
            "except Exception as exc:\n"
            "    same_key_error = getattr(exc, 'error_code', type(exc).__name__)\n"
            "else:\n"
            "    raise SystemExit('expected untrusted origin rejection')\n"
            "fresh = call(\n"
            "    's10.controlled_operation',\n"
            "    dict(base, idempotency_key='s12_legacy_reuse_b'),\n"
            ")\n"
            "print(json.dumps({\n"
            "    'first_provider_request_id': first['adapter_result_envelope']['provider_request_id'],\n"
            "    'same_key_error': same_key_error,\n"
            "    'fresh_provider_request_id': fresh['adapter_result_envelope']['provider_request_id'],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_legacy_reuse.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    observer_connection = connect_sqlite(str(database_path), check_same_thread=False)
    observer = CoreRepositories.from_connection(observer_connection)
    pending = _wait_for_pending_approval(observer, session.session_id)
    _resolve_s10_approval(observer, pending.approval_id, decision="approved")

    first_operation: ControlledOperation | None = None
    for _ in range(100):
        operations = observer.controlled_operations.list_by_session(
            session.session_id
        )
        if (
            len(operations) == 1
            and operations[0].status is ControlledOperationStatus.COMPLETED
        ):
            first_operation = operations[0]
            break
        time.sleep(0.01)
    assert first_operation is not None
    legacy_result = dict(first_operation.adapter_result_envelope or {})
    assert legacy_result["result_origin"] == "host_adapter_executor"
    observer.controlled_operations.save(
        # Simulate a pre-migration row whose caller-controlled JSON happens to
        # contain the new marker.  Only the Host-owned column grants reuse.
        replace(first_operation, adapter_result_origin=None)
    )

    fresh_approval = _wait_for_pending_approval(observer, session.session_id)
    assert fresh_approval.approval_id != pending.approval_id
    _resolve_s10_approval(
        observer,
        fresh_approval.approval_id,
        decision="approved",
    )

    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "first_provider_request_id": "provider_req_host_1",
        "same_key_error": "adapter_result_origin_untrusted",
        "fresh_provider_request_id": "provider_req_host_2",
    }
    assert len(observer.approvals.list_by_session(session.session_id)) == 2
    assert len(executor_calls) == 2
    observer_connection.close()
    service_connection.close()


def test_sandbox_exec_controlled_operation_reuses_approved_digest_without_second_approval(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_reuse.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "base = {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'logical_operation_key': 'fake.reuse',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "}\n"
            "first = call('s10.controlled_operation', dict(base, idempotency_key='op_reuse_a'))\n"
            "second = call('s10.controlled_operation', dict(base, idempotency_key='op_reuse_b'))\n"
            "print(json.dumps({\n"
            "    'first_approval': first['approval_id'],\n"
            "    'second_approval': second['approval_id'],\n"
            "    'same_operation': first['operation_id'] == second['operation_id'],\n"
            "    'statuses': [first['status'], second['status']],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_reuse.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["first_approval"] == pending.approval_id
    assert payload["second_approval"] == pending.approval_id
    assert payload["same_operation"] is False
    assert payload["statuses"] == ["completed", "completed"]
    assert len(repositories.approvals.list_by_session(session.session_id)) == 1
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert [operation.status for operation in operations] == [
        ControlledOperationStatus.COMPLETED,
        ControlledOperationStatus.COMPLETED,
    ]

    replay_run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/s10_reuse.py"],
        timeout_seconds=10,
    )

    assert replay_run.status is SandboxRunStatus.COMPLETED
    replay_payload = json.loads(str(replay_run.stdout_summary))
    assert replay_payload["first_approval"] == pending.approval_id
    assert replay_payload["second_approval"] == pending.approval_id
    assert len(repositories.approvals.list_by_session(session.session_id)) == 1


def test_sandbox_exec_controlled_operation_does_not_reuse_rejected_digest(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_rejected_no_reuse.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "base = {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'logical_operation_key': 'fake.rejected_no_reuse',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "}\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(base, idempotency_key='op_rejected_a'))\n"
            "except PipelineSdkError as exc:\n"
            "    rejected_error = exc.error_code\n"
            "else:\n"
            "    raise SystemExit('expected rejected operation')\n"
            "second = call('s10.controlled_operation', dict(base, idempotency_key='op_rejected_b'))\n"
            "print(json.dumps({\n"
            "    'rejected_error': rejected_error,\n"
            "    'second_approval': second['approval_id'],\n"
            "    'second_status': second['status'],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_rejected_no_reuse.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    first_pending = _wait_for_pending_approval(repositories, session.session_id)
    first_operation = repositories.controlled_operations.get(
        str(first_pending.request_ref)
    )
    assert first_operation is not None
    _resolve_s10_approval(
        repositories,
        first_pending.approval_id,
        decision="rejected",
    )
    second_pending = _wait_for_pending_approval(repositories, session.session_id)
    second_operation = repositories.controlled_operations.get(
        str(second_pending.request_ref)
    )
    assert second_operation is not None
    assert second_pending.approval_id != first_pending.approval_id
    assert second_operation.operation_digest == first_operation.operation_digest
    _resolve_s10_approval(
        repositories,
        second_pending.approval_id,
        decision="approved",
    )
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload == {
        "rejected_error": "approval_rejected",
        "second_approval": second_pending.approval_id,
        "second_status": "completed",
    }
    completed_first = repositories.controlled_operations.get(
        first_operation.operation_id
    )
    completed_second = repositories.controlled_operations.get(
        second_operation.operation_id
    )
    assert completed_first is not None
    assert completed_first.status is ControlledOperationStatus.FAILED
    assert completed_second is not None
    assert completed_second.status is ControlledOperationStatus.COMPLETED


def test_sandbox_exec_requires_source_snapshot_and_forbids_env_secrets(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )

    with pytest.raises(SandboxRuntimeError) as empty_source:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "-c", "print('no source')"],
        )
    assert empty_source.value.error_code == "source_snapshot_empty"
    assert empty_source.value.hint == (
        "Author at least one eligible regular file under /workspace/src before calling "
        "sandbox.exec; sandbox.exec snapshots the whole source tree. This failure "
        "occurs before SandboxRun creation or process invocation."
    )
    assert (
        repositories.sandbox_runs.list_by_workspace(workspace.sandbox_workspace_id)
        == []
    )
    assert repositories.artifacts.list_by_session(session.session_id) == []

    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/script.py",
        content="print('ready')\n",
        create_dirs=True,
    )
    with pytest.raises(SandboxRuntimeError) as bad_env:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/script.py"],
            env={"OPENAI_API_KEY": "secret"},
        )
    assert bad_env.value.error_code == "sandbox_env_forbidden"


def test_sandbox_exec_rejects_unwrapped_python_heredoc_before_snapshot(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
    )

    with pytest.raises(SandboxRuntimeError) as invalid_argv:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "- <<'PY'\nprint('must not run')\nPY"],
        )

    assert invalid_argv.value.error_code == "sandbox_argv_shell_syntax_unsupported"
    assert invalid_argv.value.hint is not None
    assert "sandbox.file.write" in invalid_argv.value.hint
    assert (
        repositories.sandbox_runs.list_by_workspace(workspace.sandbox_workspace_id)
        == []
    )
    assert repositories.artifacts.list_by_session(session.session_id) == []
    for python_argv in (
        ("python3.12", "-u", "<<-EOF\nprint('must not run')\nEOF"),
        ("python3.13t", "-u", "- <<'EOF-1'\nprint('must not run')\nEOF-1"),
        ("python", "<<0\nprint('must not run')\n0"),
    ):
        with pytest.raises(SandboxRuntimeError) as unsupported:
            service._validate_argv(python_argv)
        assert unsupported.value.error_code == "sandbox_argv_shell_syntax_unsupported"

    for direct_argv in (
        ("python", "src/script.py", "<<literal"),
        ("python", "/workspace/src/parse.py", "<<EOF\npayload\nEOF"),
        ("python", "-c", "print(1 << 2)\n"),
        ("python", "-", "<<'PY'\npayload\nPY"),
        ("python-wrapper", "- <<'PY'\nprint('not an interpreter')\nPY"),
    ):
        assert service._validate_argv(direct_argv) == direct_argv
    explicit_shell = ("bash", "-lc", "python - <<'PY'\nprint('allowed')\nPY")
    assert service._validate_argv(explicit_shell) == explicit_shell


def test_sandbox_exec_timeout_nonzero_and_truncated_logs(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/fail.py",
        content=(
            "import sys\n"
            "print('/home/operator/private.log ' + 'x' * 40000)\n"
            "print('/scratch/slurm/private.err ' + 'y' * 40000, file=sys.stderr)\n"
            "raise SystemExit(7)\n"
        ),
        create_dirs=True,
    )

    failed = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/fail.py"],
    )
    assert failed.status is SandboxRunStatus.FAILED
    assert failed.exit_code == 7
    assert failed.error_code == "sandbox_exec_nonzero"
    assert failed.log_artifact_ref == f"sandbox-log://{failed.sandbox_run_id}/stdout"
    log_records = repositories.command_log_artifacts.list_by_run(failed.sandbox_run_id)
    assert len(log_records) == 2
    log_records_by_stream = {record.stream: record for record in log_records}
    log_root = tmp_path / "logs"
    run_log_root = log_root / failed.sandbox_run_id
    stdout_log = run_log_root / "stdout.log"
    stderr_log = run_log_root / "stderr.log"
    assert log_root.stat().st_mode & 0o777 == 0o700
    assert run_log_root.stat().st_mode & 0o777 == 0o700
    assert stdout_log.stat().st_mode & 0o777 == 0o600
    assert stderr_log.stat().st_mode & 0o777 == 0o600
    raw_stdout = stdout_log.read_bytes()
    raw_stderr = stderr_log.read_bytes()
    assert b"/home/operator/private.log" in raw_stdout
    assert b"/scratch/slurm/private.err" in raw_stderr
    assert log_records_by_stream["stdout"].size_bytes == len(raw_stdout)
    assert log_records_by_stream["stdout"].content_digest == (
        "sha256:" + hashlib.sha256(raw_stdout).hexdigest()
    )
    assert log_records_by_stream["stderr"].size_bytes == len(raw_stderr)
    assert log_records_by_stream["stderr"].content_digest == (
        "sha256:" + hashlib.sha256(raw_stderr).hexdigest()
    )
    assert all(record.truncated for record in log_records)
    stdout_ref = f"sandbox-log://{failed.sandbox_run_id}/stdout"
    stderr_ref = f"sandbox-log://{failed.sandbox_run_id}/stderr"
    assert log_records_by_stream["stdout"].artifact_ref == stdout_ref
    assert log_records_by_stream["stderr"].artifact_ref == stderr_ref
    assert failed.log_artifact_ref == stdout_ref
    assert failed.stdout_metadata == {
        "raw_digest": "sha256:" + hashlib.sha256(raw_stdout).hexdigest(),
        "raw_size_bytes": len(raw_stdout),
        "truncated": True,
        "log_ref": stdout_ref,
    }
    assert failed.stderr_metadata == {
        "raw_digest": "sha256:" + hashlib.sha256(raw_stderr).hexdigest(),
        "raw_size_bytes": len(raw_stderr),
        "truncated": True,
        "log_ref": stderr_ref,
    }
    assert "/home/operator/private.log" not in str(failed.stdout_summary)
    assert "/scratch/slurm/private.err" not in str(failed.stderr_summary)

    stored = repositories.sandbox_runs.get(failed.sandbox_run_id)
    assert stored is not None
    assert stored.stdout_metadata == failed.stdout_metadata
    assert stored.stderr_metadata == failed.stderr_metadata
    workspace_record = repositories.sandbox_workspaces.get(
        workspace.sandbox_workspace_id
    )
    assert workspace_record is not None
    assert workspace_record.last_command_summary is not None
    assert workspace_record.last_command_summary["stdout_metadata"] == (
        failed.stdout_metadata
    )
    assert workspace_record.last_command_summary["stderr_metadata"] == (
        failed.stderr_metadata
    )
    tool_result = _tool_success(
        ToolInvocation(
            call_id="call_dual_stdio",
            tool_name="sandbox.exec",
            arguments={},
        ),
        failed.to_dict(),
        status="sandbox_exec_finished",
    )
    tool_payload = json.loads(tool_result.content)
    assert tool_payload["stdout_metadata"] == failed.stdout_metadata
    assert tool_payload["stderr_metadata"] == failed.stderr_metadata
    assert tool_result.envelope()["payload"] == tool_payload

    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/invalid_utf8.py",
        content=("import os\nos.write(1, b'\\xff' * 40000)\nraise SystemExit(9)\n"),
        create_dirs=True,
    )
    invalid_utf8 = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/invalid_utf8.py"],
    )
    invalid_records = repositories.command_log_artifacts.list_by_run(
        invalid_utf8.sandbox_run_id
    )
    invalid_raw = (log_root / invalid_utf8.sandbox_run_id / "stdout.log").read_bytes()
    assert invalid_utf8.status is SandboxRunStatus.FAILED
    assert invalid_raw == b"\xff" * 40000
    assert invalid_records[0].size_bytes == 40000
    assert invalid_records[0].content_digest == (
        "sha256:" + hashlib.sha256(invalid_raw).hexdigest()
    )
    assert "�" in str(invalid_utf8.stdout_summary)
    assert len(str(invalid_utf8.stdout_summary).encode("utf-8")) <= 32 * 1024

    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/slow.py",
        content="import time\ntime.sleep(2)\n",
        create_dirs=True,
    )
    timed_out = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/slow.py"],
        timeout_seconds=1,
    )
    assert timed_out.status is SandboxRunStatus.TIMEOUT
    assert timed_out.error_code == "sandbox_exec_timeout"


def test_sandbox_command_log_root_rejects_symlink(tmp_path: Path) -> None:
    repositories = _build_repositories()
    target = tmp_path / "log-target"
    target.mkdir()
    log_root = tmp_path / "logs"
    log_root.symlink_to(target, target_is_directory=True)
    service = SandboxRuntimeService(repositories, log_root=log_root)

    with pytest.raises(SandboxRuntimeError) as error:
        service._log_root()

    assert error.value.error_code == "sandbox_log_boundary_invalid"


def test_sandbox_exec_podman_backend_uses_isolation_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        execution_backend="podman",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/podman.py",
        content="print('podman')\n",
        create_dirs=True,
    )
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(
        PodmanContainerLease,
        "require_absent_before_run",
        lambda self: None,
    )
    monkeypatch.setattr(PodmanContainerLease, "retire", lambda self: None)

    def fake_active_timeout(
        self: SandboxRuntimeService,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int,
        sandbox_run_id: str,
        control_server: _ControlSocketServer,
        container_lease: PodmanContainerLease | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del (
            self,
            cwd,
            env,
            timeout_seconds,
            sandbox_run_id,
            control_server,
            container_lease,
        )
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(
        SandboxRuntimeService, "_run_process_with_active_timeout", fake_active_timeout
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/podman.py"],
    )

    assert run.status is SandboxRunStatus.COMPLETED, (
        run.error_code,
        run.stderr_summary,
    )
    command = captured["command"]
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--memory=2g" in command
    assert "--cpus=2" in command
    assert "--pids-limit=256" in command
    assert any(item.endswith(":/workspace:ro,Z") for item in command)
    assert any(item.endswith(":/workspace/input:ro,Z") for item in command)
    assert any(item.endswith(":/openzyme/sdk:ro,Z") for item in command)
    assert "PYTHONPATH=/openzyme/sdk" in command
    assert "/openzyme/control.sock" in " ".join(command)
    assert "--name" in command
    cidfile = Path(command[command.index("--cidfile") + 1])
    assert cidfile.parent == workspace_root / ".podman-leases"
    assert workspace_root / workspace.sandbox_workspace_id not in cidfile.parents
    labels = [
        command[index + 1] for index, item in enumerate(command) if item == "--label"
    ]
    assert any(label.startswith("io.openzyme.run_id=") for label in labels)
    assert any(
        label.startswith("io.openzyme.sandbox_root_digest=sha256:") for label in labels
    )
    assert command[-3:] == [workspace.image_digest, "python", "src/podman.py"]
    assert run.compatibility is not None
    assert run.compatibility["pipeline_sdk_digest"].startswith("sha256:")
    assert run.compatibility["runtime_identity_digest"].startswith("sha256:")


def test_sandbox_exec_podman_timeout_retires_container_lease(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(
        repositories,
        tmp_path,
    )
    service = SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        execution_backend="podman",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/timeout.py",
        content="print('timeout')\n",
        create_dirs=True,
    )
    lifecycle: list[str] = []
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(
        PodmanContainerLease,
        "require_absent_before_run",
        lambda self: lifecycle.append("absent"),
    )
    monkeypatch.setattr(
        PodmanContainerLease,
        "retire",
        lambda self: lifecycle.append("retired"),
    )

    def fake_active_timeout(
        self: SandboxRuntimeService,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int,
        sandbox_run_id: str,
        control_server: _ControlSocketServer,
        container_lease: PodmanContainerLease | None = None,
    ) -> subprocess.CompletedProcess[bytes]:
        del self, cwd, env, sandbox_run_id, control_server, container_lease
        lifecycle.append("run")
        raise subprocess.TimeoutExpired(
            command,
            timeout_seconds,
            output=b"",
            stderr=b"",
        )

    monkeypatch.setattr(
        SandboxRuntimeService,
        "_run_process_with_active_timeout",
        fake_active_timeout,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/timeout.py"],
        timeout_seconds=1,
    )

    assert run.status is SandboxRunStatus.TIMEOUT
    assert run.error_code == "sandbox_exec_timeout"
    assert lifecycle == ["absent", "run", "retired"]


def test_sandbox_exec_rejects_missing_ready_workspace_layout_before_snapshot(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/script.py",
        content="print('must not run')\n",
        create_dirs=True,
    )
    (workspace_root / workspace.sandbox_workspace_id / "input").rmdir()

    with pytest.raises(SandboxRuntimeError) as error:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/script.py"],
        )

    assert error.value.error_code == "sandbox_volume_corrupt"
    assert error.value.details == {
        "missing_directories": ["input"],
        "invalid_directories": [],
    }
    assert str(workspace_root) not in str(error.value)
    assert (
        repositories.sandbox_runs.list_by_workspace(workspace.sandbox_workspace_id)
        == []
    )
    assert repositories.artifacts.list_by_session(session.session_id) == []


def test_sandbox_file_write_does_not_repair_missing_workspace_layout(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
    )
    missing = workspace_root / workspace.sandbox_workspace_id / "src"
    missing.rmdir()

    with pytest.raises(SandboxRuntimeError) as error:
        service.write_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/repaired.py",
            content="print('must not be created')\n",
            create_dirs=True,
        )

    assert error.value.error_code == "sandbox_volume_corrupt"
    assert not missing.exists()


def test_sandbox_exec_redacts_host_paths_before_persisting_stdio(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        artifact_blob_root=tmp_path / "blobs",
        log_root=tmp_path / "logs",
        execution_backend="podman",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/podman.py",
        content="print('must not run')\n",
        create_dirs=True,
    )
    workspace_path = workspace_root / workspace.sandbox_workspace_id
    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr(
        PodmanContainerLease,
        "require_absent_before_run",
        lambda self: None,
    )
    monkeypatch.setattr(PodmanContainerLease, "retire", lambda self: None)

    def fake_active_timeout(
        self: SandboxRuntimeService,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int,
        sandbox_run_id: str,
        control_server: _ControlSocketServer,
        container_lease: PodmanContainerLease | None = None,
    ) -> subprocess.CompletedProcess[str]:
        del self, cwd, env, timeout_seconds, control_server, container_lease
        socket_path = Path(tempfile.gettempdir()) / f"oz-{sandbox_run_id}.sock"
        return subprocess.CompletedProcess(
            command,
            125,
            stdout=f"cwd={workspace_path}/src\n",
            stderr=(
                f"Error: statfs {workspace_path}/input: missing\n"
                f"socket={socket_path}\n"
                "config=/home/operator/private/config.toml\n"
            ),
        )

    monkeypatch.setattr(
        SandboxRuntimeService,
        "_run_process_with_active_timeout",
        fake_active_timeout,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/podman.py"],
    )

    assert run.status is SandboxRunStatus.FAILED
    assert run.stdout_summary == "cwd=/workspace/src\n"
    assert "/workspace/input" in str(run.stderr_summary)
    assert "/openzyme/control.sock" in str(run.stderr_summary)
    assert "[redacted-host-path]" in str(run.stderr_summary)
    serialized = json.dumps(run.to_dict(), sort_keys=True)
    assert str(tmp_path) not in serialized
    assert "/home/operator" not in serialized
    stored = repositories.sandbox_runs.get(run.sandbox_run_id)
    assert stored is not None
    assert stored.stderr_summary == run.stderr_summary
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    assert refreshed.last_command_summary is not None
    assert refreshed.last_command_summary["stderr_summary"] == run.stderr_summary


def test_sandbox_exec_podman_rejects_non_immutable_image_identity(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    repositories.sandbox_workspaces.save(
        replace(
            workspace,
            image_ref="localhost/openzyme-pipeline-sandbox:mutable",
            image_digest="sha256:short",
        )
    )
    service = SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        execution_backend="podman",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/podman.py",
        content="print('podman')\n",
        create_dirs=True,
    )

    with pytest.raises(SandboxRuntimeError) as error:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/podman.py"],
        )

    assert error.value.error_code == "sandbox_image_identity_invalid"
    assert (
        repositories.sandbox_runs.list_by_workspace(workspace.sandbox_workspace_id)
        == []
    )


def test_sandbox_exec_rejects_pipeline_sdk_digest_drift_before_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(
        repositories, workspace_root=workspace_root, log_root=tmp_path / "logs"
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/drift.py",
        content="print('must not run')\n",
        create_dirs=True,
    )
    digests = iter(("sha256:" + "a" * 64, "sha256:" + "b" * 64))
    monkeypatch.setattr(
        SandboxRuntimeService, "_pipeline_sdk_digest", lambda self: next(digests)
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/drift.py"],
    )

    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_runtime_identity_drift"
    assert run.compatibility is not None
    assert run.compatibility["pipeline_sdk_digest"] == "sha256:" + "a" * 64
