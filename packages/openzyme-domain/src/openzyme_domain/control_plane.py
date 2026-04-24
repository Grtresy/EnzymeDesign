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
    "EngineInvocation",
    "RunRecord",
    "SessionArtifactRecord",
    "SessionReportDraftRecord",
    "SessionReportRecord",
    "ResearchSummary",
    "ResearchEvidence",
    "ResearchSourceRef",
    "ResearchGap",
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
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.CANCELLED}


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
    IDLE = "idle"
    BLOCKED = "blocked"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"

    @property
    def is_terminal(self) -> bool:
        return self in {self.COMPLETED, self.FAILED, self.STOPPED}


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

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        return data


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
