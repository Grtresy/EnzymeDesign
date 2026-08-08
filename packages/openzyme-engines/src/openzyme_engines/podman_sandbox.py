from __future__ import annotations

from dataclasses import dataclass
import hashlib
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
from openzyme_runtime import immutable_source_tree_digest
from openzyme_runtime import ArtifactBoundaryError
from openzyme_runtime import load_artifact_registration_metadata_sidecar
from openzyme_runtime import PodmanContainerLease
from openzyme_runtime import FASTA_ZERO_RECORDS_VALIDATION_PROFILE

from .execution import ExecutionArtifactRef
from .execution import ExecutionOutcome


DEFAULT_SANDBOX_IMAGE = "localhost/openzyme-pipeline-sandbox:dev"
PODMAN_SANDBOX_PREFLIGHT_FAILURE_CODES = frozenset(
    {
        "pipeline_sdk_source_unavailable",
        "podman_binary_unavailable",
        "podman_rootless_preflight_failed",
        "sandbox_image_identity_invalid",
        "sandbox_image_unavailable",
        "sandbox_runtime_identity_drift",
    }
)
_CONTROL_SOCKET_START_ATTEMPTS = 100
_CONTROL_SOCKET_START_POLL_SECONDS = 0.01
_CONTROL_SOCKET_STOP_GRACE_SECONDS = 2.0
_CONTROL_SOCKET_FRAME_MAX_BYTES = 4 * 1024 * 1024
_CONTROL_SOCKET_CHUNK_BYTES = 64 * 1024
_CONTROL_SOCKET_IO_TIMEOUT_SECONDS = 5.0
_CONTROL_SOCKET_REQUEST_ID_MAX_BYTES = 256
_ARTIFACT_REGISTER_MANY_MAX_ITEMS = 128
_ARTIFACT_REGISTER_MANY_METADATA_MAX_BYTES = 32 * 1024 * 1024
_ARTIFACT_METADATA_INLINE_MAX_BYTES = 256 * 1024
_ARTIFACT_REQUIRED_COLUMNS_MAX_ITEMS = 4_096
_ARTIFACT_REQUIRED_COLUMN_MAX_BYTES = 256
_ARTIFACT_REQUIRED_COLUMNS_MAX_BYTES = 64 * 1024
_ARTIFACT_DERIVATION_CONTRACT_ID_MAX_BYTES = 256
_ARTIFACT_REGISTRATION_HOST_OWNED_DIGEST_FIELDS = frozenset(
    {"content_digest", "sealed_digest", "tree_digest"}
)
_PROVISIONAL_REGISTRATION_RESPONSE_SCHEMA_ID = (
    "pipeline_provisional_registration_response@1"
)


class _ControlSocketProtocolError(ValueError):
    def __init__(self, error_code: str, message: str) -> None:
        super().__init__(message)
        self.error_code = error_code


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


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
    runtime_identity: dict[str, str] | None = None
    failure_code: str | None = None


@dataclass(slots=True)
class PodmanPipelineSandboxRunner:
    image: str = DEFAULT_SANDBOX_IMAGE
    podman_binary: str = "podman"
    timeout_seconds: int = 120
    workspace_root: Path = Path(tempfile.gettempdir()) / "openzyme-podman-pipelines"
    pinned_runtime_identity: dict[str, str] | None = None

    def _local_pipeline_sdk_src(self) -> Path | None:
        candidate = Path(__file__).resolve().parents[3] / "openzyme-pipeline" / "src"
        if (candidate / "openzyme_pipeline").is_dir():
            return candidate
        return None

    def _prepare_pipeline_sdk_src(self, *, root: Path) -> Path | None:
        sdk_src = self._local_pipeline_sdk_src()
        if sdk_src is None:
            return None
        runtime_src = root / "sdk_src"
        if runtime_src.exists():
            shutil.rmtree(runtime_src)
        shutil.copytree(
            sdk_src,
            runtime_src,
            ignore=shutil.ignore_patterns("__pycache__", "*.pyc", "*.pyo"),
        )
        for path in (runtime_src, *runtime_src.rglob("*")):
            path.chmod(0o755 if path.is_dir() else 0o644)
        return runtime_src

    def _pipeline_sdk_digest(self) -> str | None:
        sdk_src = self._local_pipeline_sdk_src()
        if sdk_src is None:
            return None
        return immutable_source_tree_digest(sdk_src)

    def _inspect_image_digest(self) -> str:
        completed = subprocess.run(
            [self.podman_binary, "image", "inspect", "--format", "{{.Id}}", self.image],
            check=True,
            capture_output=True,
            text=True,
        )
        image_id = completed.stdout.strip()
        if re.fullmatch(r"[0-9a-f]{64}", image_id):
            return f"sha256:{image_id}"
        if not re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
            raise RuntimeError(f"podman returned an invalid immutable image id for {self.image!r}")
        return image_id

    def preflight(self) -> PodmanSandboxPreflight:
        podman = shutil.which(self.podman_binary)
        if podman is None:
            return PodmanSandboxPreflight(
                False,
                "podman binary is not available",
                failure_code="podman_binary_unavailable",
            )
        try:
            subprocess.run([self.podman_binary, "info", "--format", "{{.Host.Security.Rootless}}"], check=True, capture_output=True, text=True)
        except subprocess.CalledProcessError as exc:
            return PodmanSandboxPreflight(
                False,
                f"podman rootless preflight failed: {exc.stderr.strip() or exc.stdout.strip()}",
                failure_code="podman_rootless_preflight_failed",
            )
        except OSError:
            return PodmanSandboxPreflight(
                False,
                "podman rootless preflight could not execute",
                failure_code="podman_rootless_preflight_failed",
            )
        try:
            subprocess.run([self.podman_binary, "image", "exists", self.image], check=True, capture_output=True, text=True)
        except (OSError, subprocess.CalledProcessError):
            return PodmanSandboxPreflight(
                False,
                f"sandbox image {self.image!r} is not present; run `uv run python -m openzyme_pipeline.sandbox_image build`",
                failure_code="sandbox_image_unavailable",
            )
        try:
            image_digest = self._inspect_image_digest()
        except (OSError, subprocess.CalledProcessError, RuntimeError) as exc:
            return PodmanSandboxPreflight(
                False,
                str(exc),
                failure_code="sandbox_image_identity_invalid",
            )
        try:
            sdk_digest = self._pipeline_sdk_digest()
        except OSError:
            sdk_digest = None
        if sdk_digest is None:
            return PodmanSandboxPreflight(
                False,
                "openzyme_pipeline SDK source is not available",
                failure_code="pipeline_sdk_source_unavailable",
            )
        identity_without_digest = {
            "configured_image_ref": self.image,
            "immutable_image_ref": image_digest,
            "image_digest": image_digest,
            "pipeline_sdk_digest": sdk_digest,
            "sandbox_protocol_version": "s10",
        }
        identity_digest = "sha256:" + hashlib.sha256(
            json.dumps(identity_without_digest, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()
        identity = {**identity_without_digest, "runtime_identity_digest": identity_digest}
        if self.pinned_runtime_identity not in (None, identity):
            return PodmanSandboxPreflight(
                False,
                "sandbox runtime identity drifted after Host bootstrap",
                failure_code="sandbox_runtime_identity_drift",
            )
        return PodmanSandboxPreflight(True, "podman sandbox is ready", identity)

    def run_pipeline(
        self,
        *,
        session_id: str,
        invocation_id: str,
        code: str,
        inputs: tuple[SessionArtifactRecord, ...] = (),
        control_handler: Callable[[str, dict[str, Any]], Any] | None = None,
        sandbox_workspace_id: str | None = None,
        expected_runtime_identity: dict[str, str] | None = None,
    ) -> ExecutionOutcome:
        preflight = self.preflight()
        if not preflight.ok or preflight.runtime_identity is None:
            raise RuntimeError(preflight.message)
        runtime_identity = dict(preflight.runtime_identity)
        if expected_runtime_identity is not None and runtime_identity != expected_runtime_identity:
            raise RuntimeError("sandbox runtime identity drifted after execution-plan approval")
        workspace_root = self.workspace_root.resolve()
        root_segment = _safe_host_segment(
            sandbox_workspace_id or invocation_id,
            label="sandbox_workspace_id" if sandbox_workspace_id is not None else "invocation_id",
        )
        root_candidate = workspace_root / root_segment
        if root_candidate.is_symlink():
            raise RuntimeError("podman sandbox root must not be a symlink")
        root = _ensure_within(
            root_candidate,
            workspace_root,
            label="invocation sandbox",
        )
        if root.exists() and not root.is_dir():
            raise RuntimeError("podman sandbox root must be a directory")
        if sandbox_workspace_id is None and root.exists():
            shutil.rmtree(root)
        input_dir = root / "input"
        work_dir = root / "work"
        output_dir = root / "output"
        logs_dir = root / "logs"
        for directory in (input_dir, work_dir, output_dir, logs_dir):
            directory.mkdir(parents=True, exist_ok=True)
        root.chmod(0o777)
        for directory in (input_dir, work_dir, output_dir, logs_dir):
            directory.chmod(0o777)
        (work_dir / "pipeline.py").write_text(code, encoding="utf-8")
        (work_dir / "pipeline.py").chmod(0o666)
        sandbox_inputs = self._stage_inputs(input_dir, inputs)
        socket_path = root / "control.sock"
        server = _ControlSocketServer(
            socket_path=socket_path,
            input_dir=input_dir,
            output_dir=output_dir,
            artifacts=sandbox_inputs,
            control_handler=control_handler,
        )
        run_id = f"podman_{uuid4().hex[:12]}"
        container_lease = PodmanContainerLease.create(
            podman_binary=self.podman_binary,
            workspace_root=workspace_root,
            sandbox_root=root,
            run_id=run_id,
        )
        container_lease.require_absent_before_run()
        command = [
            self.podman_binary,
            "run",
            "--rm",
            *container_lease.run_options(),
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
            "-v",
            f"{root}:/workspace:Z",
            "-e",
            "OPENZYME_SANDBOX_MODE=s10",
        ]
        sdk_src = self._prepare_pipeline_sdk_src(root=root)
        if sdk_src is None:
            raise RuntimeError("openzyme_pipeline SDK source is not available")
        copied_sdk_digest = immutable_source_tree_digest(sdk_src)
        if copied_sdk_digest != runtime_identity["pipeline_sdk_digest"]:
            raise RuntimeError("pipeline SDK source drifted during sandbox materialization")
        command.extend(["-e", "PYTHONPATH=/openzyme/sdk", "-v", f"{sdk_src}:/openzyme/sdk:ro,Z"])
        command.append(runtime_identity["immutable_image_ref"])
        server.start()
        try:
            try:
                completed = subprocess.run(
                    command,
                    check=False,
                    capture_output=True,
                    text=True,
                    timeout=self.timeout_seconds,
                )
            finally:
                container_lease.retire()
        finally:
            server.stop()
        (logs_dir / "stdout.log").write_text(completed.stdout, encoding="utf-8")
        (logs_dir / "stderr.log").write_text(completed.stderr, encoding="utf-8")
        artifacts = tuple(
            ExecutionArtifactRef(
                storage_uri=str(record.host_path),
                relative_path=record.relative_path,
                kind=record.kind,
                metadata=record.metadata,
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
                "sandbox_runtime_identity": runtime_identity,
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
                "content_digest": (artifact.metadata or {}).get("content_digest"),
                "title": artifact.title,
            }
        return staged


@dataclass(frozen=True, slots=True)
class _RegisteredOutput:
    host_path: Path
    relative_path: str
    kind: ArtifactKind
    metadata: dict[str, Any]


@dataclass(slots=True)
class _ControlSocketServer:
    socket_path: Path
    input_dir: Path
    output_dir: Path
    artifacts: dict[str, dict[str, Any]]
    registered: list[_RegisteredOutput]
    control_handler: Callable[[str, dict[str, Any]], Any] | None
    _thread: threading.Thread | None
    _stop: threading.Event
    _ready: threading.Event

    def __init__(
        self,
        *,
        socket_path: Path,
        input_dir: Path,
        output_dir: Path,
        artifacts: dict[str, dict[str, Any]],
        control_handler: Callable[[str, dict[str, Any]], Any] | None = None,
    ) -> None:
        self.socket_path = socket_path
        self.input_dir = input_dir
        self.output_dir = output_dir
        self.artifacts = artifacts
        self.control_handler = control_handler
        self.registered = []
        self._thread = None
        self._stop = threading.Event()
        self._ready = threading.Event()

    def start(self) -> None:
        self._stop = threading.Event()
        self._ready = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=False)
        self._thread.start()
        for _ in range(_CONTROL_SOCKET_START_ATTEMPTS):
            if self._ready.wait(timeout=_CONTROL_SOCKET_START_POLL_SECONDS):
                return
            if not self._thread.is_alive():
                break
        self.stop()
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
            self._thread.join(timeout=_CONTROL_SOCKET_STOP_GRACE_SECONDS)
            if self._thread.is_alive():
                self._thread.join()
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
            self._ready.set()
            while not self._stop.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    request_id: Any = None
                    try:
                        conn.settimeout(_CONTROL_SOCKET_IO_TIMEOUT_SECONDS)
                        frame = self._read_frame(conn)
                        if frame is None or not frame.strip():
                            continue
                        request = self._decode_request_frame(frame)
                        request_id = self._response_request_id(request.get("id"))
                        self._validate_request_frame(request)
                        conn.settimeout(None)
                        response = self._handle(request)
                    except Exception as exc:
                        response = {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {
                                "message": str(exc),
                                "type": exc.__class__.__name__,
                                "error_code": getattr(exc, "error_code", None)
                                or "sandbox_transport_request_invalid",
                            },
                        }
                    encoded = self._encode_response(response, request_id=request_id)
                    try:
                        conn.settimeout(_CONTROL_SOCKET_IO_TIMEOUT_SECONDS)
                        conn.sendall(encoded)
                    except OSError:
                        continue

    @staticmethod
    def _read_frame(conn: socket.socket) -> bytes | None:
        payload = bytearray()
        while True:
            remaining = _CONTROL_SOCKET_FRAME_MAX_BYTES - len(payload) + 1
            try:
                chunk = conn.recv(min(_CONTROL_SOCKET_CHUNK_BYTES, remaining))
            except socket.timeout as exc:
                raise _ControlSocketProtocolError(
                    "sandbox_transport_request_timeout",
                    "control socket request frame timed out",
                ) from exc
            if not chunk:
                if not payload:
                    return None
                raise _ControlSocketProtocolError(
                    "sandbox_transport_request_invalid",
                    "control request ended before its newline delimiter",
                )
            newline_index = chunk.find(b"\n")
            if newline_index >= 0:
                payload.extend(chunk[:newline_index])
                if len(payload) > _CONTROL_SOCKET_FRAME_MAX_BYTES:
                    raise _ControlSocketProtocolError(
                        "sandbox_transport_request_too_large",
                        "control request exceeds its bounded limit",
                    )
                if chunk[newline_index + 1 :].strip():
                    raise _ControlSocketProtocolError(
                        "sandbox_transport_request_invalid",
                        "control socket accepts one request per connection",
                    )
                return bytes(payload)
            payload.extend(chunk)
            if len(payload) > _CONTROL_SOCKET_FRAME_MAX_BYTES:
                raise _ControlSocketProtocolError(
                    "sandbox_transport_request_too_large",
                    "control request exceeds its bounded limit",
                )

    @staticmethod
    def _decode_request_frame(frame: bytes) -> dict[str, Any]:
        try:
            request = json.loads(
                frame.decode("utf-8"),
                object_pairs_hook=_unique_json_object,
                parse_constant=_reject_json_constant,
            )
        except (UnicodeDecodeError, ValueError, RecursionError) as exc:
            raise _ControlSocketProtocolError(
                "sandbox_transport_request_invalid",
                "control request frame is not valid UTF-8 JSON",
            ) from exc
        if not isinstance(request, dict):
            raise _ControlSocketProtocolError(
                "sandbox_transport_request_invalid",
                "control request frame must contain a JSON object",
            )
        return request

    @staticmethod
    def _response_request_id(request_id: Any) -> str | int | None:
        if isinstance(request_id, str):
            if len(request_id.encode("utf-8")) <= _CONTROL_SOCKET_REQUEST_ID_MAX_BYTES:
                return request_id
            return None
        if (
            isinstance(request_id, int)
            and not isinstance(request_id, bool)
            and -(2**63) <= request_id < 2**63
        ):
            return request_id
        return None

    @classmethod
    def _validate_request_frame(cls, request: dict[str, Any]) -> None:
        raw_request_id = request.get("id")
        if raw_request_id is not None and cls._response_request_id(raw_request_id) is None:
            raise _ControlSocketProtocolError(
                "sandbox_transport_request_invalid",
                "control request id is outside the bounded JSON-RPC identity contract",
            )
        if request.get("jsonrpc") != "2.0":
            raise _ControlSocketProtocolError(
                "sandbox_transport_request_invalid",
                "control request frame must use JSON-RPC 2.0",
            )
        params = request.get("params")
        if params is not None and not isinstance(params, dict):
            raise _ControlSocketProtocolError(
                "sandbox_transport_request_invalid",
                "control request params must be a JSON object",
            )

    @classmethod
    def _encode_response(
        cls,
        response: dict[str, Any],
        *,
        request_id: Any,
    ) -> bytes:
        try:
            encoded = json.dumps(
                response,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except (RecursionError, TypeError, ValueError):
            encoded = b""
            error_code = "sandbox_transport_response_invalid"
            message = "control socket response is not valid JSON"
        else:
            error_code = "sandbox_transport_response_too_large"
            message = "control socket response exceeds its bounded limit"
        if len(encoded) > _CONTROL_SOCKET_FRAME_MAX_BYTES or not encoded:
            bounded_error = {
                "jsonrpc": "2.0",
                "id": cls._response_request_id(request_id),
                "error": {
                    "message": message,
                    "type": "ValueError",
                    "error_code": error_code,
                },
            }
            encoded = json.dumps(
                bounded_error,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            if len(encoded) > _CONTROL_SOCKET_FRAME_MAX_BYTES:
                encoded = (
                    b'{"error":{"error_code":"sandbox_transport_response_too_large"},'
                    b'"id":null,"jsonrpc":"2.0"}'
                )
        return encoded + b"\n"

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            method = str(request["method"])
            params = dict(request.get("params") or {})
            if method == "artifacts.get":
                result = self.artifacts[str(params["artifact_id"])]
            elif method == "artifacts.materialize":
                result = self._materialize(params)
            elif method == "artifacts.register":
                result = self._register(params)
            elif method == "artifacts.register_many":
                items = params.get("items", [])
                if not isinstance(items, list) or not all(
                    isinstance(item, dict) for item in items
                ):
                    raise ValueError("artifacts.register_many items must be objects")
                if len(items) > _ARTIFACT_REGISTER_MANY_MAX_ITEMS:
                    raise ValueError("artifacts.register_many exceeds its bounded item limit")
                resolved_metadata: list[dict[str, Any]] = []
                metadata_cache: dict[str, dict[str, Any]] = {}
                resolved_metadata_bytes = 0
                for item in items:
                    try:
                        cache_key = json.dumps(
                            {
                                "metadata": item.get("metadata")
                                if "metadata" in item
                                else None,
                                "metadata_sidecar": item.get("metadata_sidecar")
                                if "metadata_sidecar" in item
                                else None,
                            },
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    except (RecursionError, TypeError, ValueError) as exc:
                        raise ValueError(
                            "artifact registration metadata is not canonical JSON"
                        ) from exc
                    cached = metadata_cache.get(cache_key)
                    if cached is None:
                        cached = self._registration_metadata(item)
                        cached_size = len(
                            json.dumps(
                                cached,
                                ensure_ascii=True,
                                sort_keys=True,
                                separators=(",", ":"),
                                allow_nan=False,
                            ).encode("utf-8")
                        )
                        resolved_metadata_bytes += cached_size
                        if (
                            resolved_metadata_bytes
                            > _ARTIFACT_REGISTER_MANY_METADATA_MAX_BYTES
                        ):
                            raise ValueError(
                                "artifacts.register_many metadata exceeds its aggregate limit"
                            )
                        metadata_cache[cache_key] = cached
                    resolved_metadata.append(cached)
                result = [
                    self._register(item, resolved_metadata=metadata)
                    for item, metadata in zip(
                        items,
                        resolved_metadata,
                        strict=True,
                    )
                ]
            elif self.control_handler is not None:
                result = self.control_handler(method, params)
            else:
                raise ValueError(f"unsupported SDK operation {method!r}")
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                    "error_code": getattr(exc, "error_type", None)
                    or getattr(exc, "error_code", None),
                    "stage": getattr(exc, "stage", None),
                    "retryable": getattr(exc, "retryable", None),
                    "hint": getattr(exc, "hint", None),
                    "sdk_method": getattr(exc, "sdk_method", None),
                    "hpc_failure": getattr(exc, "hpc_failure", None),
                    "details": getattr(exc, "details", None),
                },
            }

    def _materialize(self, params: dict[str, Any]) -> dict[str, Any]:
        artifact_id = str(params["artifact_id"])
        result = dict(self.artifacts[artifact_id])
        path = str(result["path"])
        if path.startswith("/openzyme/input/"):
            path = "/workspace/input/" + path.removeprefix("/openzyme/input/")
        target = params.get("target") or params.get("target_path")
        if target not in {None, ""}:
            target_path = PurePath(str(target))
            if (
                not target_path.is_absolute()
                or target_path.parts[:3] != ("/", "workspace", "input")
                or any(part in {"", ".", ".."} for part in target_path.parts[3:])
            ):
                raise ValueError("materialized artifact target must be under /workspace/input")
            source_path = PurePath(path)
            source_host_path = (self.input_dir / Path(*source_path.parts[3:])).resolve()
            input_root = self.input_dir.resolve()
            if input_root not in (source_host_path, *source_host_path.parents):
                raise ValueError("materialized artifact source escapes input directory")
            target_host_path = (self.input_dir / Path(*target_path.parts[3:])).resolve()
            if input_root not in (target_host_path, *target_host_path.parents):
                raise ValueError("materialized artifact target escapes input directory")
            if target_host_path != source_host_path:
                target_host_path.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source_host_path, target_host_path)
                target_host_path.chmod(0o644)
            path = target_path.as_posix()
        return {
            "artifact_id": artifact_id,
            "path": path,
            "artifact_digest": result.get("content_digest"),
            "mode": str(params.get("mode") or "copy"),
        }

    def _register(
        self,
        params: dict[str, Any],
        *,
        resolved_metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        raw_kind = str(params["kind"]) if "kind" in params else "result"
        try:
            kind = ArtifactKind(raw_kind)
        except ValueError as exc:
            allowed_values = [item.value for item in ArtifactKind]
            raise ArtifactBoundaryError(
                "artifact_kind_invalid",
                f"artifact kind {raw_kind!r} is invalid",
                hint=f"Use exactly one of: {', '.join(allowed_values)}.",
                details={"allowed_values": allowed_values},
            ) from exc
        sandbox_path = Path(str(params["path"]))
        parts = sandbox_path.parts
        if (
            not sandbox_path.is_absolute()
            or len(parts) < 3
            or (
                parts[:3] != ("/", "workspace", "output")
                and not (parts[:2] == ("/", "openzyme") and len(parts) >= 3 and parts[2] == "output")
            )
        ):
            raise ValueError("registered artifact path must be under /workspace/output")
        relative_parts = parts[3:]
        relative_path = Path(*relative_parts).as_posix()
        if not relative_path or any(part in {"", ".", ".."} for part in PurePath(relative_path).parts):
            raise ValueError("registered artifact relative path must not contain empty, '.', or '..' segments")
        host_path = (self.output_dir / relative_path).resolve()
        if self.output_dir.resolve() not in (host_path, *host_path.parents):
            raise ValueError("registered artifact path escapes output directory")
        if not host_path.is_file():
            raise ValueError(f"registered artifact does not exist: {sandbox_path}")
        metadata = (
            self._registration_metadata(params)
            if resolved_metadata is None
            else dict(resolved_metadata)
        )
        output_format = params.get("format")
        validation_profile = params.get("validation_profile")
        if output_format is not None:
            metadata["format"] = str(output_format)
        metadata_validation_profile = metadata.get("validation_profile")
        if (
            metadata_validation_profile == FASTA_ZERO_RECORDS_VALIDATION_PROFILE
            and validation_profile != FASTA_ZERO_RECORDS_VALIDATION_PROFILE
        ):
            raise ValueError(
                "fasta_zero_records@1 must be selected through validation_profile"
            )
        if (
            validation_profile is not None
            and metadata_validation_profile not in {None, "", validation_profile}
        ):
            raise ValueError("artifact validation_profile conflicts with metadata")
        if validation_profile is not None:
            metadata["validation_profile"] = str(validation_profile)
        self._validate_registered_output(
            host_path,
            relative_path=relative_path,
            kind=kind,
            validation_profile=(
                None if validation_profile is None else str(validation_profile)
            ),
            metadata=metadata,
        )
        metadata_bytes = json.dumps(
            metadata,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        with host_path.open("rb") as handle:
            observed_content_digest = (
                f"sha256:{hashlib.file_digest(handle, 'sha256').hexdigest()}"
            )
        result = {
            "schema_id": _PROVISIONAL_REGISTRATION_RESPONSE_SCHEMA_ID,
            "canonical": False,
            "artifact_id": f"pipeline:{len(self.registered) + 1}",
            "observed_content_digest": observed_content_digest,
            "metadata": {
                "schema_id": "pipeline_provisional_metadata_summary@1",
                "projection": "bounded_provisional_summary",
                "metadata_digest": (
                    f"sha256:{hashlib.sha256(metadata_bytes).hexdigest()}"
                ),
                "metadata_size_bytes": len(metadata_bytes),
                "metadata_field_count": len(metadata),
            },
        }
        self.registered.append(
            _RegisteredOutput(
                host_path=host_path,
                relative_path=relative_path,
                kind=kind,
                metadata=metadata,
            )
        )
        return result

    def _registration_metadata(self, params: dict[str, Any]) -> dict[str, Any]:
        if "metadata_sidecar" not in params:
            if "metadata" not in params:
                return {}
            metadata = params.get("metadata")
            if not isinstance(metadata, dict):
                raise ValueError("artifact registration metadata must be an object")
            payload = json.dumps(
                metadata,
                ensure_ascii=True,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            ).encode("utf-8")
            if len(payload) > _ARTIFACT_METADATA_INLINE_MAX_BYTES:
                raise ValueError("inline artifact registration metadata is too large")
            resolved = dict(metadata)
            self._reject_host_owned_registration_metadata(resolved)
            return resolved
        if "metadata" in params:
            raise ValueError("artifact registration must use exactly one metadata transport")
        sidecar = params.get("metadata_sidecar")
        if not isinstance(sidecar, dict):
            raise ValueError("artifact registration metadata sidecar must be an object")
        resolved = load_artifact_registration_metadata_sidecar(
            workspace_path=self.output_dir.parent,
            sidecar=dict(sidecar),
        )
        self._reject_host_owned_registration_metadata(resolved)
        return resolved

    @staticmethod
    def _reject_host_owned_registration_metadata(metadata: dict[str, Any]) -> None:
        reserved_fields = sorted(
            _ARTIFACT_REGISTRATION_HOST_OWNED_DIGEST_FIELDS.intersection(metadata)
        )
        if reserved_fields:
            raise ArtifactBoundaryError(
                "artifact_registration_metadata_reserved",
                "artifact registration metadata contains Host-owned digest fields",
                details={"reserved_fields": reserved_fields},
            )

    def _validate_registered_output(
        self,
        path: Path,
        *,
        relative_path: str,
        kind: ArtifactKind,
        validation_profile: str | None,
        metadata: dict[str, Any],
    ) -> None:
        output_format = str(metadata.get("format") or "").lower()
        raw_required_columns = metadata.get("required_columns")
        if raw_required_columns is None:
            required_columns: list[str] = []
        elif not isinstance(raw_required_columns, list):
            raise ValueError("metadata.required_columns must be a bounded list")
        else:
            if len(raw_required_columns) > _ARTIFACT_REQUIRED_COLUMNS_MAX_ITEMS:
                raise ValueError("metadata.required_columns exceeds its item limit")
            required_columns = []
            total_column_bytes = 0
            for column in raw_required_columns:
                if not isinstance(column, str) or not column:
                    raise ValueError(
                        "metadata.required_columns entries must be non-empty strings"
                    )
                column_bytes = len(column.encode("utf-8"))
                if column_bytes > _ARTIFACT_REQUIRED_COLUMN_MAX_BYTES:
                    raise ValueError(
                        "metadata.required_columns contains an oversized name"
                    )
                total_column_bytes += column_bytes
                if total_column_bytes > _ARTIFACT_REQUIRED_COLUMNS_MAX_BYTES:
                    raise ValueError(
                        "metadata.required_columns exceeds its byte limit"
                    )
                required_columns.append(column)
        if validation_profile is None and not output_format and not required_columns:
            return
        content = path.read_text(encoding="utf-8", errors="replace")
        if validation_profile is not None:
            reason = metadata.get("empty_result_reason")
            derivation_contract_id = metadata.get("derivation_contract_id")
            if (
                validation_profile != FASTA_ZERO_RECORDS_VALIDATION_PROFILE
                or kind is not ArtifactKind.SEQUENCE
                or output_format not in {"fasta", "fa", "faa"}
                or not isinstance(reason, str)
                or re.fullmatch(r"[a-z][a-z0-9_]{0,127}", reason) is None
                or not isinstance(derivation_contract_id, str)
                or len(derivation_contract_id.encode("utf-8"))
                > _ARTIFACT_DERIVATION_CONTRACT_ID_MAX_BYTES
                or re.fullmatch(
                    r"[a-z][a-z0-9_.-]*@[1-9][0-9]*",
                    derivation_contract_id,
                )
                is None
                or content != ""
            ):
                raise ValueError(
                    f"registered fasta_zero_records@1 artifact is invalid: {relative_path}"
                )
            return
        if not content.strip():
            raise ValueError(f"registered artifact is empty: {relative_path}")
        if output_format in {"fasta", "fa", "faa"} and not content.lstrip().startswith(">"):
            raise ValueError(f"registered FASTA artifact is invalid: {relative_path}")
        if output_format == "hmm" and not content.startswith("HMMER"):
            raise ValueError(f"registered HMM artifact is invalid: {relative_path}")
        if output_format == "csv" or required_columns:
            header = content.splitlines()[0].split(",") if content.splitlines() else []
            missing = [column for column in required_columns if column not in header]
            if missing:
                raise ValueError(f"registered CSV artifact {relative_path} is missing required columns: {missing}")


__all__ = ["DEFAULT_SANDBOX_IMAGE", "PodmanPipelineSandboxRunner", "PodmanSandboxPreflight"]
