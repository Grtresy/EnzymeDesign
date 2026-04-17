from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Callable
from typing import Protocol
from uuid import uuid4

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain.control_plane import utc_now_iso

from .repositories import CoreRepositories


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ResumeDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


class HarnessStatus(StrEnum):
    COMPLETED = "completed"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_DELEGATION = "waiting_delegation"
    MAX_STEPS_EXCEEDED = "max_steps_exceeded"


@dataclass(frozen=True, slots=True)
class HarnessEvent:
    event_id: str
    session_id: str
    event_type: str
    created_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventSink(Protocol):
    def emit(self, event: HarnessEvent) -> None: ...


@dataclass(slots=True)
class MemoryEventBus:
    events: list[HarnessEvent]

    def __init__(self) -> None:
        self.events = []

    def emit(self, event: HarnessEvent) -> None:
        self.events.append(event)


@dataclass(frozen=True, slots=True)
class SessionRuntimeSnapshot:
    session: Session
    tasks: tuple[Task, ...]
    ready_tasks: tuple[Task, ...]
    lanes: tuple[Lane, ...]
    pending_approvals: tuple[ApprovalRequest, ...]
    inbox: tuple[InboxMessage, ...]
    memory: tuple[MemoryEntry, ...]
    agents: tuple[Any, ...]
    active_invocations: tuple[EngineInvocation, ...]

    @classmethod
    def load(cls, repositories: CoreRepositories, session_id: str) -> "SessionRuntimeSnapshot":
        session = repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        return cls(
            session=session,
            tasks=tuple(repositories.tasks.list_by_session(session_id)),
            ready_tasks=tuple(repositories.tasks.list_ready_by_session(session_id)),
            lanes=tuple(repositories.lanes.list_by_session(session_id)),
            pending_approvals=tuple(repositories.approvals.list_pending_by_session(session_id)),
            inbox=tuple(repositories.inbox.list_by_session(session_id)),
            memory=tuple(repositories.memory.list_by_session(session_id)),
            agents=tuple(repositories.agents.list_by_session(session_id)),
            active_invocations=tuple(repositories.invocations.list_active_by_session(session_id)),
        )


@dataclass(frozen=True, slots=True)
class ResumeEnvelope:
    approval_id: str
    decision: ResumeDecision
    actor_ref: str = "user"
    resolution_ref: str | None = None


@dataclass(frozen=True, slots=True)
class HarnessInput:
    session_id: str
    message: str | None = None
    resume: ResumeEnvelope | None = None
    max_steps: int = 8
    sender: str = "user"
    sender_kind: InboxParticipantKind = InboxParticipantKind.USER


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    content: str
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(frozen=True, slots=True)
class DelegationRequest:
    request_id: str
    session_id: str
    recipient: str
    payload_ref: str | None
    task_id: str | None = None
    lane_id: str | None = None
    correlation_id: str | None = None
    recipient_kind: InboxParticipantKind = InboxParticipantKind.AGENT


@dataclass(frozen=True, slots=True)
class DelegationHandle:
    request_id: str
    message_id: str
    correlation_id: str | None


@dataclass(frozen=True, slots=True)
class HarnessStep:
    assistant_message: str | None = None
    tool_invocations: tuple[ToolInvocation, ...] = ()
    task_updates: tuple[Task, ...] = ()
    approval_requests: tuple[ApprovalRequest, ...] = ()
    memory_entries: tuple[MemoryEntry, ...] = ()
    engine_invocations: tuple[EngineInvocation, ...] = ()
    delegation_requests: tuple[DelegationRequest, ...] = ()
    session_status: SessionStatus | None = None


class HarnessDriver(Protocol):
    def plan(
        self,
        context: "SessionRuntimeContext",
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep: ...


ToolHandler = Callable[["SessionRuntimeContext", ToolInvocation], ToolResult | str]


@dataclass(slots=True)
class ToolRegistry:
    _handlers: dict[str, ToolHandler]

    def __init__(self) -> None:
        self._handlers = {}

    def register(self, tool_name: str, handler: ToolHandler) -> None:
        self._handlers[tool_name] = handler

    def dispatch(self, context: "SessionRuntimeContext", invocation: ToolInvocation) -> ToolResult:
        handler = self._handlers.get(invocation.tool_name)
        if handler is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"unknown tool: {invocation.tool_name}",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
        result = handler(context, invocation)
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=str(result),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )


@dataclass(slots=True)
class SessionRuntimeContext:
    repositories: CoreRepositories
    event_sink: EventSink
    snapshot: SessionRuntimeSnapshot
    tool_registry: ToolRegistry

    def refresh(self) -> SessionRuntimeSnapshot:
        self.snapshot = SessionRuntimeSnapshot.load(self.repositories, self.snapshot.session.session_id)
        return self.snapshot

    def emit(self, event_type: str, payload: dict[str, Any]) -> HarnessEvent:
        event = HarnessEvent(
            event_id=_new_id("evt"),
            session_id=self.snapshot.session.session_id,
            event_type=event_type,
            created_at=utc_now_iso(),
            payload=payload,
        )
        self.event_sink.emit(event)
        return event


@dataclass(frozen=True, slots=True)
class HarnessResult:
    session_id: str
    status: HarnessStatus
    snapshot: SessionRuntimeSnapshot
    events: tuple[HarnessEvent, ...]
    outputs: tuple[str, ...]
    tool_results: tuple[ToolResult, ...]
    pending_approval_id: str | None = None
    delegations: tuple[DelegationHandle, ...] = ()


def _persist_message(
    repositories: CoreRepositories,
    *,
    session_id: str,
    sender: str,
    sender_kind: InboxParticipantKind,
    recipient: str,
    recipient_kind: InboxParticipantKind,
    message_type: str,
    payload_ref: str | None = None,
    correlation_id: str | None = None,
) -> InboxMessage:
    message = InboxMessage(
        message_id=_new_id("msg"),
        session_id=session_id,
        sender=sender,
        sender_kind=sender_kind,
        recipient=recipient,
        recipient_kind=recipient_kind,
        message_type=message_type,
        correlation_id=correlation_id,
        payload_ref=payload_ref,
        status=InboxStatus.DELIVERED,
        created_at=utc_now_iso(),
    )
    repositories.inbox.save(message)
    return message


def _resolve_resume(context: SessionRuntimeContext, resume: ResumeEnvelope) -> ApprovalRequest:
    approval = context.repositories.approvals.get(resume.approval_id)
    if approval is None:
        raise ValueError(f"approval {resume.approval_id!r} does not exist")
    if approval.session_id != context.snapshot.session.session_id:
        raise ValueError(
            f"approval {resume.approval_id!r} belongs to session {approval.session_id!r}, "
            f"not {context.snapshot.session.session_id!r}"
        )
    if approval.status is not ApprovalRequestStatus.PENDING:
        raise ValueError(f"approval {resume.approval_id!r} is not pending")
    status_map = {
        ResumeDecision.APPROVED: ApprovalRequestStatus.APPROVED,
        ResumeDecision.REJECTED: ApprovalRequestStatus.REJECTED,
        ResumeDecision.CANCELLED: ApprovalRequestStatus.CANCELLED,
    }
    resolved = ApprovalRequest(
        approval_id=approval.approval_id,
        session_id=approval.session_id,
        task_id=approval.task_id,
        lane_id=approval.lane_id,
        kind=approval.kind,
        requested_action=approval.requested_action,
        status=status_map[resume.decision],
        request_ref=approval.request_ref,
        resolution_ref=resume.resolution_ref,
        created_at=approval.created_at,
        resolved_at=utc_now_iso(),
    )
    context.repositories.approvals.save(resolved)
    context.emit(
        "approval.resolved",
        {
            "approval_id": resolved.approval_id,
            "decision": resume.decision.value,
            "actor_ref": resume.actor_ref,
        },
    )
    return resolved


def run_agent_harness_loop(
    repositories: CoreRepositories,
    harness_input: HarnessInput,
    *,
    driver: HarnessDriver,
    tool_registry: ToolRegistry | None = None,
    event_sink: EventSink | None = None,
) -> HarnessResult:
    registry = tool_registry or ToolRegistry()
    sink = event_sink or MemoryEventBus()
    snapshot = SessionRuntimeSnapshot.load(repositories, harness_input.session_id)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=sink,
        snapshot=snapshot,
        tool_registry=registry,
    )
    outputs: list[str] = []
    all_tool_results: list[ToolResult] = []
    delegation_handles: list[DelegationHandle] = []

    if harness_input.message is not None:
        message = _persist_message(
            repositories,
            session_id=harness_input.session_id,
            sender=harness_input.sender,
            sender_kind=harness_input.sender_kind,
            recipient="harness",
            recipient_kind=InboxParticipantKind.HARNESS,
            message_type="user_message",
        )
        context.emit(
            "message.received",
            {
                "message_id": message.message_id,
                "sender": message.sender,
                "sender_kind": message.sender_kind.value,
            },
        )

    if harness_input.resume is not None:
        _resolve_resume(context, harness_input.resume)

    context.refresh()
    tool_results: tuple[ToolResult, ...] = ()
    last_status = HarnessStatus.COMPLETED
    pending_approval_id: str | None = None

    for _ in range(harness_input.max_steps):
        step = driver.plan(context, harness_input, tool_results)
        tool_results = ()

        for task in step.task_updates:
            repositories.tasks.save(task)
            context.emit(
                "task.updated",
                {
                    "task_id": task.task_id,
                    "status": task.status.value,
                    "assigned_ref": task.assigned_ref,
                },
            )

        for memory in step.memory_entries:
            repositories.memory.save(memory)
            context.emit(
                "memory.recorded",
                {
                    "memory_id": memory.memory_id,
                    "scope_kind": memory.scope_kind.value,
                    "scope_ref": memory.scope_ref,
                    "kind": memory.kind.value,
                },
            )

        for invocation in step.engine_invocations:
            repositories.invocations.save(invocation)
            context.emit(
                "engine.invocation.updated",
                {
                    "invocation_id": invocation.invocation_id,
                    "engine_name": invocation.engine_name,
                    "status": invocation.status.value,
                },
            )

        if step.session_status is not None:
            session = context.snapshot.session
            updated = Session(
                session_id=session.session_id,
                project_id=session.project_id,
                title=session.title,
                objective=session.objective,
                status=step.session_status,
                created_at=session.created_at,
                updated_at=utc_now_iso(),
            )
            repositories.sessions.save(updated)
            context.emit(
                "session.updated",
                {"session_id": updated.session_id, "status": updated.status.value},
            )

        if step.assistant_message is not None:
            message = _persist_message(
                repositories,
                session_id=harness_input.session_id,
                sender="harness",
                sender_kind=InboxParticipantKind.HARNESS,
                recipient=harness_input.sender,
                recipient_kind=harness_input.sender_kind,
                message_type="assistant_message",
            )
            outputs.append(step.assistant_message)
            context.emit(
                "message.sent",
                {
                    "message_id": message.message_id,
                    "recipient": message.recipient,
                    "recipient_kind": message.recipient_kind.value,
                },
            )

        for approval in step.approval_requests:
            repositories.approvals.save(approval)
            pending_approval_id = approval.approval_id
            context.emit(
                "approval.requested",
                {
                    "approval_id": approval.approval_id,
                    "kind": approval.kind,
                    "task_id": approval.task_id,
                    "lane_id": approval.lane_id,
                },
            )

        for delegation in step.delegation_requests:
            message = _persist_message(
                repositories,
                session_id=delegation.session_id,
                sender="harness",
                sender_kind=InboxParticipantKind.HARNESS,
                recipient=delegation.recipient,
                recipient_kind=delegation.recipient_kind,
                message_type="delegation_request",
                payload_ref=delegation.payload_ref,
                correlation_id=delegation.correlation_id,
            )
            delegation_handles.append(
                DelegationHandle(
                    request_id=delegation.request_id,
                    message_id=message.message_id,
                    correlation_id=delegation.correlation_id,
                )
            )
            context.emit(
                "agent.delegated",
                {
                    "request_id": delegation.request_id,
                    "recipient": delegation.recipient,
                    "task_id": delegation.task_id,
                    "lane_id": delegation.lane_id,
                },
            )

        if step.approval_requests:
            last_status = HarnessStatus.WAITING_APPROVAL
            context.refresh()
            return HarnessResult(
                session_id=harness_input.session_id,
                status=last_status,
                snapshot=context.snapshot,
                events=tuple(sink.events),
                outputs=tuple(outputs),
                tool_results=tuple(all_tool_results),
                pending_approval_id=pending_approval_id,
                delegations=tuple(delegation_handles),
            )

        if step.delegation_requests and not step.tool_invocations:
            last_status = HarnessStatus.WAITING_DELEGATION
            context.refresh()
            return HarnessResult(
                session_id=harness_input.session_id,
                status=last_status,
                snapshot=context.snapshot,
                events=tuple(sink.events),
                outputs=tuple(outputs),
                tool_results=tuple(all_tool_results),
                pending_approval_id=pending_approval_id,
                delegations=tuple(delegation_handles),
            )

        if step.tool_invocations:
            current_results: list[ToolResult] = []
            for invocation in step.tool_invocations:
                context.emit(
                    "tool.invoked",
                    {
                        "call_id": invocation.call_id,
                        "tool_name": invocation.tool_name,
                        "task_id": invocation.task_id,
                        "lane_id": invocation.lane_id,
                    },
                )
                result = registry.dispatch(context, invocation)
                current_results.append(result)
                all_tool_results.append(result)
                context.emit(
                    "tool.completed",
                    {
                        "call_id": result.call_id,
                        "tool_name": result.tool_name,
                        "ok": result.ok,
                    },
                )
            tool_results = tuple(current_results)
            context.refresh()
            continue

        context.refresh()
        return HarnessResult(
            session_id=harness_input.session_id,
            status=last_status,
            snapshot=context.snapshot,
            events=tuple(sink.events),
            outputs=tuple(outputs),
            tool_results=tuple(all_tool_results),
            pending_approval_id=pending_approval_id,
            delegations=tuple(delegation_handles),
        )

    context.emit(
        "harness.max_steps_exceeded",
        {"max_steps": harness_input.max_steps},
    )
    context.refresh()
    return HarnessResult(
        session_id=harness_input.session_id,
        status=HarnessStatus.MAX_STEPS_EXCEEDED,
        snapshot=context.snapshot,
        events=tuple(sink.events),
        outputs=tuple(outputs),
        tool_results=tuple(all_tool_results),
        pending_approval_id=pending_approval_id,
        delegations=tuple(delegation_handles),
    )
