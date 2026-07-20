from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import os
import re
import shutil
import socket
import subprocess
import tempfile
import threading
import time
from typing import Any
from uuid import uuid4

from openzyme_domain import CommandLogArtifactRecord
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import FileAuditEntry
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import immutable_source_tree_digest
from openzyme_runtime import PodmanContainerLease
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime import safe_public_machine_identifier
from openzyme_runtime import sanitize_public_diagnostic_payload
from openzyme_runtime import sanitize_public_diagnostic_text

from .artifact_boundary import ArtifactBoundaryError
from .artifact_boundary import ArtifactBoundaryService
from .artifact_projection import project_artifact_for_agent
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .sandbox_workspace import SANDBOX_PROTOCOL_VERSION
from .sandbox_workspace import SANDBOX_WORKSPACE_MANIFEST_VERSION
from .sandbox_workspace import DEFAULT_SANDBOX_QUOTA_BYTES
from .sandbox_workspace import SandboxWorkspaceService
from .sandbox_workspace import WORKSPACE_DIRECTORIES
from .sandbox_workspace import summarize_workspace_directory


WORKSPACE_ROOT = PurePosixPath("/workspace")
WORKSPACE_SRC = PurePosixPath("/workspace/src")
WORKSPACE_WORK = PurePosixPath("/workspace/work")
WORKSPACE_OUTPUT = PurePosixPath("/workspace/output")
WORKSPACE_LOGS = PurePosixPath("/workspace/logs")
ALLOWED_FILE_ROOTS = (WORKSPACE_SRC, WORKSPACE_WORK, WORKSPACE_OUTPUT, WORKSPACE_LOGS)
READ_DEFAULT_LIMIT = 64 * 1024
READ_MAX_LIMIT = 256 * 1024
WRITE_MAX_BYTES = 256 * 1024
LIST_MAX_ITEMS = 1000
STDIO_INLINE_LIMIT = 32 * 1024
EXEC_DEFAULT_TIMEOUT_SECONDS = 120
EXEC_MAX_TIMEOUT_SECONDS = 3_600
EXEC_POLICY_VERSION = "s09.exec_policy.v2"
S10_SUPERVISED_RPC_SCHEMA = "s10.supervised_rpc.v1"
S12_ADAPTER_ENVELOPE_SCHEMA = "s12.adapter_envelope.v1"
S12_HOST_RESULT_ORIGIN = "host_adapter_executor"
_CONTROL_SOCKET_START_ATTEMPTS = 100
_CONTROL_SOCKET_START_POLL_SECONDS = 0.01
_CONTROL_SOCKET_STOP_GRACE_SECONDS = 2.0
# Keep this wire-contract value identical to the dependency-free pipeline SDK.
CONTROL_SOCKET_FRAME_MAX_BYTES = 4 * 1024 * 1024
_CONTROL_SOCKET_CHUNK_BYTES = 64 * 1024
_CONTROL_SOCKET_IO_TIMEOUT_SECONDS = 5.0
_CONTROL_SOCKET_REQUEST_ID_MAX_BYTES = 256
_ARTIFACT_REGISTER_MANY_MAX_ITEMS = 128
_ARTIFACT_REGISTER_MANY_METADATA_MAX_BYTES = 32 * 1024 * 1024
SandboxAdapterExecutor = Callable[[ControlledOperation, dict[str, Any]], dict[str, Any]]
SandboxHpcFetchExecutor = Callable[[dict[str, Any]], dict[str, Any]]
PRIVATE_ADAPTER_PAYLOAD_KEYS = {
    "host_path",
    "sandbox_host_path",
    "runner_path",
    "remote_path",
    "sif_path",
    "credential",
    "credentials",
    "api_key",
    "token",
    "secret",
    "provider_credential",
    "provider_credentials",
    "provider_secret",
    "private_endpoint",
    "runner_config",
    "ssh_config",
    "slurm_config",
    "database_mount",
    "database_path",
    "mount_path",
    "storage_uri",
    "command",
    "complete_command",
    "raw_command",
}
class SandboxRuntimeError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        stage: str | None = None,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
        retryable: bool | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.stage = stage
        self.hint = hint
        self.details = {} if details is None else dict(details)
        self.retryable = retryable


@dataclass(frozen=True, slots=True)
class FileDigest:
    content_digest: str
    size_bytes: int


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _sha256_bytes(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def _json_digest(value: Any) -> str:
    return _sha256_bytes(json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-finite JSON constant {value!r} is forbidden")


def _unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise ValueError(f"duplicate JSON object key {key!r}")
        result[key] = value
    return result


def _is_sha256_digest(value: str) -> bool:
    prefix, separator, digest = value.partition(":")
    if prefix != "sha256" or separator != ":" or len(digest) != 64:
        return False
    try:
        int(digest, 16)
    except ValueError:
        return False
    return True


def _scrub_private_adapter_payload(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _scrub_private_adapter_payload(item)
            for key, item in value.items()
            if str(key) not in PRIVATE_ADAPTER_PAYLOAD_KEYS
        }
    if isinstance(value, list):
        return [_scrub_private_adapter_payload(item) for item in value]
    return value


def _artifact_ref_pairs(value: Any) -> list[tuple[str, str]]:
    """Collect direct artifact refs without guessing route-specific aliases."""

    pairs: list[tuple[str, str]] = []

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            if "artifact_id" in item:
                artifact_id = str(item.get("artifact_id") or "")
                raw_digests = [
                    str(item.get(key) or "")
                    for key in ("artifact_digest", "content_digest")
                    if key in item
                ]
                digests = [digest for digest in raw_digests if digest]
                if (
                    not artifact_id
                    or artifact_id != artifact_id.strip()
                    or not digests
                    or len(set(digests)) != 1
                    or not _is_sha256_digest(digests[0])
                ):
                    raise SandboxRuntimeError(
                        "adapter_input_binding_mismatch",
                        "S12 artifact refs require one canonical artifact ID and digest.",
                    )
                pairs.append((artifact_id, digests[0]))
            for nested in item.values():
                visit(nested)
            return
        if isinstance(item, (list, tuple)):
            for nested in item:
                visit(nested)

    visit(value)
    return sorted(pairs)


_TOOLCHAIN_RUNTIME_IDENTITY_FIELDS = (
    "schema_id",
    "attestation_scope",
    "execution_mode",
    "tool_id",
    "adapter_id",
    "command_template_id",
    "runner_contract_digest",
    "image_digest",
)
_SAFE_TOOLCHAIN_IDENTIFIER_PATTERN = re.compile(
    r"^[A-Za-z0-9][A-Za-z0-9._:@-]{0,127}$"
)
_PYTHON_EXECUTABLE_PATTERN = re.compile(r"python(?:\d+(?:\.\d+)*t?)?\Z")
_UNWRAPPED_HEREDOC_ARG_PATTERN = re.compile(
    r"^[ \t]*(?:-[ \t]*)?<<-?[ \t]*[^\s\r\n]+[ \t]*\r?\n"
)


def _project_toolchain_runtime_identity(value: Any) -> dict[str, str] | None:
    if not isinstance(value, dict):
        return None
    identity = {
        field: str(value.get(field) or "")
        for field in _TOOLCHAIN_RUNTIME_IDENTITY_FIELDS
    }
    if (
        identity["schema_id"] != "mcp_hpc_toolchain_runtime_identity@1"
        or identity["attestation_scope"]
        != "same_ssh_login_shell_pre_exec"
        or identity["execution_mode"] != "ssh"
        or any(
            _SAFE_TOOLCHAIN_IDENTIFIER_PATTERN.fullmatch(identity[field]) is None
            for field in ("tool_id", "adapter_id", "command_template_id")
        )
        or any(
            not _is_sha256_digest(identity[field])
            or identity[field] != identity[field].lower()
            for field in ("runner_contract_digest", "image_digest")
        )
    ):
        return None
    return identity


def _sanitize_toolchain_runtime_identity(
    summary: dict[str, Any],
) -> dict[str, Any]:
    safe_summary = dict(summary)
    if "toolchain_runtime_identity" not in safe_summary:
        return safe_summary
    if safe_summary.get("execution_mode") != "ssh":
        safe_summary.pop("toolchain_runtime_identity", None)
        return safe_summary
    identity = _project_toolchain_runtime_identity(
        safe_summary.get("toolchain_runtime_identity")
    )
    if identity is None:
        safe_summary.pop("toolchain_runtime_identity", None)
    else:
        safe_summary["toolchain_runtime_identity"] = identity
    return safe_summary


def _structured_adapter_message(value: Any, *, default_code: str) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        message = dict(_scrub_private_adapter_payload(value))
        code = safe_public_machine_identifier(
            message.get("code")
            or message.get("error_code")
            or message.get("warning_code"),
            fallback=default_code,
        )
        summary = sanitize_public_diagnostic_text(
            message.get("summary") or message.get("message") or code
        )
        return {
            "code": code,
            "stage": safe_public_machine_identifier(
                message.get("stage"),
                fallback="adapter_result",
            ),
            "retryable": bool(message.get("retryable", False)),
            "summary": summary,
            "details_ref": (
                None
                if message.get("details_ref") is None
                else sanitize_public_diagnostic_text(message["details_ref"])
            ),
            "safe_diagnostics": sanitize_public_diagnostic_payload(
                message.get("safe_diagnostics")
            ),
        }
    return {
        "code": default_code,
        "stage": "adapter_result",
        "retryable": False,
        "summary": sanitize_public_diagnostic_text(value),
        "details_ref": None,
        "safe_diagnostics": None,
    }


def _structured_adapter_warnings(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    warnings: list[dict[str, Any]] = []
    for item in value:
        warning = _structured_adapter_message(item, default_code="adapter_warning")
        if warning is not None:
            warnings.append(warning)
    return warnings


def _workspace_root(workspace_root: Path | None) -> Path:
    root = workspace_root or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
    root.mkdir(parents=True, exist_ok=True)
    return root.resolve()


def _file_digest(path: Path) -> FileDigest:
    content = path.read_bytes()
    return FileDigest(content_digest=_sha256_bytes(content), size_bytes=len(content))


def _public_path(value: str | None, *, default: PurePosixPath) -> PurePosixPath:
    if value in {None, ""}:
        return default
    text = str(value)
    if text.startswith("/openzyme/"):
        raise SandboxRuntimeError("sandbox_path_forbidden", "agent-facing sandbox paths must use /workspace")
    candidate = PurePosixPath(text)
    if not candidate.is_absolute():
        candidate = WORKSPACE_ROOT / candidate
    if any(part in {"", ".", ".."} for part in candidate.parts[1:]):
        raise SandboxRuntimeError("sandbox_path_forbidden", "workspace path must not contain empty, '.', or '..' segments")
    return candidate


def _is_under(path: PurePosixPath, root: PurePosixPath) -> bool:
    return path == root or root in path.parents


def _allowed_root_for(path: PurePosixPath, *, allow_workspace_root: bool = False) -> PurePosixPath:
    if allow_workspace_root and path == WORKSPACE_ROOT:
        return WORKSPACE_ROOT
    for root in ALLOWED_FILE_ROOTS:
        if _is_under(path, root):
            return root
    raise SandboxRuntimeError("sandbox_path_forbidden", "path must be under /workspace/src, /workspace/work, /workspace/output, or /workspace/logs")


def _resolve_host_path(
    workspace_path: Path,
    public_path: PurePosixPath,
    *,
    allow_workspace_root: bool = False,
) -> Path:
    root = _allowed_root_for(public_path, allow_workspace_root=allow_workspace_root)
    if root == WORKSPACE_ROOT:
        relative = PurePosixPath(".")
    else:
        relative = public_path.relative_to(root)
    if relative != PurePosixPath("."):
        if relative.is_absolute() or any(part in {"", ".", ".."} for part in relative.parts):
            raise SandboxRuntimeError("sandbox_path_forbidden", "path escapes the allowed sandbox workspace root")
    host_root = workspace_path if root == WORKSPACE_ROOT else workspace_path / root.relative_to(WORKSPACE_ROOT)
    host_path = (host_root / Path(*(() if relative == PurePosixPath(".") else relative.parts))).resolve()
    resolved_root = host_root.resolve()
    if host_path != resolved_root and resolved_root not in host_path.parents:
        raise SandboxRuntimeError("sandbox_path_forbidden", "path escapes the allowed sandbox workspace root")
    for parent in (host_path, *host_path.parents):
        if parent == resolved_root.parent:
            break
        if parent.exists() and parent.is_symlink():
            raise SandboxRuntimeError("sandbox_path_forbidden", "path traverses a symlink")
    return host_path


def _bounded_text(value: str, *, limit: int = STDIO_INLINE_LIMIT) -> tuple[str, bool, int, str]:
    encoded = value.encode("utf-8", errors="replace")
    digest = _sha256_bytes(encoded)
    if len(encoded) <= limit:
        return value, False, len(encoded), digest
    bounded = encoded[:limit].decode("utf-8", errors="replace")
    while len(bounded.encode("utf-8")) > limit:
        bounded = bounded[:-1]
    return bounded, True, len(encoded), digest


def _public_sandbox_stdio(
    value: str,
    *,
    workspace_path: Path,
    socket_path: Path,
) -> str:
    replacements = (
        (str(workspace_path.resolve()), WORKSPACE_ROOT.as_posix()),
        (str(socket_path.resolve()), "/openzyme/control.sock"),
    )
    return sanitize_public_diagnostic_text(
        value,
        path_replacements=replacements,
    )


def _safe_log_ref(sandbox_run_id: str, stream: str) -> str:
    return f"sandbox-log://{sandbox_run_id}/{stream}"


def _parse_hunk_header(line: str) -> tuple[int, int]:
    # Unified diff header format: @@ -old,count +new,count @@
    try:
        old_part = line.split(" ", 2)[1]
        start_text = old_part.removeprefix("-").split(",", 1)[0]
        return int(start_text), 0
    except (IndexError, ValueError) as exc:
        raise SandboxRuntimeError("sandbox_patch_failed", "invalid unified diff hunk header") from exc


def _strip_patch_path(value: str) -> PurePosixPath:
    text = value.strip().split("\t", 1)[0].split(" ", 1)[0]
    if text in {"---", "+++", "/dev/null", ""}:
        raise SandboxRuntimeError("sandbox_path_forbidden", "patch must target an existing single file")
    if text.startswith("a/") or text.startswith("b/"):
        text = text[2:]
    path = PurePosixPath(text)
    if path.is_absolute():
        return _public_path(path.as_posix(), default=WORKSPACE_SRC)
    return _public_path(path.as_posix(), default=WORKSPACE_ROOT)


def _apply_unified_diff(original: str, patch: str, *, public_path: PurePosixPath) -> str:
    patch_lines = patch.splitlines(keepends=True)
    if len([line for line in patch_lines if line.startswith("@@")]) == 0:
        raise SandboxRuntimeError("sandbox_patch_failed", "patch must contain at least one unified diff hunk")
    header_paths: list[PurePosixPath] = []
    for line in patch_lines:
        if line.startswith("--- ") or line.startswith("+++ "):
            header_paths.append(_strip_patch_path(line[4:]))
    if header_paths and any(path != public_path for path in header_paths):
        raise SandboxRuntimeError("sandbox_path_forbidden", "unified diff path must match the tool path argument")
    original_lines = original.splitlines(keepends=True)
    output: list[str] = []
    original_index = 0
    index = 0
    while index < len(patch_lines):
        line = patch_lines[index]
        if line.startswith("--- ") or line.startswith("+++ "):
            index += 1
            continue
        if not line.startswith("@@"):
            index += 1
            continue
        old_start, _ = _parse_hunk_header(line)
        target_index = max(old_start - 1, 0)
        if target_index < original_index:
            raise SandboxRuntimeError("sandbox_patch_failed", "patch hunks overlap or move backwards")
        output.extend(original_lines[original_index:target_index])
        original_index = target_index
        index += 1
        while index < len(patch_lines) and not patch_lines[index].startswith("@@"):
            hunk_line = patch_lines[index]
            if hunk_line.startswith("\\"):
                index += 1
                continue
            marker = hunk_line[:1]
            content = hunk_line[1:]
            if marker == " ":
                if original_index >= len(original_lines) or original_lines[original_index] != content:
                    raise SandboxRuntimeError("sandbox_patch_failed", "patch context does not match the target file")
                output.append(original_lines[original_index])
                original_index += 1
            elif marker == "-":
                if original_index >= len(original_lines) or original_lines[original_index] != content:
                    raise SandboxRuntimeError("sandbox_patch_failed", "patch removal does not match the target file")
                original_index += 1
            elif marker == "+":
                output.append(content)
            elif hunk_line.strip() == "":
                raise SandboxRuntimeError("sandbox_patch_failed", "blank hunk lines must be prefixed with a diff marker")
            else:
                raise SandboxRuntimeError("sandbox_patch_failed", "patch contains an invalid hunk line")
            index += 1
    output.extend(original_lines[original_index:])
    return "".join(output)


@dataclass(slots=True)
class _ControlSocketServer:
    socket_path: Path
    repositories: Any
    session_id: str
    sandbox_workspace_id: str
    sandbox_run_id: str
    agent_id: str
    source_snapshot_artifact_id: str
    source_tree_digest: str
    task_id: str | None = None
    lane_id: str | None = None
    workspace_root: Path | None = None
    artifact_blob_root: Path | None = None
    adapter_executor: SandboxAdapterExecutor | None = None
    hpc_fetch_executor: SandboxHpcFetchExecutor | None = None
    repository_scope_factory: Callable[[], Any] | None = None
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)
    _ready: threading.Event = field(default_factory=threading.Event)

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
        raise SandboxRuntimeError("sandbox_transport_unavailable", "control socket did not start")

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
                # The grace period only bounds the cooperative shutdown path.
                # Returning with a live control worker would let repository and
                # socket ownership escape the sandbox lifecycle boundary.
                self._thread.join()
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass

    def _serve(self) -> None:
        if self.repository_scope_factory is None:
            self._serve_with_owned_repositories()
            return
        # The control socket has its own server thread.  Open the repository
        # connection in that thread instead of capturing the sandbox.exec
        # worker's thread-affine connection.
        with self.repository_scope_factory() as repositories:
            self.repositories = repositories
            self._serve_with_owned_repositories()

    def _serve_with_owned_repositories(self) -> None:
        try:
            self.socket_path.unlink()
        except FileNotFoundError:
            pass
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as server:
            server.bind(str(self.socket_path))
            os.chmod(self.socket_path, 0o600)
            server.listen(8)
            server.settimeout(0.1)
            self._ready.set()
            while not self._stop.is_set():
                try:
                    conn, _ = server.accept()
                except socket.timeout:
                    continue
                with conn:
                    response: dict[str, Any] | None = None
                    request_id: Any = None
                    try:
                        conn.settimeout(_CONTROL_SOCKET_IO_TIMEOUT_SECONDS)
                        frame = self._read_request_frame(conn)
                        if frame is None or not frame.strip():
                            continue
                        request = self._decode_request_frame(frame)
                        request_id = self._response_request_id(request.get("id"))
                        self._validate_request_frame(request)
                        conn.settimeout(None)
                        response = self._handle(request)
                    except SandboxRuntimeError as exc:
                        response = self._error_response(request_id=request_id, exc=exc)
                    except OSError:
                        continue
                    except Exception:
                        # Parser/runtime edge cases must retire only the current
                        # connection.  In particular, Python's JSON decoder may
                        # raise ValueError or RecursionError for bounded hostile
                        # inputs even though they are neither JSONDecodeError nor
                        # transport failures.
                        response = self._error_response(
                            request_id=request_id,
                            exc=SandboxRuntimeError(
                                "sandbox_transport_request_invalid",
                                "control socket request frame could not be processed",
                            ),
                        )
                    encoded = self._encode_response(response, request_id=request_id)
                    try:
                        conn.settimeout(_CONTROL_SOCKET_IO_TIMEOUT_SECONDS)
                        conn.sendall(encoded)
                    except OSError:
                        # A client disconnect must retire only this connection;
                        # it must never kill the control-socket accept worker.
                        continue

    @staticmethod
    def _read_request_frame(conn: socket.socket) -> bytes | None:
        payload = bytearray()
        while True:
            remaining = CONTROL_SOCKET_FRAME_MAX_BYTES - len(payload) + 1
            try:
                chunk = conn.recv(min(_CONTROL_SOCKET_CHUNK_BYTES, remaining))
            except socket.timeout as exc:
                raise SandboxRuntimeError(
                    "sandbox_transport_request_timeout",
                    "control socket request frame timed out",
                ) from exc
            if not chunk:
                if not payload:
                    return None
                raise SandboxRuntimeError(
                    "sandbox_transport_request_invalid",
                    "control socket request frame ended before its newline delimiter",
                )
            newline_index = chunk.find(b"\n")
            if newline_index >= 0:
                payload.extend(chunk[:newline_index])
                if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
                    raise SandboxRuntimeError(
                        "sandbox_transport_request_too_large",
                        "control socket request frame exceeds the bounded transport limit",
                    )
                if chunk[newline_index + 1 :].strip():
                    raise SandboxRuntimeError(
                        "sandbox_transport_request_invalid",
                        "control socket accepts exactly one request frame per connection",
                    )
                return bytes(payload)
            payload.extend(chunk)
            if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
                raise SandboxRuntimeError(
                    "sandbox_transport_request_too_large",
                    "control socket request frame exceeds the bounded transport limit",
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
            raise SandboxRuntimeError(
                "sandbox_transport_request_invalid",
                "control socket request frame is not valid UTF-8 JSON",
            ) from exc
        if not isinstance(request, dict):
            raise SandboxRuntimeError(
                "sandbox_transport_request_invalid",
                "control socket request frame must contain a JSON object",
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
            raise SandboxRuntimeError(
                "sandbox_transport_request_invalid",
                "control socket request id is outside the bounded JSON-RPC identity contract",
            )
        if request.get("jsonrpc") != "2.0":
            raise SandboxRuntimeError(
                "sandbox_transport_request_invalid",
                "control socket request frame must use JSON-RPC 2.0",
            )
        params = request.get("params")
        if params is not None and not isinstance(params, dict):
            raise SandboxRuntimeError(
                "sandbox_transport_request_invalid",
                "control socket request params must be a JSON object",
            )

    def _encode_response(self, response: dict[str, Any], *, request_id: Any) -> bytes:
        try:
            payload = json.dumps(
                response,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        except Exception:
            response = self._error_response(
                request_id=request_id,
                exc=SandboxRuntimeError(
                    "sandbox_transport_response_invalid",
                    "control socket response is not valid JSON",
                ),
            )
            payload = json.dumps(
                response,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
        if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
            response = self._error_response(
                request_id=self._response_request_id(request_id),
                exc=SandboxRuntimeError(
                    "sandbox_transport_response_too_large",
                    "control socket response frame exceeds the bounded transport limit",
                ),
            )
            payload = json.dumps(
                response,
                sort_keys=True,
                allow_nan=False,
            ).encode("utf-8")
            if len(payload) > CONTROL_SOCKET_FRAME_MAX_BYTES:
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {
                        "message": "control socket response frame exceeds the bounded transport limit",
                        "type": "SandboxRuntimeError",
                        "error_code": "sandbox_transport_response_too_large",
                        "hint": "",
                        "details": None,
                    },
                }
                payload = json.dumps(
                    response,
                    sort_keys=True,
                    allow_nan=False,
                ).encode("utf-8")
        return payload + b"\n"

    @staticmethod
    def _error_response(*, request_id: Any, exc: Exception) -> dict[str, Any]:
        public_message = getattr(exc, "public_message", None) or str(exc)
        raw_stage = getattr(exc, "stage", None)
        raw_retryable = getattr(exc, "retryable", None)
        error = {
            "message": sanitize_public_diagnostic_text(public_message),
            "type": safe_public_machine_identifier(
                exc.__class__.__name__,
                fallback="Exception",
            ),
            "error_code": safe_public_machine_identifier(
                getattr(exc, "error_code", None),
                fallback="sandbox_transport_error",
            ),
            "hint": sanitize_public_diagnostic_text(
                getattr(exc, "hint", None) or ""
            ),
            "details": sanitize_public_diagnostic_payload(
                getattr(exc, "details", None)
            ),
            "retryable": raw_retryable if isinstance(raw_retryable, bool) else None,
        }
        if raw_stage is not None:
            error["stage"] = safe_public_machine_identifier(
                raw_stage,
                fallback="sandbox_runtime",
            )
        return {
            "jsonrpc": "2.0",
            "id": request_id,
            "error": error,
        }

    def _handle(self, request: dict[str, Any]) -> dict[str, Any]:
        try:
            method = str(request["method"])
            params = dict(request.get("params") or {})
            if method == "s09.transport_smoke":
                return self._handle_transport_smoke(request, params)
            if method == "s10.controlled_operation":
                return self._handle_controlled_operation(request, params)
            if method.startswith("artifacts."):
                return self._handle_artifact_boundary(request, method, params)
            if method == "hpc.workspace":
                return self._handle_hpc_workspace(request, params)
            if method == "hpc.stage_artifact":
                return self._handle_hpc_stage_artifact(request, params)
            if method == "hpc.fetch_outputs":
                return self._handle_hpc_fetch_outputs(request, params)
            raise SandboxRuntimeError("sandbox_transport_method_forbidden", "control socket only supports supervised sandbox calls")
        except Exception as exc:
            return self._error_response(request_id=request.get("id"), exc=exc)

    def _handle_transport_smoke(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        call_identity = str(params.get("call_identity") or request.get("id") or "")
        result = {
            "sandbox_workspace_id": self.sandbox_workspace_id,
            "sandbox_run_id": self.sandbox_run_id,
            "source_snapshot_artifact_id": self.source_snapshot_artifact_id,
            "source_tree_digest": self.source_tree_digest,
            "artifact_read_summary": dict(params.get("artifact_read_summary") or {}),
            "call_identity": call_identity,
            "status": "ok",
        }
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _artifact_boundary_service(self) -> ArtifactBoundaryService:
        return ArtifactBoundaryService(
            self.repositories,
            workspace_root=self.workspace_root,
            blob_store_root=self.artifact_blob_root,
        )

    def _handle_artifact_boundary(
        self,
        request: dict[str, Any],
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            def _optional_object(
                payload: dict[str, Any],
                key: str,
            ) -> dict[str, Any] | None:
                if key not in payload:
                    return None
                value = payload[key]
                if not isinstance(value, dict):
                    raise ArtifactBoundaryError(
                        "artifact_registration_metadata_invalid",
                        f"artifacts registration {key} must be an object",
                    )
                return dict(value)

            if method == "artifacts.get":
                artifact = self.repositories.artifacts.get(str(params.get("artifact_id") or ""))
                if artifact is None or artifact.session_id != self.session_id:
                    raise ArtifactBoundaryError("artifact_scope_forbidden", "artifact is not available in this session")
                result = project_artifact_for_agent(artifact)
            elif method == "artifacts.materialize":
                result = self._artifact_boundary_service().materialize(
                    session_id=self.session_id,
                    sandbox_workspace_id=self.sandbox_workspace_id,
                    artifact_id=str(params.get("artifact_id") or ""),
                    target=None if params.get("target") in {None, ""} else str(params.get("target")),
                    mode=str(params.get("mode") or "copy"),
                ).to_payload()
            elif method == "artifacts.register":
                service = self._artifact_boundary_service()
                result = service.register(
                    session_id=self.session_id,
                    sandbox_workspace_id=self.sandbox_workspace_id,
                    path=str(params.get("path") or ""),
                    kind=(
                        str(params["kind"])
                        if "kind" in params
                        else "result"
                    ),
                    format=None if params.get("format") in {None, ""} else str(params.get("format")),
                    validation_profile=(
                        None
                        if params.get("validation_profile") in {None, ""}
                        else str(params.get("validation_profile"))
                    ),
                    metadata=_optional_object(params, "metadata"),
                    metadata_sidecar=_optional_object(params, "metadata_sidecar"),
                    source_snapshot_artifact_id=self.source_snapshot_artifact_id,
                ).to_control_payload()
            elif method == "artifacts.register_many":
                items = params.get("items", [])
                if not isinstance(items, list) or not all(isinstance(item, dict) for item in items):
                    raise ArtifactBoundaryError("invalid_tool_arguments", "artifacts.register_many items must be objects")
                if len(items) > _ARTIFACT_REGISTER_MANY_MAX_ITEMS:
                    raise ArtifactBoundaryError(
                        "artifact_register_many_too_many_items",
                        "artifacts.register_many exceeds its bounded item limit",
                        details={
                            "max_items": _ARTIFACT_REGISTER_MANY_MAX_ITEMS,
                            "item_count": len(items),
                        },
                    )
                service = self._artifact_boundary_service()
                resolved_metadata: list[dict[str, Any]] = []
                metadata_cache: dict[str, dict[str, Any]] = {}
                resolved_metadata_bytes = 0
                for item in items:
                    metadata = _optional_object(item, "metadata")
                    metadata_sidecar = _optional_object(item, "metadata_sidecar")
                    try:
                        cache_key = json.dumps(
                            {
                                "metadata": metadata,
                                "metadata_sidecar": metadata_sidecar,
                            },
                            ensure_ascii=True,
                            sort_keys=True,
                            separators=(",", ":"),
                            allow_nan=False,
                        )
                    except (RecursionError, TypeError, ValueError) as exc:
                        raise ArtifactBoundaryError(
                            "artifact_registration_metadata_invalid",
                            "artifact registration metadata is not canonical JSON",
                        ) from exc
                    cached = metadata_cache.get(cache_key)
                    if cached is None:
                        cached = service.resolve_registration_metadata(
                            session_id=self.session_id,
                            sandbox_workspace_id=self.sandbox_workspace_id,
                            metadata=metadata,
                            metadata_sidecar=metadata_sidecar,
                        )
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
                            raise ArtifactBoundaryError(
                                "artifact_register_many_metadata_too_large",
                                "artifacts.register_many metadata exceeds its aggregate limit",
                                details={
                                    "max_bytes": _ARTIFACT_REGISTER_MANY_METADATA_MAX_BYTES,
                                    "observed_bytes": resolved_metadata_bytes,
                                },
                            )
                        metadata_cache[cache_key] = cached
                    resolved_metadata.append(cached)
                result = [
                    service.register(
                        session_id=self.session_id,
                        sandbox_workspace_id=self.sandbox_workspace_id,
                        path=str(item.get("path") or ""),
                        kind=(
                            str(item["kind"])
                            if "kind" in item
                            else "result"
                        ),
                        format=None if item.get("format") in {None, ""} else str(item.get("format")),
                        validation_profile=(
                            None
                            if item.get("validation_profile") in {None, ""}
                            else str(item.get("validation_profile"))
                        ),
                        _resolved_metadata=metadata_payload,
                        source_snapshot_artifact_id=self.source_snapshot_artifact_id,
                    ).to_control_payload()
                    for item, metadata_payload in zip(
                        items,
                        resolved_metadata,
                        strict=True,
                    )
                ]
            elif method == "artifacts.snapshot_code":
                result = self._artifact_boundary_service().snapshot_code(
                    session_id=self.session_id,
                    sandbox_workspace_id=self.sandbox_workspace_id,
                    paths=params.get("paths"),
                    entrypoint=str(params.get("entrypoint") or ""),
                    metadata=dict(params.get("metadata") or {}),
                ).to_payload()
            else:
                raise SandboxRuntimeError("sandbox_transport_method_forbidden", "artifact method is not supported by the sandbox control socket")
        except ArtifactBoundaryError as exc:
            raise SandboxRuntimeError(
                exc.error_code,
                str(exc),
                hint=exc.hint,
                details=exc.details,
                retryable=exc.retryable,
            ) from exc
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _normalize_hpc_workspace_label(self, label: str) -> str:
        normalized = "".join(char if char.isalnum() or char in "._-" else "-" for char in label.strip()).strip("-._")
        if normalized in {"", ".", ".."} or len(normalized) > 80:
            raise SandboxRuntimeError(
                "hpc_workspace_label_invalid",
                "HPC workspace label is invalid",
                details={"label": label},
            )
        return normalized

    def _handle_hpc_workspace(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        label = str(params.get("label") or "")
        normalized = self._normalize_hpc_workspace_label(label)
        digest = hashlib.sha256(f"{self.sandbox_workspace_id}:{normalized}".encode("utf-8")).hexdigest()[:16]
        result = {
            "kind": "hpc_workspace",
            "hpc_workspace_id": f"hpcws_{digest}",
            "label": label,
            "normalized_label": normalized,
            "sandbox_workspace_id": self.sandbox_workspace_id,
            "placement_profile_id": "default",
        }
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _handle_hpc_stage_artifact(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        workspace = params.get("hpc_workspace")
        if not isinstance(workspace, dict) or not workspace.get("hpc_workspace_id"):
            raise SandboxRuntimeError("hpc_workspace_forbidden", "hpc.stage_artifact requires hpc_workspace")
        hpc_workspace_id = str(workspace["hpc_workspace_id"])
        artifact_id = str(params.get("artifact_id") or "")
        artifact = self.repositories.artifacts.get(artifact_id)
        if artifact is None or artifact.session_id != self.session_id:
            raise SandboxRuntimeError(
                "hpc_workspace_forbidden",
                "artifact is not available for staging in this session",
                details={"artifact_id": artifact_id},
            )
        metadata = dict(artifact.metadata or {})
        artifact_digest = str(
            metadata.get("sealed_digest")
            or metadata.get("content_digest")
            or metadata.get("tree_digest")
            or metadata.get("source_tree_digest")
            or ""
        )
        if not artifact_digest:
            raise SandboxRuntimeError(
                "hpc_stage_digest_missing",
                "artifact does not expose a sealed digest for HPC staging",
                details={"artifact_id": artifact_id},
            )
        workspace_relative_path = self._validated_hpc_workspace_path(str(params.get("workspace_path") or ""))
        stage_ref_id = "stage_" + hashlib.sha256(
            f"{hpc_workspace_id}:{artifact_id}:{artifact_digest}:{workspace_relative_path}".encode("utf-8")
        ).hexdigest()[:16]
        result = {
            "kind": "hpc_stage_ref",
            "stage_ref_id": stage_ref_id,
            "hpc_workspace_id": hpc_workspace_id,
            "artifact_id": artifact_id,
            "artifact_digest": artifact_digest,
            "workspace_relative_path": workspace_relative_path,
            "source": "artifact_catalog",
            "sandbox_workspace_id": self.sandbox_workspace_id,
        }
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _handle_hpc_fetch_outputs(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        workspace = params.get("hpc_workspace")
        if not isinstance(workspace, dict) or not workspace.get("hpc_workspace_id"):
            raise SandboxRuntimeError("hpc_workspace_forbidden", "hpc.fetch_outputs requires hpc_workspace")
        run_id = str(params.get("run_id") or "")
        if not run_id:
            raise SandboxRuntimeError(
                "hpc_fetch_not_declared",
                "hpc.fetch_outputs requires a completed Host-supervised HPC run with declared outputs",
                details={"run_id": run_id},
            )
        operation = self._hpc_fetch_operation(params)
        if self.hpc_fetch_executor is None:
            raise SandboxRuntimeError(
                "hpc_fetch_not_declared",
                "hpc.fetch_outputs requires a completed Host-supervised HPC run with declared outputs",
                details={"run_id": run_id, "operation_id": None if operation is None else operation.operation_id},
            )
        try:
            result = self.hpc_fetch_executor(
                {
                    **dict(params),
                    "session_id": self.session_id,
                    "sandbox_workspace_id": self.sandbox_workspace_id,
                    "sandbox_run_id": self.sandbox_run_id,
                    "task_id": self.task_id,
                    "lane_id": self.lane_id,
                }
            )
        except Exception as exc:
            (
                error_code,
                error_summary,
                stage,
                retryable,
                hint,
                details,
            ) = self._adapter_execution_error(exc)
            raise SandboxRuntimeError(
                error_code,
                error_summary,
                stage=stage,
                hint=hint,
                details={"run_id": run_id, "operation_id": None if operation is None else operation.operation_id, **details},
                retryable=retryable,
            ) from exc
        if not isinstance(result, dict):
            raise SandboxRuntimeError(
                "hpc_fetch_result_invalid",
                "Host fetch executor returned a non-object result.",
                details={"run_id": run_id, "operation_id": None if operation is None else operation.operation_id},
            )
        if operation is not None:
            self._record_hpc_fetch_result(operation, dict(result))
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _hpc_fetch_operation(self, params: dict[str, Any]) -> ControlledOperation | None:
        operation_id = str(params.get("operation_id") or "")
        if not operation_id:
            return None
        operation = self.repositories.controlled_operations.get(operation_id)
        if (
            operation is None
            or operation.session_id != self.session_id
            or operation.sandbox_workspace_id != self.sandbox_workspace_id
            or operation.sandbox_run_id != self.sandbox_run_id
        ):
            raise SandboxRuntimeError(
                "hpc_fetch_not_declared",
                "hpc.fetch_outputs operation is not available in this sandbox run",
                details={"operation_id": operation_id},
            )
        operation_digest = str(params.get("operation_digest") or "")
        if operation_digest and operation_digest != operation.operation_digest:
            raise SandboxRuntimeError(
                "operation_drift_detected",
                "hpc.fetch_outputs operation digest does not match the approved operation",
                details={
                    "operation_id": operation.operation_id,
                    "operation_digest": operation.operation_digest,
                    "fetch_operation_digest": operation_digest,
                },
            )
        hpc_workspace = params.get("hpc_workspace")
        hpc_workspace_id = str(dict(hpc_workspace).get("hpc_workspace_id") or "") if isinstance(hpc_workspace, dict) else ""
        if operation.hpc_workspace_id and hpc_workspace_id and operation.hpc_workspace_id != hpc_workspace_id:
            raise SandboxRuntimeError(
                "hpc_fetch_not_declared",
                "hpc.fetch_outputs workspace does not match the approved operation",
                details={
                    "operation_id": operation.operation_id,
                    "operation_hpc_workspace_id": operation.hpc_workspace_id,
                    "fetch_hpc_workspace_id": hpc_workspace_id,
                },
            )
        return operation

    def _record_hpc_fetch_result(self, operation: ControlledOperation, result: dict[str, Any]) -> None:
        adapter_result = dict(operation.adapter_result_envelope or {})
        fetch_refs = [dict(item) for item in list(result.get("fetch_refs") or []) if isinstance(item, dict)]
        registered_artifact_ids = [str(value) for value in list(result.get("registered_artifact_ids") or [])]
        if not fetch_refs and not registered_artifact_ids:
            return
        adapter_result["fetch_refs"] = fetch_refs
        adapter_result["registered_artifact_ids"] = registered_artifact_ids
        adapter_result["output_artifact_ids"] = [str(value) for value in list(result.get("output_artifact_ids") or registered_artifact_ids)]
        bounded_summary = dict(adapter_result.get("bounded_summary") or operation.result_summary or {})
        bounded_summary.update(
            {
                "fetch_status": result.get("status"),
                "fetch_ref_count": len(fetch_refs),
                "registered_artifact_ids": registered_artifact_ids,
            }
        )
        adapter_result["bounded_summary"] = bounded_summary
        self.repositories.controlled_operations.save(
            replace(
                operation,
                adapter_result_envelope=adapter_result,
                result_summary=bounded_summary,
                updated_at=utc_now_iso(),
            )
        )

    def _handle_controlled_operation(self, request: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
        envelope = self._validated_s10_envelope(params)
        operation_digest = self._operation_digest(envelope)
        idempotency_key = str(envelope["idempotency_key"])
        existing = self.repositories.controlled_operations.find_by_idempotency_key(
            session_id=self.session_id,
            sandbox_run_id=self.sandbox_run_id,
            idempotency_key=idempotency_key,
        )
        if existing is not None:
            if existing.operation_digest != operation_digest:
                raise SandboxRuntimeError(
                    "operation_drift_detected",
                    "supervised SDK operation idempotency key was reused with a different digest",
                    details={
                        "operation_id": existing.operation_id,
                        "operation_digest": existing.operation_digest,
                        "new_operation_digest": operation_digest,
                    },
                )
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": self._resume_or_return(existing, envelope)}

        reusable = self.repositories.controlled_operations.find_reusable_approved(
            session_id=self.session_id,
            operation_digest=operation_digest,
        )
        if (
            reusable is not None
            and envelope["schema_version"] == S12_ADAPTER_ENVELOPE_SCHEMA
            and reusable.status is ControlledOperationStatus.COMPLETED
            and reusable.adapter_result_origin != S12_HOST_RESULT_ORIGIN
        ):
            # An untrusted historical result grants neither result reuse nor
            # implicit execution authority. A fresh idempotency key must pass
            # through a new approval instead of inheriting the old approval.
            reusable = None
        if reusable is not None:
            operation = self._create_operation(
                envelope,
                operation_digest=operation_digest,
                status=ControlledOperationStatus.RUNNING,
                approval_id=reusable.approval_id,
                approval_state=ApprovalRequestStatus.APPROVED.value,
            )
            if (
                operation.adapter_envelope_schema_version == S12_ADAPTER_ENVELOPE_SCHEMA
                and reusable.status is ControlledOperationStatus.COMPLETED
                and reusable.adapter_result_envelope
                and reusable.adapter_result_origin == S12_HOST_RESULT_ORIGIN
            ):
                envelope = {
                    **envelope,
                    "adapter_result": dict(reusable.adapter_result_envelope),
                    "result_summary": dict(
                        reusable.result_summary
                        or dict(reusable.adapter_result_envelope).get("bounded_summary")
                        or {"status": "completed"}
                    ),
                    "_host_validated_result_reuse": True,
                }
            result = self._complete_running_operation(operation, envelope)
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

        operation = self._create_operation(
            envelope,
            operation_digest=operation_digest,
            status=ControlledOperationStatus.WAITING_APPROVAL,
            approval_state=ApprovalRequestStatus.PENDING.value,
        )
        approval = self._create_approval(operation, envelope)
        operation = replace(operation, approval_id=approval.approval_id, updated_at=utc_now_iso())
        if operation.adapter_envelope_schema_version == S12_ADAPTER_ENVELOPE_SCHEMA:
            operation = replace(operation, adapter_approval_envelope=self._adapter_approval_envelope(operation))
        self.repositories.controlled_operations.save(operation)
        continuation = self._create_continuation(operation, approval)
        claimed = self._wait_for_approval_and_claim(continuation.continuation_id)
        operation = self.repositories.controlled_operations.get(operation.operation_id) or operation
        if claimed.status is ContinuationStateStatus.CLAIMED:
            operation = replace(
                operation,
                status=ControlledOperationStatus.RUNNING,
                approval_state=ApprovalRequestStatus.APPROVED.value,
                updated_at=utc_now_iso(),
            )
            self.repositories.controlled_operations.save(operation)
        result = self._complete_running_operation(
            operation,
            envelope,
            continuation_id=claimed.continuation_id,
        )
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": result}

    def _validated_s10_envelope(self, params: dict[str, Any]) -> dict[str, Any]:
        schema_version = str(params.get("schema_version") or "")
        if schema_version == S12_ADAPTER_ENVELOPE_SCHEMA:
            return self._validated_s12_envelope(params)
        if schema_version != S10_SUPERVISED_RPC_SCHEMA:
            raise SandboxRuntimeError(
                "sdk_rpc_schema_unsupported",
                "supervised SDK RPC requires a supported schema_version",
            )
        backend_category = str(params.get("backend_category") or "")
        if backend_category not in {"provider_http", "host_local_tool", "hpc_runner"}:
            raise SandboxRuntimeError(
                "operation_prerequisite_missing",
                "backend_category must be provider_http, host_local_tool, or hpc_runner",
            )
        logical_operation_key = str(params.get("logical_operation_key") or "")
        idempotency_key = str(params.get("idempotency_key") or "")
        params_digest = str(params.get("params_digest") or "")
        if not logical_operation_key or not idempotency_key or not params_digest:
            raise SandboxRuntimeError(
                "invalid_tool_arguments",
                "logical_operation_key, idempotency_key, and params_digest are required",
            )
        input_artifact_digests = params.get("input_artifact_digests") or []
        if not isinstance(input_artifact_digests, list):
            raise SandboxRuntimeError("invalid_tool_arguments", "input_artifact_digests must be a list")
        expected_outputs_summary = params.get("expected_outputs_summary") or {}
        resource_estimate = params.get("resource_estimate") or {}
        if not isinstance(expected_outputs_summary, dict) or not isinstance(resource_estimate, dict):
            raise SandboxRuntimeError(
                "invalid_tool_arguments",
                "expected_outputs_summary and resource_estimate must be objects",
            )
        result_summary = params.get("result_summary") or {"status": "completed"}
        if not isinstance(result_summary, dict):
            raise SandboxRuntimeError("invalid_tool_arguments", "result_summary must be an object")
        return {
            "schema_version": schema_version,
            "adapter_envelope_schema_version": None,
            "idempotency_key": idempotency_key,
            "sandbox_workspace_id": self.sandbox_workspace_id,
            "sandbox_run_id": self.sandbox_run_id,
            "source_snapshot_artifact_id": self.source_snapshot_artifact_id,
            "source_snapshot_digest": self.source_tree_digest,
            "logical_operation_key": logical_operation_key,
            "sdk_module": None,
            "function_name": None,
            "params_digest": params_digest,
            "input_artifact_ids": [],
            "input_artifact_digests": sorted(str(item) for item in input_artifact_digests),
            "backend_category": backend_category,
            "route_policy_id": None,
            "placement": None,
            "hpc_workspace_id": None,
            "stage_refs": [],
            "selected_backend": backend_category,
            "resource_class": None,
            "runtime_packaging_id": None,
            "toolchain_id": None,
            "provider_config_digest": None,
            "planned_fetch_intent": {},
            "approval_requirement": {},
            "expected_outputs_summary": expected_outputs_summary,
            "resource_estimate": resource_estimate,
            "result_summary": result_summary,
            "route_reason": str(params.get("route_reason") or "s10_generic_backend_category"),
            "adapter_result": {},
        }

    def _validated_s12_envelope(self, params: dict[str, Any]) -> dict[str, Any]:
        caller_result_fields = sorted(
            field
            for field in ("adapter_result", "result_summary")
            if field in params
        )
        if caller_result_fields:
            raise SandboxRuntimeError(
                "adapter_result_forbidden",
                "S12 adapter_result and result_summary are Host-owned and cannot be supplied by sandbox code.",
                details={"forbidden_fields": caller_result_fields},
            )
        route_policy_id = str(params.get("route_policy_id") or "")
        policy = self._route_policy(route_policy_id)
        sdk_module = str(params.get("sdk_module") or policy["sdk_module"])
        function_name = str(params.get("function_name") or policy["function_name"])
        if sdk_module != policy["sdk_module"] or function_name != policy["function_name"]:
            raise SandboxRuntimeError(
                "adapter_schema_incompatible",
                "SDK module/function does not match the selected route policy",
                details={
                    "route_policy_id": route_policy_id,
                    "sdk_module": sdk_module,
                    "function_name": function_name,
                },
            )
        if policy["selected_backend"] == "fixture":
            raise SandboxRuntimeError(
                "fixture_backend_forbidden",
                "deterministic fixture adapter is not allowed on the product path",
                details={"route_policy_id": route_policy_id},
            )
        if policy.get("status") != "ok":
            raise SandboxRuntimeError(
                str(policy.get("error_code") or "operation_prerequisite_missing"),
                "route policy prerequisite is not satisfied",
                details={"route_policy_id": route_policy_id, "status": policy.get("status")},
            )
        self._require_policy_refs(policy, route_policy_id=route_policy_id)
        idempotency_key = str(params.get("idempotency_key") or "")
        params_digest = str(params.get("params_digest") or "")
        if not idempotency_key or not params_digest:
            raise SandboxRuntimeError(
                "invalid_tool_arguments",
                "idempotency_key and params_digest are required",
            )
        adapter_params: dict[str, Any] | None = None
        if "params" in params:
            raw_adapter_params = params.get("params")
            if not isinstance(raw_adapter_params, dict):
                raise SandboxRuntimeError("invalid_tool_arguments", "adapter params must be an object")
            if _json_digest(raw_adapter_params) != params_digest:
                raise SandboxRuntimeError(
                    "adapter_params_digest_mismatch",
                    "adapter params do not match params_digest",
                    details={"params_digest": params_digest},
                )
            scrubbed_params = _scrub_private_adapter_payload(raw_adapter_params)
            adapter_params = dict(scrubbed_params) if isinstance(scrubbed_params, dict) else {}
        input_artifact_ids = params.get("input_artifact_ids") or []
        input_artifact_digests = params.get("input_artifact_digests") or []
        stage_refs = params.get("stage_refs") or []
        if not isinstance(input_artifact_ids, list) or not isinstance(input_artifact_digests, list):
            raise SandboxRuntimeError("invalid_tool_arguments", "input artifact fields must be lists")
        if len(input_artifact_ids) != len(input_artifact_digests):
            raise SandboxRuntimeError(
                "invalid_tool_arguments",
                "input artifact IDs and digests must have the same length",
            )
        input_artifact_pairs = sorted(
            (
                (str(artifact_id), str(artifact_digest))
                for artifact_id, artifact_digest in zip(
                    input_artifact_ids,
                    input_artifact_digests,
                    strict=True,
                )
            ),
            key=lambda pair: pair[0],
        )
        if any(
            not artifact_id
            or artifact_id != artifact_id.strip()
            or not _is_sha256_digest(artifact_digest)
            for artifact_id, artifact_digest in input_artifact_pairs
        ):
            raise SandboxRuntimeError(
                "adapter_input_binding_mismatch",
                "S12 approved input artifacts require canonical IDs and sha256 digests.",
            )
        if not isinstance(stage_refs, list) or not all(isinstance(item, dict) for item in stage_refs):
            raise SandboxRuntimeError("invalid_tool_arguments", "stage_refs must be a list of objects")
        expected_outputs = params.get("expected_outputs", params.get("expected_outputs_summary") or {})
        expected_outputs_summary = self._expected_outputs_summary(expected_outputs)
        resource_estimate = params.get("resource_estimate") or {}
        if not isinstance(resource_estimate, dict):
            raise SandboxRuntimeError("invalid_tool_arguments", "resource_estimate must be an object")
        planned_fetch_intent = params.get("planned_fetch_intent") or {}
        if not isinstance(planned_fetch_intent, dict):
            raise SandboxRuntimeError("invalid_tool_arguments", "planned_fetch_intent must be an object")
        planned_fetch_intent = dict(_scrub_private_adapter_payload(planned_fetch_intent))
        placement = str(params.get("placement") or "provider")
        hpc_workspace_id = str(params.get("hpc_workspace_id") or "")
        if policy["selected_backend"] == "hpc":
            if placement != "hpc" or not hpc_workspace_id:
                raise SandboxRuntimeError(
                    "hpc_workspace_forbidden",
                    "HPC route operations require explicit hpc placement and hpc_workspace_id",
                    details={"route_policy_id": route_policy_id},
                )
            if not stage_refs:
                raise SandboxRuntimeError(
                    "hpc_workspace_forbidden",
                    "HPC route operations require stage_refs",
                    details={"route_policy_id": route_policy_id},
                )
            stage_refs = self._validated_hpc_stage_refs(stage_refs, hpc_workspace_id=hpc_workspace_id)
            planned_fetch_intent = self._validated_hpc_fetch_intent(planned_fetch_intent)
        else:
            stage_refs = self._validated_provider_stage_refs(stage_refs)
        stage_ref_pairs = _artifact_ref_pairs(stage_refs)
        adapter_param_pairs = self._validated_adapter_param_pairs(
            sdk_module=sdk_module,
            function_name=function_name,
            adapter_params=adapter_params or {},
            stage_refs=stage_refs,
        )
        if (
            len(stage_ref_pairs) != len(stage_refs)
            or stage_ref_pairs != input_artifact_pairs
            or adapter_param_pairs != input_artifact_pairs
        ):
            raise SandboxRuntimeError(
                "adapter_input_binding_mismatch",
                "S12 stage refs, adapter params, and approved input artifact pairs must match exactly.",
                details={
                    "approved_input_count": len(input_artifact_pairs),
                    "stage_ref_count": len(stage_ref_pairs),
                    "adapter_param_ref_count": len(adapter_param_pairs),
                },
            )
        logical_operation_key = f"{sdk_module}.{function_name}"
        return {
            "schema_version": S12_ADAPTER_ENVELOPE_SCHEMA,
            "adapter_envelope_schema_version": S12_ADAPTER_ENVELOPE_SCHEMA,
            "idempotency_key": idempotency_key,
            "sandbox_workspace_id": self.sandbox_workspace_id,
            "sandbox_run_id": self.sandbox_run_id,
            "source_snapshot_artifact_id": self.source_snapshot_artifact_id,
            "source_snapshot_digest": self.source_tree_digest,
            "logical_operation_key": logical_operation_key,
            "sdk_module": sdk_module,
            "function_name": function_name,
            "params_digest": params_digest,
            "input_artifact_ids": [pair[0] for pair in input_artifact_pairs],
            "input_artifact_digests": [pair[1] for pair in input_artifact_pairs],
            "backend_category": str(policy["backend_category"]),
            "route_policy_id": route_policy_id,
            "placement": placement,
            "hpc_workspace_id": hpc_workspace_id or None,
            "stage_refs": [dict(item) for item in stage_refs],
            "selected_backend": str(policy["selected_backend"]),
            "route_reason": str(policy["route_reason"]),
            "resource_class": str(policy["resource_class"]),
            "runtime_packaging_id": str(policy.get("runtime_packaging_id") or ""),
            "toolchain_id": policy.get("toolchain_id"),
            "provider_config_digest": policy.get("provider_config_digest"),
            "planned_fetch_intent": planned_fetch_intent,
            "approval_requirement": dict(policy.get("approval_requirement") or {}),
            "expected_outputs_summary": expected_outputs_summary,
            "resource_estimate": resource_estimate,
            # Result fields are internal Host slots. They are never populated
            # from the sandbox wire envelope; only the Host adapter executor or
            # a validated approved-result reuse may fill them.
            "result_summary": None,
            "adapter_result": {},
            "adapter_params": adapter_params,
        }

    def _route_policy(self, route_policy_id: str) -> dict[str, Any]:
        if not route_policy_id:
            raise SandboxRuntimeError("route_policy_missing", "route_policy_id is required")
        policy = S12_ROUTE_POLICIES.get(route_policy_id)
        if policy is None:
            raise SandboxRuntimeError(
                "route_policy_missing",
                "route policy is not registered",
                details={"route_policy_id": route_policy_id},
            )
        return dict(policy)

    def _require_policy_refs(self, policy: dict[str, Any], *, route_policy_id: str) -> None:
        if not policy.get("evidence_ref") or not policy.get("parameter_inventory_ref"):
            raise SandboxRuntimeError(
                "operation_prerequisite_missing",
                "route policy must include evidence and parameter inventory refs",
                details={"route_policy_id": route_policy_id},
            )
        if not policy.get("runtime_packaging_id"):
            raise SandboxRuntimeError(
                "runtime_packaging_missing",
                "route policy must include runtime_packaging_id",
                details={"route_policy_id": route_policy_id},
            )
        if policy.get("backend_category") == "provider_http" and not policy.get("provider_config_digest"):
            raise SandboxRuntimeError(
                "operation_prerequisite_missing",
                "provider route policy must include provider_config_digest",
                details={"route_policy_id": route_policy_id},
            )
        if policy.get("selected_backend") == "hpc" and not policy.get("toolchain_id"):
            raise SandboxRuntimeError(
                "operation_prerequisite_missing",
                "HPC route policy must include toolchain_id",
                details={"route_policy_id": route_policy_id},
            )

    def _validated_hpc_stage_refs(
        self,
        stage_refs: list[Any],
        *,
        hpc_workspace_id: str,
    ) -> list[dict[str, Any]]:
        safe_keys = {
            "kind",
            "stage_ref_id",
            "hpc_workspace_id",
            "artifact_id",
            "artifact_digest",
            "workspace_relative_path",
            "source",
            "sandbox_workspace_id",
        }
        validated: list[dict[str, Any]] = []
        for ref in stage_refs:
            raw_item = dict(ref)
            item = {key: raw_item[key] for key in safe_keys if key in raw_item}
            if item.get("kind") != "hpc_stage_ref":
                raise SandboxRuntimeError(
                    "hpc_stage_ref_required",
                    "HPC route operations require S11 hpc_stage_ref entries",
                )
            if str(item.get("hpc_workspace_id") or "") != hpc_workspace_id:
                raise SandboxRuntimeError(
                    "hpc_workspace_forbidden",
                    "HPC stage ref belongs to a different workspace",
                    details={"hpc_workspace_id": hpc_workspace_id},
                )
            if not item.get("stage_ref_id") or not item.get("artifact_id") or not item.get("artifact_digest"):
                raise SandboxRuntimeError(
                    "hpc_stage_ref_required",
                    "HPC stage refs must include stage_ref_id, artifact_id, and artifact_digest",
                )
            workspace_path = str(item.get("workspace_relative_path") or "")
            if workspace_path:
                item["workspace_relative_path"] = self._validated_hpc_workspace_path(workspace_path)
            validated.append(item)
        return validated

    def _validated_provider_stage_refs(
        self,
        stage_refs: list[Any],
    ) -> list[dict[str, str]]:
        expected_keys = {"artifact_id", "content_digest"}
        validated: list[dict[str, str]] = []
        for ref in stage_refs:
            raw_item = dict(ref)
            if set(raw_item) != expected_keys:
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    "Provider stage refs must be closed artifact_id/content_digest objects.",
                    details={"stage_ref_fields": sorted(raw_item)},
                )
            artifact_id = str(raw_item.get("artifact_id") or "")
            content_digest = str(raw_item.get("content_digest") or "")
            if (
                not artifact_id
                or artifact_id != artifact_id.strip()
                or not _is_sha256_digest(content_digest)
            ):
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    "Provider stage refs require a canonical artifact ID and sha256 digest.",
                )
            validated.append(
                {
                    "artifact_id": artifact_id,
                    "content_digest": content_digest,
                }
            )
        return validated

    def _validated_adapter_param_pairs(
        self,
        *,
        sdk_module: str,
        function_name: str,
        adapter_params: dict[str, Any],
        stage_refs: list[dict[str, Any]],
    ) -> list[tuple[str, str]]:
        route = (sdk_module, function_name)
        direct_pairs = _artifact_ref_pairs(adapter_params)

        if route == ("bio", "hmmer_search"):
            artifact_id = str(adapter_params.get("hmm_artifact_id") or "")
            artifact_digest = str(
                adapter_params.get("hmm_artifact_digest") or ""
            )
            if (
                not artifact_id
                or artifact_id != artifact_id.strip()
                or not _is_sha256_digest(artifact_digest)
                or direct_pairs
            ):
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    "bio.hmmer_search requires one closed HMM artifact ID/digest binding.",
                )
            return [(artifact_id, artifact_digest)]

        if route == ("bio", "uniprot_fetch"):
            source_ref = adapter_params.get("source_hit_artifact") or {}
            if not isinstance(source_ref, dict):
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    "bio.uniprot_fetch source_hit_artifact must be an object.",
                )
            if not source_ref:
                if direct_pairs:
                    raise SandboxRuntimeError(
                        "adapter_input_binding_mismatch",
                        "bio.uniprot_fetch contains an undeclared artifact ref.",
                    )
                return []
            if set(source_ref) != {"artifact_id", "content_digest"}:
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    "bio.uniprot_fetch source_hit_artifact must be a closed artifact ref.",
                )
            pairs = _artifact_ref_pairs(source_ref)
            if len(pairs) != 1 or direct_pairs != pairs:
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    "bio.uniprot_fetch contains an inconsistent source artifact ref.",
                )
            return pairs

        hpc_slots = {
            ("bio_tools", "cdhit"): ("input_fasta",),
            ("bio_tools", "mafft"): ("input_fasta",),
            ("bio_tools", "hmmbuild"): ("alignment",),
            ("bio_tools", "hmmalign"): ("hmm", "fasta"),
            ("structure_tools", "fpocket"): ("structure",),
        }.get(route)
        if hpc_slots is not None:
            stage_refs_by_pair = {
                pair: ref
                for ref in stage_refs
                for pair in _artifact_ref_pairs(ref)
            }
            pairs: list[tuple[str, str]] = []
            for slot in hpc_slots:
                raw_ref = adapter_params.get(slot)
                if not isinstance(raw_ref, dict):
                    raise SandboxRuntimeError(
                        "adapter_input_binding_mismatch",
                        f"{sdk_module}.{function_name} requires artifact ref slot {slot}.",
                    )
                scrubbed_ref = _scrub_private_adapter_payload(raw_ref)
                ref_pairs = _artifact_ref_pairs(scrubbed_ref)
                if len(ref_pairs) != 1:
                    raise SandboxRuntimeError(
                        "adapter_input_binding_mismatch",
                        f"{sdk_module}.{function_name} artifact ref slot {slot} is invalid.",
                    )
                pair = ref_pairs[0]
                if scrubbed_ref != stage_refs_by_pair.get(pair):
                    raise SandboxRuntimeError(
                        "adapter_input_binding_mismatch",
                        f"{sdk_module}.{function_name} artifact ref slot {slot} does not match its closed stage ref.",
                    )
                pairs.append(pair)
            if sorted(pairs) != direct_pairs:
                raise SandboxRuntimeError(
                    "adapter_input_binding_mismatch",
                    f"{sdk_module}.{function_name} contains an undeclared artifact ref.",
                )
            return sorted(pairs)

        if direct_pairs:
            raise SandboxRuntimeError(
                "adapter_input_binding_mismatch",
                f"{sdk_module}.{function_name} does not declare artifact-bearing params.",
            )
        return []

    def _validated_hpc_fetch_intent(self, planned_fetch_intent: dict[str, Any]) -> dict[str, Any]:
        intent = dict(_scrub_private_adapter_payload(planned_fetch_intent))
        declared_outputs = intent.get("declared_outputs") or intent.get("expected_outputs") or []
        if not isinstance(declared_outputs, list) or not declared_outputs:
            raise SandboxRuntimeError(
                "hpc_fetch_not_declared",
                "HPC route operations require planned_fetch_intent declared_outputs",
            )
        validated_outputs: list[dict[str, Any]] = []
        for output in declared_outputs:
            if not isinstance(output, dict):
                raise SandboxRuntimeError(
                    "hpc_fetch_not_declared",
                    "planned_fetch_intent declared_outputs must be objects",
                )
            item = dict(output)
            item["path"] = self._validated_hpc_workspace_path(str(item.get("path") or ""))
            validated_outputs.append(item)
        intent["declared_outputs"] = validated_outputs
        return intent

    def _validated_hpc_workspace_path(self, value: str) -> str:
        normalized = value.strip()
        path = PurePosixPath(normalized)
        forbidden_chars = (";", "&", "|", "`", "$", "\\", "\n", "\r", "<", ">", "*", "?", "[", "]", "{", "}", "!")
        if (
            not normalized
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
            or any(char in normalized for char in forbidden_chars)
        ):
            raise SandboxRuntimeError(
                "hpc_stage_path_invalid",
                "HPC workspace paths must be normalized workspace-relative paths",
            )
        return path.as_posix()

    def _expected_outputs_summary(self, expected_outputs: Any) -> dict[str, Any]:
        if isinstance(expected_outputs, dict):
            return dict(_scrub_private_adapter_payload(expected_outputs))
        if isinstance(expected_outputs, list):
            return {"items": list(_scrub_private_adapter_payload(expected_outputs))}
        raise SandboxRuntimeError("invalid_tool_arguments", "expected_outputs must be an object or list")

    def _operation_digest(self, envelope: dict[str, Any]) -> str:
        if envelope["schema_version"] == S12_ADAPTER_ENVELOPE_SCHEMA:
            return _json_digest(
                {
                    "schema_version": envelope["schema_version"],
                    "sandbox_workspace_id": envelope["sandbox_workspace_id"],
                    "source_snapshot_digest": envelope["source_snapshot_digest"],
                    "sdk_module": envelope["sdk_module"],
                    "function_name": envelope["function_name"],
                    "params_digest": envelope["params_digest"],
                    "input_artifact_ids": envelope["input_artifact_ids"],
                    "input_artifact_digests": envelope["input_artifact_digests"],
                    "placement": envelope["placement"],
                    "hpc_workspace_id": envelope["hpc_workspace_id"],
                    "stage_refs": envelope["stage_refs"],
                    "selected_backend": envelope["selected_backend"],
                    "route_reason": envelope["route_reason"],
                    "route_policy_id": envelope["route_policy_id"],
                    "runtime_packaging_id": envelope["runtime_packaging_id"],
                    "toolchain_id": envelope["toolchain_id"],
                    "provider_config_digest": envelope["provider_config_digest"],
                    "resource_class": envelope["resource_class"],
                    "resource_estimate": envelope["resource_estimate"],
                    "expected_outputs": envelope["expected_outputs_summary"],
                    "planned_fetch_intent": envelope["planned_fetch_intent"],
                    "approval_requirement": envelope["approval_requirement"],
                }
            )
        return _json_digest(
            {
                "schema_version": envelope["schema_version"],
                "sandbox_workspace_id": envelope["sandbox_workspace_id"],
                "source_snapshot_digest": envelope["source_snapshot_digest"],
                "logical_operation_key": envelope["logical_operation_key"],
                "params_digest": envelope["params_digest"],
                "input_artifact_digests": envelope["input_artifact_digests"],
                "backend_category": envelope["backend_category"],
                "expected_outputs_summary": envelope["expected_outputs_summary"],
                "resource_estimate": envelope["resource_estimate"],
            }
        )

    def _create_operation(
        self,
        envelope: dict[str, Any],
        *,
        operation_digest: str,
        status: ControlledOperationStatus,
        approval_id: str | None = None,
        approval_state: str | None = None,
        result_summary: dict[str, Any] | None = None,
    ) -> ControlledOperation:
        now = utc_now_iso()
        operation = ControlledOperation(
            operation_id=_new_id("op"),
            session_id=self.session_id,
            sandbox_workspace_id=self.sandbox_workspace_id,
            sandbox_run_id=self.sandbox_run_id,
            logical_operation_key=str(envelope["logical_operation_key"]),
            operation_digest=operation_digest,
            params_digest=str(envelope["params_digest"]),
            backend_category=str(envelope["backend_category"]),
            status=status,
            created_at=now,
            updated_at=now,
            task_id=self.task_id,
            lane_id=self.lane_id,
            approval_id=approval_id,
            approval_state=approval_state,
            route_reason=str(envelope["route_reason"]),
            input_artifact_digests=tuple(envelope["input_artifact_digests"]),
            source_snapshot_artifact_id=str(envelope["source_snapshot_artifact_id"]),
            source_snapshot_digest=str(envelope["source_snapshot_digest"]),
            adapter_envelope_schema_version=envelope.get("adapter_envelope_schema_version"),
            sdk_module=envelope.get("sdk_module"),
            function_name=envelope.get("function_name"),
            route_policy_id=envelope.get("route_policy_id"),
            placement=envelope.get("placement"),
            hpc_workspace_id=envelope.get("hpc_workspace_id"),
            selected_backend=envelope.get("selected_backend"),
            resource_class=envelope.get("resource_class"),
            runtime_packaging_id=envelope.get("runtime_packaging_id"),
            toolchain_id=envelope.get("toolchain_id"),
            provider_config_digest=envelope.get("provider_config_digest"),
            input_artifact_ids=tuple(envelope.get("input_artifact_ids") or ()),
            stage_refs=tuple(dict(item) for item in envelope.get("stage_refs") or ()),
            planned_fetch_intent=dict(envelope.get("planned_fetch_intent") or {}),
            approval_requirement=dict(envelope.get("approval_requirement") or {}),
            expected_outputs_summary=dict(envelope["expected_outputs_summary"]),
            resource_estimate=dict(envelope["resource_estimate"]),
            result_summary=result_summary,
            idempotency_key=str(envelope["idempotency_key"]),
        )
        if envelope["schema_version"] == S12_ADAPTER_ENVELOPE_SCHEMA:
            operation = replace(
                operation,
                adapter_approval_envelope=self._adapter_approval_envelope(operation),
                adapter_result_envelope=self._adapter_result_envelope(operation, envelope)
                if result_summary is not None
                else {},
            )
        self.repositories.controlled_operations.save(operation)
        return operation

    def _adapter_approval_envelope(self, operation: ControlledOperation) -> dict[str, Any]:
        return {
            "adapter_envelope_schema_version": operation.adapter_envelope_schema_version,
            "sandbox_workspace_id": operation.sandbox_workspace_id,
            "sandbox_run_id": operation.sandbox_run_id,
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "approval_id": operation.approval_id,
            "approval_state": operation.approval_state,
            "sdk_module": operation.sdk_module,
            "function_name": operation.function_name,
            "source_snapshot_artifact_id": operation.source_snapshot_artifact_id,
            "source_snapshot_digest": operation.source_snapshot_digest,
            "input_artifact_ids": list(operation.input_artifact_ids),
            "input_artifact_digests": list(operation.input_artifact_digests),
            "params_digest": operation.params_digest,
            "placement": operation.placement,
            "hpc_workspace_id": operation.hpc_workspace_id,
            "stage_refs": [dict(item) for item in operation.stage_refs],
            "selected_backend": operation.selected_backend,
            "route_reason": operation.route_reason,
            "route_policy_id": operation.route_policy_id,
            "runtime_packaging_id": operation.runtime_packaging_id,
            "toolchain_id": operation.toolchain_id,
            "provider_config_digest": operation.provider_config_digest,
            "resource_class": operation.resource_class,
            "resource_estimate": operation.resource_estimate or {},
            "expected_outputs": operation.expected_outputs_summary or {},
            "planned_fetch_intent": operation.planned_fetch_intent or {},
            "approval_requirement": operation.approval_requirement or {},
        }

    def _adapter_result_envelope(self, operation: ControlledOperation, envelope: dict[str, Any]) -> dict[str, Any]:
        if operation.adapter_envelope_schema_version != S12_ADAPTER_ENVELOPE_SCHEMA:
            return {}
        scrubbed_adapter_result = sanitize_public_diagnostic_payload(
            _scrub_private_adapter_payload(envelope.get("adapter_result") or {})
        )
        adapter_result = (
            dict(scrubbed_adapter_result)
            if isinstance(scrubbed_adapter_result, dict)
            else {}
        )
        forbidden_pre_run_keys = {
            "sdk_module",
            "function_name",
            "route_policy_id",
            "placement",
            "hpc_workspace_id",
            "stage_refs",
            "selected_backend",
            "params_digest",
            "source_snapshot_digest",
            "input_artifact_digests",
            "expected_outputs",
            "planned_fetch_intent",
        }
        for key in forbidden_pre_run_keys:
            adapter_result.pop(key, None)
        raw_bounded_summary = (
            adapter_result.get("bounded_summary")
            or operation.result_summary
            or {}
        )
        bounded_summary = (
            _sanitize_toolchain_runtime_identity(
                dict(
                    sanitize_public_diagnostic_payload(raw_bounded_summary)
                    if isinstance(raw_bounded_summary, dict)
                    else {}
                )
            )
            if isinstance(raw_bounded_summary, dict)
            else {}
        )
        return {
            "adapter_envelope_schema_version": operation.adapter_envelope_schema_version,
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "sandbox_run_id": operation.sandbox_run_id,
            "status": adapter_result.get("status") or operation.status.value,
            "result_origin": adapter_result.get("result_origin"),
            "backend_run_id": adapter_result.get("backend_run_id"),
            "provider_request_id": adapter_result.get("provider_request_id"),
            "fetch_refs": list(adapter_result.get("fetch_refs") or []),
            "registered_artifact_ids": list(adapter_result.get("registered_artifact_ids") or []),
            "output_artifact_ids": list(adapter_result.get("output_artifact_ids") or []),
            "validation_results": adapter_result.get("validation_results") or {},
            "bounded_summary": bounded_summary,
            "warnings": _structured_adapter_warnings(adapter_result.get("warnings")),
            "error": _structured_adapter_message(
                adapter_result.get("error"),
                default_code="adapter_error",
            ),
            "safe_diagnostics_ref": adapter_result.get("safe_diagnostics_ref"),
        }

    def _create_approval(self, operation: ControlledOperation, envelope: dict[str, Any]) -> ApprovalRequest:
        approval = ApprovalRequest(
            approval_id=_new_id("appr"),
            session_id=self.session_id,
            task_id=self.task_id,
            lane_id=self.lane_id,
            kind="sdk_controlled_operation",
            requested_action=(
                f"Approve supervised SDK operation {operation.logical_operation_key} "
                f"via {operation.backend_category}"
            ),
            status=ApprovalRequestStatus.PENDING,
            request_ref=operation.operation_id,
            resolution_ref=None,
            created_at=utc_now_iso(),
        )
        self.repositories.approvals.save(approval)
        return approval

    def _create_continuation(self, operation: ControlledOperation, approval: ApprovalRequest) -> ContinuationState:
        now = utc_now_iso()
        continuation = ContinuationState(
            continuation_id=f"{operation.sandbox_run_id}:{operation.operation_id}",
            session_id=self.session_id,
            operation_id=operation.operation_id,
            sandbox_run_id=operation.sandbox_run_id,
            approval_id=approval.approval_id,
            status=ContinuationStateStatus.WAITING_APPROVAL,
            created_at=now,
            updated_at=now,
        )
        self.repositories.continuation_states.save(continuation)
        return continuation

    def _complete_running_operation(
        self,
        operation: ControlledOperation,
        envelope: dict[str, Any],
        *,
        continuation_id: str | None = None,
    ) -> dict[str, Any]:
        envelope = self._execute_adapter_or_fail(
            operation,
            envelope,
            continuation_id=continuation_id,
        )
        safe_result_summary = sanitize_public_diagnostic_payload(
            envelope.get("result_summary") or {"status": "completed"}
        )
        result_summary = _sanitize_toolchain_runtime_identity(
            dict(safe_result_summary)
            if isinstance(safe_result_summary, dict)
            else {"status": "completed"}
        )
        completed = replace(
            operation,
            status=ControlledOperationStatus.COMPLETED,
            approval_state=ApprovalRequestStatus.APPROVED.value,
            result_summary=result_summary,
            error_code=None,
            error_summary=None,
            updated_at=utc_now_iso(),
        )
        if completed.adapter_envelope_schema_version == S12_ADAPTER_ENVELOPE_SCHEMA:
            completed = replace(
                completed,
                adapter_result_envelope=self._adapter_result_envelope(completed, envelope),
                adapter_result_origin=str(
                    dict(envelope.get("adapter_result") or {}).get("result_origin") or ""
                )
                or None,
            )
        self.repositories.controlled_operations.save(completed)
        if continuation_id is not None:
            self.repositories.continuation_states.complete(continuation_id)
        return self._operation_response(completed)

    def _execute_adapter_or_fail(
        self,
        operation: ControlledOperation,
        envelope: dict[str, Any],
        *,
        continuation_id: str | None,
    ) -> dict[str, Any]:
        if operation.adapter_envelope_schema_version != S12_ADAPTER_ENVELOPE_SCHEMA:
            return envelope
        if envelope.get("_host_validated_result_reuse") is True:
            return envelope
        if self.adapter_executor is None:
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code="adapter_execution_unavailable",
                error_summary="S12 adapter operation was approved, but no Host adapter executor is configured.",
            )
            raise SandboxRuntimeError(
                "adapter_execution_unavailable",
                "S12 adapter operation was approved, but no Host adapter executor is configured.",
                details={"operation_id": operation.operation_id},
            )
        if not isinstance(envelope.get("adapter_params"), dict):
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code="adapter_execution_unavailable",
                error_summary="S12 adapter operation was approved, but adapter params are unavailable.",
            )
            raise SandboxRuntimeError(
                "adapter_execution_unavailable",
                "S12 adapter operation was approved, but adapter params are unavailable.",
                details={"operation_id": operation.operation_id},
            )
        try:
            execution = self.adapter_executor(operation, dict(envelope))
        except Exception as exc:
            (
                error_code,
                error_summary,
                stage,
                retryable,
                hint,
                details,
            ) = self._adapter_execution_error(exc)
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code=error_code,
                error_summary=error_summary,
            )
            raise SandboxRuntimeError(
                error_code,
                error_summary,
                stage=stage,
                hint=hint,
                details={"operation_id": operation.operation_id, **details},
                retryable=retryable,
            ) from exc
        if not isinstance(execution, dict):
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code="adapter_result_invalid",
                error_summary="Host adapter executor returned a non-object result.",
            )
            raise SandboxRuntimeError(
                "adapter_result_invalid",
                "Host adapter executor returned a non-object result.",
                details={"operation_id": operation.operation_id},
            )
        adapter_result = execution.get("adapter_result")
        if adapter_result is None:
            adapter_result = execution
        if not isinstance(adapter_result, dict) or not adapter_result:
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code="adapter_result_invalid",
                error_summary="Host adapter executor did not provide an adapter_result object.",
            )
            raise SandboxRuntimeError(
                "adapter_result_invalid",
                "Host adapter executor did not provide an adapter_result object.",
                details={"operation_id": operation.operation_id},
            )
        adapter_status = str(adapter_result.get("status") or "").strip().lower()
        raw_adapter_error = adapter_result.get("error")
        raw_adapter_error_code = adapter_result.get("error_code")
        if (
            adapter_status not in {"completed", "succeeded", "success"}
            or raw_adapter_error not in (None, "", {})
            or raw_adapter_error_code not in (None, "")
        ):
            structured_error = _structured_adapter_message(
                raw_adapter_error,
                default_code="adapter_result_unsuccessful",
            )
            error_code = safe_public_machine_identifier(
                (structured_error or {}).get("code")
                or raw_adapter_error_code,
                fallback="adapter_result_unsuccessful",
            ) or "adapter_result_unsuccessful"
            error_summary = sanitize_public_diagnostic_text(
                (structured_error or {}).get("summary")
                or f"Host adapter executor returned non-success status {adapter_status or '<missing>'}."
            )
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code=error_code,
                error_summary=error_summary,
            )
            raise SandboxRuntimeError(
                error_code,
                error_summary,
                details={"operation_id": operation.operation_id},
            )
        adapter_result = {
            **adapter_result,
            "result_origin": S12_HOST_RESULT_ORIGIN,
        }
        result_summary = execution.get("result_summary") or adapter_result.get("bounded_summary") or {"status": "completed"}
        if not isinstance(result_summary, dict):
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code="adapter_result_invalid",
                error_summary="Host adapter executor returned a non-object result_summary.",
            )
            raise SandboxRuntimeError(
                "adapter_result_invalid",
                "Host adapter executor returned a non-object result_summary.",
                details={"operation_id": operation.operation_id},
            )
        summary_status = str(result_summary.get("status") or "").strip().lower()
        if (
            summary_status
            and summary_status not in {"completed", "succeeded", "success"}
        ) or result_summary.get("error") not in (None, "", {}) or result_summary.get(
            "error_code"
        ) not in (None, ""):
            self._fail_adapter_operation(
                operation,
                continuation_id,
                error_code="adapter_result_inconsistent",
                error_summary=(
                    "Host adapter executor returned a success adapter_result with "
                    "an unsuccessful result_summary."
                ),
            )
            raise SandboxRuntimeError(
                "adapter_result_inconsistent",
                "Host adapter executor returned inconsistent result status.",
                details={"operation_id": operation.operation_id},
            )
        safe_adapter_result = sanitize_public_diagnostic_payload(adapter_result)
        safe_result_summary = sanitize_public_diagnostic_payload(result_summary)
        return {
            **envelope,
            "adapter_result": (
                dict(safe_adapter_result)
                if isinstance(safe_adapter_result, dict)
                else {}
            ),
            "result_summary": (
                dict(safe_result_summary)
                if isinstance(safe_result_summary, dict)
                else {"status": "completed"}
            ),
        }

    def _adapter_execution_error(
        self,
        exc: Exception,
    ) -> tuple[str, str, str | None, bool | None, str | None, dict[str, Any]]:
        error_code = safe_public_machine_identifier(
            getattr(exc, "error_code", None)
            or getattr(exc, "error_type", None),
            fallback="adapter_execution_failed",
        )
        error_summary = sanitize_public_diagnostic_text(
            getattr(exc, "message", None)
            or str(exc)
            or "Host adapter execution failed."
        )
        hint = getattr(exc, "hint", None)
        details = getattr(exc, "details", None)
        safe_details = dict(details) if isinstance(details, dict) else {}
        stage = getattr(exc, "stage", None)
        raw_retryable = getattr(exc, "retryable", None)
        retryable = raw_retryable if isinstance(raw_retryable, bool) else None
        if stage is not None:
            safe_details["stage"] = str(stage)
        if retryable is not None:
            safe_details["retryable"] = retryable
        scrubbed = sanitize_public_diagnostic_payload(
            _scrub_private_adapter_payload(safe_details)
        )
        return (
            error_code,
            error_summary,
            (
                None
                if stage is None
                else safe_public_machine_identifier(
                    stage,
                    fallback="adapter_execution",
                )
            ),
            retryable,
            None if hint is None else sanitize_public_diagnostic_text(hint),
            dict(scrubbed) if isinstance(scrubbed, dict) else {},
        )

    def _resume_or_return(self, operation: ControlledOperation, envelope: dict[str, Any]) -> dict[str, Any]:
        if operation.status is ControlledOperationStatus.COMPLETED:
            if (
                operation.adapter_envelope_schema_version
                == S12_ADAPTER_ENVELOPE_SCHEMA
                and operation.adapter_result_origin != S12_HOST_RESULT_ORIGIN
            ):
                # A completed historical S12 row may contain caller-authored
                # adapter_result JSON, including a forged marker string. The
                # independent Host-owned column is the only reuse authority,
                # and the old approval cannot authorize a hidden rerun.
                raise SandboxRuntimeError(
                    "adapter_result_origin_untrusted",
                    "completed S12 result lacks Host-owned origin and cannot be reused or rerun",
                    details={"operation_id": operation.operation_id},
                )
            return self._operation_response(operation)
        continuation = self.repositories.continuation_states.get_by_operation_id(operation.operation_id)
        if continuation is None:
            raise SandboxRuntimeError(
                "operation_recovery_failed",
                "controlled operation is missing continuation state",
                details={"operation_id": operation.operation_id},
            )
        claimed = self._wait_for_approval_and_claim(continuation.continuation_id)
        return self._complete_running_operation(
            operation,
            envelope,
            continuation_id=claimed.continuation_id,
        )

    def _fail_adapter_operation(
        self,
        operation: ControlledOperation,
        continuation_id: str | None,
        *,
        error_code: str,
        error_summary: str,
    ) -> None:
        error_code = safe_public_machine_identifier(
            error_code,
            fallback="adapter_execution_failed",
        ) or "adapter_execution_failed"
        error_summary = sanitize_public_diagnostic_text(error_summary)
        if continuation_id is not None:
            self._fail_claimed_operation(
                operation,
                continuation_id,
                error_code=error_code,
                error_summary=error_summary,
            )
            return
        failed = replace(
            operation,
            status=ControlledOperationStatus.FAILED,
            approval_state=ApprovalRequestStatus.APPROVED.value,
            error_code=error_code,
            error_summary=error_summary,
            updated_at=utc_now_iso(),
        )
        self.repositories.controlled_operations.save(failed)

    def _fail_claimed_operation(
        self,
        operation: ControlledOperation,
        continuation_id: str,
        *,
        error_code: str,
        error_summary: str,
    ) -> None:
        error_code = safe_public_machine_identifier(
            error_code,
            fallback="adapter_execution_failed",
        ) or "adapter_execution_failed"
        error_summary = sanitize_public_diagnostic_text(error_summary)
        failed = replace(
            operation,
            status=ControlledOperationStatus.FAILED,
            approval_state=ApprovalRequestStatus.APPROVED.value,
            error_code=error_code,
            error_summary=error_summary,
            updated_at=utc_now_iso(),
        )
        self.repositories.controlled_operations.save(failed)
        self.repositories.continuation_states.fail(
            continuation_id,
            error_code=error_code,
            error_message=error_summary,
        )

    def _wait_for_approval_and_claim(self, continuation_id: str) -> ContinuationState:
        while not self._stop.is_set():
            continuation = self.repositories.continuation_states.get(continuation_id)
            if continuation is None:
                raise SandboxRuntimeError("operation_recovery_failed", "continuation state disappeared")
            if continuation.status is ContinuationStateStatus.REJECTED:
                operation = self.repositories.controlled_operations.get(continuation.operation_id)
                if operation is not None:
                    failed = replace(
                        operation,
                        status=ControlledOperationStatus.FAILED,
                        approval_state=ApprovalRequestStatus.REJECTED.value,
                        error_code="approval_rejected",
                        error_summary="User rejected supervised SDK operation.",
                        updated_at=utc_now_iso(),
                    )
                    self.repositories.controlled_operations.save(failed)
                raise SandboxRuntimeError(
                    "approval_rejected",
                    "supervised SDK operation approval was rejected",
                    details={"continuation_id": continuation_id},
                )
            if continuation.status in {
                ContinuationStateStatus.APPROVED,
                ContinuationStateStatus.CLAIMED,
            }:
                claimed = self.repositories.continuation_states.claim(
                    continuation_id,
                    claimed_by=f"sandbox-supervisor:{self.sandbox_run_id}",
                )
                if claimed is not None:
                    return claimed
                latest = self.repositories.continuation_states.get(continuation_id)
                if (
                    latest is not None
                    and latest.status is ContinuationStateStatus.CLAIMED
                    and latest.claim_expires_at is not None
                    and latest.claim_expires_at > utc_now_iso()
                ):
                    raise SandboxRuntimeError(
                        "operation_lease_conflict",
                        "SDK continuation is already claimed by another supervisor worker",
                        details={"continuation_id": continuation_id},
                    )
            if continuation.status.is_terminal:
                raise SandboxRuntimeError(
                    continuation.error_code or "operation_recovery_failed",
                    continuation.error_message or "continuation reached a terminal state before resume",
                )
            time.sleep(0.05)
        failed = self.repositories.continuation_states.fail(
            continuation_id,
            error_code="operation_recovery_failed",
            error_message="control socket stopped before SDK continuation resumed",
            recovery_failed=True,
        )
        operation = None if failed is None else self.repositories.controlled_operations.get(failed.operation_id)
        if operation is not None:
            self.repositories.controlled_operations.save(
                replace(
                    operation,
                    status=ControlledOperationStatus.RECOVERY_FAILED,
                    error_code="operation_recovery_failed",
                    error_summary="control socket stopped before SDK continuation resumed",
                    updated_at=utc_now_iso(),
                )
            )
        raise SandboxRuntimeError("operation_recovery_failed", "control socket stopped before SDK continuation resumed")

    def _operation_response(self, operation: ControlledOperation) -> dict[str, Any]:
        response = {
            "schema_version": "s10.supervised_rpc.v1",
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "approval_id": operation.approval_id,
            "approval_state": operation.approval_state,
            "backend_category": operation.backend_category,
            "route_reason": operation.route_reason,
            "status": operation.status.value,
            "result_summary": operation.result_summary or {},
        }
        if operation.adapter_envelope_schema_version == S12_ADAPTER_ENVELOPE_SCHEMA:
            response.update(
                {
                    "schema_version": S12_ADAPTER_ENVELOPE_SCHEMA,
                    "adapter_envelope_schema_version": operation.adapter_envelope_schema_version,
                    "sdk_module": operation.sdk_module,
                    "function_name": operation.function_name,
                    "route_policy_id": operation.route_policy_id,
                    "placement": operation.placement,
                    "hpc_workspace_id": operation.hpc_workspace_id,
                    "selected_backend": operation.selected_backend,
                    "resource_class": operation.resource_class,
                    "runtime_packaging_id": operation.runtime_packaging_id,
                    "toolchain_id": operation.toolchain_id,
                    "provider_config_digest": operation.provider_config_digest,
                    "stage_refs": [dict(item) for item in operation.stage_refs],
                    "planned_fetch_intent": operation.planned_fetch_intent or {},
                    "adapter_approval_envelope": operation.adapter_approval_envelope or {},
                    "adapter_result_envelope": operation.adapter_result_envelope or {},
                }
            )
        sanitized = sanitize_public_diagnostic_payload(response)
        return dict(sanitized) if isinstance(sanitized, dict) else {}


@dataclass(slots=True)
class SandboxRuntimeService:
    repositories: Any
    workspace_root: Path | None = None
    artifact_blob_root: Path | None = None
    log_root: Path | None = None
    execution_backend: str = "podman"
    podman_binary: str = "podman"
    adapter_executor: SandboxAdapterExecutor | None = None
    hpc_fetch_executor: SandboxHpcFetchExecutor | None = None
    repository_scope_factory: Callable[[], Any] | None = None

    def _local_pipeline_sdk_src(self) -> Path | None:
        candidate = Path(__file__).resolve().parents[3] / "openzyme-pipeline" / "src"
        if (candidate / "openzyme_pipeline").is_dir():
            return candidate
        return None

    def _prepare_pipeline_sdk_src(self, *, workspace_path: Path) -> Path | None:
        sdk_src = self._local_pipeline_sdk_src()
        if sdk_src is None:
            return None
        runtime_src = workspace_path / "sdk_src"
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

    def _pipeline_sdk_digest(self) -> str:
        sdk_src = self._local_pipeline_sdk_src()
        if sdk_src is None:
            raise SandboxRuntimeError(
                "sandbox_runtime_identity_unavailable",
                "openzyme_pipeline SDK source is not available",
            )
        return immutable_source_tree_digest(sdk_src)

    def _sandbox_runtime_identity(
        self,
        workspace: SandboxWorkspaceRecord,
        *,
        pipeline_sdk_digest: str,
    ) -> dict[str, str | None]:
        immutable_image_ref: str | None = None
        if self.execution_backend == "podman":
            if not isinstance(workspace.image_digest, str) or not _is_sha256_digest(
                workspace.image_digest
            ):
                raise SandboxRuntimeError(
                    "sandbox_image_identity_invalid",
                    "sandbox.exec requires a full immutable Podman image digest",
                    hint="Register the sandbox image by resolved sha256 image id before executing.",
                )
            immutable_image_ref = workspace.image_digest
        identity_without_digest: dict[str, str | None] = {
            "execution_backend": self.execution_backend,
            "configured_image_ref": workspace.image_ref,
            "immutable_image_ref": immutable_image_ref,
            "image_digest": workspace.image_digest,
            "pipeline_sdk_digest": pipeline_sdk_digest,
            "sandbox_protocol_version": workspace.sandbox_protocol_version,
            "workspace_manifest_version": workspace.manifest_version,
            "exec_policy_version": EXEC_POLICY_VERSION,
        }
        return {
            **identity_without_digest,
            "runtime_identity_digest": _json_digest(identity_without_digest),
        }

    def list_files(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        path: str = "/workspace",
        recursive: bool = False,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        self._assert_workspace_layout(sandbox_workspace_id)
        workspace_path = self._workspace_path(workspace.sandbox_workspace_id)
        public_path = _public_path(path, default=WORKSPACE_ROOT)
        host_path = _resolve_host_path(workspace_path, public_path, allow_workspace_root=True)
        if not host_path.exists():
            raise SandboxRuntimeError("sandbox_path_forbidden", "listed path does not exist")
        if host_path.is_symlink():
            raise SandboxRuntimeError("sandbox_path_forbidden", "listed path is a symlink")
        if host_path.is_file():
            items = [self._project_file(host_path, workspace_path)]
        else:
            if public_path == WORKSPACE_ROOT:
                roots = [workspace_path / root.relative_to(WORKSPACE_ROOT) for root in ALLOWED_FILE_ROOTS]
                iterator = (child for root in roots if root.exists() for child in (root.rglob("*") if recursive else (root,)))
            else:
                iterator = host_path.rglob("*") if recursive else host_path.iterdir()
            items = []
            truncated = False
            for child in sorted(iterator, key=lambda item: item.relative_to(workspace_path).as_posix()):
                if len(items) >= LIST_MAX_ITEMS:
                    truncated = True
                    break
                if child.is_dir() and recursive:
                    continue
                items.append(self._project_file(child, workspace_path))
            return {
                "sandbox_workspace_id": sandbox_workspace_id,
                "path": public_path.as_posix(),
                "recursive": recursive,
                "items": items,
                "truncated": truncated,
                "warning": "sandbox_listing_truncated" if truncated else None,
            }
        return {
            "sandbox_workspace_id": sandbox_workspace_id,
            "path": public_path.as_posix(),
            "recursive": recursive,
            "items": items,
            "truncated": False,
            "warning": None,
        }

    def read_file(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        path: str,
        offset: int = 0,
        limit: int = READ_DEFAULT_LIMIT,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        self._assert_workspace_layout(sandbox_workspace_id)
        limit = self._bounded_read_limit(limit)
        if offset < 0:
            raise SandboxRuntimeError("sandbox_read_limit_exceeded", "offset must be non-negative")
        public_path = _public_path(path, default=WORKSPACE_ROOT)
        host_path = _resolve_host_path(self._workspace_path(workspace.sandbox_workspace_id), public_path)
        if not host_path.is_file() or host_path.is_symlink():
            raise SandboxRuntimeError("sandbox_path_forbidden", "read path must be a regular file")
        content = host_path.read_bytes()
        digest = _sha256_bytes(content)
        try:
            content.decode("utf-8")
        except UnicodeDecodeError:
            return {
                "sandbox_workspace_id": sandbox_workspace_id,
                "path": public_path.as_posix(),
                "binary": True,
                "content_digest": digest,
                "size_bytes": len(content),
                "mime": "application/octet-stream",
            }
        page = content[offset : offset + limit]
        return {
            "sandbox_workspace_id": sandbox_workspace_id,
            "path": public_path.as_posix(),
            "binary": False,
            "offset": offset,
            "limit": limit,
            "content": page.decode("utf-8", errors="replace"),
            "content_digest": digest,
            "size_bytes": len(content),
            "truncated": offset + limit < len(content),
        }

    def write_file(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        actor_ref: str,
        path: str,
        content: str,
        create_dirs: bool = False,
        expected_digest: str | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_no_active_run(sandbox_workspace_id)
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        self._assert_workspace_layout(sandbox_workspace_id)
        encoded = content.encode("utf-8")
        if len(encoded) > WRITE_MAX_BYTES:
            raise SandboxRuntimeError("sandbox_resource_exceeded", "sandbox.file.write content exceeds 256KiB")
        public_path, host_path = self._regular_file_target(workspace, path)
        old_size = host_path.stat().st_size if host_path.exists() else 0
        self._assert_prospective_quota(
            workspace,
            old_size=old_size,
            new_size=len(encoded),
        )
        old_digest = _file_digest(host_path).content_digest if host_path.exists() else None
        if expected_digest not in {None, ""} and expected_digest != old_digest:
            raise SandboxRuntimeError("sandbox_digest_conflict", "expected_digest does not match current file digest")
        if not host_path.parent.exists():
            if not create_dirs:
                raise SandboxRuntimeError("sandbox_path_forbidden", "parent directory does not exist")
            host_path.parent.mkdir(parents=True, exist_ok=True)
        tmp = host_path.parent / f".{host_path.name}.tmp.{uuid4().hex}"
        tmp.write_bytes(encoded)
        tmp.replace(host_path)
        new_digest = _file_digest(host_path).content_digest
        self._write_audit(
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            actor_ref=actor_ref,
            task_id=task_id,
            lane_id=lane_id,
            operation="write",
            path=public_path.as_posix(),
            old_digest=old_digest,
            new_digest=new_digest,
        )
        self._refresh_workspace_summary(workspace)
        return {"path": public_path.as_posix(), "old_digest": old_digest, "new_digest": new_digest, "size_bytes": len(encoded)}

    def patch_file(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        actor_ref: str,
        path: str,
        base_digest: str,
        patch: str,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_no_active_run(sandbox_workspace_id)
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        self._assert_workspace_layout(sandbox_workspace_id)
        public_path, host_path = self._regular_file_target(workspace, path)
        if not host_path.is_file():
            raise SandboxRuntimeError("sandbox_path_forbidden", "patch target must be an existing regular file")
        old_digest = _file_digest(host_path).content_digest
        if base_digest != old_digest:
            raise SandboxRuntimeError("sandbox_digest_conflict", "base_digest does not match current file digest")
        original = host_path.read_text(encoding="utf-8")
        patched = _apply_unified_diff(original, patch, public_path=public_path)
        self._assert_prospective_quota(
            workspace,
            old_size=host_path.stat().st_size,
            new_size=len(patched.encode("utf-8")),
        )
        tmp = host_path.parent / f".{host_path.name}.tmp.{uuid4().hex}"
        tmp.write_text(patched, encoding="utf-8")
        tmp.replace(host_path)
        new_digest = _file_digest(host_path).content_digest
        self._write_audit(
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            actor_ref=actor_ref,
            task_id=task_id,
            lane_id=lane_id,
            operation="patch",
            path=public_path.as_posix(),
            old_digest=old_digest,
            new_digest=new_digest,
        )
        self._refresh_workspace_summary(workspace)
        return {"path": public_path.as_posix(), "old_digest": old_digest, "new_digest": new_digest}

    def delete_file(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        actor_ref: str,
        path: str,
        expected_digest: str | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> dict[str, Any]:
        self._ensure_no_active_run(sandbox_workspace_id)
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        self._assert_workspace_layout(sandbox_workspace_id)
        public_path, host_path = self._regular_file_target(workspace, path)
        if not host_path.is_file():
            raise SandboxRuntimeError("sandbox_path_forbidden", "delete target must be an existing regular file")
        old_digest = _file_digest(host_path).content_digest
        if expected_digest not in {None, ""} and expected_digest != old_digest:
            raise SandboxRuntimeError("sandbox_digest_conflict", "expected_digest does not match current file digest")
        host_path.unlink()
        self._write_audit(
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            actor_ref=actor_ref,
            task_id=task_id,
            lane_id=lane_id,
            operation="delete",
            path=public_path.as_posix(),
            old_digest=old_digest,
            new_digest=None,
        )
        self._refresh_workspace_summary(workspace)
        return {"path": public_path.as_posix(), "old_digest": old_digest, "deleted": True}

    def exec_command(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        agent_id: str,
        argv: list[str] | tuple[str, ...],
        cwd: str = "/workspace",
        timeout_seconds: int = EXEC_DEFAULT_TIMEOUT_SECONDS,
        env: dict[str, str] | None = None,
        task_id: str | None = None,
        lane_id: str | None = None,
    ) -> SandboxRunRecord:
        workspace = self._require_ready_workspace(session_id, sandbox_workspace_id)
        self._ensure_no_active_run(sandbox_workspace_id)
        argv_tuple = self._validate_argv(argv)
        timeout_seconds = self._bounded_timeout(timeout_seconds)
        user_env = self._validate_user_env(env or {})
        cwd_public = _public_path(cwd, default=WORKSPACE_ROOT)
        workspace_path = self._workspace_path(sandbox_workspace_id)
        self._assert_workspace_layout(sandbox_workspace_id)
        cwd_host = _resolve_host_path(workspace_path, cwd_public, allow_workspace_root=True)
        if not cwd_host.is_dir():
            raise SandboxRuntimeError("sandbox_path_forbidden", "cwd must be a directory under /workspace")
        pipeline_sdk_digest = self._pipeline_sdk_digest()
        runtime_identity = self._sandbox_runtime_identity(
            workspace,
            pipeline_sdk_digest=pipeline_sdk_digest,
        )
        source_snapshot = self._snapshot_source(
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            entrypoint=self._entrypoint_for(argv_tuple),
        )
        now = utc_now_iso()
        run = SandboxRunRecord(
            sandbox_run_id=_new_id("srun"),
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            agent_id=agent_id,
            task_id=task_id,
            lane_id=lane_id,
            argv=argv_tuple,
            argv_digest=_json_digest(list(argv_tuple)),
            cwd=cwd_public.as_posix(),
            env_digest=_json_digest(user_env),
            resource_policy={
                "timeout_seconds": timeout_seconds,
                "cpu": 2,
                "memory": "2GiB",
                "pids": 256,
                "exec_policy_version": EXEC_POLICY_VERSION,
            },
            source_snapshot_artifact_id=source_snapshot["source_snapshot_artifact_id"],
            source_tree_digest=source_snapshot["source_tree_digest"],
            status=SandboxRunStatus.QUEUED,
            changed_files_summary={},
            compatibility=runtime_identity,
            created_at=now,
            updated_at=now,
        )
        self.repositories.sandbox_runs.save(run)
        started_at = utc_now_iso()
        run = replace(run, status=SandboxRunStatus.RUNNING, started_at=started_at, updated_at=started_at)
        self.repositories.sandbox_runs.save(run)
        pre_summary = self._workspace_file_snapshot(sandbox_workspace_id)
        socket_path = Path(tempfile.gettempdir()) / f"oz-{run.sandbox_run_id}.sock"
        server = _ControlSocketServer(
            socket_path=socket_path,
            repositories=self.repositories,
            session_id=session_id,
            sandbox_workspace_id=sandbox_workspace_id,
            sandbox_run_id=run.sandbox_run_id,
            agent_id=agent_id,
            source_snapshot_artifact_id=str(run.source_snapshot_artifact_id),
            source_tree_digest=str(run.source_tree_digest),
            task_id=task_id,
            lane_id=lane_id,
            workspace_root=self.workspace_root,
            artifact_blob_root=self.artifact_blob_root,
            adapter_executor=self.adapter_executor,
            hpc_fetch_executor=self.hpc_fetch_executor,
            repository_scope_factory=self.repository_scope_factory,
        )
        completed: subprocess.CompletedProcess[bytes | str] | None = None
        started = time.monotonic()
        try:
            server.start()
            completed = self._run_process(
                workspace=workspace,
                workspace_path=workspace_path,
                argv=argv_tuple,
                cwd_public=cwd_public,
                cwd_host=cwd_host,
                timeout_seconds=timeout_seconds,
                user_env=user_env,
                socket_path=socket_path,
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                sandbox_run_id=run.sandbox_run_id,
                expected_pipeline_sdk_digest=pipeline_sdk_digest,
            )
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._finish_run(
                run,
                stdout=completed.stdout,
                stderr=completed.stderr,
                exit_code=completed.returncode,
                duration_ms=duration_ms,
                pre_summary=pre_summary,
            )
        except subprocess.TimeoutExpired as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            return self._finish_run(
                run,
                stdout=exc.stdout if isinstance(exc.stdout, (bytes, str)) else b"",
                stderr=exc.stderr if isinstance(exc.stderr, (bytes, str)) else b"",
                exit_code=None,
                duration_ms=duration_ms,
                pre_summary=pre_summary,
                forced_status=SandboxRunStatus.TIMEOUT,
                error_code="sandbox_exec_timeout",
            )
        except Exception as exc:
            duration_ms = int((time.monotonic() - started) * 1000)
            if isinstance(exc, SandboxRuntimeError):
                error_code = exc.error_code
                stderr = str(exc)
            else:
                error_code = "sandbox_run_recovery_failed"
                stderr = str(exc)
            return self._finish_run(
                run,
                stdout="",
                stderr=stderr,
                exit_code=None,
                duration_ms=duration_ms,
                pre_summary=pre_summary,
                forced_status=SandboxRunStatus.FAILED,
                error_code=error_code,
            )
        finally:
            server.stop()

    def mark_stale_active_runs_failed(self, *, sandbox_workspace_id: str, reason: str = "stale active run") -> list[SandboxRunRecord]:
        active = self.repositories.sandbox_runs.get_active_by_workspace(sandbox_workspace_id)
        if active is None:
            return []
        now = utc_now_iso()
        public_reason = _public_sandbox_stdio(
            reason,
            workspace_path=self._workspace_path(sandbox_workspace_id),
            socket_path=Path(tempfile.gettempdir()) / f"oz-{active.sandbox_run_id}.sock",
        )
        failed = replace(
            active,
            status=SandboxRunStatus.FAILED,
            error_code="sandbox_run_recovery_failed",
            stderr_summary=public_reason,
            ended_at=now,
            updated_at=now,
        )
        self.repositories.sandbox_runs.save(failed)
        return [failed]

    def _finish_run(
        self,
        run: SandboxRunRecord,
        *,
        stdout: bytes | str,
        stderr: bytes | str,
        exit_code: int | None,
        duration_ms: int,
        pre_summary: dict[str, Any],
        forced_status: SandboxRunStatus | None = None,
        error_code: str | None = None,
    ) -> SandboxRunRecord:
        stdout_bytes = stdout if isinstance(stdout, bytes) else stdout.encode("utf-8")
        stderr_bytes = stderr if isinstance(stderr, bytes) else stderr.encode("utf-8")
        stdout_text = stdout_bytes.decode("utf-8", errors="replace")
        stderr_text = stderr_bytes.decode("utf-8", errors="replace")
        workspace_path = self._workspace_path(run.sandbox_workspace_id)
        socket_path = Path(tempfile.gettempdir()) / f"oz-{run.sandbox_run_id}.sock"
        public_stdout = _public_sandbox_stdio(
            stdout_text,
            workspace_path=workspace_path,
            socket_path=socket_path,
        )
        public_stderr = _public_sandbox_stdio(
            stderr_text,
            workspace_path=workspace_path,
            socket_path=socket_path,
        )
        (
            stdout_summary,
            public_stdout_truncated,
            _public_stdout_size,
            _public_stdout_digest,
        ) = _bounded_text(public_stdout)
        (
            stderr_summary,
            public_stderr_truncated,
            _public_stderr_size,
            _public_stderr_digest,
        ) = _bounded_text(public_stderr)
        stdout_size = len(stdout_bytes)
        stderr_size = len(stderr_bytes)
        stdout_digest = _sha256_bytes(stdout_bytes)
        stderr_digest = _sha256_bytes(stderr_bytes)
        raw_stdout_truncated = stdout_size > STDIO_INLINE_LIMIT
        raw_stderr_truncated = stderr_size > STDIO_INLINE_LIMIT
        stdout_truncated = raw_stdout_truncated or public_stdout_truncated
        stderr_truncated = raw_stderr_truncated or public_stderr_truncated
        log_refs: dict[str, str] = {}
        if stdout_truncated or stderr_truncated:
            log_refs = self._write_logs(
                run,
                stdout=stdout_bytes,
                stderr=stderr_bytes,
                stdout_digest=stdout_digest,
                stdout_size=stdout_size,
                stdout_truncated=stdout_truncated,
                stderr_digest=stderr_digest,
                stderr_size=stderr_size,
                stderr_truncated=stderr_truncated,
            )
        post_summary = self._workspace_file_snapshot(run.sandbox_workspace_id)
        changed = self._changed_files(pre_summary, post_summary)
        if forced_status is not None:
            status = forced_status
        elif exit_code == 0:
            status = SandboxRunStatus.COMPLETED
        else:
            status = SandboxRunStatus.FAILED
            error_code = error_code or "sandbox_exec_nonzero"
        workspace = self.repositories.sandbox_workspaces.get(run.sandbox_workspace_id)
        if workspace is not None:
            directory_summary = summarize_workspace_directory(
                self._workspace_path(run.sandbox_workspace_id)
            )
            quota_summary = self._quota_summary(workspace, directory_summary)
            if quota_summary["exceeded"]:
                status = SandboxRunStatus.RESOURCE_EXCEEDED
                error_code = "sandbox_quota_exceeded"
        ended_at = utc_now_iso()
        finished = replace(
            run,
            status=status,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            stdout_metadata={
                "raw_digest": stdout_digest,
                "raw_size_bytes": stdout_size,
                "truncated": stdout_truncated,
                "log_ref": log_refs.get("stdout"),
            },
            stderr_metadata={
                "raw_digest": stderr_digest,
                "raw_size_bytes": stderr_size,
                "truncated": stderr_truncated,
                "log_ref": log_refs.get("stderr"),
            },
            exit_code=exit_code,
            duration_ms=duration_ms,
            changed_files_summary=changed,
            log_artifact_ref=log_refs.get("stdout") or log_refs.get("stderr"),
            error_code=error_code,
            ended_at=ended_at,
            updated_at=ended_at,
        )
        self.repositories.sandbox_runs.save(finished)
        if workspace is not None:
            self._refresh_workspace_summary(
                workspace,
                last_command_summary={
                    "sandbox_run_id": finished.sandbox_run_id,
                    "status": finished.status.value,
                    "argv_digest": finished.argv_digest,
                    "cwd": finished.cwd,
                    "started_at": finished.started_at,
                    "ended_at": finished.ended_at,
                    "duration_ms": finished.duration_ms,
                    "exit_code": finished.exit_code,
                    "error_code": finished.error_code,
                    "source_snapshot_artifact_id": finished.source_snapshot_artifact_id,
                    "changed_files_summary": finished.changed_files_summary,
                    "stdout_summary": finished.stdout_summary,
                    "stderr_summary": finished.stderr_summary,
                    "stdout_metadata": finished.stdout_metadata,
                    "stderr_metadata": finished.stderr_metadata,
                    "log_artifact_ref": finished.log_artifact_ref,
                },
                last_error=None
                if finished.status is SandboxRunStatus.COMPLETED
                else {"error_code": finished.error_code, "hint": "Read the sandbox run summary before retrying."},
            )
        return finished

    def _write_logs(
        self,
        run: SandboxRunRecord,
        *,
        stdout: bytes,
        stderr: bytes,
        stdout_digest: str,
        stdout_size: int,
        stdout_truncated: bool,
        stderr_digest: str,
        stderr_size: int,
        stderr_truncated: bool,
    ) -> dict[str, str]:
        root = self._log_root() / run.sandbox_run_id
        if root.is_symlink() or root.exists():
            raise SandboxRuntimeError(
                "sandbox_log_boundary_invalid",
                "sandbox command log directory already exists or is invalid",
            )
        root.mkdir(mode=0o700, exist_ok=False)
        os.chmod(root, 0o700)
        refs: dict[str, str] = {}
        for stream, content, digest, size, truncated in (
            ("stdout", stdout, stdout_digest, stdout_size, stdout_truncated),
            ("stderr", stderr, stderr_digest, stderr_size, stderr_truncated),
        ):
            if not truncated:
                continue
            path = root / f"{stream}.log"
            flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
            if hasattr(os, "O_NOFOLLOW"):
                flags |= os.O_NOFOLLOW
            descriptor = os.open(path, flags, 0o600)
            try:
                os.fchmod(descriptor, 0o600)
                with os.fdopen(descriptor, "wb") as handle:
                    descriptor = -1
                    handle.write(content)
                    handle.flush()
                    os.fsync(handle.fileno())
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            ref = _safe_log_ref(run.sandbox_run_id, stream)
            self.repositories.command_log_artifacts.save(
                CommandLogArtifactRecord(
                    command_log_id=_new_id("cmdlog"),
                    session_id=run.session_id,
                    sandbox_run_id=run.sandbox_run_id,
                    sandbox_workspace_id=run.sandbox_workspace_id,
                    stream=stream,
                    artifact_ref=ref,
                    size_bytes=size,
                    content_digest=digest,
                    truncated=truncated,
                    created_at=utc_now_iso(),
                )
            )
            refs[stream] = ref
        return refs

    def _write_audit(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        actor_ref: str,
        task_id: str | None,
        lane_id: str | None,
        operation: str,
        path: str,
        old_digest: str | None,
        new_digest: str | None,
    ) -> None:
        self.repositories.file_audit_entries.save(
            FileAuditEntry(
                audit_id=_new_id("faudit"),
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                actor_ref=actor_ref,
                task_id=task_id,
                lane_id=lane_id,
                operation=operation,
                path=path,
                old_digest=old_digest,
                new_digest=new_digest,
                created_at=utc_now_iso(),
            )
        )

    def _project_file(self, path: Path, workspace_path: Path) -> dict[str, Any]:
        relative = "/workspace/" + path.relative_to(workspace_path).as_posix()
        if path.is_symlink():
            return {"path": relative, "kind": "symlink", "size_bytes": 0}
        if path.is_dir():
            return {"path": relative, "kind": "directory", "size_bytes": None}
        digest = _file_digest(path)
        return {
            "path": relative,
            "kind": "file",
            "size_bytes": digest.size_bytes,
            "content_digest": digest.content_digest,
        }

    def _regular_file_target(self, workspace: SandboxWorkspaceRecord, path: str) -> tuple[PurePosixPath, Path]:
        public_path = _public_path(path, default=WORKSPACE_ROOT)
        root = _allowed_root_for(public_path)
        if public_path in ALLOWED_FILE_ROOTS or root == WORKSPACE_ROOT:
            raise SandboxRuntimeError("sandbox_path_forbidden", "file operation target must be a file path, not a workspace root")
        host_path = _resolve_host_path(self._workspace_path(workspace.sandbox_workspace_id), public_path)
        if host_path.exists() and host_path.is_symlink():
            raise SandboxRuntimeError("sandbox_path_forbidden", "file operation target must not be a symlink")
        return public_path, host_path

    def _validate_argv(self, argv: list[str] | tuple[str, ...]) -> tuple[str, ...]:
        values = tuple(str(item) for item in argv)
        if not values:
            raise SandboxRuntimeError("invalid_tool_arguments", "sandbox.exec argv must be non-empty")
        forbidden = {"ssh", "scp", "sftp", "sbatch", "srun", "apptainer", "singularity", "docker", "podman", "curl", "wget"}
        executable = Path(values[0]).name
        has_unwrapped_heredoc = False
        if _PYTHON_EXECUTABLE_PATTERN.fullmatch(executable):
            for argument in values[1:]:
                if _UNWRAPPED_HEREDOC_ARG_PATTERN.match(argument):
                    has_unwrapped_heredoc = True
                    break
                if (
                    argument in {"-", "--", "-c", "-m"}
                    or not argument.startswith("-")
                ):
                    break
        if has_unwrapped_heredoc:
            raise SandboxRuntimeError(
                "sandbox_argv_shell_syntax_unsupported",
                "sandbox.exec argv uses direct exec-form arguments and does not parse an unwrapped shell heredoc",
                hint=(
                    "Write the code with sandbox.file.write and run "
                    '["python", "/workspace/src/<file>.py"], or explicitly use '
                    '["bash", "-lc", "<command>"] when shell parsing is intentional.'
                ),
            )
        if executable in forbidden:
            raise SandboxRuntimeError("sandbox_path_forbidden", f"command {executable!r} is forbidden in sandbox.exec")
        joined = " ".join(values)
        forbidden_markers = ("/home/", "/tmp/openzyme", ".ssh", "hpc_runner", "runner_config", "SLURM_", "AWS_SECRET", "OPENAI_API_KEY")
        if any(marker in joined for marker in forbidden_markers):
            raise SandboxRuntimeError("sandbox_path_forbidden", "command contains a forbidden host path, runner, or secret marker")
        return values

    def _validate_user_env(self, env: dict[str, str]) -> dict[str, str]:
        safe: dict[str, str] = {}
        for key, value in env.items():
            text_key = str(key)
            upper = text_key.upper()
            if any(marker in upper for marker in ("SECRET", "TOKEN", "PASSWORD", "CREDENTIAL", "KEY")):
                raise SandboxRuntimeError("sandbox_env_forbidden", f"environment key {text_key!r} looks credential-like")
            if text_key == "PYTHONPATH" or text_key.startswith("OPENZYME_") or text_key.startswith("TASK_"):
                safe[text_key] = str(value)
                continue
            raise SandboxRuntimeError("sandbox_env_forbidden", f"environment key {text_key!r} is not allowlisted")
        return safe

    def _subprocess_env(
        self,
        user_env: dict[str, str],
        socket_path: Path,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        sandbox_run_id: str,
        sandbox_work_root: Path,
    ) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "OPENZYME_CONTROL_SOCKET": str(socket_path),
            "OPENZYME_SANDBOX_MODE": "s10",
            "OPENZYME_SESSION_ID": session_id,
            "OPENZYME_SANDBOX_WORKSPACE_ID": sandbox_workspace_id,
            "OPENZYME_SANDBOX_RUN_ID": sandbox_run_id,
        }
        env.update(user_env)
        env["OPENZYME_SANDBOX_WORK_ROOT"] = str(sandbox_work_root)
        return env

    def _container_env(
        self,
        user_env: dict[str, str],
        *,
        session_id: str,
        sandbox_workspace_id: str,
        sandbox_run_id: str,
    ) -> dict[str, str]:
        env = {
            "OPENZYME_CONTROL_SOCKET": "/openzyme/control.sock",
            "PYTHONPATH": "/openzyme/sdk",
            "OPENZYME_SANDBOX_MODE": "s10",
            "OPENZYME_SESSION_ID": session_id,
            "OPENZYME_SANDBOX_WORKSPACE_ID": sandbox_workspace_id,
            "OPENZYME_SANDBOX_RUN_ID": sandbox_run_id,
        }
        user_pythonpath = user_env.get("PYTHONPATH")
        env.update(user_env)
        env["OPENZYME_SANDBOX_WORK_ROOT"] = "/workspace/work"
        if user_pythonpath:
            env["PYTHONPATH"] = f"/openzyme/sdk:{user_pythonpath}"
        return env

    def _run_process(
        self,
        *,
        workspace: SandboxWorkspaceRecord,
        workspace_path: Path,
        argv: tuple[str, ...],
        cwd_public: PurePosixPath,
        cwd_host: Path,
        timeout_seconds: int,
        user_env: dict[str, str],
        socket_path: Path,
        session_id: str,
        sandbox_workspace_id: str,
        sandbox_run_id: str,
        expected_pipeline_sdk_digest: str,
    ) -> subprocess.CompletedProcess[bytes | str]:
        current_sdk_digest = self._pipeline_sdk_digest()
        if current_sdk_digest != expected_pipeline_sdk_digest:
            raise SandboxRuntimeError(
                "sandbox_runtime_identity_drift",
                "openzyme_pipeline SDK source changed after sandbox run creation",
            )
        if self.execution_backend == "local":
            return self._run_process_with_active_timeout(
                list(argv),
                cwd=str(cwd_host),
                env=self._subprocess_env(
                    user_env,
                    socket_path,
                    session_id=session_id,
                    sandbox_workspace_id=sandbox_workspace_id,
                    sandbox_run_id=sandbox_run_id,
                    sandbox_work_root=workspace_path / "work",
                ),
                timeout_seconds=timeout_seconds,
                sandbox_run_id=sandbox_run_id,
            )
        if self.execution_backend == "podman":
            if shutil.which(self.podman_binary) is None:
                raise SandboxRuntimeError("sandbox_image_missing", "podman binary is not available for sandbox.exec")
            container_lease = PodmanContainerLease.create(
                podman_binary=self.podman_binary,
                workspace_root=_workspace_root(self.workspace_root),
                sandbox_root=workspace_path,
                run_id=sandbox_run_id,
            )
            container_lease.require_absent_before_run()
            try:
                return self._run_process_with_active_timeout(
                    self._podman_command(
                        workspace=workspace,
                        workspace_path=workspace_path,
                        argv=argv,
                        cwd_public=cwd_public,
                        user_env=user_env,
                        socket_path=socket_path,
                        session_id=session_id,
                        sandbox_workspace_id=sandbox_workspace_id,
                        sandbox_run_id=sandbox_run_id,
                        expected_pipeline_sdk_digest=expected_pipeline_sdk_digest,
                        container_lease=container_lease,
                    ),
                    timeout_seconds=timeout_seconds,
                    sandbox_run_id=sandbox_run_id,
                )
            finally:
                container_lease.retire()
        raise SandboxRuntimeError("invalid_tool_arguments", f"unknown sandbox execution backend {self.execution_backend!r}")

    def _run_process_with_active_timeout(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int,
        sandbox_run_id: str,
    ) -> subprocess.CompletedProcess[bytes]:
        process = subprocess.Popen(
            argv,
            cwd=cwd,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        stdout_chunks: list[bytes] = []
        stderr_chunks: list[bytes] = []

        def _drain_output(stream: Any, chunks: list[bytes]) -> None:
            try:
                for chunk in iter(lambda: stream.read(8192), b""):
                    if not chunk:
                        break
                    chunks.append(bytes(chunk))
            finally:
                stream.close()

        stdout_thread = threading.Thread(target=_drain_output, args=(process.stdout, stdout_chunks), daemon=False)
        stderr_thread = threading.Thread(target=_drain_output, args=(process.stderr, stderr_chunks), daemon=False)
        stdout_thread.start()
        stderr_thread.start()
        started = time.monotonic()
        paused_started: float | None = None
        paused_seconds = 0.0
        while process.poll() is None:
            now = time.monotonic()
            if self._sandbox_run_waiting_for_user_approval(sandbox_run_id):
                if paused_started is None:
                    paused_started = now
            elif paused_started is not None:
                paused_seconds += now - paused_started
                paused_started = None
            current_pause = 0.0 if paused_started is None else now - paused_started
            active_elapsed = now - started - paused_seconds - current_pause
            if active_elapsed > timeout_seconds:
                process.kill()
                process.wait()
                stdout_thread.join()
                stderr_thread.join()
                raise subprocess.TimeoutExpired(
                    argv,
                    timeout_seconds,
                    output=b"".join(stdout_chunks),
                    stderr=b"".join(stderr_chunks),
                )
            time.sleep(0.05)
        process.wait()
        stdout_thread.join()
        stderr_thread.join()
        return subprocess.CompletedProcess(
            argv,
            process.returncode,
            stdout=b"".join(stdout_chunks),
            stderr=b"".join(stderr_chunks),
        )

    def _sandbox_run_waiting_for_user_approval(self, sandbox_run_id: str) -> bool:
        for operation in self.repositories.controlled_operations.list_by_run(sandbox_run_id):
            if operation.status is not ControlledOperationStatus.WAITING_APPROVAL:
                continue
            if operation.approval_id is None:
                continue
            approval = self.repositories.approvals.get(operation.approval_id)
            if approval is not None and approval.status is ApprovalRequestStatus.PENDING:
                return True
        return False

    def _podman_command(
        self,
        *,
        workspace: SandboxWorkspaceRecord,
        workspace_path: Path,
        argv: tuple[str, ...],
        cwd_public: PurePosixPath,
        user_env: dict[str, str],
        socket_path: Path,
        session_id: str,
        sandbox_workspace_id: str,
        sandbox_run_id: str,
        expected_pipeline_sdk_digest: str,
        container_lease: PodmanContainerLease,
    ) -> list[str]:
        self._assert_workspace_layout(sandbox_workspace_id)
        env_args = [
            item
            for key, value in sorted(
                self._container_env(
                    user_env,
                    session_id=session_id,
                    sandbox_workspace_id=sandbox_workspace_id,
                    sandbox_run_id=sandbox_run_id,
                ).items()
            )
            for item in ("--env", f"{key}={value}")
        ]
        mounts = [
            f"{workspace_path}:/workspace:ro,Z",
            f"{workspace_path / 'src'}:/workspace/src:Z",
            f"{workspace_path / 'work'}:/workspace/work:Z",
            f"{workspace_path / 'output'}:/workspace/output:Z",
            f"{workspace_path / 'logs'}:/workspace/logs:Z",
            f"{workspace_path / 'input'}:/workspace/input:ro,Z",
            f"{workspace_path / 'manifest'}:/workspace/manifest:ro,Z",
            f"{workspace_path / 'input'}:/openzyme/input:ro,Z",
            f"{workspace_path / 'output'}:/openzyme/output:Z",
            f"{workspace_path / 'work'}:/openzyme/work:Z",
            f"{socket_path}:/openzyme/control.sock:Z",
        ]
        sdk_src = self._prepare_pipeline_sdk_src(workspace_path=workspace_path)
        if sdk_src is None:
            raise SandboxRuntimeError(
                "sandbox_runtime_identity_unavailable",
                "openzyme_pipeline SDK source is not available",
            )
        if immutable_source_tree_digest(sdk_src) != expected_pipeline_sdk_digest:
            raise SandboxRuntimeError(
                "sandbox_runtime_identity_drift",
                "pipeline SDK source drifted during sandbox materialization",
            )
        mounts.append(f"{sdk_src}:/openzyme/sdk:ro,Z")
        mount_args = [item for mount in mounts for item in ("-v", mount)]
        return [
            self.podman_binary,
            "run",
            "--rm",
            *container_lease.run_options(),
            "--network=none",
            "--userns=keep-id",
            "--user",
            f"{os.getuid()}:{os.getgid()}",
            "--security-opt=no-new-privileges",
            "--cap-drop=all",
            "--read-only",
            "--memory=2g",
            "--cpus=2",
            "--pids-limit=256",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=256m",
            *mount_args,
            "-w",
            cwd_public.as_posix(),
            *env_args,
            str(workspace.image_digest),
            *argv,
        ]

    def _bounded_timeout(self, timeout_seconds: int) -> int:
        value = int(timeout_seconds)
        if value <= 0 or value > EXEC_MAX_TIMEOUT_SECONDS:
            raise SandboxRuntimeError(
                "sandbox_resource_exceeded",
                f"timeout_seconds must be between 1 and {EXEC_MAX_TIMEOUT_SECONDS}",
            )
        return value

    def _bounded_read_limit(self, limit: int) -> int:
        value = int(limit)
        if value < 0 or value > READ_MAX_LIMIT:
            raise SandboxRuntimeError("sandbox_read_limit_exceeded", "read limit must be between 0 and 256KiB")
        return value

    def _snapshot_source(self, *, session_id: str, sandbox_workspace_id: str, entrypoint: str) -> dict[str, Any]:
        try:
            result = ArtifactBoundaryService(
                self.repositories,
                workspace_root=self.workspace_root,
                blob_store_root=self.artifact_blob_root,
            ).snapshot_code(
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                paths=None,
                entrypoint=entrypoint,
                metadata={"producer": "sandbox.exec"},
            )
            return result.to_payload()
        except ArtifactBoundaryError as exc:
            raise SandboxRuntimeError(
                exc.error_code,
                str(exc),
                hint=exc.hint,
                details=exc.details,
                retryable=exc.retryable,
            ) from exc

    def _entrypoint_for(self, argv: tuple[str, ...]) -> str:
        if len(argv) >= 2 and Path(argv[0]).name.startswith("python"):
            return argv[1]
        if len(argv) >= 3 and Path(argv[0]).name == "bash" and argv[1] == "-lc":
            return "bash -lc"
        return Path(argv[0]).name

    def _require_workspace(self, session_id: str, sandbox_workspace_id: str) -> SandboxWorkspaceRecord:
        workspace = self.repositories.sandbox_workspaces.get(sandbox_workspace_id)
        if workspace is None or workspace.session_id != session_id:
            raise SandboxRuntimeError("sandbox_workspace_not_found", "sandbox workspace is not available in this session")
        return workspace

    def _require_ready_workspace(self, session_id: str, sandbox_workspace_id: str) -> SandboxWorkspaceRecord:
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
        if workspace.status is not SandboxWorkspaceStatus.READY:
            raise SandboxRuntimeError((workspace.last_error or {}).get("error_code", workspace.status.value), "sandbox workspace is not ready")
        if workspace.image_compatibility is SandboxImageCompatibility.MISSING:
            raise SandboxRuntimeError("sandbox_image_missing", "sandbox image digest is not registered")
        if workspace.image_compatibility is SandboxImageCompatibility.INCOMPATIBLE:
            raise SandboxRuntimeError("sandbox_image_incompatible", "sandbox image is incompatible")
        if workspace.sandbox_protocol_version != SANDBOX_PROTOCOL_VERSION:
            raise SandboxRuntimeError("sandbox_image_incompatible", "sandbox protocol version is incompatible")
        if workspace.manifest_version != SANDBOX_WORKSPACE_MANIFEST_VERSION:
            raise SandboxRuntimeError("sandbox_image_incompatible", "workspace manifest version is incompatible")
        return workspace

    def _assert_workspace_layout(self, sandbox_workspace_id: str) -> None:
        workspace_path = self._workspace_path(sandbox_workspace_id)
        missing: list[str] = []
        invalid: list[str] = []
        if workspace_path.is_symlink() or not workspace_path.is_dir():
            invalid.append("workspace")
        else:
            for name in WORKSPACE_DIRECTORIES:
                directory = workspace_path / name
                if not directory.exists():
                    missing.append(name)
                elif directory.is_symlink() or not directory.is_dir():
                    invalid.append(name)
        if missing or invalid:
            raise SandboxRuntimeError(
                "sandbox_volume_corrupt",
                "sandbox workspace layout is incomplete or invalid",
                hint="Ask the Host operator to inspect or repair the workspace volume before retrying.",
                details={
                    "missing_directories": missing,
                    "invalid_directories": invalid,
                },
            )

    def _ensure_no_active_run(self, sandbox_workspace_id: str) -> None:
        active = self.repositories.sandbox_runs.get_active_by_workspace(sandbox_workspace_id)
        if active is not None:
            raise SandboxRuntimeError(
                "sandbox_run_conflict",
                "sandbox workspace already has an active sandbox.exec run",
                details={"sandbox_run_id": active.sandbox_run_id},
            )

    def _workspace_path(self, sandbox_workspace_id: str) -> Path:
        return _workspace_root(self.workspace_root) / sandbox_workspace_id

    def _log_root(self) -> Path:
        if self.log_root is not None:
            root = self.log_root
        elif self.workspace_root is not None:
            root = self.workspace_root.resolve().parent / "sandbox-command-logs"
        else:
            root = Path(tempfile.gettempdir()) / "openzyme-sandbox-command-logs"
        if root.is_symlink():
            raise SandboxRuntimeError(
                "sandbox_log_boundary_invalid",
                "sandbox command log root must not be a symlink",
            )
        if root.exists():
            if not root.is_dir() or root.stat().st_uid != os.getuid():
                raise SandboxRuntimeError(
                    "sandbox_log_boundary_invalid",
                    "sandbox command log root is not an owned directory",
                )
        else:
            root.mkdir(parents=True, mode=0o700, exist_ok=False)
        os.chmod(root, 0o700)
        return root.resolve()

    def _refresh_workspace_summary(
        self,
        workspace: SandboxWorkspaceRecord,
        *,
        last_command_summary: dict[str, Any] | None = None,
        last_error: dict[str, Any] | None = None,
    ) -> None:
        workspace_path = self._workspace_path(workspace.sandbox_workspace_id)
        directory_summary = summarize_workspace_directory(workspace_path)
        quota_summary = self._quota_summary(workspace, directory_summary)
        quota_exceeded = bool(quota_summary["exceeded"])
        status = workspace.status
        resolved_last_error = last_error
        if quota_exceeded:
            status = SandboxWorkspaceStatus.QUOTA_EXCEEDED
            resolved_last_error = {
                "error_code": "sandbox_quota_exceeded",
                "hint": "Delete workspace files or raise the configured quota before continuing.",
            }
        elif status is SandboxWorkspaceStatus.QUOTA_EXCEEDED:
            status = SandboxWorkspaceStatus.READY
            if last_error is None:
                resolved_last_error = None
        refreshed = replace(
            workspace,
            status=status,
            directory_summary=directory_summary,
            volume_digest=str(directory_summary.get("volume_digest") or ""),
            quota_summary=quota_summary,
            last_command_summary=last_command_summary
            if last_command_summary is not None
            else workspace.last_command_summary,
            last_error=resolved_last_error,
            last_attached_at=utc_now_iso(),
        )
        self.repositories.sandbox_workspaces.save(refreshed)

    def _quota_summary(
        self,
        workspace: SandboxWorkspaceRecord,
        directory_summary: dict[str, Any],
    ) -> dict[str, Any]:
        configured_limit = (workspace.quota_summary or {}).get("limit_bytes")
        try:
            limit_bytes = int(configured_limit)
        except (TypeError, ValueError):
            limit_bytes = DEFAULT_SANDBOX_QUOTA_BYTES
        if limit_bytes <= 0:
            limit_bytes = DEFAULT_SANDBOX_QUOTA_BYTES
        used_bytes = int(directory_summary.get("total_bytes") or 0)
        return {
            "limit_bytes": limit_bytes,
            "used_bytes": used_bytes,
            "exceeded": used_bytes > limit_bytes,
        }

    def _assert_prospective_quota(
        self,
        workspace: SandboxWorkspaceRecord,
        *,
        old_size: int,
        new_size: int,
    ) -> None:
        directory_summary = summarize_workspace_directory(
            self._workspace_path(workspace.sandbox_workspace_id)
        )
        quota_summary = self._quota_summary(workspace, directory_summary)
        prospective_bytes = int(quota_summary["used_bytes"]) - old_size + new_size
        if prospective_bytes > int(quota_summary["limit_bytes"]):
            self._refresh_workspace_summary(workspace)
            raise SandboxRuntimeError(
                "sandbox_quota_exceeded",
                "sandbox file mutation would exceed the workspace disk quota",
                hint="Delete workspace files or request a larger quota before retrying.",
                details={
                    "limit_bytes": quota_summary["limit_bytes"],
                    "used_bytes": quota_summary["used_bytes"],
                    "prospective_bytes": prospective_bytes,
                },
            )

    def _changed_files(self, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
        before_entries = {item["relative_path"]: item for item in before.get("entries", []) if isinstance(item, dict)}
        after_entries = {item["relative_path"]: item for item in after.get("entries", []) if isinstance(item, dict)}
        added = sorted(set(after_entries) - set(before_entries))[:100]
        removed = sorted(set(before_entries) - set(after_entries))[:100]
        modified = sorted(
            path
            for path in set(before_entries) & set(after_entries)
            if before_entries[path].get("content_digest") != after_entries[path].get("content_digest")
        )[:100]
        return {
            "added": added,
            "modified": modified,
            "removed": removed,
            "truncated": any(len(values) >= 100 for values in (added, modified, removed)),
        }

    def _workspace_file_snapshot(self, sandbox_workspace_id: str) -> dict[str, Any]:
        workspace_path = self._workspace_path(sandbox_workspace_id)
        entries: list[dict[str, Any]] = []
        for root_name in ("src", "work", "output", "logs"):
            root = workspace_path / root_name
            if not root.exists():
                continue
            for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(workspace_path).as_posix()):
                if path.is_dir():
                    continue
                relative_path = path.relative_to(workspace_path).as_posix()
                if path.is_symlink():
                    entries.append({"relative_path": relative_path, "content_digest": "sha256:symlink"})
                else:
                    entries.append({"relative_path": relative_path, "content_digest": _file_digest(path).content_digest})
        return {"entries": entries}


def _tool_error(invocation: ToolInvocation, exc: SandboxRuntimeError) -> ToolResult:
    safe_details = sanitize_public_diagnostic_payload(exc.details)
    payload = {
        "error_code": exc.error_code,
        **(dict(safe_details) if isinstance(safe_details, dict) else {}),
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=exc.error_code,
        summary=sanitize_public_diagnostic_text(str(exc)),
        error_code=exc.error_code,
        hint=None
        if exc.hint is None
        else sanitize_public_diagnostic_text(exc.hint),
        details=payload,
    )


def register_sandbox_runtime_tools(
    registry: ToolRegistry,
    *,
    agent_id: str | None = None,
    adapter_executor: SandboxAdapterExecutor | None = None,
    hpc_fetch_executor: SandboxHpcFetchExecutor | None = None,
    repository_scope_factory: Callable[[], Any] | None = None,
) -> None:
    def _service(context: SessionRuntimeContext) -> SandboxRuntimeService:
        return SandboxRuntimeService(
            context.repositories,
            workspace_root=context.sandbox_workspace_root,
            artifact_blob_root=context.artifact_blob_root,
            adapter_executor=adapter_executor,
            hpc_fetch_executor=hpc_fetch_executor,
            repository_scope_factory=repository_scope_factory,
        )

    def _workspace_id(context: SessionRuntimeContext, invocation: ToolInvocation) -> str:
        raw = invocation.arguments.get("sandbox_workspace_id")
        workspace, error_code, hint = SandboxWorkspaceService(
            context.repositories,
            workspace_root=context.sandbox_workspace_root,
        ).status_for_agent(
            session_id=context.snapshot.session.session_id,
            agent_id=agent_id or "",
            sandbox_workspace_id=None if raw in {None, ""} else str(raw),
            focus_task_id=context.restore_focus.task_id,
            focus_lane_id=context.restore_focus.lane_id,
        )
        if workspace is None:
            raise SandboxRuntimeError(error_code or "sandbox_workspace_not_found", hint or "sandbox workspace is unavailable")
        return workspace.sandbox_workspace_id

    def list_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).list_files(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=_workspace_id(context, invocation),
                path=str(invocation.arguments.get("path") or "/workspace"),
                recursive=bool(invocation.arguments.get("recursive") or False),
            )
        except SandboxRuntimeError as exc:
            return _tool_error(invocation, exc)
        return _tool_success(invocation, result, status="sandbox_files_listed")

    def read_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).read_file(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=_workspace_id(context, invocation),
                path=str(invocation.arguments["path"]),
                offset=int(invocation.arguments.get("offset") or 0),
                limit=int(invocation.arguments.get("limit") or READ_DEFAULT_LIMIT),
            )
        except SandboxRuntimeError as exc:
            return _tool_error(invocation, exc)
        return _tool_success(invocation, result, status="sandbox_file_read")

    def write_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).write_file(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=_workspace_id(context, invocation),
                actor_ref=agent_id or "agent:unknown",
                path=str(invocation.arguments["path"]),
                content=str(invocation.arguments.get("content") or ""),
                create_dirs=bool(invocation.arguments.get("create_dirs") or False),
                expected_digest=None
                if invocation.arguments.get("expected_digest") in {None, ""}
                else str(invocation.arguments.get("expected_digest")),
                task_id=context.restore_focus.task_id,
                lane_id=context.restore_focus.lane_id,
            )
        except SandboxRuntimeError as exc:
            return _tool_error(invocation, exc)
        return _tool_success(invocation, result, status="sandbox_file_written")

    def patch_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).patch_file(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=_workspace_id(context, invocation),
                actor_ref=agent_id or "agent:unknown",
                path=str(invocation.arguments["path"]),
                base_digest=str(invocation.arguments["base_digest"]),
                patch=str(invocation.arguments["patch"]),
                task_id=context.restore_focus.task_id,
                lane_id=context.restore_focus.lane_id,
            )
        except SandboxRuntimeError as exc:
            return _tool_error(invocation, exc)
        return _tool_success(invocation, result, status="sandbox_file_patched")

    def delete_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).delete_file(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=_workspace_id(context, invocation),
                actor_ref=agent_id or "agent:unknown",
                path=str(invocation.arguments["path"]),
                expected_digest=None
                if invocation.arguments.get("expected_digest") in {None, ""}
                else str(invocation.arguments.get("expected_digest")),
                task_id=context.restore_focus.task_id,
                lane_id=context.restore_focus.lane_id,
            )
        except SandboxRuntimeError as exc:
            return _tool_error(invocation, exc)
        return _tool_success(invocation, result, status="sandbox_file_deleted")

    def exec_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        try:
            result = _service(context).exec_command(
                session_id=context.snapshot.session.session_id,
                sandbox_workspace_id=_workspace_id(context, invocation),
                agent_id=agent_id or "agent:unknown",
                argv=list(invocation.arguments["argv"]),
                cwd=str(invocation.arguments.get("cwd") or "/workspace"),
                timeout_seconds=int(invocation.arguments.get("timeout_seconds") or EXEC_DEFAULT_TIMEOUT_SECONDS),
                env=dict(invocation.arguments.get("env") or {}),
                task_id=context.restore_focus.task_id,
                lane_id=context.restore_focus.lane_id,
            ).to_dict()
        except SandboxRuntimeError as exc:
            return _tool_error(invocation, exc)
        return _tool_success(invocation, result, status=str(result.get("status") or "sandbox_exec_finished"))

    registry.register("sandbox.file.list", list_handler)
    registry.register("sandbox.file.read", read_handler)
    registry.register("sandbox.file.write", write_handler)
    registry.register("sandbox.file.patch", patch_handler)
    registry.register("sandbox.file.delete", delete_handler)
    registry.register("sandbox.exec", exec_handler)


def _tool_success(invocation: ToolInvocation, payload: dict[str, Any], *, status: str) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=status,
        summary=status,
        details=payload,
    )


__all__ = [
    "EXEC_POLICY_VERSION",
    "SandboxRuntimeError",
    "SandboxRuntimeService",
    "register_sandbox_runtime_tools",
]
