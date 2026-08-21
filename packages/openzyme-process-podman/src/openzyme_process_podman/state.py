from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class SandboxWorkspaceStatus(StrEnum):
    READY = "ready"
    ATTACHED = "attached"
    DETACHED = "detached"
    CORRUPT = "corrupt"
    QUOTA_EXCEEDED = "quota_exceeded"
    MISSING_IMAGE = "missing_image"
    IMAGE_INCOMPATIBLE = "image_incompatible"
    FROZEN_LEGACY = "frozen_legacy"


class SandboxRunStatus(StrEnum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    RESOURCE_EXCEEDED = "resource_exceeded"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {
            self.COMPLETED,
            self.FAILED,
            self.TIMEOUT,
            self.RESOURCE_EXCEEDED,
            self.CANCELLED,
        }


class SandboxImageCompatibility(StrEnum):
    COMPATIBLE = "compatible"
    COMPATIBLE_NON_CUTOVER_GRADE = "compatible_non_cutover_grade"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"


@dataclass(frozen=True, slots=True)
class SandboxImageRecord:
    image_ref: str
    image_digest: str | None
    image_family: str
    image_version: str
    sandbox_protocol_version: str
    manifest_schema_version: str
    capabilities_declared: tuple[str, ...]
    compatibility: SandboxImageCompatibility
    is_default: bool
    created_at: str
    updated_at: str
    compatibility_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["capabilities_declared"] = list(self.capabilities_declared)
        data["compatibility"] = self.compatibility.value
        return data


@dataclass(frozen=True, slots=True)
class SandboxWorkspaceRecord:
    sandbox_workspace_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    status: SandboxWorkspaceStatus
    image_ref: str
    image_digest: str | None
    image_version: str | None
    sandbox_protocol_version: str | None
    image_compatibility: SandboxImageCompatibility
    manifest_version: str
    created_at: str
    last_attached_at: str
    focus_task_id: str | None = None
    focus_lane_id: str | None = None
    volume_digest: str | None = None
    quota_summary: dict[str, Any] | None = None
    directory_summary: dict[str, Any] | None = None
    last_command_summary: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["image_compatibility"] = self.image_compatibility.value
        return data


@dataclass(frozen=True, slots=True)
class SandboxRunRecord:
    sandbox_run_id: str
    session_id: str
    sandbox_workspace_id: str
    agent_id: str
    argv: tuple[str, ...]
    argv_digest: str
    cwd: str
    env_digest: str
    status: SandboxRunStatus
    created_at: str
    updated_at: str
    task_id: str | None = None
    lane_id: str | None = None
    resource_policy: dict[str, Any] | None = None
    source_tree_digest: str | None = None
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    stdout_metadata: dict[str, Any] | None = None
    stderr_metadata: dict[str, Any] | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    changed_files_summary: dict[str, Any] | None = None
    error_code: str | None = None
    compatibility: dict[str, Any] | None = None
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["argv"] = list(self.argv)
        data["status"] = self.status.value
        return data


__all__ = [
    "SandboxImageCompatibility",
    "SandboxImageRecord",
    "SandboxRunRecord",
    "SandboxRunStatus",
    "SandboxWorkspaceRecord",
    "SandboxWorkspaceStatus",
]
