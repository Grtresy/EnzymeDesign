from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import hashlib
import json
import re
import tempfile
import threading
from typing import Any
from weakref import WeakValueDictionary

from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxImageRecord
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import CoreRepositories

DEFAULT_SANDBOX_IMAGE_REF = "localhost/openzyme-pipeline-sandbox:dev"
DEFAULT_SANDBOX_IMAGE_FAMILY = "openzyme-pipeline-sandbox"
DEFAULT_SANDBOX_IMAGE_VERSION = "dev"
SANDBOX_PROTOCOL_VERSION = "s07"
SANDBOX_MANIFEST_SCHEMA_VERSION = "s07.workspace_manifest.v1"
SANDBOX_WORKSPACE_MANIFEST_VERSION = "s07.workspace_manifest.v1"
DEFAULT_SANDBOX_QUOTA_BYTES = 2 * 1024 * 1024 * 1024
WORKSPACE_DIRECTORIES = ("src", "input", "work", "output", "logs", "manifest")
_WORKSPACE_CREATION_LOCKS_GUARD = threading.Lock()
_WORKSPACE_CREATION_LOCKS: WeakValueDictionary[str, threading.RLock] = (
    WeakValueDictionary()
)
REQUIRED_IMAGE_CAPABILITIES = (
    "rootless_podman",
    "non_root_user",
    "no_network_default",
    "workspace_mount",
    "control_socket_mount",
    "bash",
    "python",
    "openzyme_pipeline",
)


def normalize_immutable_image_id(value: str) -> str:
    """Normalize a Podman image ID without accepting tags or short digests."""

    image_id = value.strip()
    if re.fullmatch(r"[0-9a-f]{64}", image_id):
        return f"sha256:{image_id}"
    if re.fullmatch(r"sha256:[0-9a-f]{64}", image_id):
        return image_id
    raise ValueError("image ID must be a full sha256 digest")


def derive_sandbox_workspace_id(session_id: str, agent_member_id: str) -> str:
    digest = hashlib.sha256(f"{session_id}:{agent_member_id}".encode("utf-8")).hexdigest()
    return f"sw_{digest[:24]}"


def _workspace_creation_lock(workspace_path: Path) -> threading.RLock:
    key = str(workspace_path)
    with _WORKSPACE_CREATION_LOCKS_GUARD:
        lock = _WORKSPACE_CREATION_LOCKS.get(key)
        if lock is None:
            lock = threading.RLock()
            _WORKSPACE_CREATION_LOCKS[key] = lock
        return lock


def default_missing_image_record(*, now: str | None = None) -> SandboxImageRecord:
    timestamp = now or utc_now_iso()
    return SandboxImageRecord(
        image_ref=DEFAULT_SANDBOX_IMAGE_REF,
        image_digest=None,
        image_family=DEFAULT_SANDBOX_IMAGE_FAMILY,
        image_version=DEFAULT_SANDBOX_IMAGE_VERSION,
        sandbox_protocol_version=SANDBOX_PROTOCOL_VERSION,
        manifest_schema_version=SANDBOX_MANIFEST_SCHEMA_VERSION,
        capabilities_declared=(),
        compatibility=SandboxImageCompatibility.MISSING,
        compatibility_error="sandbox image digest is not registered",
        is_default=True,
        created_at=timestamp,
        updated_at=timestamp,
    )


def sandbox_image_record(
    *,
    image_ref: str = DEFAULT_SANDBOX_IMAGE_REF,
    image_digest: str,
    image_version: str = DEFAULT_SANDBOX_IMAGE_VERSION,
    sandbox_protocol_version: str = SANDBOX_PROTOCOL_VERSION,
    manifest_schema_version: str = SANDBOX_MANIFEST_SCHEMA_VERSION,
    capabilities_declared: tuple[str, ...] = REQUIRED_IMAGE_CAPABILITIES,
    is_default: bool = True,
    now: str | None = None,
) -> SandboxImageRecord:
    timestamp = now or utc_now_iso()
    compatibility, error = evaluate_image_compatibility(
        image_digest=image_digest,
        sandbox_protocol_version=sandbox_protocol_version,
        manifest_schema_version=manifest_schema_version,
        capabilities_declared=capabilities_declared,
        image_ref=image_ref,
    )
    return SandboxImageRecord(
        image_ref=image_ref,
        image_digest=image_digest,
        image_family=DEFAULT_SANDBOX_IMAGE_FAMILY,
        image_version=image_version,
        sandbox_protocol_version=sandbox_protocol_version,
        manifest_schema_version=manifest_schema_version,
        capabilities_declared=capabilities_declared,
        compatibility=compatibility,
        compatibility_error=error,
        is_default=is_default,
        created_at=timestamp,
        updated_at=timestamp,
    )


def evaluate_image_compatibility(
    *,
    image_digest: str | None,
    sandbox_protocol_version: str,
    manifest_schema_version: str,
    capabilities_declared: tuple[str, ...],
    image_ref: str,
) -> tuple[SandboxImageCompatibility, str | None]:
    if not image_digest:
        return SandboxImageCompatibility.MISSING, "sandbox image digest is not registered"
    if sandbox_protocol_version != SANDBOX_PROTOCOL_VERSION:
        return (
            SandboxImageCompatibility.INCOMPATIBLE,
            f"sandbox_protocol_version {sandbox_protocol_version!r} is not supported",
        )
    if manifest_schema_version != SANDBOX_MANIFEST_SCHEMA_VERSION:
        return (
            SandboxImageCompatibility.INCOMPATIBLE,
            f"manifest_schema_version {manifest_schema_version!r} is not supported",
        )
    missing_capabilities = sorted(set(REQUIRED_IMAGE_CAPABILITIES) - set(capabilities_declared))
    if missing_capabilities:
        return (
            SandboxImageCompatibility.INCOMPATIBLE,
            "missing declared capabilities: " + ", ".join(missing_capabilities),
        )
    if ":" in image_ref and "@" not in image_ref:
        return SandboxImageCompatibility.COMPATIBLE_NON_CUTOVER_GRADE, None
    return SandboxImageCompatibility.COMPATIBLE, None


@dataclass(slots=True)
class SandboxWorkspaceService:
    repositories: CoreRepositories
    workspace_root: Path | None = None
    default_image_ref: str = DEFAULT_SANDBOX_IMAGE_REF
    quota_bytes: int = DEFAULT_SANDBOX_QUOTA_BYTES

    def create_or_get(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        focus_task_id: str | None = None,
        focus_lane_id: str | None = None,
    ) -> SandboxWorkspaceRecord:
        agent = self.repositories.agents.get_by_member_id(agent_member_id)
        if agent is None or agent.session_id != session_id:
            raise ValueError(f"agent_member_id {agent_member_id!r} does not belong to session {session_id!r}")
        workspace_id = derive_sandbox_workspace_id(session_id, agent_member_id)
        workspace_path = self._workspace_path(workspace_id)
        with _workspace_creation_lock(workspace_path):
            existing = self.repositories.sandbox_workspaces.get_by_session_member(
                session_id, agent_member_id
            )
            if existing is not None and existing.sandbox_workspace_id != workspace_id:
                raise ValueError(
                    "sandbox workspace identity does not match session/member derivation"
                )
            image = self._default_image_record()
            try:
                directory_summary = (
                    self._ensure_and_summarize_directory(workspace_path)
                    if existing is None
                    else self._summarize_existing_directory(workspace_path)
                )
                quota_summary = self._quota_summary(directory_summary)
                status, last_error = self._status_for(image, quota_summary)
            except OSError:
                directory_summary = {
                    "summary_unavailable": True,
                    "error_code": "sandbox_volume_corrupt",
                }
                quota_summary = {
                    "limit_bytes": self.quota_bytes,
                    "used_bytes": None,
                    "exceeded": None,
                    "summary_unavailable": True,
                }
                status = SandboxWorkspaceStatus.CORRUPT
                last_error = {
                    "error_code": "sandbox_volume_corrupt",
                    "hint": "Inspect or repair the sandbox workspace volume before continuing.",
                }
            now = utc_now_iso()
            record = SandboxWorkspaceRecord(
                sandbox_workspace_id=workspace_id,
                session_id=session_id,
                agent_member_id=agent_member_id,
                agent_id=agent.agent_id,
                focus_task_id=focus_task_id
                if focus_task_id is not None
                else agent.task_id,
                focus_lane_id=focus_lane_id
                if focus_lane_id is not None
                else agent.lane_id,
                status=status,
                image_ref=image.image_ref,
                image_digest=image.image_digest,
                image_version=image.image_version,
                sandbox_protocol_version=image.sandbox_protocol_version,
                image_compatibility=image.compatibility,
                manifest_version=SANDBOX_WORKSPACE_MANIFEST_VERSION,
                volume_digest=str(directory_summary.get("volume_digest") or ""),
                quota_summary=quota_summary,
                directory_summary=directory_summary,
                materialized_input_artifact_ids=()
                if existing is None
                else existing.materialized_input_artifact_ids,
                registered_artifact_ids=()
                if existing is None
                else existing.registered_artifact_ids,
                source_code_artifact_ids=()
                if existing is None
                else existing.source_code_artifact_ids,
                last_command_summary=None
                if existing is None
                else existing.last_command_summary,
                last_error=last_error,
                created_at=now if existing is None else existing.created_at,
                last_attached_at=now,
            )
            self.repositories.sandbox_workspaces.save(record)
            return record

    def status_for_agent(
        self,
        *,
        session_id: str,
        agent_id: str,
        sandbox_workspace_id: str | None = None,
        focus_task_id: str | None = None,
        focus_lane_id: str | None = None,
    ) -> tuple[SandboxWorkspaceRecord | None, str | None, str | None]:
        agent = self.repositories.agents.get(session_id, agent_id)
        if agent is None or agent.member_id is None:
            return None, "sandbox_workspace_forbidden", "executor agent member is not registered"
        if agent.role != "executor":
            return None, "sandbox_workspace_forbidden", "sandbox workspace status is executor-facing"
        if sandbox_workspace_id is None:
            return (
                self.create_or_get(
                    session_id=session_id,
                    agent_member_id=agent.member_id,
                    focus_task_id=focus_task_id,
                    focus_lane_id=focus_lane_id,
                ),
                None,
                None,
            )
        record = self.repositories.sandbox_workspaces.get(sandbox_workspace_id)
        if record is None:
            return None, "sandbox_workspace_not_found", "sandbox workspace was not found"
        if record.session_id != session_id or record.agent_member_id != agent.member_id:
            return None, "sandbox_workspace_forbidden", "sandbox workspace belongs to another actor"
        return (
            self.create_or_get(
                session_id=session_id,
                agent_member_id=agent.member_id,
                focus_task_id=focus_task_id if focus_task_id is not None else record.focus_task_id,
                focus_lane_id=focus_lane_id if focus_lane_id is not None else record.focus_lane_id,
            ),
            None,
            None,
        )

    def _default_image_record(self) -> SandboxImageRecord:
        record = self.repositories.sandbox_images.get_default()
        if record is None:
            record = default_missing_image_record()
            self.repositories.sandbox_images.save(record)
        return record

    def _status_for(
        self, image: SandboxImageRecord, quota_summary: dict[str, Any]
    ) -> tuple[SandboxWorkspaceStatus, dict[str, Any] | None]:
        if image.compatibility is SandboxImageCompatibility.MISSING:
            return (
                SandboxWorkspaceStatus.MISSING_IMAGE,
                {
                    "error_code": "sandbox_image_missing",
                    "hint": "Install or register the configured sandbox image digest explicitly.",
                    "image_ref": image.image_ref,
                },
            )
        if image.compatibility is SandboxImageCompatibility.INCOMPATIBLE:
            return (
                SandboxWorkspaceStatus.IMAGE_INCOMPATIBLE,
                {
                    "error_code": "sandbox_image_incompatible",
                    "hint": "Register a sandbox image with the expected protocol, manifest schema, and capabilities.",
                    "image_ref": image.image_ref,
                    "details": image.compatibility_error,
                },
            )
        if quota_summary.get("exceeded"):
            return (
                SandboxWorkspaceStatus.QUOTA_EXCEEDED,
                {
                    "error_code": "sandbox_quota_exceeded",
                    "hint": "Run explicit cleanup or increase the sandbox quota before continuing.",
                },
            )
        return SandboxWorkspaceStatus.READY, None

    def _workspace_path(self, sandbox_workspace_id: str) -> Path:
        root = self.workspace_root or Path(tempfile.gettempdir()) / "openzyme-sandbox-workspaces"
        return root.resolve() / sandbox_workspace_id

    def _ensure_and_summarize_directory(self, workspace_path: Path) -> dict[str, Any]:
        if workspace_path.is_symlink() or workspace_path.exists():
            raise OSError("new sandbox workspace root already exists")
        workspace_path.mkdir(parents=True, exist_ok=False)
        if workspace_path.is_symlink() or not workspace_path.is_dir():
            raise OSError("sandbox workspace root is missing or invalid")
        for name in WORKSPACE_DIRECTORIES:
            directory = workspace_path / name
            if directory.is_symlink():
                raise OSError("sandbox workspace directory is a symlink")
            if directory.exists():
                if not directory.is_dir():
                    raise OSError("sandbox workspace entry is not a directory")
            else:
                directory.mkdir(exist_ok=False)
            if directory.is_symlink() or not directory.is_dir():
                raise OSError("sandbox workspace directory is missing or invalid")
        return summarize_workspace_directory(workspace_path)

    def _summarize_existing_directory(self, workspace_path: Path) -> dict[str, Any]:
        if workspace_path.is_symlink() or not workspace_path.is_dir():
            raise OSError("sandbox workspace root is missing or invalid")
        for name in WORKSPACE_DIRECTORIES:
            directory = workspace_path / name
            if directory.is_symlink() or not directory.is_dir():
                raise OSError("sandbox workspace layout is incomplete or invalid")
        return summarize_workspace_directory(workspace_path)

    def _quota_summary(self, directory_summary: dict[str, Any]) -> dict[str, Any]:
        total_bytes = int(directory_summary.get("total_bytes") or 0)
        return {
            "limit_bytes": self.quota_bytes,
            "used_bytes": total_bytes,
            "exceeded": total_bytes > self.quota_bytes,
        }


def summarize_workspace_directory(workspace_path: Path) -> dict[str, Any]:
    root = workspace_path.resolve()
    entries: list[dict[str, Any]] = []
    directory_summaries: dict[str, dict[str, Any]] = {}
    for directory_name in WORKSPACE_DIRECTORIES:
        directory = root / directory_name
        files = []
        total_bytes = 0
        latest_mtime = 0.0
        if directory.exists():
            for path in sorted(directory.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
                if path.is_dir():
                    continue
                relative_path = path.relative_to(root).as_posix()
                stat = path.lstat()
                latest_mtime = max(latest_mtime, stat.st_mtime)
                if path.is_symlink():
                    size = 0
                    content_digest = "sha256:symlink"
                    kind = "symlink"
                else:
                    content = path.read_bytes()
                    size = len(content)
                    content_digest = "sha256:" + hashlib.sha256(content).hexdigest()
                    kind = "file"
                total_bytes += size
                files.append(
                    {
                        "relative_path": relative_path,
                        "kind": kind,
                        "size": size,
                        "content_digest": content_digest,
                    }
                )
        directory_digest = _summary_digest(files)
        directory_summaries[directory_name] = {
            "file_count": len(files),
            "total_bytes": total_bytes,
            "latest_mtime": latest_mtime,
            "content_digest": directory_digest,
            "truncated": False,
        }
        entries.extend(files)
    return {
        "directories": directory_summaries,
        "file_count": sum(item["file_count"] for item in directory_summaries.values()),
        "total_bytes": sum(item["total_bytes"] for item in directory_summaries.values()),
        "volume_digest": _summary_digest(entries),
        "truncated": False,
    }


def _summary_digest(entries: list[dict[str, Any]]) -> str:
    normalized = [
        {
            "relative_path": item["relative_path"],
            "kind": item["kind"],
            "size": item["size"],
            "content_digest": item["content_digest"],
        }
        for item in sorted(entries, key=lambda value: value["relative_path"])
    ]
    payload = json.dumps(normalized, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def register_sandbox_workspace_tools(
    registry: ToolRegistry, *, agent_id: str | None = None
) -> None:
    def status_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        requested_workspace_id = invocation.arguments.get("sandbox_workspace_id")
        service = SandboxWorkspaceService(
            context.repositories,
            workspace_root=context.sandbox_workspace_root,
        )
        record, error_code, hint = service.status_for_agent(
            session_id=context.snapshot.session.session_id,
            agent_id=agent_id or "",
            sandbox_workspace_id=None
            if requested_workspace_id in {None, ""}
            else str(requested_workspace_id),
            focus_task_id=context.restore_focus.task_id,
            focus_lane_id=context.restore_focus.lane_id,
        )
        if record is None:
            payload = {
                "error_code": error_code,
                "sandbox_workspace_id": requested_workspace_id,
            }
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(payload, sort_keys=True),
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status=error_code or "sandbox_status_unavailable",
                summary=hint or "Sandbox workspace status is unavailable.",
                error_code=error_code or "sandbox_status_unavailable",
                hint=hint,
                details=payload,
            )
        payload = record.to_dict()
        ok = record.status is SandboxWorkspaceStatus.READY
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(payload, sort_keys=True),
            task_id=record.focus_task_id,
            lane_id=record.focus_lane_id,
            status=record.status.value,
            summary=f"Sandbox workspace {record.sandbox_workspace_id} is {record.status.value}.",
            error_code=None
            if ok
            else (record.last_error or {}).get("error_code", record.status.value),
            hint=None if ok else (record.last_error or {}).get("hint"),
            details=payload,
        )

    registry.register("sandbox.workspace.status", status_handler)


__all__ = [
    "DEFAULT_SANDBOX_IMAGE_REF",
    "DEFAULT_SANDBOX_QUOTA_BYTES",
    "REQUIRED_IMAGE_CAPABILITIES",
    "SANDBOX_MANIFEST_SCHEMA_VERSION",
    "SANDBOX_PROTOCOL_VERSION",
    "SANDBOX_WORKSPACE_MANIFEST_VERSION",
    "SandboxWorkspaceService",
    "default_missing_image_record",
    "derive_sandbox_workspace_id",
    "normalize_immutable_image_id",
    "register_sandbox_workspace_tools",
    "sandbox_image_record",
    "summarize_workspace_directory",
]
