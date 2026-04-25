from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import InboxStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .task_board import TaskBoardService
from .task_board import TaskMutation
from .teammate_roster import teammate_role_for_task_kind
from .teammates import finalize_teammate_result
from .teammates import run_teammate_loop


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class AgentRuntimeOutcome:
    signal: AgentRuntimeSignal
    task: Task | None
    agent: AgentMember | None
    ok: bool
    summary: str
    teammate_status: str | None = None
    outputs: tuple[str, ...] = ()
    waiting_approval_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "signal": self.signal.to_dict(),
            "task": None if self.task is None else self.task.to_dict(),
            "agent": None if self.agent is None else self.agent.to_dict(),
            "ok": self.ok,
            "summary": self.summary,
            "teammate_status": self.teammate_status,
            "outputs": list(self.outputs),
            "waiting_approval_id": self.waiting_approval_id,
        }


@dataclass(slots=True)
class AgentRuntimeService:
    context: SessionRuntimeContext

    def enqueue_signal(
        self,
        *,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        task_id: str | None = None,
        lane_id: str | None = None,
        correlation_id: str | None = None,
        source_ref: str | None = None,
    ) -> AgentRuntimeSignal | None:
        agent = self.context.repositories.agents.get(agent_id)
        if agent is None:
            return None
        existing = self.context.repositories.runtime_signals.find_pending_duplicate(
            session_id=agent.session_id,
            agent_id=agent_id,
            reason=reason,
            source_ref=source_ref,
        )
        if existing is not None:
            return existing
        signal = AgentRuntimeSignal(
            signal_id=_new_id("sig"),
            session_id=agent.session_id,
            agent_id=agent_id,
            task_id=task_id,
            lane_id=lane_id,
            correlation_id=correlation_id,
            reason=reason,
            source_ref=source_ref,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at=utc_now_iso(),
        )
        self.context.repositories.runtime_signals.save(signal)
        return signal

    def auto_enqueue_ready_tasks(self, session_id: str) -> tuple[AgentRuntimeSignal, ...]:
        signals: list[AgentRuntimeSignal] = []
        idle_agents = [
            agent
            for agent in self.context.repositories.agents.list_by_session(session_id)
            if agent.status in {AgentMemberStatus.IDLE, AgentMemberStatus.ACTIVE}
        ]
        for task in self.context.repositories.tasks.list_ready_by_session(session_id):
            if task.assigned_ref:
                continue
            role = teammate_role_for_task_kind(task.kind)
            if role is None:
                continue
            agent = next((candidate for candidate in idle_agents if candidate.role == role), None)
            if agent is None:
                continue
            signal = self.enqueue_signal(
                agent_id=agent.agent_id,
                task_id=task.task_id,
                lane_id=task.lane_id,
                correlation_id=None,
                reason=AgentRuntimeSignalReason.TASK_AVAILABLE,
                source_ref=task.task_id,
            )
            if signal is not None:
                signals.append(signal)
        return tuple(signals)

    def drain_session(
        self,
        session_id: str,
        *,
        max_signals: int = 3,
        max_steps_per_agent: int = 8,
        signal_ids: set[str] | None = None,
    ) -> tuple[AgentRuntimeOutcome, ...]:
        if self.context.model_factory is None:
            return ()
        pending = self.context.repositories.runtime_signals.list_pending_by_session(session_id)
        if signal_ids is not None:
            pending = [signal for signal in pending if signal.signal_id in signal_ids]
        outcomes: list[AgentRuntimeOutcome] = []
        for signal in pending[:max_signals]:
            outcomes.append(self.wake_agent(signal, max_steps=max_steps_per_agent))
        return tuple(outcomes)

    def wake_agent(self, signal: AgentRuntimeSignal, *, max_steps: int = 8) -> AgentRuntimeOutcome:
        now = utc_now_iso()
        claimed = replace(signal, status=AgentRuntimeSignalStatus.CLAIMED, claimed_at=now)
        self.context.repositories.runtime_signals.save(claimed)
        agent = self.context.repositories.agents.get(signal.agent_id)
        if agent is None:
            failed = replace(claimed, status=AgentRuntimeSignalStatus.FAILED, completed_at=utc_now_iso(), error_message="agent not found")
            self.context.repositories.runtime_signals.save(failed)
            return AgentRuntimeOutcome(signal=failed, task=None, agent=None, ok=False, summary="agent not found")

        payload = self._payload_for_signal(signal)
        task = self._resolve_task(signal, agent, payload)
        lane_id = signal.lane_id or (None if payload is None else payload.get("lane_id"))
        agent = self._update_agent(
            agent,
            status=AgentMemberStatus.WORKING,
            task_id=None if task is None else task.task_id,
            lane_id=str(lane_id) if lane_id is not None else (None if task is None else task.lane_id),
            correlation_id=signal.correlation_id,
            wakeup_reason=signal.reason.value,
            runtime_state="working",
            last_active_at=now,
            idle_since=None,
        )
        self.context.emit(
            "agent.woken",
            {
                "agent_id": agent.agent_id,
                "signal_id": signal.signal_id,
                "reason": signal.reason.value,
                "task_id": agent.task_id,
                "lane_id": agent.lane_id,
                "correlation_id": signal.correlation_id,
            },
        )
        consumed_message_ids: list[str] = []
        for message in self.context.repositories.inbox.list_unread_for_recipient(agent.session_id, agent.agent_id):
            consumed_message_ids.append(message.message_id)
            self.context.repositories.inbox.set_status(message.message_id, InboxStatus.DELIVERED)

        if task is None:
            completed = replace(claimed, status=AgentRuntimeSignalStatus.COMPLETED, completed_at=utc_now_iso())
            self.context.repositories.runtime_signals.save(completed)
            agent = self._update_agent(agent, status=AgentMemberStatus.IDLE, runtime_state="idle", idle_since=utc_now_iso())
            self.context.emit("agent.idle", {"agent_id": agent.agent_id, "signal_id": signal.signal_id})
            return AgentRuntimeOutcome(signal=completed, task=None, agent=agent, ok=True, summary="No focused task for wakeup.")

        service = TaskBoardService(self.context.repositories, event_emitter=self.context.emit)
        if task.status in {TaskStatus.TODO, TaskStatus.BLOCKED}:
            task = service.update_task(task.task_id, TaskMutation(assigned_ref=agent.agent_id, status=TaskStatus.IN_PROGRESS))
            if signal.reason is AgentRuntimeSignalReason.TASK_AVAILABLE:
                self.context.emit(
                    "agent.task_claimed",
                    {"agent_id": agent.agent_id, "task_id": task.task_id, "signal_id": signal.signal_id},
                )

        instructions = self._instructions_for_signal(signal, task, payload)
        correlation_id = signal.correlation_id or _new_id("corr")
        result = run_teammate_loop(
            self.context,
            agent_id=agent.agent_id,
            role=agent.role,
            task_id=task.task_id,
            lane_id=task.lane_id,
            correlation_id=correlation_id,
            instructions=instructions,
            max_steps=max_steps,
        )
        summary, final_status = finalize_teammate_result(
            self.context,
            agent_id=agent.agent_id,
            task_id=task.task_id,
            correlation_id=correlation_id,
            result=result,
        )
        is_diagnostic = self._is_diagnostic_signal(signal, payload)
        if result.pending_approval_id is not None:
            task = service.update_task(task.task_id, TaskMutation(status=TaskStatus.BLOCKED))
            signal_status = AgentRuntimeSignalStatus.COMPLETED
            ok = True
        elif final_status is AgentMemberStatus.IDLE:
            if not is_diagnostic:
                task = service.update_task(task.task_id, TaskMutation(status=TaskStatus.COMPLETED))
            signal_status = AgentRuntimeSignalStatus.COMPLETED
            ok = True
        else:
            signal_status = AgentRuntimeSignalStatus.FAILED
            ok = False

        completed = replace(
            claimed,
            status=signal_status,
            completed_at=utc_now_iso(),
            error_message=None if ok else summary,
        )
        self.context.repositories.runtime_signals.save(completed)
        for message_id in consumed_message_ids:
            self.context.repositories.inbox.set_status(message_id, InboxStatus.ACKNOWLEDGED)
        for pending_signal in self.context.repositories.runtime_signals.list_pending_by_session(agent.session_id):
            if pending_signal.source_ref in set(consumed_message_ids):
                self.context.repositories.runtime_signals.save(
                    replace(
                        pending_signal,
                        status=AgentRuntimeSignalStatus.COMPLETED,
                        completed_at=utc_now_iso(),
                    )
                )
        agent = self._update_agent(
            self.context.repositories.agents.get(agent.agent_id) or agent,
            status=final_status,
            runtime_state=final_status.value,
            last_active_at=utc_now_iso(),
            idle_since=utc_now_iso() if final_status is AgentMemberStatus.IDLE else None,
        )
        if final_status is AgentMemberStatus.IDLE:
            self.context.emit("agent.idle", {"agent_id": agent.agent_id, "signal_id": signal.signal_id, "task_id": task.task_id})
        return AgentRuntimeOutcome(
            signal=completed,
            task=task,
            agent=agent,
            ok=ok,
            summary=summary,
            teammate_status=result.status.value,
            outputs=tuple(result.outputs),
            waiting_approval_id=result.pending_approval_id,
        )

    def _payload_for_signal(self, signal: AgentRuntimeSignal) -> dict[str, Any] | None:
        message = self._message_for_signal(signal)
        if message is None or message.payload_ref is None:
            return None
        document = self.context.repositories.engine_documents.get(message.payload_ref)
        if document is None:
            return None
        return dict(document.payload)

    def _message_for_signal(self, signal: AgentRuntimeSignal):
        if not signal.source_ref:
            return None
        return self.context.repositories.inbox.get(signal.source_ref)

    def _resolve_task(self, signal: AgentRuntimeSignal, agent: AgentMember, payload: dict[str, Any] | None) -> Task | None:
        task_id = signal.task_id
        if task_id is None and payload is not None:
            task_id = payload.get("task_id")
        if task_id is None:
            task_id = agent.task_id
        if task_id is None:
            return None
        return self.context.repositories.tasks.get(str(task_id))

    def _instructions_for_signal(self, signal: AgentRuntimeSignal, task: Task, payload: dict[str, Any] | None) -> str:
        message = self._message_for_signal(signal)
        if payload is not None:
            instructions = payload.get("instructions")
            if self._is_diagnostic_signal(signal, payload):
                lines = [
                    "Handle this diagnostic request from the team protocol.",
                    f"Message type: {None if message is None else message.message_type}",
                    f"Sender: {None if message is None else message.sender}",
                    f"Correlation id: {signal.correlation_id or (None if message is None else message.correlation_id)}",
                    f"Task id: {payload.get('task_id') or task.task_id}",
                ]
                if payload.get("question"):
                    lines.append(f"Diagnostic question: {payload['question']}")
                if payload.get("failed_summary"):
                    lines.append(f"Failed summary: {payload['failed_summary']}")
                if instructions:
                    lines.append(f"Instructions: {instructions}")
                if payload.get("expected_response"):
                    lines.append(f"Expected response: {payload['expected_response']}")
                lines.append(
                    "Reply on the same correlation thread with diagnostic_response or delegation_result. "
                    "Do not mark the original task complete unless you actually completed it."
                )
                return "\n".join(lines)
            if instructions:
                return str(instructions)
        return task.description or task.subject

    def _is_diagnostic_signal(self, signal: AgentRuntimeSignal, payload: dict[str, Any] | None) -> bool:
        message = self._message_for_signal(signal)
        if message is not None and message.message_type == "diagnostic_request":
            return True
        return payload is not None and any(key in payload for key in ("question", "failed_summary", "expected_response"))

    def _update_agent(
        self,
        agent: AgentMember,
        *,
        status: AgentMemberStatus,
        task_id: str | None | object = ...,
        lane_id: str | None | object = ...,
        correlation_id: str | None | object = ...,
        wakeup_reason: str | None | object = ...,
        runtime_state: str | None | object = ...,
        last_active_at: str | None | object = ...,
        idle_since: str | None | object = ...,
    ) -> AgentMember:
        updated = AgentMember(
            agent_id=agent.agent_id,
            session_id=agent.session_id,
            lane_id=agent.lane_id if lane_id is ... else lane_id,
            task_id=agent.task_id if task_id is ... else task_id,
            name=agent.name,
            role=agent.role,
            status=status,
            parent_agent_id=agent.parent_agent_id,
            created_at=agent.created_at,
            updated_at=utc_now_iso(),
            runtime_state=agent.runtime_state if runtime_state is ... else runtime_state,
            current_correlation_id=agent.current_correlation_id if correlation_id is ... else correlation_id,
            wakeup_reason=agent.wakeup_reason if wakeup_reason is ... else wakeup_reason,
            last_active_at=agent.last_active_at if last_active_at is ... else last_active_at,
            idle_since=agent.idle_since if idle_since is ... else idle_since,
            shutdown_requested_at=agent.shutdown_requested_at,
        )
        self.context.repositories.agents.save(updated)
        self.context.emit(
            "agent.status_updated",
            {
                "agent_id": updated.agent_id,
                "status": updated.status.value,
                "task_id": updated.task_id,
                "lane_id": updated.lane_id,
                "wakeup_reason": updated.wakeup_reason,
            },
        )
        return updated


__all__ = ["AgentRuntimeOutcome", "AgentRuntimeService"]
