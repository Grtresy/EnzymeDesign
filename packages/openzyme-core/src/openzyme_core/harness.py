from __future__ import annotations

from contextlib import contextmanager
from contextlib import nullcontext
from dataclasses import asdict
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from typing import Any
from typing import Callable
from typing import Iterator
from typing import Protocol
from uuid import uuid4

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import EngineInvocation
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureRecoverability
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import MutationWriterKind
from openzyme_domain import RetryEligibility
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionRuntimeLease
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import AgentStepContext
from openzyme_runtime import LegacyFunctionToolRuntime
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult
from openzyme_runtime import ToolRouter
from openzyme_runtime import ToolRuntime
from openzyme_runtime import ToolSpec
from openzyme_runtime import sanitize_tool_result_diagnostics
from openzyme_runtime import sanitize_public_diagnostic_text
from openzyme_runtime import record_failure_observation

from .engines import EngineRegistry
from .mutation_authority import current_mutation_write_authority
from .mutation_quiescence import MutationScopeService
from .repositories import EngineDocumentRecord
from .repositories import CoreRepositories
from .repositories import TaskWriteIntent
from .sandbox_host import SandboxHostBinding
from .sandbox_host import SandboxMutationWriterScopeFactory
from .scientific_workflow_contracts import ScientificWorkflowContractRegistry
from .conversation import persist_conversation_message
from .prompt_budget import PromptBudgetAction
from .prompt_budget import PromptBudgetDecision
from .prompt_budget import estimate_and_decide_prompt_budget
from .prompt_budget import prompt_budget_config_from_env
from .trace_projection import project_public_llm_trace_step


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


class ContextBudgetExceededError(RuntimeError):
    """Raised before a provider call when the prompt cannot fit the budget."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        super().__init__(json.dumps(payload, sort_keys=True))


@dataclass(frozen=True, slots=True)
class PromptPayload:
    system_prompt: str
    messages: list[Any]
    tools: list[Any]


@dataclass(frozen=True, slots=True)
class PromptBudgetPreflightResult:
    payload: PromptPayload
    initial_decision: PromptBudgetDecision
    final_decision: PromptBudgetDecision
    compacted: bool = False


def _message_role(message: Any) -> str:
    if isinstance(message, dict):
        return str(message.get("role") or "message")
    role = message.__class__.__name__.removesuffix("Message").lower()
    return role or "message"


def _message_content(message: Any) -> str:
    value = (
        message.get("content")
        if isinstance(message, dict)
        else getattr(message, "content", "")
    )
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=True, sort_keys=True, default=str)


def _is_user_message(message: Any) -> bool:
    if isinstance(message, dict):
        return str(message.get("role") or "").lower() in {"user", "human"}
    role = message.__class__.__name__.lower()
    return "human" in role or role.startswith("user")


def _bounded_compacted_current_turn_messages(messages: list[Any]) -> list[Any]:
    snippets: list[str] = []
    for message in messages[-3:]:
        content = _message_content(message).strip()
        if not content:
            continue
        if len(content) > 1200:
            content = content[:1200] + "\n[truncated by prompt budget compaction]"
        snippets.append(f"{_message_role(message)}: {content}")
    if not snippets:
        content = (
            "Continue from the restore context and session state. "
            "No user transcript message is available in this compacted provider payload."
        )
    else:
        content = (
            "The immediately preceding turn was compacted before the model call. "
            "Use the restore context for durable state, and use this bounded current-turn summary without assuming omitted text was read in full.\n"
            + "\n\n".join(snippets)
        )
    try:
        from langchain_core.messages import HumanMessage
    except ImportError:
        return [{"role": "user", "content": content}]
    return [HumanMessage(content=content)]


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
    failure_observations: tuple[Any, ...]

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
            failure_observations=tuple(
                repositories.failure_observations.list_by_session(session_id)
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
    agent_id: str | None = None
    actor_kind: str | None = None
    actor_role: str | None = None
    correlation_id: str | None = None
    signal_id: str | None = None
    wakeup_reason: str | None = None
    wake_instructions: str | None = None


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
    step_context: AgentStepContext | None = None

    def to_payload(self, *, trace_id: str, created_at: str) -> dict[str, Any]:
        payload: dict[str, Any] = {
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
        if self.step_context is not None:
            payload["agent_step"] = self.step_context.to_dict()
        return project_public_llm_trace_step(payload)


@dataclass(frozen=True, slots=True)
class HarnessStep:
    assistant_message: str | None = None
    tool_invocations: tuple[ToolInvocation, ...] = ()
    tool_rejections: tuple[ToolResult, ...] = ()
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
ToolDispatchPrecondition = Callable[
    ["SessionRuntimeContext", AgentStepContext, ToolInvocation],
    ToolResult | None,
]


@dataclass(slots=True)
class ToolRegistry:
    _handlers: dict[str, ToolHandler]
    _runtimes: dict[str, ToolRuntime]

    def __init__(self) -> None:
        self._handlers = {}
        self._runtimes = {}

    def register(self, tool_name: str, handler: ToolHandler) -> None:
        self._handlers[tool_name] = handler

    def register_runtime(
        self,
        runtime_or_tool_name: ToolRuntime | str,
        runtime: ToolRuntime | None = None,
    ) -> None:
        if runtime is None:
            runtime = runtime_or_tool_name  # type: ignore[assignment]
            tool_name = getattr(runtime, "tool_name", None)
            if not isinstance(tool_name, str) or not tool_name:
                raise ValueError(
                    "register_runtime(runtime) requires runtime.tool_name to be a non-empty string."
                )
        else:
            tool_name = str(runtime_or_tool_name)
        self._runtimes[tool_name] = runtime

    def to_tool_router(
        self,
        context: "SessionRuntimeContext",
        *,
        descriptors: tuple[Any, ...] = (),
    ) -> ToolRouter:
        specs: dict[str, ToolSpec] = {}
        for descriptor in descriptors:
            if not hasattr(descriptor, "tool_name") or not hasattr(
                descriptor, "to_tool_spec"
            ):
                continue
            tool_name = str(descriptor.tool_name)
            if tool_name not in specs:
                specs[tool_name] = descriptor.to_tool_spec()
        runtimes: dict[str, ToolRuntime] = dict(self._runtimes)
        for tool_name, spec in specs.items():
            if tool_name in runtimes or tool_name not in self._handlers:
                continue
            runtimes[tool_name] = LegacyFunctionToolRuntime(
                tool_name=tool_name,
                handler=self._handlers[tool_name],
                tool_spec=spec,
            )
        return ToolRouter(runtimes=runtimes, dispatch_context=context)

    def dispatch(
        self, context: "SessionRuntimeContext", invocation: ToolInvocation
    ) -> ToolResult:
        handler = self._handlers.get(invocation.tool_name)
        if handler is None:
            return self._attach_legacy_failure(
                context,
                invocation,
                ToolResult(
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
                ),
                failure_class=FailureClass.VALIDATION,
                recoverability=FailureRecoverability.AGENT_CAN_RETRY,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
            )
        try:
            result = handler(context, invocation)
        except Exception as exc:
            validation = isinstance(exc, (KeyError, TypeError, ValueError))
            safe_error = sanitize_public_diagnostic_text(str(exc)).strip()
            message = (
                f"Tool {invocation.tool_name} failed: "
                f"{safe_error or exc.__class__.__name__}"
            )
            return self._attach_legacy_failure(
                context,
                invocation,
                ToolResult(
                    call_id=invocation.call_id,
                    tool_name=invocation.tool_name,
                    ok=False,
                    content=message,
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                    status=(
                        "invalid_tool_arguments" if validation else "tool_runtime_error"
                    ),
                    summary=message,
                    error_code=(
                        "invalid_tool_arguments" if validation else "tool_runtime_error"
                    ),
                    hint=(
                        "Fix the tool arguments or referenced task/lane/session state before retrying."
                        if validation
                        else (
                            "Inspect the structured failure, then repair, replan, "
                            "request help, or explicitly block the task."
                        )
                    ),
                    details={
                        "exception_type": exc.__class__.__name__,
                        "public_error": safe_error,
                    },
                ),
                failure_class=(
                    FailureClass.VALIDATION if validation else FailureClass.TOOL
                ),
                recoverability=(
                    FailureRecoverability.AGENT_CAN_RETRY
                    if validation
                    else FailureRecoverability.AGENT_CAN_REPLAN
                ),
                effect_certainty=(
                    ExternalEffectCertainty.NO_EFFECT
                    if validation
                    else ExternalEffectCertainty.TERMINAL_KNOWN
                ),
                retry_eligibility=(
                    RetryEligibility.SAME_PHASE_SAFE
                    if validation
                    else RetryEligibility.TERMINAL
                ),
                private_diagnostic=exc,
            )
        if isinstance(result, ToolResult):
            if not result.ok and result.failure_observation is None:
                return self._attach_legacy_failure(
                    context,
                    invocation,
                    result,
                    failure_class=FailureClass.TOOL,
                    recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                    retry_eligibility=RetryEligibility.TERMINAL,
                )
            return sanitize_tool_result_diagnostics(result)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=result,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="ok",
            summary=result,
        )

    @staticmethod
    def _attach_legacy_failure(
        context: "SessionRuntimeContext",
        invocation: ToolInvocation,
        result: ToolResult,
        *,
        failure_class: FailureClass,
        recoverability: FailureRecoverability,
        effect_certainty: ExternalEffectCertainty,
        retry_eligibility: RetryEligibility,
        private_diagnostic: object | None = None,
    ) -> ToolResult:
        step_context = context.current_step_context
        observation = record_failure_observation(
            context.repositories,
            session_id=context.snapshot.session.session_id,
            task_id=invocation.task_id
            or (None if step_context is None else step_context.task_id),
            lane_id=invocation.lane_id
            or (None if step_context is None else step_context.lane_id),
            agent_id=context.agent_id,
            source_kind="tool_invocation",
            source_ref=invocation.call_id,
            source_version=(
                invocation.call_id if step_context is None else step_context.step_id
            ),
            phase=(
                "validation" if failure_class is FailureClass.VALIDATION else "dispatch"
            ),
            failure_class=failure_class,
            recoverability=recoverability,
            effect_certainty=effect_certainty,
            retry_eligibility=retry_eligibility,
            actor_kind=FailureActorKind.HARNESS,
            error_code=result.error_code or result.status or "tool_error",
            safe_summary=result.summary or result.content,
            safe_hint=result.hint,
            facts={
                **(result.details or {}),
                "tool_name": invocation.tool_name,
                "legacy_dispatch": True,
            },
            private_diagnostic=private_diagnostic,
        )
        return sanitize_tool_result_diagnostics(
            replace(result, failure_observation=observation.to_dict())
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
    scientific_workflow_contract_registry: ScientificWorkflowContractRegistry | None = (
        None
    )
    sandbox_workspace_root: Path | None = None
    artifact_blob_root: Path | None = None
    signal_notifier: Any | None = None
    reliability_shadow_observer: Any | None = None
    reliability_settings: Any | None = None
    durable_route_adapter_policy_ids: dict[str, str] = field(default_factory=dict)
    tool_dispatch_precondition: ToolDispatchPrecondition | None = None
    assistant_response_recipient: str = "user"
    assistant_response_recipient_kind: InboxParticipantKind = InboxParticipantKind.USER
    persist_conversation: bool = True
    mutation_writer_scope_factory: SandboxMutationWriterScopeFactory | None = None
    sandbox_host_binding_factory: (
        Callable[
            [EngineRegistry, SessionRuntimeLease | None],
            SandboxHostBinding,
        ]
        | None
    ) = None
    session_runtime_lease: SessionRuntimeLease | None = None
    agent_id: str | None = None
    actor_kind: str | None = None
    actor_role: str | None = None
    correlation_id: str | None = None
    signal_id: str | None = None
    wakeup_reason: str | None = None
    current_step_context: AgentStepContext | None = None
    current_tool_router: ToolRouter | None = None

    def persist_outbound_assistant_message(
        self,
        *,
        content: str,
        message_id: str | None = None,
        document_id: str | None = None,
        created_at: str | None = None,
    ) -> InboxMessage:
        return _persist_outbound_assistant_message(
            self,
            content,
            message_id=message_id,
            document_id=document_id,
            created_at=created_at,
        )

    @contextmanager
    def mutation_writer_scope(
        self,
        *,
        owner_kind: MutationWriterKind,
        owner_ref: str,
        process_epoch: int | None = None,
    ) -> Iterator[object | None]:
        session_id = self.snapshot.session.session_id
        parent_authority = current_mutation_write_authority()
        if parent_authority is not None:
            scope = MutationScopeService(self.repositories).writer_turn(
                session_id=session_id,
                owner_kind=owner_kind,
                owner_ref=owner_ref,
                process_epoch=process_epoch,
            )
        elif (
            self.repositories.in_managed_transaction
            and not self.repositories.mutation_scopes.list_by_session(session_id)
        ):
            # The owning BEGIN IMMEDIATE establishes a stable no-scope snapshot.
            # Opening the external factory here would ask a second SQLite
            # connection to acquire the write lock already held by this one.
            scope = nullcontext(None)
        elif self.mutation_writer_scope_factory is None:
            scope = nullcontext(None)
        else:
            scope = self.mutation_writer_scope_factory(
                session_id=session_id,
                owner_kind=owner_kind,
                owner_ref=owner_ref,
                process_epoch=process_epoch,
            )
        with scope as writer_authority:
            authority = current_mutation_write_authority()
            if authority is None:
                yield writer_authority
                return
            with self.repositories.mutation_write_authority(authority):
                yield writer_authority

    def tool_mutation_writer_scope(
        self,
        *,
        tool_name: str,
        call_id: str,
    ) -> Any:
        artifact_publishing_tools = {
            "interpro.query",
            "pubmed.search",
            "rcsb_pdb.download_structure",
            "rcsb_pdb.search",
            "semantic_scholar.search",
            "uniprot.download_fasta",
            "uniprot.lookup",
            "web.fetch",
            "web.search",
        }
        if (
            tool_name.startswith(("artifact.", "artifacts.", "deep_research."))
            or tool_name in artifact_publishing_tools
        ):
            owner_kind = MutationWriterKind.ARTIFACT_PUBLISHER
        elif tool_name == "report.publish" or tool_name.startswith("report_draft."):
            owner_kind = MutationWriterKind.REPORT_PUBLISHER
        else:
            return nullcontext(None)
        call_digest = hashlib.sha256(call_id.encode("utf-8")).hexdigest()[:16]
        return self.mutation_writer_scope(
            owner_kind=owner_kind,
            owner_ref=f"tool:{tool_name}:{call_digest}",
        )

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
        with self.mutation_writer_scope(
            owner_kind=MutationWriterKind.EVENT_OUTBOX_PUBLISHER,
            owner_ref=f"event:{event.event_id}",
        ):
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


def _exact_pending_approval_for_suspension(
    context: SessionRuntimeContext,
    result: ToolResult,
) -> ApprovalRequest | None:
    approval_id = str((result.details or {}).get("approval_id") or "").strip()
    if not approval_id or not result.task_id:
        return None
    approval = context.repositories.approvals.get(approval_id)
    if (
        approval is None
        or approval.status is not ApprovalRequestStatus.PENDING
        or approval.session_id != context.snapshot.session.session_id
        or approval.task_id != result.task_id
        or (result.lane_id is not None and approval.lane_id != result.lane_id)
    ):
        return None
    return approval


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _sha256_digest(payload: Any) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        default=str,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()[:16]}"


def _restore_context_public_payload(context: SessionRuntimeContext) -> dict[str, Any]:
    snapshot = context.snapshot
    return {
        "session": {
            "session_id": snapshot.session.session_id,
            "status": _enum_value(snapshot.session.status),
            "updated_at": snapshot.session.updated_at,
        },
        "focus": {
            "task_id": context.restore_focus.task_id,
            "lane_id": context.restore_focus.lane_id,
            "skill_keys": list(context.restore_focus.skill_keys),
        },
        "tasks": [
            {
                "task_id": task.task_id,
                "status": _enum_value(task.status),
                "kind": task.kind,
                "assigned_ref": task.assigned_ref,
                "lane_id": task.lane_id,
                "updated_at": task.updated_at,
            }
            for task in sorted(snapshot.tasks, key=lambda item: item.task_id)
        ],
        "ready_task_ids": sorted(task.task_id for task in snapshot.ready_tasks),
        "lanes": [
            {
                "lane_id": lane.lane_id,
                "status": _enum_value(lane.status),
                "claimed_ref": lane.claimed_ref,
                "updated_at": lane.updated_at,
            }
            for lane in sorted(snapshot.lanes, key=lambda item: item.lane_id)
        ],
        "pending_approvals": [
            {
                "approval_id": approval.approval_id,
                "task_id": approval.task_id,
                "lane_id": approval.lane_id,
                "kind": approval.kind,
                "status": _enum_value(approval.status),
            }
            for approval in sorted(
                snapshot.pending_approvals, key=lambda item: item.approval_id
            )
        ],
        "inbox": [
            {
                "message_id": message.message_id,
                "message_type": message.message_type,
                "sender_kind": _enum_value(message.sender_kind),
                "recipient_kind": _enum_value(message.recipient_kind),
                "correlation_id": message.correlation_id,
                "status": _enum_value(message.status),
            }
            for message in sorted(snapshot.inbox, key=lambda item: item.message_id)
        ],
        "memory": [
            {
                "memory_id": memory.memory_id,
                "scope_kind": _enum_value(memory.scope_kind),
                "scope_ref": memory.scope_ref,
                "kind": _enum_value(memory.kind),
                "importance": memory.importance,
            }
            for memory in sorted(snapshot.memory, key=lambda item: item.memory_id)
        ],
        "agents": [
            {
                "agent_id": agent.agent_id,
                "role": agent.role,
                "status": _enum_value(agent.status),
                "task_id": agent.task_id,
                "lane_id": agent.lane_id,
                "current_correlation_id": agent.current_correlation_id,
                "wakeup_reason": agent.wakeup_reason,
                "updated_at": agent.updated_at,
            }
            for agent in sorted(snapshot.agents, key=lambda item: item.agent_id)
        ],
        "active_invocations": [
            {
                "invocation_id": invocation.invocation_id,
                "engine_name": invocation.engine_name,
                "status": _enum_value(invocation.status),
                "task_id": invocation.task_id,
                "lane_id": invocation.lane_id,
                "approval_id": invocation.approval_id,
            }
            for invocation in sorted(
                snapshot.active_invocations, key=lambda item: item.invocation_id
            )
        ],
        "failure_observations": [
            {
                "failure_id": observation.failure_id,
                "source_kind": observation.source_kind,
                "source_ref": observation.source_ref,
                "source_version": observation.source_version,
                "error_code": observation.error_code,
                "recoverability": observation.recoverability.value,
                "effect_certainty": observation.effect_certainty.value,
                "retry_eligibility": observation.retry_eligibility.value,
            }
            for observation in sorted(
                snapshot.failure_observations,
                key=lambda item: (item.created_at, item.failure_id),
            )
        ],
    }


def restore_context_digest(context: SessionRuntimeContext) -> str:
    return _sha256_digest(_restore_context_public_payload(context))


def tool_catalog_digest(tool_specs: tuple[ToolSpec, ...]) -> str:
    return _sha256_digest(
        [
            {
                "tool_name": spec.tool_name,
                "description": spec.description,
                "input_schema": spec.input_schema,
            }
            for spec in sorted(tool_specs, key=lambda item: item.tool_name)
        ]
    )


def build_agent_step_context(
    context: SessionRuntimeContext,
    *,
    call_index: int,
    tool_specs: tuple[ToolSpec, ...] = (),
) -> AgentStepContext:
    agent_id = context.agent_id or "harness"
    actor_kind = context.actor_kind or (
        "master" if agent_id in {"harness", "agent:master"} else "teammate"
    )
    role = context.actor_role or ("master" if actor_kind == "master" else actor_kind)
    return AgentStepContext(
        step_id=_new_id("agentstep"),
        session_id=context.snapshot.session.session_id,
        agent_id=agent_id,
        actor_kind=actor_kind,
        role=role,
        call_index=call_index,
        task_id=context.restore_focus.task_id,
        lane_id=context.restore_focus.lane_id,
        correlation_id=context.correlation_id,
        signal_id=context.signal_id,
        wakeup_reason=context.wakeup_reason,
        restore_context_digest=restore_context_digest(context),
        tool_catalog_digest=tool_catalog_digest(tool_specs),
        created_at=utc_now_iso(),
    )


@dataclass(frozen=True, slots=True)
class HarnessResult:
    session_id: str
    status: HarnessStatus
    snapshot: SessionRuntimeSnapshot
    events: tuple[HarnessEvent, ...]
    outputs: tuple[str, ...]
    tool_results: tuple[ToolResult, ...]
    pending_approval_id: str | None = None
    error: BaseException | None = None


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
    message_id: str | None = None,
    document_id: str | None = None,
    created_at: str | None = None,
) -> InboxMessage:
    resolved_message_id = message_id or _new_id("msg")
    resolved_created_at = created_at or utc_now_iso()
    if content is not None and payload_ref is None:
        role = "assistant" if message_type == "assistant_message" else "user"
        payload_ref = persist_conversation_message(
            repositories,
            session_id=session_id,
            message_id=resolved_message_id,
            role=role,
            content=content,
            created_at=resolved_created_at,
            document_id=document_id,
        )
    message = InboxMessage(
        message_id=resolved_message_id,
        session_id=session_id,
        sender=sender,
        sender_kind=sender_kind,
        recipient=recipient,
        recipient_kind=recipient_kind,
        message_type=message_type,
        correlation_id=correlation_id,
        payload_ref=payload_ref,
        status=InboxStatus.DELIVERED,
        created_at=resolved_created_at,
    )
    repositories.inbox.save(message)
    return message


def _persist_outbound_assistant_message(
    context: SessionRuntimeContext,
    content: str,
    *,
    message_id: str | None = None,
    document_id: str | None = None,
    created_at: str | None = None,
) -> InboxMessage:
    message = _persist_message(
        context.repositories,
        session_id=context.snapshot.session.session_id,
        sender="harness",
        sender_kind=InboxParticipantKind.HARNESS,
        recipient=context.assistant_response_recipient,
        recipient_kind=context.assistant_response_recipient_kind,
        message_type="assistant_message",
        content=content if context.persist_conversation else None,
        message_id=message_id,
        document_id=document_id,
        created_at=created_at,
    )
    context.emit(
        "message.sent",
        {
            "message_id": message.message_id,
            "recipient": message.recipient,
            "recipient_kind": message.recipient_kind.value,
        },
    )
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
    from .failure_tools import register_failure_tools
    from .lane_manager import register_lane_tools
    from .memory import register_memory_tools
    from .protocol_tools import register_protocol_tools
    from .scientific_attempt_tools import register_scientific_attempt_tools
    from .subagents import register_subagent_tools
    from .task_board import register_task_board_tools
    from .world_inspection import register_world_inspection_tools

    register_artifact_tools(registry)
    register_artifact_boundary_tools(registry)
    register_task_board_tools(registry)
    register_failure_tools(registry)
    register_subagent_tools(registry)
    register_protocol_tools(registry)
    register_scientific_attempt_tools(registry)
    register_lane_tools(registry)
    register_memory_tools(registry)
    register_docs_tools(registry)
    register_world_inspection_tools(registry)
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
    session_restore = service.build_restore_context(
        context.snapshot.session.session_id,
        skill_keys=(),
        skill_registry=context.skill_registry,
    )
    session_summary = service.render_compaction_summary(
        session_restore,
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
        lane_restore = service.build_restore_context(
            context.snapshot.session.session_id,
            lane_id=context.restore_focus.lane_id,
            skill_keys=(),
            skill_registry=context.skill_registry,
        )
        lane_summary = service.render_compaction_summary(
            lane_restore,
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


def _bounded_tool_result_summary(result: ToolResult) -> str:
    summary = result.summary or result.status or ("ok" if result.ok else "failed")
    if len(summary) > 800:
        summary = summary[:800] + "... [truncated]"
    return summary


def _decision_payload(decision: Any) -> dict[str, Any]:
    return {
        "action": decision.action.value,
        "prompt_tokens": decision.prompt_tokens,
        "reserved_output_tokens": decision.reserved_output_tokens,
        "safety_margin_tokens": decision.safety_margin_tokens,
        "total_budgeted_tokens": decision.total_budgeted_tokens,
        "context_window_tokens": decision.context_window_tokens,
        "ratio": round(decision.ratio, 6),
        "model": decision.profile.model,
        "profile_known": decision.profile.profile_known,
        "tokenizer_calibrated": decision.tokenizer_calibrated,
        "tokenizer_available": decision.tokenizer_available,
        "tokenizer_error": decision.tokenizer_error,
        "breakdown": dict(decision.breakdown),
    }


def _provider_tokenizer_result(
    model_factory: Any | None,
    *,
    system_prompt: str,
    messages: list[Any],
    tools: list[Any],
) -> dict[str, Any] | None:
    if model_factory is None or not hasattr(model_factory, "count_prompt_tokens"):
        return None
    try:
        result = model_factory.count_prompt_tokens(
            system_prompt=system_prompt,
            messages=messages,
            tools=tools,
        )
    except Exception as exc:
        return {
            "available": False,
            "error": sanitize_public_diagnostic_text(str(exc))
            or exc.__class__.__name__,
        }
    if not isinstance(result, dict):
        return None
    public_result = dict(result)
    if public_result.get("error") is not None:
        public_result["error"] = sanitize_public_diagnostic_text(public_result["error"])
    return public_result


def _compact_before_model_call(
    context: SessionRuntimeContext,
    *,
    actor_ref: str,
    decision_payload: dict[str, Any],
    recent_tool_result: ToolResult | None = None,
) -> None:
    from .memory import MemoryService

    context.refresh()
    service = MemoryService(
        context.repositories,
        event_emitter=lambda event_type, payload: context.emit(event_type, payload),
    )

    def render_summary(*, lane_id: str | None) -> str:
        restore = service.build_restore_context(
            context.snapshot.session.session_id,
            lane_id=lane_id,
            skill_keys=(),
            skill_registry=context.skill_registry,
        )
        summary = service.render_compaction_summary(
            restore,
            recent_tool_result=None,
        )
        if recent_tool_result is not None:
            summary += (
                "\nRecent tool activity bounded: "
                f"{recent_tool_result.tool_name} "
                f"call_id={recent_tool_result.call_id} "
                f"ok={recent_tool_result.ok} "
                f"status={recent_tool_result.status or 'unknown'} "
                f"summary={_bounded_tool_result_summary(recent_tool_result)}"
            )
        summary += (
            "\nContext budget action: auto_compact before model call; "
            f"actor_ref={actor_ref}; "
            f"prompt_tokens={decision_payload.get('prompt_tokens')}; "
            f"ratio={decision_payload.get('ratio')}"
        )
        return summary

    session_summary = render_summary(lane_id=None)
    service.compact_scope(
        session_id=context.snapshot.session.session_id,
        scope_kind=MemoryScopeKind.SESSION,
        scope_ref=context.snapshot.session.session_id,
        summary=session_summary,
        source_range="auto:prompt_budget",
    )
    if context.restore_focus.lane_id is not None:
        lane_summary = render_summary(lane_id=context.restore_focus.lane_id)
        service.compact_scope(
            session_id=context.snapshot.session.session_id,
            scope_kind=MemoryScopeKind.LANE,
            scope_ref=context.restore_focus.lane_id,
            summary=lane_summary,
            source_range="auto:prompt_budget",
        )
    context.refresh()


def ensure_prompt_budget_before_model_call(
    context: SessionRuntimeContext,
    *,
    actor_ref: str,
    system_prompt: str,
    messages: list[Any],
    tools: list[Any],
    recent_tool_result: ToolResult | None = None,
    rebuild_payload: Callable[[], PromptPayload] | None = None,
) -> PromptBudgetPreflightResult:
    prompt_payload = PromptPayload(
        system_prompt=system_prompt,
        messages=list(messages),
        tools=list(tools),
    )
    if not any(_is_user_message(message) for message in prompt_payload.messages):
        prompt_payload = PromptPayload(
            system_prompt=prompt_payload.system_prompt,
            messages=[
                *_bounded_compacted_current_turn_messages(prompt_payload.messages),
                *prompt_payload.messages,
            ],
            tools=prompt_payload.tools,
        )
    tokenizer_result = _provider_tokenizer_result(
        context.model_factory,
        system_prompt=prompt_payload.system_prompt,
        messages=prompt_payload.messages,
        tools=prompt_payload.tools,
    )
    decision = estimate_and_decide_prompt_budget(
        system_prompt=prompt_payload.system_prompt,
        messages=prompt_payload.messages,
        tools=prompt_payload.tools,
        model_factory=context.model_factory,
        tokenizer_result=tokenizer_result,
    )
    initial_decision = decision
    compacted = False
    payload = _decision_payload(decision)
    if decision.should_warn:
        context.emit("llm.context_budget.warning", {"actor_ref": actor_ref, **payload})
    if decision.action in {
        PromptBudgetAction.AUTO_COMPACT,
        PromptBudgetAction.EMERGENCY,
    }:
        compacted = True
        _compact_before_model_call(
            context,
            actor_ref=actor_ref,
            decision_payload=payload,
            recent_tool_result=recent_tool_result,
        )
        if rebuild_payload is not None:
            prompt_payload = rebuild_payload()
        if not any(_is_user_message(message) for message in prompt_payload.messages):
            prompt_payload = PromptPayload(
                system_prompt=prompt_payload.system_prompt,
                messages=[
                    *_bounded_compacted_current_turn_messages(messages),
                    *prompt_payload.messages,
                ],
                tools=prompt_payload.tools,
            )
        tokenizer_result = _provider_tokenizer_result(
            context.model_factory,
            system_prompt=prompt_payload.system_prompt,
            messages=prompt_payload.messages,
            tools=prompt_payload.tools,
        )
        decision = estimate_and_decide_prompt_budget(
            system_prompt=prompt_payload.system_prompt,
            messages=prompt_payload.messages,
            tools=prompt_payload.tools,
            model_factory=context.model_factory,
            tokenizer_result=tokenizer_result,
        )
        payload = _decision_payload(decision)
        context.emit(
            "llm.context_budget.after_compaction",
            {"actor_ref": actor_ref, **payload},
        )
    if decision.action is PromptBudgetAction.EMERGENCY:
        payload = {
            "error_code": "context_budget_exceeded",
            "message": (
                "LLM prompt exceeds the configured context budget; provider call was not attempted."
            ),
            "actor_ref": actor_ref,
            **payload,
        }
        context.emit("llm.context_budget.exceeded", payload)
        raise ContextBudgetExceededError(payload)
    return PromptBudgetPreflightResult(
        payload=prompt_payload,
        initial_decision=initial_decision,
        final_decision=decision,
        compacted=compacted,
    )


def _tool_result_artifact_payload(
    result: ToolResult, *, reason: str, token_estimate: int
) -> dict[str, Any]:
    return {
        "status": "persisted",
        "reason": reason,
        "token_estimate": token_estimate,
        "tool_name": result.tool_name,
        "call_id": result.call_id,
        "original_tool_ok": result.ok,
        "original_status": result.status or ("ok" if result.ok else "failed"),
        "tool_result": result.envelope(),
    }


def persist_tool_result_observation_artifact(
    context: SessionRuntimeContext,
    result: ToolResult,
    *,
    reason: str,
    token_estimate: int,
) -> ToolResult:
    call_digest = hashlib.sha256(result.call_id.encode("utf-8")).hexdigest()[:16]
    with context.mutation_writer_scope(
        owner_kind=MutationWriterKind.ARTIFACT_PUBLISHER,
        owner_ref=f"tool-result-artifact:{call_digest}",
    ):
        return _persist_tool_result_observation_artifact_scoped(
            context,
            result,
            reason=reason,
            token_estimate=token_estimate,
        )


def _persist_tool_result_observation_artifact_scoped(
    context: SessionRuntimeContext,
    result: ToolResult,
    *,
    reason: str,
    token_estimate: int,
) -> ToolResult:
    created_at = utc_now_iso()
    document_id = _new_id("toolresult")
    artifact_id = _new_id("art")
    context.repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=document_id,
            session_id=context.snapshot.session.session_id,
            invocation_id=None,
            document_kind="tool_result_full",
            payload=_tool_result_artifact_payload(
                result,
                reason=reason,
                token_estimate=token_estimate,
            ),
            created_at=created_at,
            updated_at=created_at,
        )
    )
    artifact = SessionArtifactRecord(
        artifact_id=artifact_id,
        session_id=context.snapshot.session.session_id,
        task_id=result.task_id,
        lane_id=result.lane_id,
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.RESULT,
        storage_uri=f"engine-document://{document_id}",
        relative_path=f"tool_results/{result.call_id}.json",
        title=f"Full tool result for {result.tool_name}",
        description="Full tool result persisted because it exceeded the LLM context budget.",
        metadata={
            "document_kind": "tool_result_full",
            "output_ref": document_id,
            "tool_name": result.tool_name,
            "call_id": result.call_id,
            "original_tool_ok": result.ok,
            "original_status": result.status or ("ok" if result.ok else "failed"),
            "reason": reason,
            "token_estimate": token_estimate,
        },
        created_at=created_at,
    )
    context.repositories.artifacts.save(artifact)
    context.emit(
        "tool_result.artifactized",
        {
            "call_id": result.call_id,
            "tool_name": result.tool_name,
            "artifact_id": artifact.artifact_id,
            "document_id": document_id,
            "reason": reason,
            "token_estimate": token_estimate,
            "original_tool_ok": result.ok,
        },
    )
    read_hint = (
        f'Use artifact.get with artifact_id="{artifact.artifact_id}" for summary, '
        'then path="output_payload.tool_result", offset=0, limit=30 to page the full result.'
    )
    observation = {
        "ok": False,
        "status": "tool_result_context_over_budget",
        "error_code": "tool_result_context_over_budget",
        "original_tool_ok": result.ok,
        "original_status": result.status or ("ok" if result.ok else "failed"),
        "artifact_id": artifact.artifact_id,
        "read_hint": read_hint,
    }
    return ToolResult(
        call_id=result.call_id,
        tool_name=result.tool_name,
        ok=False,
        content=json.dumps(observation, sort_keys=True),
        task_id=result.task_id,
        lane_id=result.lane_id,
        status="tool_result_context_over_budget",
        summary="Full tool result was persisted as an artifact because it exceeded the LLM context budget.",
        error_code="tool_result_context_over_budget",
        hint=read_hint,
        details={
            "artifact_id": artifact.artifact_id,
            "document_id": document_id,
            "original_tool_ok": result.ok,
            "original_status": result.status or ("ok" if result.ok else "failed"),
            "reason": reason,
            "token_estimate": token_estimate,
        },
    )


def budget_tool_results_for_prompt(
    context: SessionRuntimeContext,
    tool_results: tuple[ToolResult, ...],
    *,
    system_prompt: str,
    messages: list[Any],
    tools: list[Any],
) -> tuple[ToolResult, ...]:
    if not tool_results:
        return ()
    budgeted: list[ToolResult] = []
    config = prompt_budget_config_from_env()
    for result in tool_results:
        tool_message_content = result.to_tool_message_content()
        candidate_messages = [
            *messages,
            *[item.to_tool_message_content() for item in budgeted],
            tool_message_content,
        ]
        single_tokens = max(1, (len(tool_message_content) + 3) // 4)
        decision = estimate_and_decide_prompt_budget(
            system_prompt=system_prompt,
            messages=candidate_messages,
            tools=tools,
            model_factory=context.model_factory,
            config=config,
        )
        result_alone_over_budget = (
            single_tokens
            + decision.reserved_output_tokens
            + decision.safety_margin_tokens
            >= int(decision.context_window_tokens * config.auto_compact_ratio)
        )
        if result_alone_over_budget or decision.action in {
            PromptBudgetAction.AUTO_COMPACT,
            PromptBudgetAction.EMERGENCY,
        }:
            budgeted.append(
                persist_tool_result_observation_artifact(
                    context,
                    result,
                    reason=(
                        "single_tool_result_over_budget"
                        if result_alone_over_budget
                        else "next_prompt_over_budget"
                    ),
                    token_estimate=single_tokens,
                )
            )
        else:
            budgeted.append(result)
    context.refresh()
    return tuple(budgeted)


def _pending_approval_id(snapshot: SessionRuntimeSnapshot) -> str | None:
    if not snapshot.pending_approvals:
        return None
    return snapshot.pending_approvals[0].approval_id


def _format_runtime_error(exc: Exception) -> str:
    message = (
        sanitize_public_diagnostic_text(str(exc)).strip() or exc.__class__.__name__
    )
    return f"OpenZyme could not complete this turn: {message}"


def _record_system_runtime_failure(
    context: SessionRuntimeContext,
    harness_input: HarnessInput,
    exc: Exception,
    *,
    source_kind: str,
    source_ref: str,
    source_version: str,
    phase: str,
    error_code: str,
    facts: dict[str, Any] | None = None,
):
    classification = None
    try:
        from openzyme_runtime import classify_llm_provider_error

        classification = classify_llm_provider_error(exc)
    except Exception:
        classification = None
    resolved_error_code = error_code
    safe_hint = (
        "Inspect the system diagnostic and explicitly resume the runtime after "
        "provider or operator recovery."
    )
    if classification is not None:
        category = getattr(classification, "category", None)
        category_value = getattr(category, "value", category)
        if category_value and category_value != "unknown_provider_error":
            resolved_error_code = "provider_unavailable"
        retryable = bool(getattr(classification, "retryable", False))
    else:
        retryable = bool(getattr(exc, "retryable", False))
    observation = record_failure_observation(
        context.repositories,
        session_id=harness_input.session_id,
        task_id=(
            context.current_step_context.task_id
            if context.current_step_context is not None
            else (
                None
                if harness_input.restore_focus is None
                else harness_input.restore_focus.task_id
            )
        ),
        lane_id=(
            context.current_step_context.lane_id
            if context.current_step_context is not None
            else (
                None
                if harness_input.restore_focus is None
                else harness_input.restore_focus.lane_id
            )
        ),
        agent_id=harness_input.agent_id,
        source_kind=source_kind,
        source_ref=source_ref,
        source_version=source_version,
        phase=phase,
        failure_class=(
            FailureClass.PROVIDER
            if resolved_error_code == "provider_unavailable"
            else FailureClass.SYSTEM
        ),
        recoverability=(
            FailureRecoverability.RUNTIME_RETRY
            if retryable
            else FailureRecoverability.TERMINAL
        ),
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=(
            RetryEligibility.SAME_PHASE_SAFE if retryable else RetryEligibility.TERMINAL
        ),
        actor_kind=FailureActorKind.SYSTEM,
        error_code=resolved_error_code,
        safe_summary=(
            "The agent runtime could not produce a decision for this turn. "
            "The business task status was not changed."
        ),
        safe_hint=safe_hint,
        facts={
            "agent_decision_produced": False,
            "exception_type": exc.__class__.__name__,
            "public_error": sanitize_public_diagnostic_text(str(exc)),
            **(facts or {}),
        },
        private_diagnostic={
            "exception_type": exc.__class__.__name__,
            "message": str(exc),
        },
    )
    context.emit(
        "runtime.system_diagnostic",
        {
            "failure": observation.to_dict(),
            "agent_decision_produced": False,
            "task_status_changed": False,
        },
    )
    return observation


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


def _tool_event_metadata(
    context: SessionRuntimeContext, invocation: ToolInvocation
) -> dict[str, Any]:
    step_context = context.current_step_context
    metadata: dict[str, Any] = {
        "step_id": None if step_context is None else step_context.step_id,
        "agent_id": None if step_context is None else step_context.agent_id,
        "actor_kind": None if step_context is None else step_context.actor_kind,
        "role": None if step_context is None else step_context.role,
        "call_index": None if step_context is None else step_context.call_index,
        "tool_catalog_digest": None
        if step_context is None
        else step_context.tool_catalog_digest,
        "restore_context_digest": None
        if step_context is None
        else step_context.restore_context_digest,
        "side_effect": None,
        "supports_parallel": False,
        "approval_required": None,
    }
    if context.current_tool_router is None or step_context is None:
        return metadata
    governance = context.current_tool_router.governance(
        step_context, invocation.tool_name
    )
    if governance is None:
        return metadata
    public_governance = governance.to_public_metadata()
    metadata["side_effect"] = public_governance["side_effect"]
    metadata["supports_parallel"] = public_governance["supports_parallel"]
    metadata["approval_required"] = public_governance["approval_required"]
    return metadata


def _record_tool_rejection(
    context: SessionRuntimeContext,
    harness_input: HarnessInput,
    result: ToolResult,
    *,
    fallback_source_version: str,
    phase: str = "validation",
    failure_class: FailureClass = FailureClass.VALIDATION,
    recoverability: FailureRecoverability = FailureRecoverability.AGENT_CAN_REPLAN,
    retry_eligibility: RetryEligibility = RetryEligibility.SAME_PHASE_SAFE,
) -> ToolResult:
    step_context = context.current_step_context
    result_task = (
        None
        if result.task_id is None
        else context.repositories.tasks.get(result.task_id)
    )
    observation_task_id = (
        result.task_id
        if result_task is not None
        and result_task.session_id == harness_input.session_id
        else (None if step_context is None else step_context.task_id)
    )
    result_lane = (
        None
        if result.lane_id is None
        else context.repositories.lanes.get(result.lane_id)
    )
    observation_lane_id = (
        result.lane_id
        if result_lane is not None
        and result_lane.session_id == harness_input.session_id
        else (None if step_context is None else step_context.lane_id)
    )
    details = {
        **(result.details or {}),
        "dispatched": False,
        "effect_certainty": ExternalEffectCertainty.NO_EFFECT.value,
        "retry_eligibility": retry_eligibility.value,
    }
    result = replace(result, details=details)
    observation = record_failure_observation(
        context.repositories,
        session_id=harness_input.session_id,
        task_id=observation_task_id,
        lane_id=observation_lane_id,
        agent_id=context.agent_id or harness_input.agent_id,
        source_kind="tool_invocation",
        source_ref=result.call_id,
        source_version=(
            fallback_source_version if step_context is None else step_context.step_id
        ),
        phase=phase,
        failure_class=failure_class,
        recoverability=recoverability,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=retry_eligibility,
        actor_kind=FailureActorKind.HARNESS,
        error_code=result.error_code or "tool_call_rejected",
        safe_summary=result.summary or result.content,
        safe_hint=result.hint,
        facts={
            **details,
            "tool_call_lane_id": result.lane_id,
            "tool_call_task_id": result.task_id,
            "tool_name": result.tool_name,
        },
    )
    return sanitize_tool_result_diagnostics(
        replace(result, failure_observation=observation.to_dict())
    )


def _tool_call_batch_interrupted_result(
    invocation: ToolInvocation,
    *,
    position: int,
    interrupted_by_call_id: str,
    interruption_reason: str,
) -> ToolResult:
    summary = (
        "This tool call was not executed because an earlier tool call ended "
        "or suspended the current tool-call batch."
    )
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=summary,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status="rejected",
        summary=summary,
        error_code="tool_call_batch_interrupted",
        hint=(
            "Inspect the earlier result and current durable state, then decide "
            "whether to issue this work in a new agent turn."
        ),
        details={
            "dispatched": False,
            "effect_certainty": ExternalEffectCertainty.NO_EFFECT.value,
            "interrupted_by_call_id": interrupted_by_call_id,
            "interruption_reason": interruption_reason,
            "retry_eligibility": RetryEligibility.VERIFY_THEN_RETRY.value,
            "tool_call_position": position,
        },
    )


def _dispatched_failure_result(
    invocation: ToolInvocation,
    observation: Any,
) -> ToolResult:
    effect_certainty = observation.effect_certainty.value
    retry_eligibility = observation.retry_eligibility.value
    return sanitize_tool_result_diagnostics(
        ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            content=observation.safe_summary,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="dispatch_failed",
            summary=observation.safe_summary,
            error_code=observation.error_code,
            hint=observation.safe_hint,
            details={
                "boundary_fatal": True,
                "dispatched": True,
                "effect_certainty": effect_certainty,
                "failure_id": observation.failure_id,
                "retry_eligibility": retry_eligibility,
            },
            failure_observation=observation.to_dict(),
        )
    )


def _emit_tool_completed(
    context: SessionRuntimeContext,
    result: ToolResult,
    invocation: ToolInvocation,
) -> None:
    context.emit(
        "tool.completed",
        {
            "call_id": result.call_id,
            "tool_name": result.tool_name,
            "task_id": result.task_id or invocation.task_id,
            "lane_id": result.lane_id or invocation.lane_id,
            "ok": result.ok,
            "status": result.status or ("ok" if result.ok else "failed"),
            "error_code": result.error_code,
            **_tool_event_metadata(context, invocation),
        },
    )


def _emit_tool_rejection(
    context: SessionRuntimeContext,
    result: ToolResult,
    invocation: ToolInvocation,
) -> None:
    details = dict(result.details or {})
    context.emit(
        "tool.rejected",
        {
            "call_id": result.call_id,
            "tool_name": result.tool_name,
            "task_id": result.task_id,
            "lane_id": result.lane_id,
            "ok": False,
            "status": result.status,
            "error_code": result.error_code,
            "effect_certainty": details.get(
                "effect_certainty",
                ExternalEffectCertainty.NO_EFFECT.value,
            ),
            "retry_eligibility": details.get("retry_eligibility"),
            **_tool_event_metadata(context, invocation),
        },
    )
    _emit_tool_completed(context, result, invocation)


def _settle_undispatched_tool_calls(
    context: SessionRuntimeContext,
    harness_input: HarnessInput,
    *,
    eligible_calls: tuple[tuple[int, ToolInvocation], ...],
    prepared_overflow_calls: tuple[tuple[ToolResult, ToolInvocation], ...],
    interrupted_by_call_id: str | None,
    interruption_reason: str | None,
    fallback_source_version: str,
) -> tuple[ToolResult, ...]:
    settled: list[ToolResult] = []
    if eligible_calls:
        if interrupted_by_call_id is None or interruption_reason is None:
            raise ValueError(
                "interrupted eligible tool calls require a causal call and boundary"
            )
        for position, invocation in eligible_calls:
            interrupted_recoverability = (
                FailureRecoverability.RUNTIME_RETRY
                if interruption_reason == "pending_approval"
                else FailureRecoverability.TERMINAL
            )
            result = _record_tool_rejection(
                context,
                harness_input,
                _tool_call_batch_interrupted_result(
                    invocation,
                    position=position,
                    interrupted_by_call_id=interrupted_by_call_id,
                    interruption_reason=interruption_reason,
                ),
                fallback_source_version=fallback_source_version,
                phase="dispatch",
                failure_class=FailureClass.HARNESS,
                recoverability=interrupted_recoverability,
                retry_eligibility=RetryEligibility.VERIFY_THEN_RETRY,
            )
            _emit_tool_rejection(context, result, invocation)
            settled.append(result)
    for result, invocation in prepared_overflow_calls:
        _emit_tool_rejection(context, result, invocation)
        settled.append(result)
    return tuple(settled)


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
    scientific_workflow_contract_registry: (
        ScientificWorkflowContractRegistry | None
    ) = None,
    sandbox_workspace_root: Path | None = None,
    artifact_blob_root: Path | None = None,
    signal_notifier: Any | None = None,
    reliability_shadow_observer: Any | None = None,
    reliability_settings: Any | None = None,
    durable_route_adapter_policy_ids: dict[str, str] | None = None,
    tool_dispatch_precondition: ToolDispatchPrecondition | None = None,
    mutation_writer_scope_factory: SandboxMutationWriterScopeFactory | None = None,
    sandbox_host_binding_factory: (
        Callable[
            [EngineRegistry, SessionRuntimeLease | None],
            SandboxHostBinding,
        ]
        | None
    ) = None,
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
        scientific_workflow_contract_registry=(scientific_workflow_contract_registry),
        sandbox_workspace_root=sandbox_workspace_root,
        artifact_blob_root=artifact_blob_root,
        signal_notifier=signal_notifier,
        reliability_shadow_observer=reliability_shadow_observer,
        reliability_settings=reliability_settings,
        durable_route_adapter_policy_ids=dict(durable_route_adapter_policy_ids or {}),
        tool_dispatch_precondition=tool_dispatch_precondition,
        assistant_response_recipient=harness_input.sender,
        assistant_response_recipient_kind=harness_input.sender_kind,
        persist_conversation=harness_input.persist_conversation,
        mutation_writer_scope_factory=mutation_writer_scope_factory,
        sandbox_host_binding_factory=sandbox_host_binding_factory,
        agent_id=harness_input.agent_id,
        actor_kind=harness_input.actor_kind,
        actor_role=harness_input.actor_role,
        correlation_id=harness_input.correlation_id,
        signal_id=harness_input.signal_id,
        wakeup_reason=harness_input.wakeup_reason,
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
    turn_source_ref = (
        harness_input.signal_id
        or harness_input.correlation_id
        or _new_id("harness_turn")
    )

    for _ in range(harness_input.max_steps):
        try:
            repositories.assert_runtime_write_fence(
                session_id=harness_input.session_id,
            )
            step = driver.plan(context, harness_input, tool_results)
        except Exception as exc:
            step_context = context.current_step_context
            observation = _record_system_runtime_failure(
                context,
                harness_input,
                exc,
                source_kind=(
                    "runtime_signal"
                    if harness_input.signal_id is not None
                    else "harness_turn"
                ),
                source_ref=turn_source_ref,
                source_version=(
                    step_context.step_id
                    if step_context is not None
                    else turn_source_ref
                ),
                phase="planning",
                error_code="harness_plan_failed",
                facts={
                    "call_index": None
                    if step_context is None
                    else step_context.call_index
                },
            )
            public_error = str(observation.facts.get("public_error") or "").strip()
            outputs.append(
                "OpenZyme system diagnostic "
                f"{observation.failure_id}: the agent runtime could not produce "
                "a decision for this turn. The business task remains unchanged."
                + (f" Error: {public_error}" if public_error else "")
            )
            context.emit(
                "harness.failed",
                {
                    "failure_id": observation.failure_id,
                    "error_code": observation.error_code,
                    "agent_decision_produced": False,
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
                error=exc,
            )
        tool_results = ()
        if step.next_focus is not None:
            context.set_focus(step.next_focus)

        if step.llm_trace is not None:
            _persist_llm_trace_step(context, step.llm_trace)
            activity_happened = True

        for task in step.task_updates:
            repositories.tasks.save(task, intent=TaskWriteIntent.EDIT)
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
            _persist_outbound_assistant_message(
                context,
                step.assistant_message,
            )
            outputs.append(step.assistant_message)
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

        if step.tool_invocations or step.tool_rejections:
            raw_invocations = tuple(step.tool_invocations)
            prepared_overflow_calls: list[tuple[ToolResult, ToolInvocation]] = []
            for rejection in step.tool_rejections:
                rejection_invocation = ToolInvocation(
                    call_id=rejection.call_id,
                    tool_name=rejection.tool_name,
                    arguments={},
                    task_id=rejection.task_id,
                    lane_id=rejection.lane_id,
                )
                prepared_overflow_calls.append(
                    (
                        _record_tool_rejection(
                            context,
                            harness_input,
                            rejection,
                            fallback_source_version=turn_source_ref,
                        ),
                        rejection_invocation,
                    )
                )

            current_results: list[ToolResult] = []
            for index, raw_invocation in enumerate(raw_invocations):
                position = index + 1
                try:
                    invocation = replace(
                        raw_invocation,
                        lane_id=(
                            raw_invocation.lane_id
                            if raw_invocation.tool_name == "task.get"
                            else _resolve_effective_lane_id(
                                repositories,
                                session_id=harness_input.session_id,
                                task_id=raw_invocation.task_id,
                                lane_id=raw_invocation.lane_id,
                            )
                        ),
                    )
                except ValueError as exc:
                    public_error = sanitize_public_diagnostic_text(str(exc)).strip()
                    invocation = raw_invocation
                    result = _record_tool_rejection(
                        context,
                        harness_input,
                        ToolResult(
                            call_id=invocation.call_id,
                            tool_name=invocation.tool_name,
                            ok=False,
                            content=(
                                "Tool invocation context is invalid: "
                                f"{public_error or exc.__class__.__name__}"
                            ),
                            task_id=None,
                            lane_id=None,
                            status="invalid_tool_context",
                            summary=(
                                "The tool was not dispatched because its "
                                "task/lane context is stale or invalid."
                            ),
                            error_code="invalid_tool_context",
                            hint=(
                                "Correct the exact task_id/lane_id reference "
                                "and retry the same tool."
                            ),
                            details={
                                "exception_type": exc.__class__.__name__,
                                "public_error": public_error,
                                "precondition_rejected": True,
                                "requested_task_id": invocation.task_id,
                                "requested_lane_id": invocation.lane_id,
                            },
                        ),
                        fallback_source_version=turn_source_ref,
                    )
                    current_results.append(result)
                    _emit_tool_rejection(context, result, invocation)
                    activity_happened = True
                    context.refresh()
                    continue
                context.emit(
                    "tool.invoked",
                    {
                        "call_id": invocation.call_id,
                        "tool_name": invocation.tool_name,
                        "task_id": invocation.task_id,
                        "lane_id": invocation.lane_id,
                        **_tool_event_metadata(context, invocation),
                    },
                )
                try:
                    if (
                        context.current_tool_router is not None
                        and context.current_step_context is not None
                    ):
                        result = context.current_tool_router.dispatch(
                            context.current_step_context, invocation
                        )
                    else:
                        result = registry.dispatch(context, invocation)
                except Exception as exc:
                    step_context = context.current_step_context
                    existing = context.repositories.failure_observations.list_by_source(
                        session_id=harness_input.session_id,
                        source_kind="tool_invocation",
                        source_ref=invocation.call_id,
                    )
                    observation = (
                        existing[-1]
                        if existing
                        else _record_system_runtime_failure(
                            context,
                            harness_input,
                            exc,
                            source_kind="tool_invocation",
                            source_ref=invocation.call_id,
                            source_version=(
                                step_context.step_id
                                if step_context is not None
                                else turn_source_ref
                            ),
                            phase="dispatch",
                            error_code="harness_tool_dispatch_failed",
                            facts={
                                "tool_name": invocation.tool_name,
                                "call_id": invocation.call_id,
                            },
                        )
                    )
                    failure_result = _dispatched_failure_result(
                        invocation,
                        observation,
                    )
                    current_results.append(failure_result)
                    _emit_tool_completed(context, failure_result, invocation)
                    current_results.extend(
                        _settle_undispatched_tool_calls(
                            context,
                            harness_input,
                            eligible_calls=tuple(
                                (
                                    remaining_position,
                                    raw_invocations[remaining_position - 1],
                                )
                                for remaining_position in range(
                                    position + 1,
                                    len(raw_invocations) + 1,
                                )
                            ),
                            prepared_overflow_calls=tuple(prepared_overflow_calls),
                            interrupted_by_call_id=invocation.call_id,
                            interruption_reason="boundary_fatal_dispatch",
                            fallback_source_version=turn_source_ref,
                        )
                    )
                    all_tool_results.extend(current_results)
                    outputs.append(
                        "OpenZyme system diagnostic "
                        f"{observation.failure_id}: tool execution crossed a "
                        "fail-closed boundary before the agent could choose recovery. "
                        "The business task remains unchanged."
                        + (
                            " Error: "
                            + str(observation.facts.get("public_error") or "").strip()
                            if observation.facts.get("public_error")
                            else ""
                        )
                    )
                    context.emit(
                        "harness.failed",
                        {
                            "failure_id": observation.failure_id,
                            "error_code": observation.error_code,
                            "agent_decision_produced": False,
                            "tool_name": invocation.tool_name,
                            "call_id": invocation.call_id,
                        },
                    )
                    activity_happened = True
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
                        error=exc,
                    )
                current_results.append(result)
                _emit_tool_completed(context, result, invocation)
                activity_happened = True
                context.refresh()
                if result.ok and result.terminates_turn:
                    context.emit(
                        "harness.terminal_action",
                        {
                            "call_id": result.call_id,
                            "tool_name": result.tool_name,
                            "terminal_action": result.terminal_action,
                            "status": result.status
                            or ("ok" if result.ok else "failed"),
                        },
                    )
                    current_results.extend(
                        _settle_undispatched_tool_calls(
                            context,
                            harness_input,
                            eligible_calls=tuple(
                                (
                                    remaining_position,
                                    raw_invocations[remaining_position - 1],
                                )
                                for remaining_position in range(
                                    position + 1,
                                    len(raw_invocations) + 1,
                                )
                            ),
                            prepared_overflow_calls=tuple(prepared_overflow_calls),
                            interrupted_by_call_id=result.call_id,
                            interruption_reason=(
                                result.terminal_action or "terminal_action"
                            ),
                            fallback_source_version=turn_source_ref,
                        )
                    )
                    all_tool_results.extend(current_results)
                    _auto_compact_if_needed(
                        context,
                        activity_happened=activity_happened,
                        outputs=outputs,
                        all_tool_results=all_tool_results,
                    )
                    context.refresh()
                    if result.terminal_action == "runtime_suspended":
                        pending_approval = _exact_pending_approval_for_suspension(
                            context,
                            result,
                        )
                        if pending_approval is None:
                            error = RuntimeError(
                                "runtime suspension omitted or mismatched its "
                                "exact durable pending approval"
                            )
                            return HarnessResult(
                                session_id=harness_input.session_id,
                                status=HarnessStatus.FAILED,
                                snapshot=context.snapshot,
                                events=tuple(sink.events),
                                outputs=tuple(outputs),
                                tool_results=tuple(all_tool_results),
                                error=error,
                            )
                        pending_approval_id = pending_approval.approval_id
                        return HarnessResult(
                            session_id=harness_input.session_id,
                            status=HarnessStatus.WAITING_APPROVAL,
                            snapshot=context.snapshot,
                            events=tuple(sink.events),
                            outputs=tuple(outputs),
                            tool_results=tuple(all_tool_results),
                            pending_approval_id=pending_approval_id,
                        )
                    return HarnessResult(
                        session_id=harness_input.session_id,
                        status=HarnessStatus.COMPLETED,
                        snapshot=context.snapshot,
                        events=tuple(sink.events),
                        outputs=tuple(outputs),
                        tool_results=tuple(all_tool_results),
                        pending_approval_id=pending_approval_id,
                    )
                pending_approval_id = _pending_approval_id(context.snapshot)
                if pending_approval_id is not None:
                    current_results.extend(
                        _settle_undispatched_tool_calls(
                            context,
                            harness_input,
                            eligible_calls=tuple(
                                (
                                    remaining_position,
                                    raw_invocations[remaining_position - 1],
                                )
                                for remaining_position in range(
                                    position + 1,
                                    len(raw_invocations) + 1,
                                )
                            ),
                            prepared_overflow_calls=tuple(prepared_overflow_calls),
                            interrupted_by_call_id=result.call_id,
                            interruption_reason="pending_approval",
                            fallback_source_version=turn_source_ref,
                        )
                    )
                    all_tool_results.extend(current_results)
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
            current_results.extend(
                _settle_undispatched_tool_calls(
                    context,
                    harness_input,
                    eligible_calls=(),
                    prepared_overflow_calls=tuple(prepared_overflow_calls),
                    interrupted_by_call_id=None,
                    interruption_reason=None,
                    fallback_source_version=turn_source_ref,
                )
            )
            all_tool_results.extend(current_results)
            if prepared_overflow_calls:
                activity_happened = True
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
            and (not outputs or outputs == ["No user-facing response was generated."])
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
