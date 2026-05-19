from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
from pathlib import PurePath
import shutil
import socket
import subprocess
import tempfile
import threading
from typing import Any
from typing import Callable
from uuid import uuid4
import re

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SessionArtifactRecord

from .execution import ExecutionArtifactRef
from .execution import ExecutionOutcome


DEFAULT_SANDBOX_IMAGE = "localhost/openzyme-pipeline-sandbox:dev"


def _safe_host_segment(value: str, *, label: str) -> str:
    safe = re.sub(r"[^a-zA-Z0-9._-]+", "_", value).strip("._-")
    if not safe:
        raise ValueError(f"{label} must contain at least one safe path character")
    return safe[:120]


def _ensure_within(path: Path, root: Path, *, label: str) -> Path:
    resolved = path.resolve()
    resolved_root = root.resolve()
    if resolved != resolved_root and resolved_root not in resolved.parents:
        raise ValueError(f"{label} escapes sandbox root")
    return resolved


@dataclass(frozen=True, slots=True)
class PodmanSandboxPreflight:
    ok: bool
    message: str


@dataclass(slots=True)
class PodmanPipelineSandboxRunner:
    image: str = DEFAULT_SANDBOX_IMAGE
    podman_binary: str = "podman"
    timeout_seconds: int = 120
    workspace_root: Path = Path(tempfile.gettempdir()) / "openzyme-podman-pipelines"

    def preflight(self) -> PodmanSandboxPreflight:
        podman = shutil.which(self.podman_binary)
        if podman is None:
            return PodmanSandboxPreflight(False, "podman binary is not available")
        try:
            subprocess.run([self.podman_binary, "info", "--format", "{{.Host.Security.Rootless}}"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            return PodmanSandboxPreflight(False, f"podman rootless preflight failed: {exc.stderr.strip() or exc.stdout.strip()}")
        try:
            subprocess.run([self.podman_binary, "image", "exists", self.image], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError:
            return PodmanSandboxPreflight(False, f"sandbox image {self.image!r} is not present; run `uv run python -m openzyme_pipeline.sandbox_image build`")
        return PodmanSandboxPreflight(True, "podman sandbox is ready")

    def run_pipeline(
        self,
        *,
        session_id: str,
        invocation_id: str,
        code: str,
        inputs: tuple[SessionArtifactRecord, ...] = (),
        control_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> ExecutionOutcome:
        workspace_root = self.workspace_root.resolve()
        root = _ensure_within(workspace_root / _safe_host_segment(invocation_id, label="invocation_id"), workspace_root, label="invocation sandbox")
        if root.exists():
            shutil.rmtree(root)
        input_dir = root / "input"
        work_dir = root / "work"
        output_dir = root / "output"
        logs_dir = root / "logs"
        for directory in (input_dir, work_dir, output_dir, logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        for directory in (input_dir, work_dir, output_dir, logs_dir):
            directory.chmod(0o777)
        (work_dir / "pipeline.py").write_text(code, encoding="utf-8")
        (work_dir / "pipeline.py").chmod(0o666)
        sandbox_inputs = self._stage_inputs(input_dir, inputs)
        socket_path = root / "control.sock"
        server = _ControlSocketServer(
            socket_path=socket_path,
            output_dir=output_dir,
            artifacts=sandbox_inputs,
            control_handler=control_handler,
        )
        server.start()
        run_id = f"podman_{uuid4().hex[:12]}"
        try:
            completed = subprocess.run(
                [
                    self.podman_binary,
                    "run",
                    "--rm",
                    "--network=none",
                    "--userns=keep-id",
                    "--security-opt=no-new-privileges",
                    "--cap-drop=all",
                    "--read-only",
                    "--memory=2g",
                    "--cpus=2",
                    "--pids-limit=256",
                    "--tmpfs",
                    "/tmp:rw,noexec,nosuid,nodev,size=256m",
                    "-v",
                    f"{input_dir}:/openzyme/input:ro,Z",
                    "-v",
                    f"{work_dir}:/openzyme/work:Z",
                    "-v",
                    f"{output_dir}:/openzyme/output:Z",
                    "-v",
                    f"{logs_dir}:/openzyme/logs:Z",
                    "-v",
                    f"{socket_path}:/openzyme/control.sock:Z",
                    self.image,
                ],
                check=False,
                capture_output=True,
                text=True,
                timeout=self.timeout_seconds,
            )
        finally:
            server.stop()
        (logs_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (logs_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        artifacts = tuple(
            ExecutionArtifactRef(
                storage_uri=str(record.host_path),
                relative_path=record.relative_path,
                kind=record.kind,
            )
            for record in server.registered
        )
        log_artifacts = (
            ExecutionArtifactRef(str(logs_dir / "stdout.log"), "logs/stdout.log", ArtifactKind.LOG),
            ExecutionArtifactRef(str(logs_dir / "stderr.log"), "logs/stderr.log", ArtifactKind.LOG),
        )
        status = RunStatus.SUCCEEDED if completed.returncode == 0 else RunStatus.FAILED
        return ExecutionOutcome(
            run_id=run_id,
            status=status,
            execution_mode="podman",
            remote_run_dir=f"podman://{root.name}",
            raw_result={
                "session_id": session_id,
                "invocation_id": invocation_id,
                "exit_code": completed.returncode,
                "registered_artifact_count": len(artifacts),
            },
            artifacts=(*artifacts, *log_artifacts),
            exit_code=completed.returncode,
        )

    def _stage_inputs(self, input_dir: Path, inputs: tuple[SessionArtifactRecord, ...]) -> dict[str, dict[str, Any]]:
        staged: dict[str, dict[str, Any]] = {}
        resolved_input_dir = input_dir.resolve()
        for artifact in inputs:
            source = Path(artifact.storage_uri)
            artifact_segment = _safe_host_segment(artifact.artifact_id, label="artifact_id")
            filename = _safe_host_segment(Path(artifact.relative_path).name or artifact.artifact_id, label="relative_path")
            target = _ensure_within(input_dir / f"{artifact_segment}_{filename}", resolved_input_dir, label="staged input")
            shutil.copyfile(source, target)
            target.chmod(0o644)
            staged[artifact.artifact_id] = {
                "artifact_id": artifact.artifact_id,
                "path": f"/openzyme/input/{target.name}",
                "kind": artifact.kind.value,
                "format": (artifact.metadata or {}).get("format"),
                "title": artifact.title,
            }
        return staged


@dataclass(frozen=True, slots=True)
class _RegisteredOutput:
    host_path: Path
    relative_path: str
    kind: ArtifactKind


@dataclass(slots=True)
class _ControlSocketServer:
    socket_path: Path
    output_dir: Path
    artifacts: dict[str, dict[str, Any]]
    registered: list[_RegisteredOutput]
    control_handler: Callable[[str, dict[str, Any]], Any] | None
    _thread: threading.Thread | None
    _stop: threading.Event

    def __init__(
        self,
        *,
        socket_path: Path,
        output_dir: Path,
        artifacts: dict[str, dict[str, Any]],
        control_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.output_dir = output_dir
        self.artifacts = artifacts
        self.control_handler = control_handler
        self.registered = []
        self._thread = None
        self._stop = threading.Event()

    def start(self) -> None:
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        for _ in range(100):
            if self.socket_path.exists():
                return
            import time

            time.sleep(0.01)
        raise RuntimeError("control socket did not start")

    def stop(self) -> None:
        self._stop.set()
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
                client.connect(str(self.socket_path))
                client.sendall(b"\n")
        except OSError:
            pass
        if self._thread is not None:
            self._thread.join(timeout=2)
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def _serve(self) -> None:
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o666)
            server.listen(8)
            server.settimeout(0.1)
            while not self._stop.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    payload = conn.recv(65536).decode("utf-8").strip()
                    if not payload:
                        continue
                    response = self._handle(json.loads(payload))
                    conn.sendall(json.dumps(response, sort_keys=True).encode("utf-8") + b"\n")

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            method = str(request["method"])
            params = dict(request.get("params") or {})
            if method == "artifacts.get":
                result = self.artifacts[str(params["artifact_id"])]
            elif method == "artifacts.register":
                result = self._register(params)
            elif method == "artifacts.register_many":
                result = [self._register(item) for item in list(params.get("items") or [])]
            elif self.control_handler is not None:
                result = self.control_handler(method, params)
            else:
                raise ValueError(f"unsupported SDK operation {method!r}")
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except Exception as exc:
            return {"jsonrpc": "2.0", "id": request.get("id"), "error": {"message": str(exc), "type": exc.__class__.__name__}}

    def _register(self, params: dict[str, Any]) -> dict[str, Any]:
        sandbox_path = Path(str(params["path"]))
        if not sandbox_path.is_absolute() or sandbox_path.parts[:2] != ("/", "openzyme") or len(sandbox_path.parts) < 3 or sandbox_path.parts[2] != "output":
            raise ValueError("registered artifact path must be under /openzyme/output")
        relative_path = Path(*sandbox_path.parts[3:]).as_posix()
        if not relative_path or any(part in {"", ".", ".."} for part in PurePath(relative_path).parts):
            raise ValueError("registered artifact relative path must not contain empty, '.', or '..' segments")
        host_path = (self.output_dir / relative_path).resolve()
        if self.output_dir.resolve() not in (host_path, *host_path.parents):
            raise ValueError("registered artifact path escapes output directory")
        if not host_path.is_file():
            raise ValueError(f"registered artifact does not exist: {sandbox_path}")
        kind = ArtifactKind(str(params.get("kind") or "result"))
        self.registered.append(_RegisteredOutput(host_path=host_path, relative_path=relative_path, kind=kind))
        return {
            "artifact_id": f"pipeline:{len(self.registered)}:{relative_path}",
            "path": str(sandbox_path),
            "relative_path": relative_path,
            "kind": kind.value,
        }


__all__ = ["DEFAULT_SANDBOX_IMAGE", "PodmanPipelineSandboxRunner", "PodmanSandboxPreflight"]
