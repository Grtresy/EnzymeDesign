from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from enum import StrEnum
from typing import Any

from .models import ArtifactKind
from .models import RunStatus
from .models import SourceRefKind


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


CONTROL_PLANE_ENTITY_NAMES = (
    "Session",
    "Task",
    "Lane",
    "ApprovalRequest",
    "InboxMessage",
    "MemoryEntry",
    "AgentMember",
    "AgentRuntimeSignal",
    "EngineInvocation",
    "RunRecord",
    "SessionArtifactRecord",
    "SessionReportDraftRecord",
    "SessionReportRecord",
    "ResearchSummary",
    "ResearchEvidence",
    "ResearchSourceRef",
    "ResearchGap",
    "SandboxImageRecord",
    "SandboxWorkspaceRecord",
    "SandboxRunRecord",
    "ControlledOperation",
    "ContinuationState",
    "FileAuditEntry",
    "CommandLogArtifactRecord",
)


class SessionStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    ARCHIVED = "archived"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.ARCHIVED}


class TaskStatus(StrEnum):
    TODO = "todo"
    IN_PROGRESS = "in_progress"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class TaskPriority(StrEnum):
    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    URGENT = "urgent"


class LaneStatus(StrEnum):
    IDLE = "idle"
    CLAIMED = "claimed"
    ACTIVE = "active"
    RELEASED = "released"
    REMOVED = "removed"

    @property
    def is_terminal(self) -> bool:
        return self is self.REMOVED


class ApprovalRequestStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.APPROVED, self.REJECTED, self.EXPIRED, self.CANCELLED}


class InboxParticipantKind(StrEnum):
    USER = "user"
    AGENT = "agent"
    SYSTEM = "system"
    HARNESS = "harness"


class InboxStatus(StrEnum):
    UNREAD = "unread"
    PENDING = "pending"
    DELIVERED = "delivered"
    ACKNOWLEDGED = "acknowledged"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.ACKNOWLEDGED, self.FAILED}


class MemoryScopeKind(StrEnum):
    SESSION = "session"
    LANE = "lane"
    TASK = "task"


class MemoryKind(StrEnum):
    SUMMARY = "summary"
    COMPACTION = "compaction"
    NOTE = "note"
    CONTINUITY = "continuity"


class AgentMemberStatus(StrEnum):
    ACTIVE = "active"
    WORKING = "working"
    IDLE = "idle"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"
    SHUTDOWN = "shutdown"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.STOPPED, self.SHUTDOWN}


class AgentRuntimeSignalReason(StrEnum):
    DELEGATION_ASSIGNED = "delegation_assigned"
    INBOX_UNREAD = "inbox_unread"
    TASK_AVAILABLE = "task_available"
    APPROVAL_RESOLVED = "approval_resolved"
    ENGINE_COMPLETED = "engine_completed"
    MANUAL_RESUME = "manual_resume"


class AgentRuntimeSignalStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.CANCELLED}


class SandboxWorkspaceStatus(StrEnum):
    READY = "ready"
    ATTACHED = "attached"
    DETACHED = "detached"
    CORRUPT = "corrupt"
    QUOTA_EXCEEDED = "quota_exceeded"
    MISSING_IMAGE = "missing_image"
    IMAGE_INCOMPATIBLE = "image_incompatible"


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


class ControlledOperationStatus(StrEnum):
    CREATED = "created"
    WAITING_APPROVAL = "waiting_approval"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERY_FAILED = "recovery_failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.RECOVERY_FAILED}


class ContinuationStateStatus(StrEnum):
    WAITING_APPROVAL = "waiting_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    CLAIMED = "claimed"
    COMPLETED = "completed"
    FAILED = "failed"
    RECOVERY_FAILED = "recovery_failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.REJECTED, self.COMPLETED, self.FAILED, self.RECOVERY_FAILED}


class SandboxImageCompatibility(StrEnum):
    COMPATIBLE = "compatible"
    COMPATIBLE_NON_CUTOVER_GRADE = "compatible_non_cutover_grade"
    MISSING = "missing"
    INCOMPATIBLE = "incompatible"


class EngineInvocationStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.SUCCEEDED, self.FAILED, self.CANCELLED}


class ResearchSummaryStatus(StrEnum):
    COMPLETED = "completed"
    PARTIAL = "partial"
    NEEDS_CLARIFICATION = "needs_clarification"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.PARTIAL, self.NEEDS_CLARIFICATION, self.FAILED}


class SessionReportStatus(StrEnum):
    DRAFT = "draft"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.READY, self.PUBLISHED, self.FAILED}


class SessionReportDraftStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    READY = "ready"
    PUBLISHED = "published"
    FAILED = "failed"

    @property
    def is_terminal(self) -> bool:
        return self in {self.PUBLISHED, self.FAILED}


@dataclass(frozen=True, slots=True)
class Session:
    session_id: str
    project_id: str
    title: str
    objective: str
    status: SessionStatus
    created_at: str
    updated_at: str

    @classmethod
    def create(
        cls,
        session_id: str,
        project_id: str,
        title: str,
        objective: str,
        status: SessionStatus = SessionStatus.ACTIVE,
    ) -> "Session":
        now = utc_now_iso()
        return cls(
            session_id=session_id,
            project_id=project_id,
            title=title,
            objective=objective,
            status=status,
            created_at=now,
            updated_at=now,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data.pop("member_id", None)
        return data


@dataclass(frozen=True, slots=True)
class Task:
    task_id: str
    session_id: str
    subject: str
    description: str
    status: TaskStatus
    priority: TaskPriority
    kind: str
    assigned_ref: str | None
    created_at: str
    updated_at: str
    lane_id: str | None = None
    blocked_by: tuple[str, ...] = ()
    failure_summary: str | None = None
    failure_ref: str | None = None

    @classmethod
    def create(
        cls,
        task_id: str,
        session_id: str,
        subject: str,
        description: str,
        *,
        priority: TaskPriority = TaskPriority.NORMAL,
        kind: str = "general",
        status: TaskStatus = TaskStatus.TODO,
        assigned_ref: str | None = None,
        lane_id: str | None = None,
        blocked_by: tuple[str, ...] = (),
        failure_summary: str | None = None,
        failure_ref: str | None = None,
    ) -> "Task":
        now = utc_now_iso()
        return cls(
            task_id=task_id,
            session_id=session_id,
            subject=subject,
            description=description,
            status=status,
            priority=priority,
            kind=kind,
            assigned_ref=assigned_ref,
            created_at=now,
            updated_at=now,
            lane_id=lane_id,
            blocked_by=blocked_by,
            failure_summary=failure_summary,
            failure_ref=failure_ref,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["priority"] = self.priority.value
        data["blocked_by"] = list(self.blocked_by)
        return data


@dataclass(frozen=True, slots=True)
class Lane:
    lane_id: str
    session_id: str
    name: str
    status: LaneStatus
    cwd: str
    branch_name: str | None
    claimed_ref: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class ApprovalRequest:
    approval_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    kind: str
    requested_action: str
    status: ApprovalRequestStatus
    request_ref: str | None
    resolution_ref: str | None
    created_at: str
    resolved_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class InboxMessage:
    message_id: str
    session_id: str
    sender: str
    sender_kind: InboxParticipantKind
    recipient: str
    recipient_kind: InboxParticipantKind
    message_type: str
    correlation_id: str | None
    payload_ref: str | None
    status: InboxStatus
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["sender_kind"] = self.sender_kind.value
        data["recipient_kind"] = self.recipient_kind.value
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    memory_id: str
    session_id: str
    scope_kind: MemoryScopeKind
    scope_ref: str
    kind: MemoryKind
    summary: str
    source_range: str | None
    importance: int
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["scope_kind"] = self.scope_kind.value
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True, slots=True)
class AgentMember:
    agent_id: str
    session_id: str
    lane_id: str | None
    task_id: str | None
    name: str
    role: str
    status: AgentMemberStatus
    parent_agent_id: str | None
    created_at: str
    updated_at: str
    runtime_state: str | None = None
    current_correlation_id: str | None = None
    wakeup_reason: str | None = None
    last_active_at: str | None = None
    idle_since: str | None = None
    shutdown_requested_at: str | None = None
    member_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class AgentRuntimeSignal:
    signal_id: str
    session_id: str
    agent_id: str
    reason: AgentRuntimeSignalReason
    status: AgentRuntimeSignalStatus
    created_at: str
    task_id: str | None = None
    lane_id: str | None = None
    correlation_id: str | None = None
    source_ref: str | None = None
    claimed_at: str | None = None
    claimed_by: str | None = None
    claim_expires_at: str | None = None
    attempt_count: int = 0
    completed_at: str | None = None
    error_message: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reason"] = self.reason.value
        data["status"] = self.status.value
        return data


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
    materialized_input_artifact_ids: tuple[str, ...] = ()
    registered_artifact_ids: tuple[str, ...] = ()
    source_code_artifact_ids: tuple[str, ...] = ()
    last_command_summary: dict[str, Any] | None = None
    last_error: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["image_compatibility"] = self.image_compatibility.value
        data["materialized_input_artifact_ids"] = list(self.materialized_input_artifact_ids)
        data["registered_artifact_ids"] = list(self.registered_artifact_ids)
        data["source_code_artifact_ids"] = list(self.source_code_artifact_ids)
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
    source_snapshot_artifact_id: str | None = None
    source_tree_digest: str | None = None
    stdout_summary: str | None = None
    stderr_summary: str | None = None
    exit_code: int | None = None
    duration_ms: int | None = None
    changed_files_summary: dict[str, Any] | None = None
    log_artifact_ref: str | None = None
    error_code: str | None = None
    compatibility: dict[str, Any] | None = None
    started_at: str | None = None
    ended_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["argv"] = list(self.argv)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class ControlledOperation:
    operation_id: str
    session_id: str
    sandbox_workspace_id: str
    sandbox_run_id: str
    logical_operation_key: str
    operation_digest: str
    params_digest: str
    backend_category: str
    status: ControlledOperationStatus
    created_at: str
    updated_at: str
    task_id: str | None = None
    lane_id: str | None = None
    approval_id: str | None = None
    approval_state: str | None = None
    route_reason: str | None = None
    input_artifact_digests: tuple[str, ...] = ()
    source_snapshot_artifact_id: str | None = None
    source_snapshot_digest: str | None = None
    expected_outputs_summary: dict[str, Any] | None = None
    resource_estimate: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_summary: str | None = None
    idempotency_key: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["input_artifact_digests"] = list(self.input_artifact_digests)
        return data


@dataclass(frozen=True, slots=True)
class ContinuationState:
    continuation_id: str
    session_id: str
    operation_id: str
    sandbox_run_id: str
    approval_id: str
    status: ContinuationStateStatus
    created_at: str
    updated_at: str
    claimed_at: str | None = None
    claimed_by: str | None = None
    claim_expires_at: str | None = None
    attempt_count: int = 0
    completed_at: str | None = None
    error_code: str | None = None
    error_message: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class FileAuditEntry:
    audit_id: str
    session_id: str
    sandbox_workspace_id: str
    actor_ref: str
    operation: str
    path: str
    created_at: str
    task_id: str | None = None
    lane_id: str | None = None
    old_digest: str | None = None
    new_digest: str | None = None
    sandbox_run_id: str | None = None
    details: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class CommandLogArtifactRecord:
    command_log_id: str
    session_id: str
    sandbox_run_id: str
    sandbox_workspace_id: str
    stream: str
    artifact_ref: str
    size_bytes: int
    content_digest: str
    truncated: bool
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class EngineInvocation:
    invocation_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    engine_name: str
    status: EngineInvocationStatus
    input_ref: str | None
    output_ref: str | None
    approval_id: str | None
    idempotency_key: str
    started_at: str
    finished_at: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class RunRecord:
    run_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    approval_id: str | None
    engine_name: str
    runner_run_id: str
    status: RunStatus
    execution_mode: str
    remote_run_dir: str
    created_at: str
    updated_at: str
    finished_at: str | None = None
    summary: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class SessionArtifactRecord:
    artifact_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str | None
    run_id: str | None
    kind: ArtifactKind
    storage_uri: str
    relative_path: str
    created_at: str
    title: str | None = None
    description: str | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True, slots=True)
class SessionReportRecord:
    report_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str | None
    run_id: str | None
    artifact_id: str | None
    status: SessionReportStatus
    title: str
    summary: str
    stage_summary: str
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class SessionReportDraftRecord:
    draft_id: str
    session_id: str
    task_id: str | None
    owner_agent_id: str | None
    status: SessionReportDraftStatus
    title: str
    summary: str
    content_ref: str | None
    published_report_id: str | None
    created_at: str
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchSummary:
    summary_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    status: ResearchSummaryStatus
    completion_reason: str
    research_brief: str
    summary: str
    created_at: str
    updated_at: str
    clarification_question: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchEvidence:
    evidence_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    summary_id: str
    summary: str
    query: str
    created_at: str
    confidence_label: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True, slots=True)
class ResearchSourceRef:
    source_ref_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    evidence_id: str
    title: str
    locator: str
    kind: SourceRefKind
    created_at: str
    snippet: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["kind"] = self.kind.value
        return data


@dataclass(frozen=True, slots=True)
class ResearchGap:
    gap_id: str
    session_id: str
    task_id: str | None
    lane_id: str | None
    invocation_id: str
    summary_id: str
    summary: str
    created_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
