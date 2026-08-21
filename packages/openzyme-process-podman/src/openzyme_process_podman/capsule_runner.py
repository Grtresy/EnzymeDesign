from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
import shutil
import socket
import tempfile
import threading
from typing import Protocol

from .capsule_image import CapsuleCommandExecutor
from .capsule_image import CapsuleCommandResult


_SAFE_NETWORK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")
_CONTROL_FRAME_MAX_BYTES = 4 * 1024 * 1024


class AgentCapsuleWorkspace(Protocol):
    volume_id: str
    clone_logical_root: str
    image_ref: str


class AgentCapsuleControlHandler(Protocol):
    def dispatch(self, method: str, params: dict[str, object]) -> dict[str, object]: ...


@dataclass(slots=True)
class PodmanAgentCapsuleProcessRunner:
    executor: CapsuleCommandExecutor
    deployment_network: str
    podman_binary: str = "/usr/bin/podman"

    def __post_init__(self) -> None:
        if _SAFE_NETWORK_NAME.fullmatch(self.deployment_network) is None:
            raise ValueError("deployment_network is not a safe Podman network name")

    def run(
        self,
        *,
        workspace: AgentCapsuleWorkspace,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> CapsuleCommandResult:
        return self._run(
            workspace=workspace,
            argv=argv,
            credential_environment=credential_environment,
            timeout_seconds=timeout_seconds,
            control_handler=None,
        )

    def run_with_control(
        self,
        *,
        workspace: AgentCapsuleWorkspace,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
        control_handler: AgentCapsuleControlHandler,
    ) -> CapsuleCommandResult:
        return self._run(
            workspace=workspace,
            argv=argv,
            credential_environment=credential_environment,
            timeout_seconds=timeout_seconds,
            control_handler=control_handler,
        )

    def _run(
        self,
        *,
        workspace: AgentCapsuleWorkspace,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
        control_handler: AgentCapsuleControlHandler | None,
    ) -> CapsuleCommandResult:
        environment = {"PATH": "/usr/bin:/bin", **dict(credential_environment)}
        command: list[str] = [
            self.podman_binary,
            "run",
            "--rm",
            "--network",
            self.deployment_network,
            "--read-only",
            "--user",
            "10001:10001",
            "--cap-drop=all",
            "--security-opt=no-new-privileges",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,noexec,uid=10001,gid=10001,mode=0700",
            "--mount",
            f"type=volume,src={workspace.volume_id},dst=/workspace,rw",
            "--workdir",
            workspace.clone_logical_root,
        ]
        control_root: Path | None = None
        server: _AgentCapsuleControlSocketServer | None = None
        if control_handler is not None:
            control_root = Path(tempfile.mkdtemp(prefix="openzyme-capsule-control-"))
            socket_path = control_root / "control.sock"
            server = _AgentCapsuleControlSocketServer(
                socket_path=socket_path,
                handler=control_handler,
            )
            command.extend(
                (
                    "--mount",
                    f"type=bind,src={socket_path},dst=/openzyme/control.sock,rw,Z",
                    "--env",
                    "OPENZYME_CONTROL_SOCKET=/openzyme/control.sock",
                    "--env",
                    "OPENZYME_SANDBOX_MODE=file_workspace",
                )
            )
        for key, _ in credential_environment:
            command.extend(("--env", key))
        command.extend(
            (
                workspace.image_ref,
                "/usr/bin/timeout",
                "--signal=TERM",
                "--kill-after=5",
                str(timeout_seconds),
                *argv,
            )
        )
        if server is not None:
            server.start()
        try:
            return self.executor.run(tuple(command), environment=environment)
        finally:
            if server is not None:
                server.stop()
            if control_root is not None:
                shutil.rmtree(control_root)


@dataclass(slots=True)
class _AgentCapsuleControlSocketServer:
    socket_path: Path
    handler: AgentCapsuleControlHandler
    _thread: threading.Thread | None = None
    _stop: threading.Event | None = None
    _ready: threading.Event | None = None

    def start(self) -> None:
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=False)
        self._thread.start()
        if not self._ready.wait(timeout=2):
            self.stop()
            raise RuntimeError("capsule control socket did not start")

    def stop(self) -> None:
        if self._stop is None:
            return
        self._stop.set()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(self.socket_path))
                client.sendall(b"\n")
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=5)
            if self._thread.is_alive():
                raise RuntimeError("capsule control socket worker did not terminate")

    def _serve(self) -> None:
        assert self._stop is not None
        assert self._ready is not None
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o666)
            server.listen(8)
            server.settimeout(0.1)
            self._ready.set()
            while not self._stop.is_set():
                try:
                    connection, _ = server.accept()
                except TimeoutError:
                    continue
                with connection:
                    self._serve_connection(connection)

    def _serve_connection(self, connection: socket.socket) -> None:
        request_id: object = None
        try:
            frame = bytearray()
            connection.settimeout(5)
            while b"\n" not in frame:
                chunk = connection.recv(64 * 1024)
                if not chunk:
                    raise ValueError("control request ended before newline")
                frame.extend(chunk)
                if len(frame) > _CONTROL_FRAME_MAX_BYTES:
                    raise ValueError("control request exceeds bounded frame")
            payload, remainder = bytes(frame).split(b"\n", 1)
            if remainder.strip():
                raise ValueError("control socket accepts one request frame")
            request = json.loads(
                payload,
                object_pairs_hook=_unique_control_json_object,
                parse_constant=_reject_control_json_constant,
            )
            if not isinstance(request, dict):
                raise ValueError("control request must be an object")
            request_id = request.get("id")
            if not (
                request_id is None
                or (
                    isinstance(request_id, str)
                    and len(request_id.encode("utf-8")) <= 256
                )
                or (isinstance(request_id, int) and not isinstance(request_id, bool))
            ):
                raise ValueError("control request id is outside its bounded contract")
            method = request.get("method")
            params = request.get("params", {})
            if request.get("jsonrpc") != "2.0" or not isinstance(method, str):
                raise ValueError("control request must use JSON-RPC 2.0")
            if not isinstance(params, dict):
                raise ValueError("control request params must be an object")
            response: dict[str, object] = {
                "jsonrpc": "2.0",
                "id": request_id,
                "result": self.handler.dispatch(method, dict(params)),
            }
        except (KeyError, TypeError, ValueError, RuntimeError) as exc:
            response = {
                "jsonrpc": "2.0",
                "id": request_id,
                "error": {
                    "message": str(exc),
                    "type": type(exc).__name__,
                    "error_code": getattr(exc, "error_code", None)
                    or "sandbox_transport_request_invalid",
                    "retryable": bool(getattr(exc, "retryable", False)),
                    "details": dict(getattr(exc, "details", {}) or {}),
                },
            }
        encoded = json.dumps(response, allow_nan=False, sort_keys=True).encode()
        if len(encoded) > _CONTROL_FRAME_MAX_BYTES:
            encoded = json.dumps(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {
                        "message": "control response exceeds bounded frame",
                        "error_code": "sandbox_transport_response_too_large",
                        "retryable": False,
                    },
                },
                sort_keys=True,
            ).encode()
        connection.sendall(encoded + b"\n")


def _unique_control_json_object(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    result: dict[str, object] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _reject_control_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


__all__ = [
    "AgentCapsuleControlHandler",
    "AgentCapsuleWorkspace",
    "PodmanAgentCapsuleProcessRunner",
]
