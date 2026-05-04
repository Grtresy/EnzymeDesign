from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
import json
from typing import Any
from uuid import uuid4

from openzyme_core import CoreRepositories
from openzyme_core import EngineRegistry
from openzyme_core import HarnessInput
from openzyme_core import HarnessStatus
from openzyme_core import LaneManager
from openzyme_core import LlmConversationDriver
from openzyme_core import MemoryEventBus
from openzyme_core import ProtocolService
from openzyme_core import RestoreFocus
from openzyme_core import ResumeDecision
from openzyme_core import ResumeEnvelope
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import TaskBoardService
from openzyme_core import TaskMutation
from openzyme_core import ToolRegistry
from openzyme_core import AgentRuntimeService
from openzyme_core import persist_conversation_message
from openzyme_core import run_agent_harness_loop
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import MissingLlmConfigurationError


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _event(event_type: str, session_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "event_id": _new_id("evt"),
        "session_id": session_id,
        "event_type": event_type,
        "created_at": utc_now_iso(),
        "payload": payload,
    }


def _event_fingerprint(event: dict[str, Any]) -> tuple[str, str, str]:
    return (
        str(event["event_type"]),
        str(event["created_at"]),
        json.dumps(event.get("payload", {}), sort_keys=True, separators=(",", ":")),
    )


@dataclass(slots=True)
class V3EventStore:
    _events: dict[str, list[dict[str, Any]]]

    def __init__(self) -> None:
        self._events = {}

    def append(self, session_id: str, events: list[dict[str, Any]]) -> None:
        self._events.setdefault(session_id, []).extend(events)

    def list(self, session_id: str) -> list[dict[str, Any]]:
        return list(self._events.get(session_id, ()))


@dataclass(frozen=True, slots=True)
class V3CommandResult:
    session_id: str
    status: str
    outputs: tuple[str, ...]
    events: list[dict[str, Any]]
    workspace: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "status": self.status,
            "outputs": list(self.outputs),
            "events": self.events,
            "workspace": self.workspace,
        }


@dataclass(slots=True)
class V3HostApiService:
    repositories: CoreRepositories
    event_store: V3EventStore
    engine_registry: EngineRegistry | None = None
    model_factory: Any | None = None
    bio_research_service: Any | None = None
    research_adapter: Any | None = None

    def create_session(
        self,
        *,
        project_id: str,
        objective: str,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        resolved_session_id = session_id or _new_id("sess")
        session = Session.create(
            session_id=resolved_session_id,
            project_id=project_id,
            title=title or objective,
            objective=objective,
            status=SessionStatus.ACTIVE,
        )
        self.repositories.sessions.save(session)
        events = [
            _event(
                "session.created",
                session.session_id,
                {"session": session.to_dict()},
            )
        ]
        self.event_store.append(session.session_id, events)
        return {
            "session_id": session.session_id,
            "workspace": self.workspace(session.session_id),
            "events": events,
        }

    def workspace(self, session_id: str) -> dict[str, Any]:
        return (
            SessionProjectionBuilder(self.repositories)
            .build_session_workspace(session_id)
            .to_dict()
        )

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for session in self.repositories.sessions.list_by_project(project_id):
            messages = self.repositories.inbox.list_by_session(session.session_id)
            approvals = self.repositories.approvals.list_by_session(session.session_id)
            latest_preview = ""
            for message in reversed(messages):
                if (
                    message.message_type not in {"user_message", "assistant_message"}
                    or not message.payload_ref
                ):
                    continue
                payload = self.repositories.engine_documents.get(message.payload_ref)
                if payload is None:
                    continue
                content = str(payload.payload.get("content") or "").strip()
                if content:
                    latest_preview = content
                    break
            summaries.append(
                {
                    "session_id": session.session_id,
                    "project_id": session.project_id,
                    "title": session.title,
                    "objective": session.objective,
                    "status": session.status.value,
                    "created_at": session.created_at,
                    "updated_at": session.updated_at,
                    "latest_message_preview": latest_preview,
                    "pending_approval_count": sum(
                        1
                        for approval in approvals
                        if approval.status is ApprovalRequestStatus.PENDING
                    ),
                }
            )
        summaries.sort(
            key=lambda item: (item["updated_at"], item["session_id"]), reverse=True
        )
        return summaries

    def events(self, session_id: str) -> list[dict[str, Any]]:
        return self.event_store.list(session_id)

    def _touch_session(self, session_id: str) -> None:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            return
        next_updated_at = utc_now_iso()
        latest_project_updated_at = max(
            (
                candidate.updated_at
                for candidate in self.repositories.sessions.list_by_project(
                    session.project_id
                )
            ),
            default=session.updated_at,
        )
        if next_updated_at <= latest_project_updated_at:
            next_updated_at = (
                datetime.fromisoformat(latest_project_updated_at) + timedelta(seconds=1)
            ).isoformat()
        self.repositories.sessions.save(replace(session, updated_at=next_updated_at))

    def _extend_with_activity_events(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        existing = {
            _event_fingerprint(event) for event in self.event_store.list(session_id)
        }
        current = {_event_fingerprint(event) for event in events}
        for item in self.workspace(session_id).get("activity_feed", []):
            event = {
                "event_id": _new_id("evt"),
                "session_id": session_id,
                "event_type": item["event_type"],
                "created_at": item["created_at"],
                "payload": item["payload"],
            }
            fingerprint = _event_fingerprint(event)
            if fingerprint in existing or fingerprint in current:
                continue
            events.append(event)
            current.add(fingerprint)

    def _drain_agent_runtime(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        event_bus = MemoryEventBus()
        context = SessionRuntimeContext(
            repositories=self.repositories,
            event_sink=event_bus,
            snapshot=SessionRuntimeSnapshot.load(self.repositories, session_id),
            tool_registry=ToolRegistry(),
            restore_focus=RestoreFocus(),
            model_factory=self.model_factory,
            engine_registry=self.engine_registry,
            bio_research_service=self.bio_research_service,
            research_adapter=self.research_adapter,
        )
        runtime = AgentRuntimeService(context)
        runtime.auto_enqueue_ready_tasks(session_id)
        outcomes = runtime.drain_session(session_id, max_signals=3)
        events.extend(event.to_dict() for event in event_bus.events)
        return [outcome.to_dict() for outcome in outcomes]

    def _terminal_teammate_outcomes(
        self, outcomes: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        terminal: list[dict[str, Any]] = []
        for outcome in outcomes:
            if outcome.get("waiting_approval_id"):
                continue
            task = outcome.get("task")
            task_status = (
                "" if not isinstance(task, dict) else str(task.get("status") or "")
            )
            task_id = None if not isinstance(task, dict) else task.get("task_id")
            current_task = (
                None if task_id is None else self.repositories.tasks.get(str(task_id))
            )
            if current_task is not None:
                task_status = current_task.status.value
            teammate_status = str(outcome.get("teammate_status") or "")
            if task_status in {
                TaskStatus.COMPLETED.value,
                TaskStatus.FAILED.value,
                TaskStatus.CANCELLED.value,
            } or teammate_status in {
                HarnessStatus.COMPLETED.value,
                HarnessStatus.FAILED.value,
                HarnessStatus.MAX_STEPS_EXCEEDED.value,
            }:
                terminal.append(outcome)
        return terminal

    def _outcomes_include_failure(self, outcomes: list[dict[str, Any]]) -> bool:
        for outcome in self._terminal_teammate_outcomes(outcomes):
            task = outcome.get("task")
            task_status = (
                "" if not isinstance(task, dict) else str(task.get("status") or "")
            )
            if outcome.get("ok") is False or task_status == TaskStatus.FAILED.value:
                return True
            task_id = None if not isinstance(task, dict) else task.get("task_id")
            current_task = (
                None if task_id is None else self.repositories.tasks.get(str(task_id))
            )
            if current_task is not None and current_task.status is TaskStatus.FAILED:
                return True
        return False

    def _outcomes_include_waiting_approval(
        self, outcomes: list[dict[str, Any]]
    ) -> bool:
        return any(outcome.get("waiting_approval_id") for outcome in outcomes)

    def _teammate_outcomes_from_tool_results(
        self, tool_results: tuple[Any, ...]
    ) -> list[dict[str, Any]]:
        outcomes: list[dict[str, Any]] = []
        for tool_result in tool_results:
            if getattr(tool_result, "tool_name", None) != "task.delegate":
                continue
            try:
                payload = json.loads(str(tool_result.content))
            except (TypeError, json.JSONDecodeError):
                continue
            if not isinstance(payload, dict):
                continue
            outcomes.append(
                {
                    "task": payload.get("task"),
                    "agent": payload.get("agent"),
                    "ok": bool(getattr(tool_result, "ok", False)),
                    "summary": payload.get("summary"),
                    "teammate_status": payload.get("teammate_status"),
                    "outputs": payload.get("teammate_outputs") or (),
                    "waiting_approval_id": payload.get("waiting_approval_id"),
                }
            )
        return outcomes

    def _run_master_followup_after_teammates(
        self,
        session_id: str,
        events: list[dict[str, Any]],
        outcomes: list[dict[str, Any]],
        *,
        max_steps: int = 4,
    ):
        terminal = self._terminal_teammate_outcomes(outcomes)
        if not terminal:
            return None
        focus_task_id = None
        focus_lane_id = None
        if len(terminal) == 1 and isinstance(terminal[0].get("task"), dict):
            task = terminal[0]["task"]
            focus_task_id = task.get("task_id")
            focus_lane_id = task.get("lane_id")
        event_bus = MemoryEventBus()
        result = run_agent_harness_loop(
            self.repositories,
            HarnessInput(
                session_id=session_id,
                message=None,
                max_steps=max_steps,
                restore_focus=RestoreFocus(
                    task_id=focus_task_id, lane_id=focus_lane_id
                ),
                persist_conversation=True,
            ),
            driver=self._require_llm_driver(),
            engine_registry=self.engine_registry,
            event_sink=event_bus,
            model_factory=self.model_factory,
            bio_research_service=self.bio_research_service,
            research_adapter=self.research_adapter,
        )
        events.extend(event.to_dict() for event in event_bus.events)
        for output in result.outputs:
            events.append(
                _event(
                    "conversation.assistant_message",
                    session_id,
                    {"content": output},
                )
            )
        return result

    def post_message(
        self,
        *,
        session_id: str,
        message: str | None,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
        max_steps: int = 8,
    ) -> V3CommandResult:
        if self.repositories.sessions.get(session_id) is None:
            raise KeyError(f"session {session_id!r} does not exist")
        driver = self._require_llm_driver()
        event_bus = MemoryEventBus()
        result = run_agent_harness_loop(
            self.repositories,
            HarnessInput(
                session_id=session_id,
                message=message,
                max_steps=max_steps,
                restore_focus=RestoreFocus(
                    task_id=task_id, lane_id=lane_id, skill_keys=skill_keys
                ),
            ),
            driver=driver,
            engine_registry=self.engine_registry,
            event_sink=event_bus,
            model_factory=self.model_factory,
            bio_research_service=self.bio_research_service,
            research_adapter=self.research_adapter,
        )
        events: list[dict[str, Any]] = []
        if message:
            events.append(
                _event("conversation.user_message", session_id, {"content": message})
            )
        events.extend(event.to_dict() for event in result.events)
        if result.status is not HarnessStatus.WAITING_APPROVAL:
            for output in result.outputs:
                events.append(
                    _event(
                        "conversation.assistant_message",
                        session_id,
                        {"content": output},
                    )
                )
        outcomes = self._teammate_outcomes_from_tool_results(result.tool_results)
        outcomes.extend(self._drain_agent_runtime(session_id, events))
        followup = self._run_master_followup_after_teammates(
            session_id, events, outcomes
        )
        if followup is not None:
            result = followup
        has_pending_approval = bool(
            self.repositories.approvals.list_pending_by_session(session_id)
        )
        response_status = (
            HarnessStatus.WAITING_APPROVAL
            if has_pending_approval or self._outcomes_include_waiting_approval(outcomes)
            else HarnessStatus.FAILED
            if self._outcomes_include_failure(outcomes)
            else result.status
        )
        response_outputs = () if has_pending_approval else result.outputs
        self._touch_session(session_id)
        self._extend_with_activity_events(session_id, events)
        self.event_store.append(session_id, events)
        return V3CommandResult(
            session_id=session_id,
            status=response_status.value,
            outputs=response_outputs,
            events=events,
            workspace=self.workspace(session_id),
        )

    def resolve_approval(
        self, approval_id: str, *, decision: str, actor_ref: str = "user"
    ) -> V3CommandResult:
        approval = self.repositories.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"approval {approval_id!r} does not exist")
        if approval.status is not ApprovalRequestStatus.PENDING:
            raise ValueError(f"approval {approval_id!r} is not pending")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        execution_approval = (
            approval.kind
            in {
                "execution_launch",
                "execution_pipeline_plan",
                "execution_pipeline_operation",
            }
            or self._execution_waiting_invocation_id(approval) is not None
        )
        continuation_output: dict[str, Any] | None = None
        events = [
            _event(
                "approval.resolved",
                approval.session_id,
                {
                    "approval_id": approval_id,
                    "decision": decision,
                    "actor_ref": actor_ref,
                },
            )
        ]
        runtime_outcomes: list[dict[str, Any]] = []
        if execution_approval:
            self._resolve_approval_record(
                approval, decision=decision, actor_ref=actor_ref
            )
            continuation_output = self._continue_execution_after_approval(
                approval_id, decision
            )
            result_status = HarnessStatus.COMPLETED
            pending_approval_id = None
            result_outputs: list[str] = []
            if continuation_output is None:
                result_status = HarnessStatus.FAILED
                result_outputs = [
                    "Execution approval was resolved, but no waiting execution invocation was linked to it."
                ]
            else:
                events.append(
                    _event(
                        "execution.pipeline.completed",
                        approval.session_id,
                        {
                            "invocation_id": continuation_output["invocation_id"],
                            "status": continuation_output["status"],
                        },
                    )
                )
                if (
                    continuation_output["status"]
                    == EngineInvocationStatus.WAITING_APPROVAL.value
                ):
                    result_status = HarnessStatus.WAITING_APPROVAL
                    pending_approval_id = continuation_output.get("approval_id")
                elif continuation_output["status"] in {
                    EngineInvocationStatus.FAILED.value,
                    EngineInvocationStatus.CANCELLED.value,
                }:
                    result_status = HarnessStatus.FAILED
        else:
            driver = self._require_llm_driver()
            result = run_agent_harness_loop(
                self.repositories,
                HarnessInput(
                    session_id=approval.session_id,
                    resume=ResumeEnvelope(
                        approval_id=approval_id,
                        decision=ResumeDecision.APPROVED
                        if decision == "approved"
                        else ResumeDecision.REJECTED,
                        actor_ref=actor_ref,
                    ),
                    restore_focus=RestoreFocus(
                        task_id=approval.task_id, lane_id=approval.lane_id
                    ),
                    persist_conversation=False,
                ),
                driver=driver,
                engine_registry=self.engine_registry,
                model_factory=self.model_factory,
                bio_research_service=self.bio_research_service,
                research_adapter=self.research_adapter,
            )
            events.extend(event.to_dict() for event in result.events)
            result_outputs = list(result.outputs)
            result_status = result.status
            pending_approval_id = result.pending_approval_id

        for output in result_outputs:
            message_id = _new_id("msg")
            created_at = utc_now_iso()
            payload_ref = persist_conversation_message(
                self.repositories,
                session_id=approval.session_id,
                message_id=message_id,
                role="assistant",
                content=output,
                created_at=created_at,
            )
            self.repositories.inbox.save(
                InboxMessage(
                    message_id=message_id,
                    session_id=approval.session_id,
                    sender="harness",
                    sender_kind=InboxParticipantKind.HARNESS,
                    recipient="user",
                    recipient_kind=InboxParticipantKind.USER,
                    message_type="assistant_message",
                    correlation_id=None,
                    payload_ref=payload_ref,
                    status=InboxStatus.DELIVERED,
                    created_at=created_at,
                )
            )
            events.append(
                _event(
                    "conversation.assistant_message",
                    approval.session_id,
                    {"content": output},
                )
            )
        if execution_approval:
            self._record_execution_continuation_result(
                approval, continuation_output=continuation_output
            )
            if continuation_output is not None and continuation_output["status"] in {
                EngineInvocationStatus.SUCCEEDED.value,
                EngineInvocationStatus.FAILED.value,
                EngineInvocationStatus.CANCELLED.value,
            }:
                wake_outcome = self._wake_execution_agent_after_pipeline_completion(
                    approval, continuation_output=continuation_output, events=events
                )
                if wake_outcome is not None:
                    runtime_outcomes = [wake_outcome]
                    pending_approval_id = wake_outcome.get("waiting_approval_id")
                    teammate_status = str(wake_outcome.get("teammate_status") or "")
                    if pending_approval_id:
                        result_status = HarnessStatus.WAITING_APPROVAL
                    elif continuation_output["status"] in {
                        EngineInvocationStatus.FAILED.value,
                        EngineInvocationStatus.CANCELLED.value,
                    }:
                        result_status = HarnessStatus.FAILED
                    elif (
                        wake_outcome.get("ok") is False
                        or teammate_status == HarnessStatus.FAILED.value
                    ):
                        result_status = HarnessStatus.FAILED
                    elif teammate_status == HarnessStatus.WAITING_APPROVAL.value:
                        result_status = HarnessStatus.WAITING_APPROVAL
                    else:
                        result_status = HarnessStatus.COMPLETED
        elif approval.task_id is not None:
            task = self.repositories.tasks.get(approval.task_id)
            if (
                task is not None
                and task.assigned_ref
                and task.assigned_ref.startswith("agent:")
            ):
                event_bus = MemoryEventBus()
                context = SessionRuntimeContext(
                    repositories=self.repositories,
                    event_sink=event_bus,
                    snapshot=SessionRuntimeSnapshot.load(
                        self.repositories, approval.session_id
                    ),
                    tool_registry=ToolRegistry(),
                    restore_focus=RestoreFocus(
                        task_id=approval.task_id, lane_id=approval.lane_id
                    ),
                    model_factory=self.model_factory,
                    engine_registry=self.engine_registry,
                    bio_research_service=self.bio_research_service,
                    research_adapter=self.research_adapter,
                )
                AgentRuntimeService(context).enqueue_signal(
                    agent_id=task.assigned_ref,
                    task_id=approval.task_id,
                    lane_id=approval.lane_id,
                    correlation_id=approval.approval_id,
                    reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED,
                    source_ref=approval.approval_id,
                )
                events.extend(event.to_dict() for event in event_bus.events)
            runtime_outcomes = self._drain_agent_runtime(approval.session_id, events)
        followup = self._run_master_followup_after_teammates(
            approval.session_id, events, runtime_outcomes
        )
        if followup is not None:
            result_outputs = list(followup.outputs)
            pending_approval_id = followup.pending_approval_id
            if pending_approval_id:
                result_status = HarnessStatus.WAITING_APPROVAL
            elif self._outcomes_include_failure(runtime_outcomes):
                result_status = HarnessStatus.FAILED
            else:
                result_status = followup.status
        self._touch_session(approval.session_id)
        self._extend_with_activity_events(approval.session_id, events)
        self.event_store.append(approval.session_id, events)
        return V3CommandResult(
            session_id=approval.session_id,
            status=HarnessStatus.WAITING_APPROVAL.value
            if pending_approval_id
            else result_status.value,
            outputs=tuple(result_outputs),
            events=events,
            workspace=self.workspace(approval.session_id),
        )

    def _wake_execution_agent_after_pipeline_completion(
        self,
        approval: ApprovalRequest,
        *,
        continuation_output: dict[str, Any],
        events: list[dict[str, Any]],
    ) -> dict[str, Any] | None:
        if approval.task_id is None:
            return None
        task = self.repositories.tasks.get(approval.task_id)
        if task is None:
            return None
        agent_id = (
            task.assigned_ref
            if task.assigned_ref and task.assigned_ref.startswith("agent:")
            else None
        )
        if agent_id is None:
            agent = next(
                (
                    candidate
                    for candidate in self.repositories.agents.list_by_session(
                        approval.session_id
                    )
                    if candidate.role == "executor"
                    and (
                        candidate.task_id == approval.task_id
                        or candidate.lane_id == approval.lane_id
                    )
                ),
                None,
            )
            agent_id = None if agent is None else agent.agent_id
        if agent_id is None:
            return None
        event_bus = MemoryEventBus()
        context = SessionRuntimeContext(
            repositories=self.repositories,
            event_sink=event_bus,
            snapshot=SessionRuntimeSnapshot.load(
                self.repositories, approval.session_id
            ),
            tool_registry=ToolRegistry(),
            restore_focus=RestoreFocus(
                task_id=approval.task_id, lane_id=approval.lane_id
            ),
            model_factory=self.model_factory,
            engine_registry=self.engine_registry,
            bio_research_service=self.bio_research_service,
            research_adapter=self.research_adapter,
        )
        signal = AgentRuntimeService(context).enqueue_signal(
            agent_id=agent_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            correlation_id=approval.approval_id,
            reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED,
            source_ref=approval.approval_id,
        )
        events.extend(event.to_dict() for event in event_bus.events)
        if signal is not None:
            outcomes = self._drain_agent_runtime(approval.session_id, events)
            for outcome in outcomes:
                if outcome.get("signal", {}).get("signal_id") == signal.signal_id:
                    return outcome
            return outcomes[-1] if outcomes else None
        return None

    def _resolve_approval_record(
        self, approval: ApprovalRequest, *, decision: str, actor_ref: str
    ) -> ApprovalRequest:
        del actor_ref
        status = (
            ApprovalRequestStatus.APPROVED
            if decision == "approved"
            else ApprovalRequestStatus.REJECTED
        )
        resolved = ApprovalRequest(
            approval_id=approval.approval_id,
            session_id=approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            kind=approval.kind,
            requested_action=approval.requested_action,
            status=status,
            request_ref=approval.request_ref,
            resolution_ref=approval.resolution_ref,
            created_at=approval.created_at,
            resolved_at=utc_now_iso(),
        )
        self.repositories.approvals.save(resolved)
        return resolved

    def _execution_waiting_invocation_id(self, approval: ApprovalRequest) -> str | None:
        for invocation in self.repositories.invocations.list_by_session(
            approval.session_id
        ):
            if (
                invocation.approval_id == approval.approval_id
                and invocation.engine_name == "execution"
                and invocation.status is EngineInvocationStatus.WAITING_APPROVAL
            ):
                return invocation.invocation_id
        return None

    def _record_execution_continuation_result(
        self,
        approval: ApprovalRequest,
        *,
        continuation_output: dict[str, Any] | None,
    ) -> None:
        if approval.task_id is None:
            return
        task = self.repositories.tasks.get(approval.task_id)
        if task is None:
            return
        agent = next(
            (
                candidate
                for candidate in self.repositories.agents.list_by_session(
                    approval.session_id
                )
                if candidate.role == "executor"
                and (
                    candidate.task_id == approval.task_id
                    or candidate.lane_id == approval.lane_id
                )
            ),
            None,
        )
        correlation_id = (
            None if agent is None else agent.current_correlation_id
        ) or approval.approval_id
        status = None if continuation_output is None else continuation_output["status"]
        summary = (
            "Execution approval resolved."
            if continuation_output is None
            else f"Execution pipeline {status}."
        )
        if continuation_output is not None and continuation_output.get("summary"):
            summary = str(continuation_output["summary"])
        protocol = ProtocolService(self.repositories)
        payload_ref = protocol.persist_payload(
            session_id=approval.session_id,
            document_kind="protocol_payload",
            payload={
                "task_id": approval.task_id,
                "status": status,
                "summary": summary,
                "tool_result": {
                    "tool_name": "execution.pipeline.start",
                    "ok": status == EngineInvocationStatus.SUCCEEDED.value,
                    "status": status,
                    "summary": summary,
                    "payload": continuation_output,
                },
            },
        )
        protocol.reply(
            session_id=approval.session_id,
            sender="agent:executor",
            sender_kind=InboxParticipantKind.AGENT,
            recipient="harness",
            recipient_kind=InboxParticipantKind.HARNESS,
            message_type="delegation_result",
            correlation_id=correlation_id,
            payload_ref=payload_ref,
        )

    def _continue_execution_after_approval(
        self, approval_id: str, decision: str
    ) -> dict[str, Any] | None:
        approval = self.repositories.approvals.get(approval_id)
        if approval is None:
            return None
        if self.engine_registry is None:
            return None
        engine = self.engine_registry.get("execution")
        if engine is None or not hasattr(engine, "continue_after_approval"):
            return None
        waiting = [
            invocation
            for invocation in self.repositories.invocations.list_by_session(
                approval.session_id
            )
            if invocation.approval_id == approval_id
            and invocation.engine_name == "execution"
            and invocation.status is EngineInvocationStatus.WAITING_APPROVAL
        ]
        if not waiting:
            return None
        continuation = engine.continue_after_approval(  # type: ignore[attr-defined]
            invocation_id=waiting[0].invocation_id, resolution=decision
        )
        return {
            "invocation_id": continuation.invocation.invocation_id,
            "status": continuation.invocation.status.value,
            "approval_id": None
            if continuation.approval is None
            else continuation.approval.approval_id,
            "summary": None
            if continuation.parsed_result is None
            else continuation.parsed_result.result_summary,
            "details": None
            if continuation.parsed_result is None
            else continuation.parsed_result.structured_findings,
        }

    def _require_llm_driver(self) -> LlmConversationDriver:
        if self.model_factory is None:
            raise MissingLlmConfigurationError(
                "V3 top-level harness loop requires a configured model_factory; deterministic fallback has been removed."
            )
        return LlmConversationDriver(
            self.model_factory, engine_registry=self.engine_registry
        )

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = TaskBoardService(self.repositories).create_task(
            session_id=str(payload["session_id"]),
            task_id=str(payload.get("task_id") or _new_id("task")),
            subject=str(payload["subject"]),
            description=str(payload.get("description") or ""),
            priority=TaskPriority(
                str(payload.get("priority") or TaskPriority.NORMAL.value)
            ),
            kind=str(payload.get("kind") or "general"),
            status=TaskStatus(str(payload.get("status") or TaskStatus.TODO.value)),
            assigned_ref=payload.get("assigned_ref"),
            lane_id=payload.get("lane_id"),
            blocked_by=tuple(payload.get("blocked_by") or ()),
            failure_summary=payload.get("failure_summary"),
            failure_ref=payload.get("failure_ref"),
        )
        events = [_event("task.created", task.session_id, {"task": task.to_dict()})]
        self._drain_agent_runtime(task.session_id, events)
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {
            "task": task.to_dict(),
            "workspace": self.workspace(task.session_id),
            "events": events,
        }

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        mutation_kwargs: dict[str, Any] = {}
        if "subject" in payload:
            mutation_kwargs["subject"] = payload["subject"]
        if "description" in payload:
            mutation_kwargs["description"] = payload["description"]
        if "status" in payload:
            mutation_kwargs["status"] = TaskStatus(payload["status"])
        if "priority" in payload:
            mutation_kwargs["priority"] = TaskPriority(payload["priority"])
        if "kind" in payload:
            mutation_kwargs["kind"] = payload["kind"]
        if "assigned_ref" in payload:
            mutation_kwargs["assigned_ref"] = payload["assigned_ref"]
        if "lane_id" in payload:
            mutation_kwargs["lane_id"] = payload["lane_id"]
        if "blocked_by" in payload:
            mutation_kwargs["blocked_by"] = tuple(payload["blocked_by"])
        if "failure_summary" in payload:
            mutation_kwargs["failure_summary"] = payload["failure_summary"]
        if "failure_ref" in payload:
            mutation_kwargs["failure_ref"] = payload["failure_ref"]
        mutation = TaskMutation(**mutation_kwargs)
        task = TaskBoardService(self.repositories).update_task(task_id, mutation)
        events = [_event("task.updated", task.session_id, {"task": task.to_dict()})]
        self._drain_agent_runtime(task.session_id, events)
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {
            "task": task.to_dict(),
            "workspace": self.workspace(task.session_id),
            "events": events,
        }

    def create_lane(self, payload: dict[str, Any]) -> dict[str, Any]:
        lane = LaneManager(self.repositories).create_lane(
            session_id=str(payload["session_id"]),
            lane_id=str(payload.get("lane_id") or _new_id("lane")),
            name=str(payload["name"]),
            cwd=str(payload.get("cwd") or "."),
            branch_name=payload.get("branch_name"),
        )
        events = [_event("lane.created", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }

    def claim_lane(self, lane_id: str, *, claimed_ref: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).claim_lane(
            lane_id, claimed_ref=claimed_ref
        )
        events = [_event("lane.claimed", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }

    def keep_lane(self, lane_id: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).keep_lane(lane_id)
        events = [_event("lane.released", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }

    def remove_lane(self, lane_id: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).remove_lane(lane_id)
        events = [_event("lane.removed", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {
            "lane": lane.to_dict(),
            "workspace": self.workspace(lane.session_id),
            "events": events,
        }
