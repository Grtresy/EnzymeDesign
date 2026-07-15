from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
import json
import threading
from typing import Any
from typing import Callable
from typing import ContextManager
from uuid import uuid4

from openzyme_core import CoreRepositories
from openzyme_core import EngineRegistry
from openzyme_core import HarnessEvent
from openzyme_core import HarnessStatus
from openzyme_core import LaneManager
from openzyme_core import RestoreFocus
from openzyme_core import RuntimeConsistencyService
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import TaskBoardService
from openzyme_core import TaskMutation
from openzyme_core import ToolRegistry
from openzyme_core import AgentRuntimeService
from openzyme_core import AgentRuntimeScheduler
from openzyme_core import persist_conversation_message
from openzyme_core import SessionRuntimeLeaseLockedError
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import SandboxRunStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso


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
    _lock: threading.RLock

    def __init__(self) -> None:
        self._events = {}
        self._lock = threading.RLock()

    def append(self, session_id: str, events: list[dict[str, Any]]) -> None:
        with self._lock:
            session_events = self._events.setdefault(session_id, [])
            seen_event_ids = {
                event.get("event_id")
                for event in session_events
                if event.get("event_id")
            }
            seen_trace_ids = {
                event.get("payload", {}).get("trace_id")
                for event in session_events
                if event.get("event_type") == "llm.response.created"
                and isinstance(event.get("payload"), dict)
                and event.get("payload", {}).get("trace_id")
            }
            seen_fingerprints = {_event_fingerprint(event) for event in session_events}
            for event in events:
                event_id = event.get("event_id")
                if event_id and event_id in seen_event_ids:
                    continue
                trace_id = None
                if event.get("event_type") == "llm.response.created" and isinstance(
                    event.get("payload"), dict
                ):
                    trace_id = event["payload"].get("trace_id")
                    if trace_id and trace_id in seen_trace_ids:
                        continue
                fingerprint = _event_fingerprint(event)
                if fingerprint in seen_fingerprints:
                    continue
                session_events.append(event)
                if event_id:
                    seen_event_ids.add(event_id)
                if trace_id:
                    seen_trace_ids.add(trace_id)
                seen_fingerprints.add(fingerprint)

    def list(self, session_id: str) -> list[dict[str, Any]]:
        with self._lock:
            return list(self._events.get(session_id, ()))


@dataclass(slots=True)
class V3EventStoreSink:
    event_store: V3EventStore
    events: list[HarnessEvent]

    def __init__(self, event_store: V3EventStore) -> None:
        self.event_store = event_store
        self.events = []

    def emit(self, event: HarnessEvent) -> None:
        self.events.append(event)
        self.event_store.append(event.session_id, [event.to_dict()])


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
    scheduler_limits: dict[str, int] = field(default_factory=dict)
    signal_notifier: Any | None = None
    runtime_repository_scope_factory: Callable[
        [], ContextManager[CoreRepositories]
    ] | None = None
    engine_registry_factory: Callable[[CoreRepositories], EngineRegistry] | None = None
    operation_lock: threading.RLock = field(default_factory=threading.RLock)

    def _event_sink(self) -> V3EventStoreSink:
        return V3EventStoreSink(self.event_store)

    def _record_events(
        self, session_id: str, target: list[dict[str, Any]], events: list[dict[str, Any]]
    ) -> None:
        target.extend(events)
        self.event_store.append(session_id, events)

    def create_session(
        self,
        *,
        project_id: str,
        objective: str,
        title: str | None = None,
        session_id: str | None = None,
    ) -> dict[str, Any]:
        with self.operation_lock:
            return self._create_session_locked(
                project_id=project_id,
                objective=objective,
                title=title,
                session_id=session_id,
            )

    def _create_session_locked(
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
        self._ensure_master_agent(session.session_id)
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

    def recover_abandoned_sdk_continuations(
        self,
        *,
        actor_ref: str = "host_startup",
    ) -> list[dict[str, Any]]:
        with self.operation_lock:
            return self._recover_abandoned_sdk_continuations_locked(
                actor_ref=actor_ref,
            )

    def _recover_abandoned_sdk_continuations_locked(
        self,
        *,
        actor_ref: str,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        touched_session_ids: set[str] = set()
        for continuation in self.repositories.continuation_states.list_recoverable():
            failed_continuation = self.repositories.continuation_states.fail(
                continuation.continuation_id,
                error_code="operation_recovery_failed",
                error_message="Host restarted before the SDK continuation could be resumed.",
                recovery_failed=True,
            )
            operation = self.repositories.controlled_operations.get(
                continuation.operation_id
            )
            if operation is not None and not operation.status.is_terminal:
                operation = replace(
                    operation,
                    status=ControlledOperationStatus.RECOVERY_FAILED,
                    error_code="operation_recovery_failed",
                    error_summary=(
                        "Host restarted before the SDK continuation could be resumed."
                    ),
                    updated_at=utc_now_iso(),
                )
                self.repositories.controlled_operations.save(operation)
            run = self.repositories.sandbox_runs.get(continuation.sandbox_run_id)
            if run is not None and not run.status.is_terminal:
                now = utc_now_iso()
                self.repositories.sandbox_runs.save(
                    replace(
                        run,
                        status=SandboxRunStatus.FAILED,
                        stderr_summary=(
                            "operation_recovery_failed: Host restarted before the "
                            "SDK continuation could be resumed."
                        ),
                        error_code="operation_recovery_failed",
                        ended_at=now,
                        updated_at=now,
                    )
                )
            event = _event(
                "sdk_controlled_operation.recovery_failed",
                continuation.session_id,
                {
                    "actor_ref": actor_ref,
                    "approval_id": continuation.approval_id,
                    "continuation_id": continuation.continuation_id,
                    "operation_id": continuation.operation_id,
                    "sandbox_run_id": continuation.sandbox_run_id,
                    "status": None
                    if failed_continuation is None
                    else failed_continuation.status.value,
                    "error_code": "operation_recovery_failed",
                },
            )
            self._record_events(continuation.session_id, events, [event])
            touched_session_ids.add(continuation.session_id)
        for session_id in touched_session_ids:
            self._touch_session(session_id)
        return events

    def _ensure_master_agent(self, session_id: str) -> AgentMember:
        existing = self.repositories.agents.get(session_id, "agent:master")
        if existing is not None:
            return existing
        now = utc_now_iso()
        master = AgentMember(
            agent_id="agent:master",
            session_id=session_id,
            lane_id=None,
            task_id=None,
            name="OpenZyme",
            role="master",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now,
            updated_at=now,
            runtime_state="idle",
            idle_since=now,
            nickname="OpenZyme",
            display_name="OpenZyme",
            handle="@openzyme",
        )
        self.repositories.agents.save(master)
        return master

    def workspace(self, session_id: str) -> dict[str, Any]:
        with self.operation_lock:
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

    def _extend_with_trace_events(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        seen_trace_ids = {
            event.get("payload", {}).get("trace_id")
            for event in [*self.event_store.list(session_id), *events]
            if event.get("event_type") == "llm.response.created"
            and isinstance(event.get("payload"), dict)
            and event.get("payload", {}).get("trace_id")
        }
        traces = self.workspace(session_id).get("agent_traces", {})
        for entries in traces.values():
            for payload in entries:
                trace_id = payload.get("trace_id")
                if trace_id in seen_trace_ids:
                    continue
                event = {
                    "event_id": _new_id("evt"),
                    "session_id": session_id,
                    "event_type": "llm.response.created",
                    "created_at": payload.get("created_at") or utc_now_iso(),
                    "payload": payload,
                }
                events.append(event)
                seen_trace_ids.add(trace_id)

    def _extend_with_runtime_consistency_events(
        self, session_id: str, events: list[dict[str, Any]]
    ) -> None:
        audit = RuntimeConsistencyService(self.repositories).audit_session(session_id)
        for warning in audit.warnings:
            events.append(
                _event(
                    "runtime.consistency.warning",
                    session_id,
                    warning.to_dict(),
                )
            )
        attention_items = [
            item
            for item in audit.task_attention
            if item.get("needs_attention") or item.get("runtime_attention")
        ]
        if attention_items:
            events.append(
                _event(
                    "runtime.state_attention",
                    session_id,
                    {"tasks": attention_items},
                )
            )

    def _build_runtime_context(
        self,
        session_id: str,
        *,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
    ) -> SessionRuntimeContext:
        return SessionRuntimeContext(
            repositories=self.repositories,
            event_sink=self._event_sink(),
            snapshot=SessionRuntimeSnapshot.load(self.repositories, session_id),
            tool_registry=ToolRegistry(),
            restore_focus=RestoreFocus(
                task_id=task_id, lane_id=lane_id, skill_keys=skill_keys
            ),
            model_factory=self.model_factory,
            engine_registry=self.engine_registry,
            bio_research_service=self.bio_research_service,
            research_adapter=self.research_adapter,
            signal_notifier=self.signal_notifier,
        )

    async def run_background_runtime_once(
        self,
        *,
        session_id: str,
        worker_id: str = "host-api:background-runtime",
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
    ) -> list[dict[str, Any]]:
        with self.operation_lock:
            if self.repositories.sessions.get(session_id) is None:
                raise KeyError(f"session {session_id!r} does not exist")
            context = self._build_runtime_context(session_id)
            scheduler = self._build_scheduler(
                context, worker_id=worker_id, runtime_mode="background"
            )
        try:
            outcomes = await scheduler.run_once(
                session_id,
                max_signals=max_signals,
                max_steps_per_agent=max_steps_per_agent,
            )
        except SessionRuntimeLeaseLockedError as exc:
            event = self._runtime_locked_event(session_id, exc)
            with self.operation_lock:
                self.event_store.append(session_id, [event])
            return []
        events = [event.to_dict() for event in context.event_sink.events]
        with self.operation_lock:
            self._touch_session(session_id)
            self._extend_with_trace_events(session_id, events)
            self._extend_with_activity_events(session_id, events)
            self._extend_with_runtime_consistency_events(session_id, events)
            self.event_store.append(session_id, events)
        return [outcome.to_dict() for outcome in outcomes]

    def _build_scheduler(
        self,
        context: SessionRuntimeContext,
        *,
        worker_id: str,
        runtime_mode: str = "manual_drain",
    ) -> AgentRuntimeScheduler:
        return AgentRuntimeScheduler(
            context,
            worker_id=worker_id,
            runtime_mode=runtime_mode,
            max_global_concurrency=int(self.scheduler_limits.get("global", 1)),
            max_session_concurrency=int(self.scheduler_limits.get("session", 1)),
            max_agent_concurrency=int(self.scheduler_limits.get("agent", 1)),
            repository_scope_factory=self.runtime_repository_scope_factory,
            engine_registry_factory=self.engine_registry_factory,
        )

    def _runtime_locked_event(
        self, session_id: str, exc: SessionRuntimeLeaseLockedError
    ) -> dict[str, Any]:
        return _event(
            "runtime.session_locked",
            session_id,
            {
                "status": "locked",
                "owner_id": exc.active_lease.owner_id,
                "mode": exc.active_lease.mode.value,
                "lease_token": exc.active_lease.lease_token,
                "fencing_token": exc.active_lease.fencing_token,
                "expires_at": exc.active_lease.expires_at,
                "retry_after_seconds": exc.retry_after_seconds,
            },
        )

    def _drain_pending_agent_signals(
        self,
        session_id: str,
        events: list[dict[str, Any]],
        *,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        auto_enqueue_ready_tasks: bool = False,
        worker_id: str = "host-api:runtime-drain",
    ) -> list[dict[str, Any]]:
        context = self._build_runtime_context(session_id)
        scheduler = self._build_scheduler(
            context, worker_id=worker_id, runtime_mode="manual_drain"
        )
        outcomes = scheduler.run_once_sync(
            session_id,
            max_signals=max_signals,
            max_steps_per_agent=max_steps_per_agent,
            auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
        )
        events.extend(event.to_dict() for event in context.event_sink.events)
        return [outcome.to_dict() for outcome in outcomes]

    def drain_runtime(
        self,
        *,
        session_id: str,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        auto_enqueue_ready_tasks: bool = False,
    ) -> V3CommandResult:
        with self.operation_lock:
            if self.repositories.sessions.get(session_id) is None:
                raise KeyError(f"session {session_id!r} does not exist")
        events: list[dict[str, Any]] = []
        try:
            outcomes = self._drain_pending_agent_signals(
                session_id,
                events,
                max_signals=max_signals,
                max_steps_per_agent=max_steps_per_agent,
                auto_enqueue_ready_tasks=auto_enqueue_ready_tasks,
            )
        except SessionRuntimeLeaseLockedError as exc:
            with self.operation_lock:
                locked_event = self._runtime_locked_event(session_id, exc)
                events.append(locked_event)
                self.event_store.append(session_id, events)
                workspace = self.workspace(session_id)
            return V3CommandResult(
                session_id=session_id,
                status="locked",
                outputs=(),
                events=events,
                workspace=workspace,
            )
        with self.operation_lock:
            has_pending_approval = bool(
                self.repositories.approvals.list_pending_by_session(session_id)
            )
            if has_pending_approval or self._outcomes_include_waiting_approval(outcomes):
                response_status = HarnessStatus.WAITING_APPROVAL
            elif self._outcomes_include_failure(outcomes):
                response_status = HarnessStatus.FAILED
            else:
                response_status = HarnessStatus.COMPLETED
            master_outputs = tuple(
                output
                for outcome in outcomes
                if isinstance(outcome.get("agent"), dict)
                and outcome["agent"].get("agent_id") == "agent:master"
                for output in outcome.get("outputs", ())
            )
            response_outputs = () if has_pending_approval else master_outputs
            self._touch_session(session_id)
            self._extend_with_trace_events(session_id, events)
            self._extend_with_activity_events(session_id, events)
            self._extend_with_runtime_consistency_events(session_id, events)
            self.event_store.append(session_id, events)
            workspace = self.workspace(session_id)
        return V3CommandResult(
            session_id=session_id,
            status=response_status.value,
            outputs=response_outputs,
            events=events,
            workspace=workspace,
        )

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
        if any(outcome.get("ok") is False for outcome in outcomes):
            return True
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

    def post_message(
        self,
        *,
        session_id: str,
        message: str | None,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
    ) -> V3CommandResult:
        with self.operation_lock:
            return self._post_message_locked(
                session_id=session_id,
                message=message,
                task_id=task_id,
                lane_id=lane_id,
                skill_keys=skill_keys,
            )

    def _post_message_locked(
        self,
        *,
        session_id: str,
        message: str | None,
        task_id: str | None = None,
        lane_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
    ) -> V3CommandResult:
        if self.repositories.sessions.get(session_id) is None:
            raise KeyError(f"session {session_id!r} does not exist")
        self._ensure_master_agent(session_id)
        events: list[dict[str, Any]] = []
        message_id = None
        if message:
            message_id = _new_id("msg")
            created_at = utc_now_iso()
            payload_ref = persist_conversation_message(
                self.repositories,
                session_id=session_id,
                message_id=message_id,
                role="user",
                content=message,
                created_at=created_at,
            )
            self.repositories.inbox.save(
                InboxMessage(
                    message_id=message_id,
                    session_id=session_id,
                    sender="user",
                    sender_kind=InboxParticipantKind.USER,
                    recipient="harness",
                    recipient_kind=InboxParticipantKind.HARNESS,
                    message_type="user_message",
                    correlation_id=None,
                    payload_ref=payload_ref,
                    status=InboxStatus.DELIVERED,
                    created_at=created_at,
                )
            )
            self._record_events(
                session_id,
                events,
                [_event("conversation.user_message", session_id, {"content": message})],
            )
        context = self._build_runtime_context(
            session_id, task_id=task_id, lane_id=lane_id, skill_keys=skill_keys
        )
        AgentRuntimeService(context).enqueue_signal(
            session_id=session_id,
            agent_id="agent:master",
            task_id=task_id,
            lane_id=lane_id,
            correlation_id=None,
            reason=AgentRuntimeSignalReason.INBOX_UNREAD,
            source_ref=message_id,
        )
        events.extend(event.to_dict() for event in context.event_sink.events)
        has_pending_approval = bool(
            self.repositories.approvals.list_pending_by_session(session_id)
        )
        response_status = (
            HarnessStatus.WAITING_APPROVAL
            if has_pending_approval
            else HarnessStatus.COMPLETED
        )
        response_outputs = ()
        self._touch_session(session_id)
        self._extend_with_trace_events(session_id, events)
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
        with self.operation_lock:
            return self._resolve_approval_locked(
                approval_id, decision=decision, actor_ref=actor_ref
            )

    def _resolve_approval_locked(
        self, approval_id: str, *, decision: str, actor_ref: str = "user"
    ) -> V3CommandResult:
        approval = self.repositories.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"approval {approval_id!r} does not exist")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        if approval.status is not ApprovalRequestStatus.PENDING:
            if approval.kind == "sdk_controlled_operation":
                return self._resolve_existing_sdk_controlled_operation(
                    approval,
                    decision=decision,
                )
            raise ValueError(f"approval {approval_id!r} is not pending")
        events: list[dict[str, Any]] = []
        self._record_events(
            approval.session_id,
            events,
            [
                _event(
                    "approval.resolved",
                    approval.session_id,
                    {
                        "approval_id": approval_id,
                        "decision": decision,
                        "actor_ref": actor_ref,
                    },
                )
            ],
        )
        resolved = self._resolve_approval_record(approval, decision=decision, actor_ref=actor_ref)
        if approval.kind == "sdk_controlled_operation":
            self._resolve_sdk_controlled_operation(
                resolved,
                decision=decision,
                events=events,
            )
        else:
            assigned_agent_id = self._approval_assigned_agent_id(approval)
            if assigned_agent_id is not None:
                self._enqueue_approval_resolved_signal(
                    approval, agent_id=assigned_agent_id, events=events
                )
            else:
                self._ensure_master_agent(approval.session_id)
                self._enqueue_approval_resolved_signal(
                    approval, agent_id="agent:master", events=events
                )
        self._touch_session(approval.session_id)
        self._extend_with_trace_events(approval.session_id, events)
        self._extend_with_activity_events(approval.session_id, events)
        self.event_store.append(approval.session_id, events)
        return V3CommandResult(
            session_id=approval.session_id,
            status=HarnessStatus.COMPLETED.value,
            outputs=(),
            events=events,
            workspace=self.workspace(approval.session_id),
        )

    def _resolve_existing_sdk_controlled_operation(
        self,
        approval: ApprovalRequest,
        *,
        decision: str,
    ) -> V3CommandResult:
        expected_status = (
            ApprovalRequestStatus.APPROVED
            if decision == "approved"
            else ApprovalRequestStatus.REJECTED
        )
        if approval.status is not expected_status:
            raise ValueError(
                f"approval_state_conflict: approval {approval.approval_id!r} "
                f"is already {approval.status.value}"
            )
        events: list[dict[str, Any]] = []
        self._resolve_sdk_controlled_operation(
            approval,
            decision=decision,
            events=events,
        )
        self._extend_with_trace_events(approval.session_id, events)
        self._extend_with_activity_events(approval.session_id, events)
        self.event_store.append(approval.session_id, events)
        return V3CommandResult(
            session_id=approval.session_id,
            status=HarnessStatus.COMPLETED.value,
            outputs=(),
            events=events,
            workspace=self.workspace(approval.session_id),
        )

    def _resolve_sdk_controlled_operation(
        self,
        approval: ApprovalRequest,
        *,
        decision: str,
        events: list[dict[str, Any]],
    ) -> None:
        continuation = self.repositories.continuation_states.resolve_for_approval(
            approval.approval_id,
            decision=decision,
        )
        operation = self.repositories.controlled_operations.get_by_approval_id(
            approval.approval_id
        )
        if operation is not None:
            status = operation.status
            error_code = operation.error_code
            error_summary = operation.error_summary
            if decision == "rejected":
                status = ControlledOperationStatus.FAILED
                error_code = "approval_rejected"
                error_summary = "User rejected supervised SDK operation."
            updated = replace(
                operation,
                approval_state=approval.status.value,
                status=status,
                error_code=error_code,
                error_summary=error_summary,
                updated_at=utc_now_iso(),
            )
            self.repositories.controlled_operations.save(updated)
        self._record_events(
            approval.session_id,
            events,
            [
                _event(
                    "sdk_controlled_operation.approval_resolved",
                    approval.session_id,
                    {
                        "approval_id": approval.approval_id,
                        "operation_id": None if operation is None else operation.operation_id,
                        "continuation_id": None if continuation is None else continuation.continuation_id,
                        "decision": decision,
                    },
                )
            ],
        )

    def _enqueue_approval_resolved_signal(
        self,
        approval: ApprovalRequest,
        *,
        agent_id: str | None,
        events: list[dict[str, Any]],
    ) -> None:
        if agent_id is None:
            return
        if approval.task_id is None and agent_id != "agent:master":
            return
        context = self._build_runtime_context(
            approval.session_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
        )
        AgentRuntimeService(context).enqueue_signal(
            session_id=approval.session_id,
            agent_id=agent_id,
            task_id=approval.task_id,
            lane_id=approval.lane_id,
            correlation_id=approval.approval_id,
            reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED,
            source_ref=approval.approval_id,
        )
        events.extend(event.to_dict() for event in context.event_sink.events)

    def _approval_assigned_agent_id(self, approval: ApprovalRequest) -> str | None:
        if approval.task_id is None:
            return None
        task = self.repositories.tasks.get(approval.task_id)
        if (
            task is not None
            and task.assigned_ref
            and task.assigned_ref.startswith("agent:")
        ):
            return task.assigned_ref
        agent = next(
            (
                candidate
                for candidate in self.repositories.agents.list_by_session(
                    approval.session_id
                )
                if (
                    candidate.task_id == approval.task_id
                    or (
                        approval.lane_id is not None
                        and candidate.lane_id == approval.lane_id
                    )
                )
            ),
            None,
        )
        return None if agent is None else agent.agent_id

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

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        with self.operation_lock:
            return self._create_task_locked(payload)

    def _create_task_locked(self, payload: dict[str, Any]) -> dict[str, Any]:
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
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {
            "task": task.to_dict(),
            "workspace": self.workspace(task.session_id),
            "events": events,
        }

    def update_task(self, task_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        with self.operation_lock:
            return self._update_task_locked(task_id, payload)

    def _update_task_locked(
        self, task_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
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
        task = TaskBoardService(self.repositories).edit_task(task_id, mutation)
        events = [_event("task.updated", task.session_id, {"task": task.to_dict()})]
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
