from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import os
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

from .artifact_boundary import ArtifactBoundaryError
from .artifact_boundary import ArtifactBoundaryService
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .sandbox_workspace import SANDBOX_PROTOCOL_VERSION
from .sandbox_workspace import SANDBOX_WORKSPACE_MANIFEST_VERSION
from .sandbox_workspace import SandboxWorkspaceService
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
EXEC_MAX_TIMEOUT_SECONDS = 900
EXEC_POLICY_VERSION = "s09.exec_policy.v1"
S10_SUPERVISED_RPC_SCHEMA = "s10.supervised_rpc.v1"
S12_ADAPTER_ENVELOPE_SCHEMA = "s12.adapter_envelope.v1"
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
S12_ROUTE_POLICIES: dict[str, dict[str, Any]] = {
    "bio.ncbi_fetch_proteins.provider:v1": {
        "sdk_module": "bio",
        "function_name": "ncbi_fetch_proteins",
        "selected_backend": "provider_http",
        "backend_category": "provider_http",
        "route_reason": "static_policy:v1",
        "resource_class": "network_io",
        "runtime_packaging_id": "provider_http:v1",
        "provider_config_digest": "provider_config:ncbi:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#provider-evidence-ncbi",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#provider-evidence-ncbi",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio.uniprot_fetch.provider:v1": {
        "sdk_module": "bio",
        "function_name": "uniprot_fetch",
        "selected_backend": "provider_http",
        "backend_category": "provider_http",
        "route_reason": "static_policy:v1",
        "resource_class": "network_io",
        "runtime_packaging_id": "provider_http:v1",
        "provider_config_digest": "provider_config:uniprot:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#provider-evidence-uniprot",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#provider-evidence-uniprot",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio.hmmer_search.provider:v1": {
        "sdk_module": "bio",
        "function_name": "hmmer_search",
        "selected_backend": "provider_http",
        "backend_category": "provider_http",
        "route_reason": "static_policy:v1",
        "resource_class": "network_io",
        "runtime_packaging_id": "provider_http:v1",
        "provider_config_digest": "provider_config:ebi_hmmer:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#provider-evidence-ebi-hmmer-rest",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#provider-evidence-ebi-hmmer-rest",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio_tools.cdhit.hpc:v1": {
        "sdk_module": "bio_tools",
        "function_name": "cdhit",
        "selected_backend": "hpc",
        "backend_category": "hpc_runner",
        "route_reason": "static_policy:v1",
        "resource_class": "hpc_batch_small",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "cdhit_4.8.1.hpc_apptainer_sif:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#hpc-evidence",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#parameter-inventory-cd-hit",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio_tools.mafft.hpc:v1": {
        "sdk_module": "bio_tools",
        "function_name": "mafft",
        "selected_backend": "hpc",
        "backend_category": "hpc_runner",
        "route_reason": "static_policy:v1",
        "resource_class": "hpc_batch_small",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#hpc-evidence",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#parameter-inventory-mafft",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio_tools.hmmbuild.hpc:v1": {
        "sdk_module": "bio_tools",
        "function_name": "hmmbuild",
        "selected_backend": "hpc",
        "backend_category": "hpc_runner",
        "route_reason": "static_policy:v1",
        "resource_class": "hpc_batch_small",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#hpc-evidence",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#parameter-inventory-hmmer-cli",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio_tools.hmmalign.hpc:v1": {
        "sdk_module": "bio_tools",
        "function_name": "hmmalign",
        "selected_backend": "hpc",
        "backend_category": "hpc_runner",
        "route_reason": "static_policy:v1",
        "resource_class": "hpc_batch_small",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#hpc-evidence",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#parameter-inventory-hmmer-cli",
        "approval_requirement": {"required": True},
        "status": "ok",
    },
    "bio_tools.hmmer_search_cli.disabled:v1": {
        "sdk_module": "bio_tools",
        "function_name": "hmmer_search_cli",
        "selected_backend": "disabled",
        "backend_category": "unsupported",
        "route_reason": "unsupported_in_s14",
        "resource_class": "unsupported",
        "runtime_packaging_id": "disabled",
        "toolchain_id": "disabled",
        "evidence_ref": "docs/v3/sessions/14-real-bio-tools-local-hpc-backends.md#declared-outputs--validators",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#parameter-inventory-hmmer-cli",
        "approval_requirement": {"required": False},
        "status": "disabled",
        "error_code": "unsupported_in_s14",
    },
    "test.fixture_adapter:v1": {
        "sdk_module": "bio_tools",
        "function_name": "mafft",
        "selected_backend": "fixture",
        "backend_category": "host_local_tool",
        "route_reason": "unit_fixture_forbidden",
        "resource_class": "fixture",
        "runtime_packaging_id": "fixture",
        "toolchain_id": "fixture",
        "evidence_ref": "fixture",
        "parameter_inventory_ref": "fixture",
        "approval_requirement": {"required": False},
        "status": "ok",
    },
    "test.prerequisite_missing:v1": {
        "sdk_module": "bio_tools",
        "function_name": "mafft",
        "selected_backend": "hpc",
        "backend_category": "hpc_runner",
        "route_reason": "static_policy:v1",
        "resource_class": "hpc_batch_small",
        "runtime_packaging_id": "hpc_apptainer_sif.aox_hmm_2026_05_30",
        "toolchain_id": "mafft_7.525.hpc_apptainer_sif:v1",
        "evidence_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#hpc-evidence",
        "parameter_inventory_ref": "docs/v3/sessions/06-adapter-foundation-evidence.md#parameter-inventory-mafft",
        "approval_requirement": {"required": True},
        "status": "prerequisite_missing",
        "error_code": "operation_prerequisite_missing",
    },
}


class SandboxRuntimeError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        hint: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        super().__init__(message)
        self.error_code = error_code
        self.hint = hint
        self.details = {} if details is None else dict(details)


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


def _structured_adapter_message(value: Any, *, default_code: str) -> dict[str, Any] | None:
    if value is None or value == "":
        return None
    if isinstance(value, dict):
        message = dict(_scrub_private_adapter_payload(value))
        code = str(
            message.get("code")
            or message.get("error_code")
            or message.get("warning_code")
            or default_code
        )
        summary = str(message.get("summary") or message.get("message") or code)
        return {
            "code": code,
            "stage": str(message.get("stage") or "adapter_result"),
            "retryable": bool(message.get("retryable", False)),
            "summary": summary,
            "details_ref": message.get("details_ref"),
            "safe_diagnostics": message.get("safe_diagnostics"),
        }
    return {
        "code": default_code,
        "stage": "adapter_result",
        "retryable": False,
        "summary": str(value),
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
    return encoded[:limit].decode("utf-8", errors="replace"), True, len(encoded), digest


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
    _thread: threading.Thread | None = None
    _stop: threading.Event = field(default_factory=threading.Event)

    def start(self) -> None:
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._serve, daemon=True)
        self._thread.start()
        for _ in range(100):
            if self.socket_path.exists():
                return
            time.sleep(0.01)
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
            os.chmod(self.socket_path, 0o600)
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
            if method == "s09.transport_smoke":
                return self._handle_transport_smoke(request, params)
            if method == "s10.controlled_operation":
                return self._handle_controlled_operation(request, params)
            raise SandboxRuntimeError("sandbox_transport_method_forbidden", "control socket only supports supervised sandbox calls")
        except Exception as exc:
            return {
                "jsonrpc": "2.0",
                "id": request.get("id"),
                "error": {
                    "message": str(exc),
                    "type": exc.__class__.__name__,
                    "error_code": getattr(exc, "error_code", None),
                    "hint": getattr(exc, "hint", None),
                    "details": getattr(exc, "details", None),
                },
            }

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
        if reusable is not None:
            operation = self._create_operation(
                envelope,
                operation_digest=operation_digest,
                status=ControlledOperationStatus.COMPLETED,
                approval_id=reusable.approval_id,
                approval_state=ApprovalRequestStatus.APPROVED.value,
                result_summary=dict(envelope.get("result_summary") or {"status": "completed"}),
            )
            return {"jsonrpc": "2.0", "id": request.get("id"), "result": self._operation_response(operation)}

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
        result_summary = dict(envelope.get("result_summary") or {"status": "completed"})
        completed = replace(
            operation,
            status=ControlledOperationStatus.COMPLETED,
            result_summary=result_summary,
            error_code=None,
            error_summary=None,
            updated_at=utc_now_iso(),
        )
        if completed.adapter_envelope_schema_version == S12_ADAPTER_ENVELOPE_SCHEMA:
            completed = replace(
                completed,
                adapter_result_envelope=self._adapter_result_envelope(completed, envelope),
            )
        operation = completed
        self.repositories.controlled_operations.save(operation)
        self.repositories.continuation_states.complete(claimed.continuation_id)
        return {"jsonrpc": "2.0", "id": request.get("id"), "result": self._operation_response(operation)}

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
        input_artifact_ids = params.get("input_artifact_ids") or []
        input_artifact_digests = params.get("input_artifact_digests") or []
        stage_refs = params.get("stage_refs") or []
        if not isinstance(input_artifact_ids, list) or not isinstance(input_artifact_digests, list):
            raise SandboxRuntimeError("invalid_tool_arguments", "input artifact fields must be lists")
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
        adapter_result = params.get("adapter_result") or {}
        if not isinstance(adapter_result, dict):
            raise SandboxRuntimeError("invalid_tool_arguments", "adapter_result must be an object")
        result_summary = params.get("result_summary") or adapter_result.get("bounded_summary") or {"status": "completed"}
        if not isinstance(result_summary, dict):
            raise SandboxRuntimeError("invalid_tool_arguments", "result_summary must be an object")
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
            "input_artifact_ids": sorted(str(item) for item in input_artifact_ids),
            "input_artifact_digests": sorted(str(item) for item in input_artifact_digests),
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
            "result_summary": result_summary,
            "adapter_result": adapter_result,
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
        adapter_result = dict(_scrub_private_adapter_payload(envelope.get("adapter_result") or {}))
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
        return {
            "adapter_envelope_schema_version": operation.adapter_envelope_schema_version,
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "sandbox_run_id": operation.sandbox_run_id,
            "status": adapter_result.get("status") or operation.status.value,
            "backend_run_id": adapter_result.get("backend_run_id"),
            "provider_request_id": adapter_result.get("provider_request_id"),
            "fetch_refs": list(adapter_result.get("fetch_refs") or []),
            "registered_artifact_ids": list(adapter_result.get("registered_artifact_ids") or []),
            "output_artifact_ids": list(adapter_result.get("output_artifact_ids") or []),
            "validation_results": adapter_result.get("validation_results") or {},
            "bounded_summary": adapter_result.get("bounded_summary") or operation.result_summary or {},
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

    def _resume_or_return(self, operation: ControlledOperation, envelope: dict[str, Any]) -> dict[str, Any]:
        if operation.status is ControlledOperationStatus.COMPLETED:
            return self._operation_response(operation)
        continuation = self.repositories.continuation_states.get_by_operation_id(operation.operation_id)
        if continuation is None:
            raise SandboxRuntimeError(
                "operation_recovery_failed",
                "controlled operation is missing continuation state",
                details={"operation_id": operation.operation_id},
            )
        claimed = self._wait_for_approval_and_claim(continuation.continuation_id)
        result_summary = dict(envelope.get("result_summary") or {"status": "completed"})
        completed = replace(
            operation,
            status=ControlledOperationStatus.COMPLETED,
            approval_state=ApprovalRequestStatus.APPROVED.value,
            result_summary=result_summary,
            updated_at=utc_now_iso(),
        )
        if completed.adapter_envelope_schema_version == S12_ADAPTER_ENVELOPE_SCHEMA:
            completed = replace(
                completed,
                adapter_result_envelope=self._adapter_result_envelope(completed, envelope),
            )
        self.repositories.controlled_operations.save(completed)
        self.repositories.continuation_states.complete(claimed.continuation_id)
        return self._operation_response(completed)

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
        return response


@dataclass(slots=True)
class SandboxRuntimeService:
    repositories: Any
    workspace_root: Path | None = None
    log_root: Path | None = None
    execution_backend: str = "podman"
    podman_binary: str = "podman"

    def list_files(
        self,
        *,
        session_id: str,
        sandbox_workspace_id: str,
        path: str = "/workspace",
        recursive: bool = False,
    ) -> dict[str, Any]:
        workspace = self._require_workspace(session_id, sandbox_workspace_id)
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
        encoded = content.encode("utf-8")
        if len(encoded) > WRITE_MAX_BYTES:
            raise SandboxRuntimeError("sandbox_resource_exceeded", "sandbox.file.write content exceeds 256KiB")
        public_path, host_path = self._regular_file_target(workspace, path)
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
        public_path, host_path = self._regular_file_target(workspace, path)
        if not host_path.is_file():
            raise SandboxRuntimeError("sandbox_path_forbidden", "patch target must be an existing regular file")
        old_digest = _file_digest(host_path).content_digest
        if base_digest != old_digest:
            raise SandboxRuntimeError("sandbox_digest_conflict", "base_digest does not match current file digest")
        original = host_path.read_text(encoding="utf-8")
        patched = _apply_unified_diff(original, patch, public_path=public_path)
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
        cwd_host = _resolve_host_path(workspace_path, cwd_public, allow_workspace_root=True)
        if not cwd_host.is_dir():
            raise SandboxRuntimeError("sandbox_path_forbidden", "cwd must be a directory under /workspace")
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
            compatibility={
                "image_digest": workspace.image_digest,
                "sandbox_protocol_version": workspace.sandbox_protocol_version,
                "workspace_manifest_version": workspace.manifest_version,
                "exec_policy_version": EXEC_POLICY_VERSION,
            },
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
        )
        completed: subprocess.CompletedProcess[str] | None = None
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
                stdout=(exc.stdout or "") if isinstance(exc.stdout, str) else "",
                stderr=(exc.stderr or "") if isinstance(exc.stderr, str) else "",
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
        failed = replace(
            active,
            status=SandboxRunStatus.FAILED,
            error_code="sandbox_run_recovery_failed",
            stderr_summary=reason,
            ended_at=now,
            updated_at=now,
        )
        self.repositories.sandbox_runs.save(failed)
        return [failed]

    def _finish_run(
        self,
        run: SandboxRunRecord,
        *,
        stdout: str,
        stderr: str,
        exit_code: int | None,
        duration_ms: int,
        pre_summary: dict[str, Any],
        forced_status: SandboxRunStatus | None = None,
        error_code: str | None = None,
    ) -> SandboxRunRecord:
        stdout_summary, stdout_truncated, stdout_size, stdout_digest = _bounded_text(stdout)
        stderr_summary, stderr_truncated, stderr_size, stderr_digest = _bounded_text(stderr)
        log_refs = []
        if stdout_truncated or stderr_truncated:
            log_refs.extend(
                self._write_logs(
                    run,
                    stdout=stdout,
                    stderr=stderr,
                    stdout_digest=stdout_digest,
                    stdout_size=stdout_size,
                    stdout_truncated=stdout_truncated,
                    stderr_digest=stderr_digest,
                    stderr_size=stderr_size,
                    stderr_truncated=stderr_truncated,
                )
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
        ended_at = utc_now_iso()
        finished = replace(
            run,
            status=status,
            stdout_summary=stdout_summary,
            stderr_summary=stderr_summary,
            exit_code=exit_code,
            duration_ms=duration_ms,
            changed_files_summary=changed,
            log_artifact_ref=log_refs[0] if log_refs else None,
            error_code=error_code,
            ended_at=ended_at,
            updated_at=ended_at,
        )
        self.repositories.sandbox_runs.save(finished)
        workspace = self.repositories.sandbox_workspaces.get(run.sandbox_workspace_id)
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
        stdout: str,
        stderr: str,
        stdout_digest: str,
        stdout_size: int,
        stdout_truncated: bool,
        stderr_digest: str,
        stderr_size: int,
        stderr_truncated: bool,
    ) -> list[str]:
        root = self._log_root() / run.sandbox_run_id
        root.mkdir(parents=True, exist_ok=True)
        refs: list[str] = []
        for stream, text, digest, size, truncated in (
            ("stdout", stdout, stdout_digest, stdout_size, stdout_truncated),
            ("stderr", stderr, stderr_digest, stderr_size, stderr_truncated),
        ):
            if not truncated:
                continue
            path = root / f"{stream}.log"
            path.write_text(text, encoding="utf-8")
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
            refs.append(ref)
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

    def _subprocess_env(self, user_env: dict[str, str], socket_path: Path) -> dict[str, str]:
        env = {
            "PATH": os.environ.get("PATH", ""),
            "PYTHONPATH": os.environ.get("PYTHONPATH", ""),
            "OPENZYME_CONTROL_SOCKET": str(socket_path),
            "OPENZYME_SANDBOX_MODE": "s10",
        }
        env.update(user_env)
        return env

    def _container_env(self, user_env: dict[str, str]) -> dict[str, str]:
        env = {
            "OPENZYME_CONTROL_SOCKET": "/openzyme/control.sock",
            "OPENZYME_SANDBOX_MODE": "s10",
        }
        env.update(user_env)
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
    ) -> subprocess.CompletedProcess[str]:
        if self.execution_backend == "local":
            return subprocess.run(
                list(argv),
                cwd=str(cwd_host),
                env=self._subprocess_env(user_env, socket_path),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        if self.execution_backend == "podman":
            if shutil.which(self.podman_binary) is None:
                raise SandboxRuntimeError("sandbox_image_missing", "podman binary is not available for sandbox.exec")
            return subprocess.run(
                self._podman_command(
                    workspace=workspace,
                    workspace_path=workspace_path,
                    argv=argv,
                    cwd_public=cwd_public,
                    user_env=user_env,
                    socket_path=socket_path,
                ),
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
                check=False,
            )
        raise SandboxRuntimeError("invalid_tool_arguments", f"unknown sandbox execution backend {self.execution_backend!r}")

    def _podman_command(
        self,
        *,
        workspace: SandboxWorkspaceRecord,
        workspace_path: Path,
        argv: tuple[str, ...],
        cwd_public: PurePosixPath,
        user_env: dict[str, str],
        socket_path: Path,
    ) -> list[str]:
        env_args = [
            item
            for key, value in sorted(self._container_env(user_env).items())
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
            f"{socket_path}:/openzyme/control.sock:Z",
        ]
        mount_args = [item for mount in mounts for item in ("-v", mount)]
        return [
            self.podman_binary,
            "run",
            "--rm",
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
            workspace.image_ref,
            *argv,
        ]

    def _bounded_timeout(self, timeout_seconds: int) -> int:
        value = int(timeout_seconds)
        if value <= 0 or value > EXEC_MAX_TIMEOUT_SECONDS:
            raise SandboxRuntimeError("sandbox_resource_exceeded", "timeout_seconds must be between 1 and 900")
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
            ).snapshot_code(
                session_id=session_id,
                sandbox_workspace_id=sandbox_workspace_id,
                paths=None,
                entrypoint=entrypoint,
                metadata={"producer": "sandbox.exec"},
            )
            return result.to_payload()
        except ArtifactBoundaryError as exc:
            raise SandboxRuntimeError(exc.error_code, str(exc), hint=exc.hint, details=exc.details) from exc

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
        root = self.log_root or Path(tempfile.gettempdir()) / "openzyme-sandbox-command-logs"
        root.mkdir(parents=True, exist_ok=True)
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
        refreshed = replace(
            workspace,
            directory_summary=directory_summary,
            volume_digest=str(directory_summary.get("volume_digest") or ""),
            last_command_summary=last_command_summary
            if last_command_summary is not None
            else workspace.last_command_summary,
            last_error=last_error,
            last_attached_at=utc_now_iso(),
        )
        self.repositories.sandbox_workspaces.save(refreshed)

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
    payload = {"error_code": exc.error_code, **exc.details}
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=exc.error_code,
        summary=str(exc),
        error_code=exc.error_code,
        hint=exc.hint,
        details=payload,
    )


def register_sandbox_runtime_tools(registry: ToolRegistry, *, agent_id: str | None = None) -> None:
    def _service(context: SessionRuntimeContext) -> SandboxRuntimeService:
        return SandboxRuntimeService(context.repositories)

    def _workspace_id(context: SessionRuntimeContext, invocation: ToolInvocation) -> str:
        raw = invocation.arguments.get("sandbox_workspace_id")
        if raw not in {None, ""}:
            return str(raw)
        workspace, error_code, hint = SandboxWorkspaceService(context.repositories).status_for_agent(
            session_id=context.snapshot.session.session_id,
            agent_id=agent_id or "",
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
