from __future__ import annotations

from dataclasses import asdict
from dataclasses import replace
from dataclasses import dataclass
from enum import StrEnum
import json
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
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso

from .engines import EngineRegistry
from .repositories import EngineDocumentRecord
from .repositories import CoreRepositories
from .conversation import persist_conversation_message


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


class ResumeDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class RestoreFocus:
    task_id: str | None = None
    lane_id: str | None = None
    skill_keys: tuple[str, ...] = ()

    def normalized(self) -> "RestoreFocus":
        return RestoreFocus(
            task_id=self.task_id,
            lane_id=self.lane_id,
            skill_keys=tuple(dict.fromkeys(self.skill_keys)),
        )


class HarnessStatus(StrEnum):
    COMPLETED = "completed"
    FAILED = "failed"
    WAITING_APPROVAL = "waiting_approval"
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
    def load(
        cls, repositories: CoreRepositories, session_id: str
    ) -> "SessionRuntimeSnapshot":
        session = repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        return cls(
            session=session,
            tasks=tuple(repositories.tasks.list_by_session(session_id)),
            ready_tasks=tuple(repositories.tasks.list_ready_by_session(session_id)),
            lanes=tuple(repositories.lanes.list_by_session(session_id)),
            pending_approvals=tuple(
                repositories.approvals.list_pending_by_session(session_id)
            ),
            inbox=tuple(repositories.inbox.list_by_session(session_id)),
            memory=tuple(repositories.memory.list_by_session(session_id)),
            agents=tuple(repositories.agents.list_by_session(session_id)),
            active_invocations=tuple(
                repositories.invocations.list_active_by_session(session_id)
            ),
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
    restore_focus: RestoreFocus | None = None
    persist_conversation: bool = True
    skip_resume_resolution: bool = False


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    call_id: str
    tool_name: str
    arguments: dict[str, Any]
    task_id: str | None = None
    lane_id: str | None = None


@dataclass(frozen=True, slots=True)
class LlmTraceToolCall:
    call_id: str
    tool_name: str
    args_public: dict[str, Any]
    task_id: str | None = None
    lane_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "args_public": self.args_public,
        }


@dataclass(frozen=True, slots=True)
class LlmTraceStep:
    actor_ref: str
    actor_kind: str
    display_name: str
    role: str
    call_index: int
    response_text: str
    tool_calls: tuple[LlmTraceToolCall, ...] = ()
    initial_prompt: dict[str, Any] | None = None

    def to_payload(self, *, trace_id: str, created_at: str) -> dict[str, Any]:
        payload = {
            "trace_id": trace_id,
            "actor_ref": self.actor_ref,
            "actor_kind": self.actor_kind,
            "display_name": self.display_name,
            "role": self.role,
            "call_index": self.call_index,
            "created_at": created_at,
            "response_text": self.response_text,
            "tool_calls": [tool_call.to_dict() for tool_call in self.tool_calls],
        }
        if self.initial_prompt is not None:
            payload["initial_prompt"] = self.initial_prompt
        return payload


@dataclass(frozen=True, slots=True)
class ToolResult:
    call_id: str
    tool_name: str
    ok: bool
    content: str
    task_id: str | None = None
    lane_id: str | None = None
    status: str | None = None
    summary: str | None = None
    error_code: str | None = None
    hint: str | None = None
    details: dict[str, Any] | None = None

    def envelope(self) -> dict[str, Any]:
        details = dict(self.details or {})
        envelope: dict[str, Any] = {
            "ok": self.ok,
            "status": self.status or ("ok" if self.ok else "failed"),
            "summary": self.summary or self.content,
            "error_code": self.error_code,
            "hint": self.hint,
            "details": details,
            "content": self.content,
        }
        try:
            envelope["payload"] = json.loads(self.content)
        except (TypeError, json.JSONDecodeError):
            pass
        return envelope

    def to_tool_message_content(self) -> str:
        return json.dumps(self.envelope(), sort_keys=True)


@dataclass(frozen=True, slots=True)
class HarnessStep:
    assistant_message: str | None = None
    tool_invocations: tuple[ToolInvocation, ...] = ()
    llm_trace: LlmTraceStep | None = None
    task_updates: tuple[Task, ...] = ()
    approval_requests: tuple[ApprovalRequest, ...] = ()
    memory_entries: tuple[MemoryEntry, ...] = ()
    engine_invocations: tuple[EngineInvocation, ...] = ()
    session_status: SessionStatus | None = None
    next_focus: RestoreFocus | None = None


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

    def dispatch(
        self, context: "SessionRuntimeContext", invocation: ToolInvocation
    ) -> ToolResult:
        handler = self._handlers.get(invocation.tool_name)
        if handler is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"unknown tool: {invocation.tool_name}",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="unknown_tool",
                summary=f"Tool {invocation.tool_name!r} is not registered.",
                error_code="unknown_tool",
                hint="Use one of the tools exposed in the current V3 tool catalog.",
            )
        try:
            result = handler(context, invocation)
        except (KeyError, TypeError, ValueError) as exc:
            message = f"Tool {invocation.tool_name} failed: {str(exc).strip() or exc.__class__.__name__}"
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=message,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                status="invalid_tool_arguments",
                summary=message,
                error_code="invalid_tool_arguments",
                hint="Fix the tool arguments or referenced task/lane/session state before retrying.",
                details={"exception_type": exc.__class__.__name__},
            )
        if isinstance(result, ToolResult):
            return result
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=str(result),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="ok",
            summary=str(result),
        )


@dataclass(slots=True)
class SessionRuntimeContext:
    repositories: CoreRepositories
    event_sink: EventSink
    snapshot: SessionRuntimeSnapshot
    tool_registry: ToolRegistry
    restore_focus: RestoreFocus
    restore_context: Any | None = None
    active_skill_keys: tuple[str, ...] = ()
    skill_registry: Any | None = None
    model_factory: Any | None = None
    engine_registry: EngineRegistry | None = None
    bio_research_service: Any | None = None
    research_adapter: Any | None = None
    signal_notifier: Any | None = None

    def refresh(self) -> SessionRuntimeSnapshot:
        self.snapshot = SessionRuntimeSnapshot.load(
            self.repositories, self.snapshot.session.session_id
        )
        self.refresh_restore_context()
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

    def build_restore_context(
        self,
        *,
        lane_id: str | None = None,
        task_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
        skill_registry: Any | None = None,
    ) -> Any:
        from .memory import MemoryService

        return MemoryService(self.repositories).build_restore_context(
            self.snapshot.session.session_id,
            lane_id=lane_id,
            task_id=task_id,
            skill_keys=skill_keys or self.active_skill_keys,
            skill_registry=skill_registry or self.skill_registry,
        )

    def set_focus(self, focus: RestoreFocus | None) -> RestoreFocus:
        if focus is None:
            focus = RestoreFocus()
        normalized = focus.normalized()
        self.restore_focus = normalized
        if normalized.skill_keys:
            self.add_skill_keys(normalized.skill_keys)
        return normalized

    def add_skill_keys(
        self, skill_keys: tuple[str, ...] | list[str]
    ) -> tuple[str, ...]:
        merged = tuple(dict.fromkeys((*self.active_skill_keys, *tuple(skill_keys))))
        self.active_skill_keys = merged
        return merged

    def refresh_restore_context(self) -> Any:
        self.restore_context = self.build_restore_context(
            lane_id=self.restore_focus.lane_id,
            task_id=self.restore_focus.task_id,
            skill_keys=self.active_skill_keys,
        )
        return self.restore_context


@dataclass(frozen=True, slots=True)
class HarnessResult:
    session_id: str
    status: HarnessStatus
    snapshot: SessionRuntimeSnapshot
    events: tuple[HarnessEvent, ...]
    outputs: tuple[str, ...]
    tool_results: tuple[ToolResult, ...]
    pending_approval_id: str | None = None


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
    content: str | None = None,
) -> InboxMessage:
    message_id = _new_id("msg")
    created_at = utc_now_iso()
    if content is not None and payload_ref is None:
        role = "assistant" if message_type == "assistant_message" else "user"
        payload_ref = persist_conversation_message(
            repositories,
            session_id=session_id,
            message_id=message_id,
            role=role,
            content=content,
            created_at=created_at,
        )
    message = InboxMessage(
        message_id=message_id,
        session_id=session_id,
        sender=sender,
        sender_kind=sender_kind,
        recipient=recipient,
        recipient_kind=recipient_kind,
        message_type=message_type,
        correlation_id=correlation_id,
        payload_ref=payload_ref,
        status=InboxStatus.DELIVERED,
        created_at=created_at,
    )
    repositories.inbox.save(message)
    return message


def _resolve_effective_lane_id(
    repositories: CoreRepositories,
    *,
    session_id: str,
    task_id: str | None,
    lane_id: str | None,
) -> str | None:
    if task_id is None:
        return lane_id
    task = repositories.tasks.get(task_id)
    if task is None:
        raise ValueError(f"task {task_id!r} does not exist")
    if task.session_id != session_id:
        raise ValueError(
            f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}"
        )
    if lane_id is not None and task.lane_id is not None and lane_id != task.lane_id:
        raise ValueError(
            f"task {task_id!r} is bound to lane {task.lane_id!r}, not {lane_id!r}"
        )
    return task.lane_id if lane_id is None else lane_id


def _resolve_resume(
    context: SessionRuntimeContext, resume: ResumeEnvelope
) -> ApprovalRequest:
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


def _resolve_default_focus(snapshot: SessionRuntimeSnapshot) -> RestoreFocus:
    if len(snapshot.ready_tasks) == 1:
        task = snapshot.ready_tasks[0]
        return RestoreFocus(task_id=task.task_id, lane_id=task.lane_id)
    in_progress = [
        task for task in snapshot.tasks if task.status is TaskStatus.IN_PROGRESS
    ]
    if len(in_progress) == 1:
        task = in_progress[0]
        return RestoreFocus(task_id=task.task_id, lane_id=task.lane_id)
    return RestoreFocus()


def _register_builtin_tools(
    registry: ToolRegistry, *, engine_registry: EngineRegistry | None = None
) -> None:
    from .artifact_boundary import register_artifact_boundary_tools
    from .artifact_tools import register_artifact_tools
    from .docs import register_docs_tools
    from .lane_manager import register_lane_tools
    from .memory import register_memory_tools
    from .protocol_tools import register_protocol_tools
    from .subagents import register_subagent_tools
    from .task_board import register_task_board_tools

    register_artifact_tools(registry)
    register_artifact_boundary_tools(registry)
    register_task_board_tools(registry)
    register_subagent_tools(registry)
    register_protocol_tools(registry)
    register_lane_tools(registry)
    register_memory_tools(registry)
    register_docs_tools(registry)
    if engine_registry is not None:
        for engine in engine_registry.list_engines():
            engine.register_tools(registry)


def _auto_compact_if_needed(
    context: SessionRuntimeContext,
    *,
    activity_happened: bool,
    outputs: list[str],
    all_tool_results: list[ToolResult],
) -> None:
    if not activity_happened:
        return
    from .memory import MemoryService

    context.refresh()
    service = MemoryService(
        context.repositories,
        event_emitter=lambda event_type, payload: context.emit(event_type, payload),
    )
    recent_output = outputs[-1] if outputs else None
    recent_tool = None if not all_tool_results else all_tool_results[-1]
    session_summary = service.render_compaction_summary(
        context.restore_context,
        recent_output=recent_output,
        recent_tool_result=recent_tool,
    )
    service.compact_scope(
        session_id=context.snapshot.session.session_id,
        scope_kind=MemoryScopeKind.SESSION,
        scope_ref=context.snapshot.session.session_id,
        summary=session_summary,
        source_range="auto:harness_run",
    )
    if context.restore_focus.lane_id is not None:
        lane_summary = service.render_compaction_summary(
            context.restore_context,
            recent_output=recent_output,
            recent_tool_result=recent_tool,
        )
        service.compact_scope(
            session_id=context.snapshot.session.session_id,
            scope_kind=MemoryScopeKind.LANE,
            scope_ref=context.restore_focus.lane_id,
            summary=lane_summary,
            source_range="auto:harness_run",
        )
    context.refresh()


def _pending_approval_id(snapshot: SessionRuntimeSnapshot) -> str | None:
    if not snapshot.pending_approvals:
        return None
    return snapshot.pending_approvals[0].approval_id


def _format_runtime_error(exc: Exception) -> str:
    message = str(exc).strip() or exc.__class__.__name__
    return f"OpenZyme could not complete this turn: {message}"


def _persist_llm_trace_step(
    context: SessionRuntimeContext, trace: LlmTraceStep
) -> dict[str, Any]:
    trace_id = _new_id("llmtrace")
    created_at = utc_now_iso()
    payload = trace.to_payload(trace_id=trace_id, created_at=created_at)
    context.repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=trace_id,
            session_id=context.snapshot.session.session_id,
            invocation_id=None,
            document_kind="llm_trace_step",
            payload=payload,
            created_at=created_at,
            updated_at=created_at,
        )
    )
    context.emit("llm.response.created", payload)
    return payload


def run_agent_harness_loop(
    repositories: CoreRepositories,
    harness_input: HarnessInput,
    *,
    driver: HarnessDriver,
    tool_registry: ToolRegistry | None = None,
    engine_registry: EngineRegistry | None = None,
    event_sink: EventSink | None = None,
    model_factory: Any | None = None,
    bio_research_service: Any | None = None,
    research_adapter: Any | None = None,
    signal_notifier: Any | None = None,
) -> HarnessResult:
    from .skills import SkillRegistry

    registry = tool_registry or ToolRegistry()
    _register_builtin_tools(registry, engine_registry=engine_registry)
    sink = event_sink or MemoryEventBus()
    snapshot = SessionRuntimeSnapshot.load(repositories, harness_input.session_id)
    resolved_focus = harness_input.restore_focus or _resolve_default_focus(snapshot)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=sink,
        snapshot=snapshot,
        tool_registry=registry,
        restore_focus=resolved_focus.normalized(),
        active_skill_keys=resolved_focus.normalized().skill_keys,
        skill_registry=SkillRegistry(),
        model_factory=model_factory,
        engine_registry=engine_registry,
        bio_research_service=bio_research_service,
        research_adapter=research_adapter,
        signal_notifier=signal_notifier,
    )
    outputs: list[str] = []
    all_tool_results: list[ToolResult] = []
    activity_happened = False

    if harness_input.message is not None:
        message = _persist_message(
            repositories,
            session_id=harness_input.session_id,
            sender=harness_input.sender,
            sender_kind=harness_input.sender_kind,
            recipient="harness",
            recipient_kind=InboxParticipantKind.HARNESS,
            message_type="user_message",
            content=harness_input.message
            if harness_input.persist_conversation
            else None,
        )
        context.emit(
            "message.received",
            {
                "message_id": message.message_id,
                "sender": message.sender,
                "sender_kind": message.sender_kind.value,
            },
        )
        activity_happened = True

    if harness_input.resume is not None and not harness_input.skip_resume_resolution:
        resolved_approval = _resolve_resume(context, harness_input.resume)
        activity_happened = True
        del resolved_approval

    context.refresh()
    tool_results: tuple[ToolResult, ...] = ()
    last_status = HarnessStatus.COMPLETED
    pending_approval_id: str | None = None

    for _ in range(harness_input.max_steps):
        try:
            step = driver.plan(context, harness_input, tool_results)
        except Exception as exc:
            outputs.append(_format_runtime_error(exc))
            context.emit(
                "harness.failed",
                {"error": str(exc), "error_type": exc.__class__.__name__},
            )
            _auto_compact_if_needed(
                context,
                activity_happened=True,
                outputs=outputs,
                all_tool_results=all_tool_results,
            )
            context.refresh()
            return HarnessResult(
                session_id=harness_input.session_id,
                status=HarnessStatus.FAILED,
                snapshot=context.snapshot,
                events=tuple(sink.events),
                outputs=tuple(outputs),
                tool_results=tuple(all_tool_results),
                pending_approval_id=pending_approval_id,
            )
        tool_results = ()
        if step.next_focus is not None:
            context.set_focus(step.next_focus)

        if step.llm_trace is not None:
            _persist_llm_trace_step(context, step.llm_trace)
            activity_happened = True

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
            activity_happened = True

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
            if memory.kind is MemoryKind.COMPACTION:
                context.emit(
                    "memory.compacted",
                    {
                        "memory_id": memory.memory_id,
                        "scope_kind": memory.scope_kind.value,
                        "scope_ref": memory.scope_ref,
                    },
                )
            activity_happened = True

        for invocation in step.engine_invocations:
            invocation = replace(
                invocation,
                lane_id=_resolve_effective_lane_id(
                    repositories,
                    session_id=harness_input.session_id,
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                ),
            )
            repositories.invocations.save(invocation)
            context.emit(
                "engine.invocation.updated",
                {
                    "invocation_id": invocation.invocation_id,
                    "engine_name": invocation.engine_name,
                    "status": invocation.status.value,
                },
            )
            activity_happened = True

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
            activity_happened = True

        if step.assistant_message is not None:
            message = _persist_message(
                repositories,
                session_id=harness_input.session_id,
                sender="harness",
                sender_kind=InboxParticipantKind.HARNESS,
                recipient=harness_input.sender,
                recipient_kind=harness_input.sender_kind,
                message_type="assistant_message",
                content=step.assistant_message
                if harness_input.persist_conversation
                else None,
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
            activity_happened = True

        for approval in step.approval_requests:
            approval = replace(
                approval,
                lane_id=_resolve_effective_lane_id(
                    repositories,
                    session_id=harness_input.session_id,
                    task_id=approval.task_id,
                    lane_id=approval.lane_id,
                ),
            )
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
            activity_happened = True

        if step.approval_requests:
            last_status = HarnessStatus.WAITING_APPROVAL
            _auto_compact_if_needed(
                context,
                activity_happened=activity_happened,
                outputs=outputs,
                all_tool_results=all_tool_results,
            )
            context.refresh()
            return HarnessResult(
                session_id=harness_input.session_id,
                status=last_status,
                snapshot=context.snapshot,
                events=tuple(sink.events),
                outputs=tuple(outputs),
                tool_results=tuple(all_tool_results),
                pending_approval_id=pending_approval_id,
            )

        if step.tool_invocations:
            current_results: list[ToolResult] = []
            for invocation in step.tool_invocations:
                invocation = replace(
                    invocation,
                    lane_id=_resolve_effective_lane_id(
                        repositories,
                        session_id=harness_input.session_id,
                        task_id=invocation.task_id,
                        lane_id=invocation.lane_id,
                    ),
                )
                context.emit(
                    "tool.invoked",
                    {
                        "call_id": invocation.call_id,
                        "tool_name": invocation.tool_name,
                        "task_id": invocation.task_id,
                        "lane_id": invocation.lane_id,
                    },
                )
                try:
                    result = registry.dispatch(context, invocation)
                except Exception as exc:
                    outputs.append(_format_runtime_error(exc))
                    context.emit(
                        "harness.failed",
                        {
                            "error": str(exc),
                            "error_type": exc.__class__.__name__,
                            "tool_name": invocation.tool_name,
                            "call_id": invocation.call_id,
                        },
                    )
                    _auto_compact_if_needed(
                        context,
                        activity_happened=True,
                        outputs=outputs,
                        all_tool_results=all_tool_results,
                    )
                    context.refresh()
                    return HarnessResult(
                        session_id=harness_input.session_id,
                        status=HarnessStatus.FAILED,
                        snapshot=context.snapshot,
                        events=tuple(sink.events),
                        outputs=tuple(outputs),
                        tool_results=tuple(all_tool_results),
                        pending_approval_id=pending_approval_id,
                    )
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
                activity_happened = True
                context.refresh()
                pending_approval_id = _pending_approval_id(context.snapshot)
                if pending_approval_id is not None:
                    _auto_compact_if_needed(
                        context,
                        activity_happened=activity_happened,
                        outputs=outputs,
                        all_tool_results=all_tool_results,
                    )
                    context.refresh()
                    return HarnessResult(
                        session_id=harness_input.session_id,
                        status=HarnessStatus.WAITING_APPROVAL,
                        snapshot=context.snapshot,
                        events=tuple(sink.events),
                        outputs=tuple(outputs),
                        tool_results=tuple(all_tool_results),
                        pending_approval_id=pending_approval_id,
                    )
            tool_results = tuple(current_results)
            context.refresh()
            continue

        _auto_compact_if_needed(
            context,
            activity_happened=activity_happened,
            outputs=outputs,
            all_tool_results=all_tool_results,
        )
        context.refresh()
        pending_approval_id = _pending_approval_id(context.snapshot)
        if pending_approval_id is not None:
            return HarnessResult(
                session_id=harness_input.session_id,
                status=HarnessStatus.WAITING_APPROVAL,
                snapshot=context.snapshot,
                events=tuple(sink.events),
                outputs=tuple(outputs),
                tool_results=tuple(all_tool_results),
                pending_approval_id=pending_approval_id,
            )
        if (
            harness_input.resume is not None
            and last_status is HarnessStatus.COMPLETED
            and (
                not outputs
                or outputs == ["No user-facing response was generated."]
            )
        ):
            if outputs == ["No user-facing response was generated."]:
                outputs.clear()
        return HarnessResult(
            session_id=harness_input.session_id,
            status=last_status,
            snapshot=context.snapshot,
            events=tuple(sink.events),
            outputs=tuple(outputs),
            tool_results=tuple(all_tool_results),
            pending_approval_id=pending_approval_id,
        )

    context.emit(
        "harness.max_steps_exceeded",
        {"max_steps": harness_input.max_steps},
    )
    _auto_compact_if_needed(
        context,
        activity_happened=True,
        outputs=outputs,
        all_tool_results=all_tool_results,
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
    )
