from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from enum import StrEnum
from typing import Any
from typing import ClassVar

from .identity import require_digest
from .identity import require_identifier
from .reliability import CONTINUATION_STATE_SCHEMA_VERSION
from .reliability import ContinuationDeliveryState
from .reliability import ContinuationResumeStrategy
from .reliability import ControlledOperationOwnerMode
from .repository_bindings import SessionRepositoryBindingStatus


def utc_now_iso() -> str:
    return datetime.now(tz=UTC).isoformat()


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


class SessionRuntimeLeaseMode(StrEnum):
    BACKGROUND = "background"
    MANUAL_DRAIN = "manual_drain"
    RECOVERY = "recovery"
    TEST = "test"


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
class Session:
    session_id: str
    project_id: str
    title: str
    objective: str
    status: SessionStatus
    created_at: str
    updated_at: str
    repository_binding_status: SessionRepositoryBindingStatus = (
        SessionRepositoryBindingStatus.REPOSITORY_BINDING_REQUIRED
    )

    @classmethod
    def create(
        cls,
        session_id: str,
        project_id: str,
        title: str,
        objective: str,
        status: SessionStatus = SessionStatus.ACTIVE,
        repository_binding_status: SessionRepositoryBindingStatus = (
            SessionRepositoryBindingStatus.REPOSITORY_BINDING_REQUIRED
        ),
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
            repository_binding_status=repository_binding_status,
        )

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["repository_binding_status"] = self.repository_binding_status.value
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
    workflow_authority_id: str | None = None
    workflow_authority_epoch: int | None = None
    workflow_authority_digest: str | None = None

    def __post_init__(self) -> None:
        workflow_identity = (
            self.workflow_authority_id,
            self.workflow_authority_epoch,
            self.workflow_authority_digest,
        )
        if any(value is None for value in workflow_identity) and any(
            value is not None for value in workflow_identity
        ):
            raise ValueError("approval workflow authority identity must be complete")
        if self.workflow_authority_id is not None:
            require_identifier(
                self.workflow_authority_id,
                field_name="workflow_authority_id",
            )
            if (
                not isinstance(self.workflow_authority_epoch, int)
                or isinstance(self.workflow_authority_epoch, bool)
                or self.workflow_authority_epoch < 1
            ):
                raise ValueError("workflow_authority_epoch must be positive")
            require_digest(
                self.workflow_authority_digest or "",
                field_name="workflow_authority_digest",
            )

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
    created_at: str
    updated_at: str
    parent_agent_id: str | None = None
    runtime_state: str | None = None
    current_correlation_id: str | None = None
    wakeup_reason: str | None = None
    last_active_at: str | None = None
    idle_since: str | None = None
    shutdown_requested_at: str | None = None
    member_id: str | None = None
    nickname: str | None = None
    display_name: str | None = None
    handle: str | None = None

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
    session_lease_token: str | None = None
    session_fencing_token: int | None = None
    capability_lease_id: str | None = None
    workspace_generation: int | None = None

    def __post_init__(self) -> None:
        if (self.capability_lease_id is None) != (self.workspace_generation is None):
            raise ValueError(
                "capability_lease_id and workspace_generation must be provided together"
            )
        if self.capability_lease_id is not None and (
            not self.capability_lease_id
            or self.capability_lease_id != self.capability_lease_id.strip()
        ):
            raise ValueError("capability_lease_id must be a non-empty identifier")
        if self.workspace_generation is not None and (
            not isinstance(self.workspace_generation, int)
            or isinstance(self.workspace_generation, bool)
            or self.workspace_generation <= 0
        ):
            raise ValueError("workspace_generation must be a positive integer")

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["reason"] = self.reason.value
        data["status"] = self.status.value
        return data


@dataclass(frozen=True, slots=True)
class SessionRuntimeLease:
    session_id: str
    owner_id: str
    lease_token: str
    mode: SessionRuntimeLeaseMode
    acquired_at: str
    heartbeat_at: str
    expires_at: str
    fencing_token: int
    released_at: str | None = None
    last_error: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["mode"] = self.mode.value
        return data


@dataclass(frozen=True, slots=True)
class ControlledOperation:
    operation_id: str
    session_id: str
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
    adapter_envelope_schema_version: str | None = None
    sdk_module: str | None = None
    function_name: str | None = None
    route_policy_id: str | None = None
    placement: str | None = None
    selected_backend: str | None = None
    resource_class: str | None = None
    runtime_packaging_id: str | None = None
    toolchain_id: str | None = None
    provider_config_digest: str | None = None
    approval_requirement: dict[str, Any] | None = None
    adapter_approval_envelope: dict[str, Any] | None = None
    adapter_result_envelope: dict[str, Any] | None = None
    adapter_result_origin: str | None = None
    resource_estimate: dict[str, Any] | None = None
    result_summary: dict[str, Any] | None = None
    error_code: str | None = None
    error_summary: str | None = None
    idempotency_key: str | None = None
    owner_mode: ControlledOperationOwnerMode = ControlledOperationOwnerMode.DURABLE_ASYNC_V1

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["owner_mode"] = self.owner_mode.value
        return data


@dataclass(frozen=True, slots=True)
class ContinuationState:
    SCHEMA_VERSION: ClassVar[str] = CONTINUATION_STATE_SCHEMA_VERSION

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
    originating_signal_id: str | None = None
    originating_agent_id: str | None = None
    originating_task_id: str | None = None
    originating_lane_id: str | None = None
    originating_tool_call_id: str | None = None
    originating_invocation_id: str | None = None
    sandbox_workspace_id: str | None = None
    sandbox_runtime_identity: str | None = None
    process_epoch: int | None = None
    resume_strategy: ContinuationResumeStrategy = (
        ContinuationResumeStrategy.LEGACY_NON_RESUMABLE
    )
    delivery_state: ContinuationDeliveryState = (
        ContinuationDeliveryState.LEGACY_UNAVAILABLE
    )
    delivery_generation: int = 0
    delivery_result_digest: str | None = None
    state_version: int = 0
    delivery_claim_owner: str | None = None
    delivery_lease_token: str | None = None
    delivery_lease_expires_at: str | None = None
    delivery_fencing_token: int = 0

    def to_dict(self) -> dict[str, Any]:
        data = {"schema_version": self.SCHEMA_VERSION, **asdict(self)}
        data["status"] = self.status.value
        data["resume_strategy"] = self.resume_strategy.value
        data["delivery_state"] = self.delivery_state.value
        return data


__all__ = [
    'SessionStatus',
    'TaskStatus',
    'TaskPriority',
    'LaneStatus',
    'ApprovalRequestStatus',
    'InboxParticipantKind',
    'InboxStatus',
    'MemoryScopeKind',
    'MemoryKind',
    'AgentMemberStatus',
    'AgentRuntimeSignalReason',
    'AgentRuntimeSignalStatus',
    'SessionRuntimeLeaseMode',
    'ControlledOperationStatus',
    'ContinuationStateStatus',
    'EngineInvocationStatus',
    'EngineInvocation',
    'Session',
    'Task',
    'Lane',
    'ApprovalRequest',
    'InboxMessage',
    'MemoryEntry',
    'AgentMember',
    'AgentRuntimeSignal',
    'SessionRuntimeLease',
    'ControlledOperation',
    'ContinuationState',
]
