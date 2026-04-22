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
from openzyme_core import HarnessStep
from openzyme_core import HarnessStatus
from openzyme_core import LaneManager
from openzyme_core import LlmConversationDriver
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import ResumeDecision
from openzyme_core import ResumeEnvelope
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import TaskBoardService
from openzyme_core import TaskMutation
from openzyme_core import ToolInvocation
from openzyme_core import ToolResult
from openzyme_core import run_agent_harness_loop
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
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
class EchoConversationDriver:
    message: str | None

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep:
        del context, harness_input
        if tool_results:
            rendered = "; ".join(f"{result.tool_name}: {result.content}" for result in tool_results)
            return HarnessStep(assistant_message=rendered)
        if self.message:
            return HarnessStep(assistant_message=f"Received: {self.message}")
        return HarnessStep(assistant_message="Workspace is ready.")


@dataclass(frozen=True, slots=True)
class EngineBackedConversationDriver:
    message: str | None

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[ToolResult, ...],
    ) -> HarnessStep:
        if tool_results:
            return self._after_tool_result(context, tool_results[0])
        if harness_input.resume is not None:
            step = self._resume_waiting_invocation(context, harness_input.resume.decision)
            if step is not None:
                return step
        task = self._select_task(context, harness_input)
        if task is None or task.kind not in {"research", "execution", "reporting"}:
            return EchoConversationDriver(self.message).plan(context, harness_input, tool_results)
        return self._start_task(task)

    def _select_task(self, context: SessionRuntimeContext, harness_input: HarnessInput) -> Task | None:
        focus = harness_input.restore_focus
        if focus is not None and focus.task_id is not None:
            task = context.repositories.tasks.get(focus.task_id)
            if task is not None and task.session_id == context.snapshot.session.session_id:
                return task
        for task in context.snapshot.ready_tasks:
            if task.kind in {"research", "execution", "reporting"}:
                return task
        return None

    def _start_task(self, task: Task) -> HarnessStep:
        if task.status not in {TaskStatus.TODO, TaskStatus.BLOCKED}:
            return HarnessStep(assistant_message=f"Task {task.task_id} is already {task.status.value}.")
        invocation = self._tool_for_task(task)
        return HarnessStep(
            assistant_message=f"Starting {task.kind} task {task.task_id}.",
            tool_invocations=(invocation,),
            task_updates=(
                replace(
                    task,
                    status=TaskStatus.IN_PROGRESS,
                    updated_at=utc_now_iso(),
                ),
            ),
            next_focus=RestoreFocus(task_id=task.task_id, lane_id=task.lane_id),
        )

    def _tool_for_task(self, task: Task) -> ToolInvocation:
        if task.kind == "research":
            return ToolInvocation(
                call_id=f"call_research_{task.task_id}",
                tool_name="deep_research.start",
                arguments={"task_id": task.task_id, "brief": task.description or task.subject},
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        if task.kind == "execution":
            return ToolInvocation(
                call_id=f"call_execution_{task.task_id}",
                tool_name="execution.start",
                arguments={
                    "task_id": task.task_id,
                    "handoff": {
                        "execution_goal": task.description or task.subject,
                        "catalog_tool_id": "fpocket",
                        "require_approval": True,
                    },
                },
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        return ToolInvocation(
            call_id=f"call_reporting_{task.task_id}",
            tool_name="reporting.start",
            arguments={"task_id": task.task_id, "report_brief": task.description or task.subject},
            task_id=task.task_id,
            lane_id=task.lane_id,
        )

    def _resume_waiting_invocation(
        self,
        context: SessionRuntimeContext,
        decision: ResumeDecision,
    ) -> HarnessStep | None:
        waiting = [
            invocation
            for invocation in context.snapshot.active_invocations
            if invocation.status is EngineInvocationStatus.WAITING_APPROVAL
            and invocation.engine_name == "execution"
            and invocation.approval_id is not None
        ]
        if not waiting:
            return None
        invocation = waiting[0]
        return HarnessStep(
            assistant_message=f"Resuming execution invocation {invocation.invocation_id}.",
            tool_invocations=(
                ToolInvocation(
                    call_id=f"call_resume_{invocation.invocation_id}",
                    tool_name="execution.resume",
                    arguments={
                        "invocation_id": invocation.invocation_id,
                        "resolution": f"Approval {decision.value} by user.",
                    },
                    task_id=invocation.task_id,
                    lane_id=invocation.lane_id,
                ),
            ),
            next_focus=RestoreFocus(task_id=invocation.task_id, lane_id=invocation.lane_id),
        )

    def _after_tool_result(self, context: SessionRuntimeContext, result: ToolResult) -> HarnessStep:
        task = None if result.task_id is None else context.repositories.tasks.get(result.task_id)
        status = self._invocation_status_from_result(result)
        if status == EngineInvocationStatus.WAITING_APPROVAL.value:
            return HarnessStep(assistant_message=f"{result.tool_name} is waiting for approval.")
        if result.ok and status not in {EngineInvocationStatus.FAILED.value, EngineInvocationStatus.CANCELLED.value}:
            updates = ()
            if task is not None:
                updates = (replace(task, status=TaskStatus.COMPLETED, updated_at=utc_now_iso()),)
            return HarnessStep(
                assistant_message=f"{result.tool_name} completed.",
                task_updates=updates,
            )
        updates = ()
        if task is not None:
            updates = (replace(task, status=TaskStatus.BLOCKED, updated_at=utc_now_iso()),)
        return HarnessStep(
            assistant_message=f"{result.tool_name} did not complete successfully.",
            task_updates=updates,
        )

    def _invocation_status_from_result(self, result: ToolResult) -> str | None:
        try:
            payload = json.loads(result.content)
        except json.JSONDecodeError:
            return None
        if isinstance(payload, dict):
            invocation = payload.get("invocation")
            if isinstance(invocation, dict) and invocation.get("status") is not None:
                return str(invocation["status"])
        return None


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
        return SessionProjectionBuilder(self.repositories).build_session_workspace(session_id).to_dict()

    def list_sessions(self, project_id: str) -> list[dict[str, Any]]:
        summaries: list[dict[str, Any]] = []
        for session in self.repositories.sessions.list_by_project(project_id):
            messages = self.repositories.inbox.list_by_session(session.session_id)
            approvals = self.repositories.approvals.list_by_session(session.session_id)
            latest_preview = ""
            for message in reversed(messages):
                if message.message_type not in {"user_message", "assistant_message"} or not message.payload_ref:
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
                        1 for approval in approvals if approval.status is ApprovalRequestStatus.PENDING
                    ),
                }
            )
        summaries.sort(key=lambda item: (item["updated_at"], item["session_id"]), reverse=True)
        return summaries

    def events(self, session_id: str) -> list[dict[str, Any]]:
        return self.event_store.list(session_id)

    def _touch_session(self, session_id: str) -> None:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            return
        next_updated_at = utc_now_iso()
        if next_updated_at <= session.updated_at:
            next_updated_at = (datetime.fromisoformat(session.updated_at) + timedelta(seconds=1)).isoformat()
        self.repositories.sessions.save(replace(session, updated_at=next_updated_at))

    def _extend_with_activity_events(self, session_id: str, events: list[dict[str, Any]]) -> None:
        existing = {_event_fingerprint(event) for event in self.event_store.list(session_id)}
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
                restore_focus=RestoreFocus(task_id=task_id, lane_id=lane_id, skill_keys=skill_keys),
            ),
            driver=driver,
            engine_registry=self.engine_registry,
            event_sink=event_bus,
        )
        events: list[dict[str, Any]] = []
        if message:
            events.append(_event("conversation.user_message", session_id, {"content": message}))
        events.extend(event.to_dict() for event in result.events)
        for output in result.outputs:
            events.append(_event("conversation.assistant_message", session_id, {"content": output}))
        self._touch_session(session_id)
        self._extend_with_activity_events(session_id, events)
        self.event_store.append(session_id, events)
        return V3CommandResult(
            session_id=session_id,
            status=result.status.value,
            outputs=result.outputs,
            events=events,
            workspace=self.workspace(session_id),
        )

    def resolve_approval(self, approval_id: str, *, decision: str, actor_ref: str = "user") -> V3CommandResult:
        approval = self.repositories.approvals.get(approval_id)
        if approval is None:
            raise KeyError(f"approval {approval_id!r} does not exist")
        if approval.status is not ApprovalRequestStatus.PENDING:
            raise ValueError(f"approval {approval_id!r} is not pending")
        if decision not in {"approved", "rejected"}:
            raise ValueError("decision must be 'approved' or 'rejected'")
        driver = self._require_llm_driver()
        result = run_agent_harness_loop(
            self.repositories,
            HarnessInput(
                session_id=approval.session_id,
                resume=ResumeEnvelope(
                    approval_id=approval_id,
                    decision=ResumeDecision.APPROVED if decision == "approved" else ResumeDecision.REJECTED,
                    actor_ref=actor_ref,
                ),
                restore_focus=RestoreFocus(task_id=approval.task_id, lane_id=approval.lane_id),
            ),
            driver=driver,
            engine_registry=self.engine_registry,
        )
        events = [
            _event(
                "approval.resolved",
                approval.session_id,
                {"approval_id": approval_id, "decision": decision, "actor_ref": actor_ref},
            )
        ]
        events.extend(event.to_dict() for event in result.events)
        for output in result.outputs:
            events.append(_event("conversation.assistant_message", approval.session_id, {"content": output}))
        self._touch_session(approval.session_id)
        self._extend_with_activity_events(approval.session_id, events)
        self.event_store.append(approval.session_id, events)
        return V3CommandResult(
            session_id=approval.session_id,
            status=HarnessStatus.WAITING_APPROVAL.value if result.pending_approval_id else result.status.value,
            outputs=result.outputs,
            events=events,
            workspace=self.workspace(approval.session_id),
        )

    def _require_llm_driver(self) -> LlmConversationDriver:
        if self.model_factory is None:
            raise MissingLlmConfigurationError(
                "V3 top-level harness loop requires a configured model_factory; deterministic fallback has been removed."
            )
        return LlmConversationDriver(self.model_factory, engine_registry=self.engine_registry)

    def create_task(self, payload: dict[str, Any]) -> dict[str, Any]:
        task = TaskBoardService(self.repositories).create_task(
            session_id=str(payload["session_id"]),
            task_id=str(payload.get("task_id") or _new_id("task")),
            subject=str(payload["subject"]),
            description=str(payload.get("description") or ""),
            priority=TaskPriority(str(payload.get("priority") or TaskPriority.NORMAL.value)),
            kind=str(payload.get("kind") or "general"),
            status=TaskStatus(str(payload.get("status") or TaskStatus.TODO.value)),
            assigned_ref=payload.get("assigned_ref"),
            lane_id=payload.get("lane_id"),
            blocked_by=tuple(payload.get("blocked_by") or ()),
        )
        events = [_event("task.created", task.session_id, {"task": task.to_dict()})]
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {"task": task.to_dict(), "workspace": self.workspace(task.session_id), "events": events}

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
        mutation = TaskMutation(**mutation_kwargs)
        task = TaskBoardService(self.repositories).update_task(task_id, mutation)
        events = [_event("task.updated", task.session_id, {"task": task.to_dict()})]
        self._extend_with_activity_events(task.session_id, events)
        self.event_store.append(task.session_id, events)
        return {"task": task.to_dict(), "workspace": self.workspace(task.session_id), "events": events}

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
        return {"lane": lane.to_dict(), "workspace": self.workspace(lane.session_id), "events": events}

    def claim_lane(self, lane_id: str, *, claimed_ref: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).claim_lane(lane_id, claimed_ref=claimed_ref)
        events = [_event("lane.claimed", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {"lane": lane.to_dict(), "workspace": self.workspace(lane.session_id), "events": events}

    def keep_lane(self, lane_id: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).keep_lane(lane_id)
        events = [_event("lane.released", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {"lane": lane.to_dict(), "workspace": self.workspace(lane.session_id), "events": events}

    def remove_lane(self, lane_id: str) -> dict[str, Any]:
        lane = LaneManager(self.repositories).remove_lane(lane_id)
        events = [_event("lane.removed", lane.session_id, {"lane": lane.to_dict()})]
        self._extend_with_activity_events(lane.session_id, events)
        self.event_store.append(lane.session_id, events)
        return {"lane": lane.to_dict(), "workspace": self.workspace(lane.session_id), "events": events}
