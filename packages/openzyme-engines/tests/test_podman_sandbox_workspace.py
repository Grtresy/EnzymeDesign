from __future__ import annotations

import json
from pathlib import Path
import socket
import subprocess
import threading
from types import SimpleNamespace

import pytest

from openzyme_engines import PodmanPipelineSandboxRunner
from openzyme_engines.podman_sandbox import _ControlSocketServer


def test_podman_runner_rejects_symlink_sandbox_root_without_touching_target(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    workspace_root = tmp_path / "workspaces"
    workspace_root.mkdir()
    target = tmp_path / "outside-target"
    target.mkdir()
    sentinel = target / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    (workspace_root / "inv_symlink").symlink_to(target, target_is_directory=True)
    runner = PodmanPipelineSandboxRunner(workspace_root=workspace_root)
    monkeypatch.setattr(
        PodmanPipelineSandboxRunner,
        "preflight",
        lambda self: SimpleNamespace(ok=True, runtime_identity={}),
    )

    with pytest.raises(RuntimeError, match="must not be a symlink"):
        runner.run_pipeline(
            session_id="sess_001",
            invocation_id="inv_symlink",
            code="print('must not run')\n",
        )

    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_podman_runner_can_bind_existing_sandbox_workspace(
    monkeypatch, tmp_path: Path
) -> None:
    calls: list[list[str]] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        del kwargs
        calls.append(list(command))
        if command[1:3] == ["container", "exists"]:
            return SimpleNamespace(returncode=1, stdout="", stderr="")
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(
                returncode=0,
                stdout="a" * 64 + "\n",
                stderr="",
            )
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("openzyme_engines.podman_sandbox.subprocess.run", fake_run)
    monkeypatch.setattr("openzyme_engines.podman_sandbox.shutil.which", lambda binary: f"/usr/bin/{binary}")
    monkeypatch.setattr("openzyme_engines.podman_sandbox._ControlSocketServer.start", lambda self: None)
    monkeypatch.setattr("openzyme_engines.podman_sandbox._ControlSocketServer.stop", lambda self: None)
    workspace_id = "sw_existing_workspace"
    workspace_root = tmp_path / "workspaces"
    sentinel = workspace_root / workspace_id / "work" / "keep.txt"
    sentinel.parent.mkdir(parents=True)
    sentinel.write_text("keep", encoding="utf-8")
    runner = PodmanPipelineSandboxRunner(
        workspace_root=workspace_root,
        timeout_seconds=30,
    )

    outcome = runner.run_pipeline(
        session_id="sess_001",
        invocation_id="inv_001",
        code="print('ok')\n",
        sandbox_workspace_id=workspace_id,
    )

    assert sentinel.read_text(encoding="utf-8") == "keep"
    assert outcome.remote_run_dir == f"podman://{workspace_id}"
    podman_run = next(command for command in calls if command[1] == "run")
    assert any(
        item == f"{workspace_root / workspace_id}:/workspace:Z"
        for item in podman_run
    )
    assert podman_run[-1] == "sha256:" + "a" * 64
    assert "--name" in podman_run
    cidfile = Path(podman_run[podman_run.index("--cidfile") + 1])
    assert cidfile.parent == workspace_root / ".podman-leases"
    assert workspace_root / workspace_id not in cidfile.parents
    labels = [
        podman_run[index + 1]
        for index, item in enumerate(podman_run)
        if item == "--label"
    ]
    assert any(label.startswith("io.openzyme.run_id=") for label in labels)
    assert any(
        label.startswith("io.openzyme.sandbox_root_digest=sha256:")
        for label in labels
    )
    runtime_identity = outcome.raw_result["sandbox_runtime_identity"]
    assert runtime_identity["image_digest"] == "sha256:" + "a" * 64
    assert runtime_identity["pipeline_sdk_digest"].startswith("sha256:")


def test_control_socket_materialize_copies_input_to_requested_workspace_target(
    tmp_path: Path,
) -> None:
    input_dir = tmp_path / "input"
    output_dir = tmp_path / "output"
    input_dir.mkdir()
    output_dir.mkdir()
    source = input_dir / "art_input.txt"
    source.write_text("authorized input\n", encoding="utf-8")
    server = _ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        input_dir=input_dir,
        output_dir=output_dir,
        artifacts={
            "art_input": {
                "artifact_id": "art_input",
                "path": "/openzyme/input/art_input.txt",
                "content_digest": "sha256:test",
            }
        },
    )

    result = server._materialize(
        {
            "artifact_id": "art_input",
            "target": "/workspace/input/nested/protein.txt",
            "mode": "copy",
        }
    )

    assert result["path"] == "/workspace/input/nested/protein.txt"
    assert (input_dir / "nested" / "protein.txt").read_text(encoding="utf-8") == "authorized input\n"
    with pytest.raises(ValueError, match="under /workspace/input"):
        server._materialize(
            {
                "artifact_id": "art_input",
                "target": "/workspace/output/protein.txt",
            }
        )


@pytest.mark.parametrize(
    ("method", "params"),
    (
        (
            "artifacts.register",
            {
                "path": "/workspace/output/AOX_ref.hmm",
                "kind": "model",
                "format": "hmm",
            },
        ),
        (
            "artifacts.register_many",
            {
                "items": [
                    {
                        "path": "/workspace/output/AOX_ref.hmm",
                        "kind": False,
                        "format": "hmm",
                    }
                ]
            },
        ),
    ),
)
def test_control_socket_rejects_raw_invalid_artifact_kind_nonretryably(
    tmp_path: Path,
    method: str,
    params: dict[str, object],
) -> None:
    server = _ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        artifacts={},
    )

    response = server._handle(
        {"jsonrpc": "2.0", "id": 1, "method": method, "params": params}
    )

    error = response["error"]
    assert error["error_code"] == "artifact_kind_invalid"
    assert error["retryable"] is False
    assert error["details"] == {
        "allowed_values": [
            "code",
            "log",
            "sequence",
            "structure",
            "report",
            "research_dossier",
            "result",
            "cache",
            "other",
        ]
    }
    assert error["hint"] == (
        "Use exactly one of: code, log, sequence, structure, report, "
        "research_dossier, result, cache, other."
    )
    assert server.registered == []


def test_control_socket_stop_waits_for_blocking_handler_after_grace(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox._CONTROL_SOCKET_STOP_GRACE_SECONDS",
        0.05,
    )
    handler_started = threading.Event()
    release_handler = threading.Event()
    client_done = threading.Event()
    stop_done = threading.Event()
    client_errors: list[BaseException] = []
    client_responses: list[dict[str, object]] = []

    def blocking_handler(method: str, params: dict[str, object]) -> object:
        del method, params
        handler_started.set()
        release_handler.wait()
        return {"status": "released"}

    server = _ControlSocketServer(
        socket_path=tmp_path / "control.sock",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        artifacts={},
        control_handler=blocking_handler,
    )
    server.start()

    def call_handler() -> None:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(server.socket_path))
                client.sendall(
                    json.dumps(
                        {"jsonrpc": "2.0", "id": 1, "method": "blocking"}
                    ).encode("utf-8")
                    + b"\n"
                )
                response = client.recv(65536)
            client_responses.append(json.loads(response.decode("utf-8")))
        except BaseException as exc:  # pragma: no cover - asserted below
            client_errors.append(exc)
        finally:
            client_done.set()

    def stop_server() -> None:
        server.stop()
        stop_done.set()

    client_thread = threading.Thread(target=call_handler)
    stop_thread = threading.Thread(target=stop_server)
    try:
        client_thread.start()
        assert handler_started.wait(timeout=1.0)
        stop_thread.start()

        assert stop_done.wait(timeout=0.15) is False

        release_handler.set()
        assert stop_done.wait(timeout=1.0)
        assert client_done.wait(timeout=1.0)
    finally:
        release_handler.set()
        if stop_thread.ident is not None:
            stop_thread.join(timeout=2.0)
        client_thread.join(timeout=2.0)
        if server._thread is not None and server._thread.is_alive():
            server.stop()

    assert stop_thread.is_alive() is False
    assert client_thread.is_alive() is False
    assert server._thread is not None
    assert server._thread.is_alive() is False
    assert server.socket_path.exists() is False
    assert client_errors == []
    assert client_responses == [
        {"id": 1, "jsonrpc": "2.0", "result": {"status": "released"}}
    ]


def test_control_socket_start_failure_retires_created_worker(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox._CONTROL_SOCKET_START_ATTEMPTS",
        1,
    )
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox._CONTROL_SOCKET_START_POLL_SECONDS",
        0.001,
    )
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox._CONTROL_SOCKET_STOP_GRACE_SECONDS",
        0.01,
    )
    release_worker = threading.Event()
    worker_started = threading.Event()
    start_done = threading.Event()
    start_errors: list[BaseException] = []

    def blocked_serve(_server: _ControlSocketServer) -> None:
        worker_started.set()
        release_worker.wait()

    monkeypatch.setattr(_ControlSocketServer, "_serve", blocked_serve)
    server = _ControlSocketServer(
        socket_path=tmp_path / "never-started-control.sock",
        input_dir=tmp_path / "input",
        output_dir=tmp_path / "output",
        artifacts={},
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
    assert isinstance(start_errors[0], RuntimeError)
    assert str(start_errors[0]) == "control socket did not start"


def test_podman_runner_retires_exact_container_before_stop_on_timeout(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    container_id = "d" * 64
    container_exists = False
    container_run_id = ""
    container_root_digest = ""
    call_order: list[str] = []

    def fake_run(command, **kwargs):  # noqa: ANN001, ANN202
        nonlocal container_exists, container_run_id, container_root_digest
        command = list(command)
        if command[1:3] == ["image", "inspect"]:
            return SimpleNamespace(
                returncode=0,
                stdout="a" * 64 + "\n",
                stderr="",
            )
        if command[1:3] == ["container", "exists"]:
            call_order.append("exists")
            return SimpleNamespace(
                returncode=0 if container_exists else 1,
                stdout="",
                stderr="",
            )
        if command[1] == "run":
            call_order.append("run")
            labels = [
                command[index + 1]
                for index, item in enumerate(command)
                if item == "--label"
            ]
            container_run_id = next(
                label.split("=", 1)[1]
                for label in labels
                if label.startswith("io.openzyme.run_id=")
            )
            container_root_digest = next(
                label.split("=", 1)[1]
                for label in labels
                if label.startswith("io.openzyme.sandbox_root_digest=")
            )
            cidfile = Path(command[command.index("--cidfile") + 1])
            cidfile.write_text(container_id + "\n", encoding="ascii")
            container_exists = True
            raise subprocess.TimeoutExpired(command, kwargs["timeout"])
        if command[1:3] == ["container", "inspect"]:
            call_order.append("inspect")
            return SimpleNamespace(
                returncode=0,
                stdout=(
                    f"{container_id} {container_run_id} "
                    f"{container_root_digest}\n"
                ).encode("ascii"),
                stderr=b"",
            )
        if command[1] in {"kill", "wait", "rm"}:
            call_order.append(command[1])
            if command[1] == "rm":
                container_exists = False
            return SimpleNamespace(returncode=0, stdout="", stderr="")
        return SimpleNamespace(returncode=0, stdout="", stderr="")

    monkeypatch.setattr("openzyme_engines.podman_sandbox.subprocess.run", fake_run)
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox.shutil.which",
        lambda binary: f"/usr/bin/{binary}",
    )
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox._ControlSocketServer.start",
        lambda self: call_order.append("control-start"),
    )
    monkeypatch.setattr(
        "openzyme_engines.podman_sandbox._ControlSocketServer.stop",
        lambda self: call_order.append("control-stop"),
    )
    runner = PodmanPipelineSandboxRunner(
        workspace_root=tmp_path / "workspaces",
        timeout_seconds=1,
    )

    with pytest.raises(subprocess.TimeoutExpired):
        runner.run_pipeline(
            session_id="sess_timeout",
            invocation_id="inv_timeout",
            code="print('never completes')\n",
        )

    assert call_order[-1] == "control-stop"
    assert call_order.index("kill") < call_order.index("wait")
    assert call_order.index("wait") < call_order.index("rm")
    assert call_order.index("rm") < len(call_order) - 2
    assert call_order[-2] == "exists"
    assert container_exists is False
    assert not list((tmp_path / "workspaces" / ".podman-leases").glob("*.cid"))
