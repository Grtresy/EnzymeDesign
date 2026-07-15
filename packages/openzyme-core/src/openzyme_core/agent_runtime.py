from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import classify_llm_provider_error

from .harness import HarnessInput
from .harness import HarnessStatus
from .harness import RestoreFocus
from .harness import SessionRuntimeContext
from .harness import run_agent_harness_loop
from .llm_driver import LlmConversationDriver
from .task_board import TaskBoardService
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
        session_id: str,
        agent_id: str,
        reason: AgentRuntimeSignalReason,
        task_id: str | None = None,
        lane_id: str | None = None,
        correlation_id: str | None = None,
        source_ref: str | None = None,
    ) -> AgentRuntimeSignal | None:
        agent = self.context.repositories.agents.get(session_id, agent_id)
        if agent is None:
            return None
        existing = self.context.repositories.runtime_signals.find_pending_duplicate(
            session_id=session_id,
            agent_id=agent_id,
            reason=reason,
            source_ref=source_ref,
        )
        if existing is not None:
            self._notify_signal(existing.session_id)
            return existing
        signal = AgentRuntimeSignal(
            signal_id=_new_id("sig"),
            session_id=session_id,
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
        self.context.emit(
            "signal.queued",
            {
                "signal_id": signal.signal_id,
                "agent_id": signal.agent_id,
                "reason": signal.reason.value,
                "task_id": signal.task_id,
                "lane_id": signal.lane_id,
                "correlation_id": signal.correlation_id,
                "source_ref": signal.source_ref,
            },
        )
        self._notify_signal(signal.session_id)
        return signal

    def _notify_signal(self, session_id: str) -> None:
        notifier = self.context.signal_notifier
        if notifier is not None and hasattr(notifier, "notify"):
            notifier.notify(session_id)

    def auto_enqueue_ready_tasks(self, session_id: str) -> tuple[AgentRuntimeSignal, ...]:
        signals: list[AgentRuntimeSignal] = []
        pending_task_ids = {
            signal.task_id
            for signal in self.context.repositories.runtime_signals.list_pending_by_session(
                session_id
            )
            if signal.task_id is not None
        }
        idle_agents = [
            agent
            for agent in self.context.repositories.agents.list_by_session(session_id)
            if agent.status in {AgentMemberStatus.IDLE, AgentMemberStatus.ACTIVE}
        ]
        for task in self.context.repositories.tasks.list_ready_by_session(session_id):
            if task.task_id in pending_task_ids:
                continue
            if task.assigned_ref:
                continue
            role = teammate_role_for_task_kind(task.kind)
            if role is None:
                continue
            agent = next((candidate for candidate in idle_agents if candidate.role == role), None)
            if agent is None:
                continue
            signal = self.enqueue_signal(
                session_id=session_id,
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

    def wake_agent(self, signal: AgentRuntimeSignal, *, max_steps: int = 8) -> AgentRuntimeOutcome:
        now = utc_now_iso()
        if signal.status is AgentRuntimeSignalStatus.CLAIMED:
            claimed = signal
        else:
            claimed = self.context.repositories.runtime_signals.claim_next(
                session_id=signal.session_id,
                claimed_by="runtime:wake_agent",
                lease_seconds=300,
                signal_ids={signal.signal_id},
                **self._signal_lease_claim_kwargs(),
            )
            if claimed is None:
                current = self.context.repositories.runtime_signals.get(signal.signal_id) or signal
                return AgentRuntimeOutcome(
                    signal=current,
                    task=None,
                    agent=None,
                    ok=False,
                    summary="signal is not claimable",
                    teammate_status="signal_not_claimable",
                )
        self.context.emit(
            "signal.claimed",
            {
                "signal_id": claimed.signal_id,
                "agent_id": claimed.agent_id,
                "claimed_by": claimed.claimed_by,
                "claim_expires_at": claimed.claim_expires_at,
                "attempt_count": claimed.attempt_count,
            },
        )
        agent = self.context.repositories.agents.get(signal.session_id, signal.agent_id)
        if agent is None:
            failed, _ = self._fail_signal(claimed, error_message="agent not found")
            return AgentRuntimeOutcome(signal=failed, task=None, agent=None, ok=False, summary="agent not found")
        if agent.agent_id == "agent:master" or agent.role == "master":
            return self._wake_master(claimed, agent, max_steps=max_steps)

        payload = self._payload_for_signal(signal)
        task = self._resolve_task(signal, agent, payload)
        if task is None:
            summary = "Focused task required for wakeup."
            failed, _ = self._fail_signal(claimed, error_message=summary)
            agent = self._update_agent(
                agent,
                status=AgentMemberStatus.IDLE,
                correlation_id=signal.correlation_id,
                wakeup_reason=signal.reason.value,
                runtime_state="idle",
                idle_since=utc_now_iso(),
            )
            return AgentRuntimeOutcome(
                signal=failed,
                task=None,
                agent=agent,
                ok=False,
                summary=summary,
                teammate_status="focused_task_missing",
            )
        not_ready = self._task_not_ready_outcome(claimed, agent, task)
        if not_ready is not None:
            return not_ready
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

        service = TaskBoardService(self.context.repositories, event_emitter=self.context.emit)
        if task.status is TaskStatus.TODO:
            task = service.claim_task(
                task.task_id,
                assigned_ref=agent.agent_id,
            )
        elif task.status is TaskStatus.BLOCKED:
            task = service.resume_after_approval(task.task_id)
            if signal.reason is AgentRuntimeSignalReason.TASK_AVAILABLE:
                self.context.emit(
                    "agent.task_claimed",
                    {"agent_id": agent.agent_id, "task_id": task.task_id, "signal_id": signal.signal_id},
                )

        self._continue_execution_after_approval_signal(signal)
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
            signal_id=signal.signal_id,
            wakeup_reason=signal.reason.value,
        )
        summary, final_status = finalize_teammate_result(
            self.context,
            agent_id=agent.agent_id,
            task_id=task.task_id,
            correlation_id=correlation_id,
            result=result,
        )
        if result.pending_approval_id is not None:
            task = service.block_for_approval(task.task_id)
            ok = True
        elif final_status in {AgentMemberStatus.IDLE, AgentMemberStatus.BLOCKED}:
            ok = True
        else:
            ok = False

        if ok:
            completed, signal_write_ok = self._complete_signal(claimed)
        else:
            completed, signal_write_ok = self._fail_signal(
                claimed,
                error_message=summary,
                retryable=_is_retryable_runtime_error(result.error),
                emit=False,
            )
        if not signal_write_ok:
            ok = False
            summary = "session runtime lease fencing rejected; signal write was not applied"
        event_type = (
            "signal.completed"
            if ok and signal_write_ok
            else (
                "signal.retry_scheduled"
                if signal_write_ok and completed.status is AgentRuntimeSignalStatus.PENDING
                else "signal.failed"
            )
        )
        if signal_write_ok:
            self.context.emit(
                event_type,
                {
                    "signal_id": completed.signal_id,
                    "agent_id": completed.agent_id,
                    "status": completed.status.value,
                    "error_message": completed.error_message,
                },
            )
        for message_id in consumed_message_ids:
            self.context.repositories.inbox.set_status(message_id, InboxStatus.ACKNOWLEDGED)
        for pending_signal in self.context.repositories.runtime_signals.list_pending_by_session(agent.session_id):
            if pending_signal.source_ref in set(consumed_message_ids):
                self.context.repositories.runtime_signals.complete(pending_signal.signal_id)
        effective_final_status = (
            AgentMemberStatus.IDLE
            if not ok and completed.status is AgentRuntimeSignalStatus.PENDING
            else final_status
        )
        agent = self._update_agent(
            self.context.repositories.agents.get(agent.session_id, agent.agent_id) or agent,
            status=effective_final_status,
            runtime_state=effective_final_status.value,
            last_active_at=utc_now_iso(),
            idle_since=utc_now_iso()
            if effective_final_status is AgentMemberStatus.IDLE
            else None,
        )
        if effective_final_status is AgentMemberStatus.IDLE:
            self.context.emit("agent.idle", {"agent_id": agent.agent_id, "signal_id": signal.signal_id, "task_id": task.task_id})
        if result.pending_approval_id is None:
            self._enqueue_master_wakeup_after_teammate(
                session_id=agent.session_id,
                source_signal=signal,
                task=task,
                correlation_id=correlation_id,
            )
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

    def _wake_master(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        *,
        max_steps: int,
    ) -> AgentRuntimeOutcome:
        now = utc_now_iso()
        agent = self._update_agent(
            agent,
            status=AgentMemberStatus.WORKING,
            task_id=claimed.task_id,
            lane_id=claimed.lane_id,
            correlation_id=claimed.correlation_id,
            wakeup_reason=claimed.reason.value,
            runtime_state="working",
            last_active_at=now,
            idle_since=None,
        )
        self.context.emit(
            "agent.woken",
            {
                "agent_id": agent.agent_id,
                "signal_id": claimed.signal_id,
                "reason": claimed.reason.value,
                "task_id": claimed.task_id,
                "lane_id": claimed.lane_id,
                "correlation_id": claimed.correlation_id,
            },
        )
        result = run_agent_harness_loop(
            self.context.repositories,
            HarnessInput(
                session_id=claimed.session_id,
                message=None,
                max_steps=max_steps,
                restore_focus=RestoreFocus(
                    task_id=claimed.task_id,
                    lane_id=claimed.lane_id,
                ),
                persist_conversation=True,
                agent_id=agent.agent_id,
                actor_kind="master",
                actor_role=agent.role,
                correlation_id=claimed.correlation_id,
                signal_id=claimed.signal_id,
                wakeup_reason=claimed.reason.value,
            ),
            driver=LlmConversationDriver(
                self.context.model_factory,
                engine_registry=self.context.engine_registry,
            ),
            engine_registry=self.context.engine_registry,
            event_sink=self.context.event_sink,
            model_factory=self.context.model_factory,
            bio_research_service=self.context.bio_research_service,
            research_adapter=self.context.research_adapter,
            signal_notifier=self.context.signal_notifier,
        )
        ok = result.status is not HarnessStatus.FAILED
        if ok:
            completed, signal_write_ok = self._complete_signal(claimed)
        else:
            completed, signal_write_ok = self._fail_signal(
                claimed,
                error_message=result.outputs[-1] if result.outputs else result.status.value,
                retryable=_is_retryable_runtime_error(result.error),
                emit=False,
            )
        if not signal_write_ok:
            ok = False
            summary = "session runtime lease fencing rejected; signal write was not applied"
        else:
            summary = result.outputs[-1] if result.outputs else result.status.value
        event_type = (
            "signal.completed"
            if ok and signal_write_ok
            else (
                "signal.retry_scheduled"
                if signal_write_ok and completed.status is AgentRuntimeSignalStatus.PENDING
                else "signal.failed"
            )
        )
        if signal_write_ok:
            self.context.emit(
                event_type,
                {
                    "signal_id": completed.signal_id,
                    "agent_id": completed.agent_id,
                    "status": completed.status.value,
                    "error_message": completed.error_message,
                },
            )
        agent = self._update_agent(
            self.context.repositories.agents.get(agent.session_id, agent.agent_id) or agent,
            status=AgentMemberStatus.IDLE,
            runtime_state="idle",
            last_active_at=utc_now_iso(),
            idle_since=utc_now_iso(),
        )
        self.context.emit(
            "agent.idle",
            {
                "agent_id": agent.agent_id,
                "signal_id": claimed.signal_id,
                "task_id": claimed.task_id,
            },
        )
        return AgentRuntimeOutcome(
            signal=completed,
            task=None
            if claimed.task_id is None
            else self.context.repositories.tasks.get(claimed.task_id),
            agent=agent,
            ok=ok,
            summary=summary,
            teammate_status=result.status.value,
            outputs=tuple(result.outputs),
            waiting_approval_id=result.pending_approval_id,
        )

    def _task_not_ready_outcome(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        task: Task,
    ) -> AgentRuntimeOutcome | None:
        service = TaskBoardService(self.context.repositories, event_emitter=self.context.emit)
        open_blockers = service.open_blocker_ids(task)
        if open_blockers:
            summary = (
                f"Task {task.task_id} is blocked by unfinished task(s): "
                f"{', '.join(open_blockers)}."
            )
            return self._fail_ready_gate(
                claimed,
                agent,
                task,
                summary=summary,
                teammate_status="task_blocked",
            )
        if task.status.is_terminal:
            summary = (
                f"Stale wakeup ignored because task {task.task_id} is already "
                f"{task.status.value}."
            )
            return self._complete_stale_signal(
                claimed,
                agent,
                task,
                summary=summary,
                teammate_status="stale_signal_ignored",
            )
        if claimed.reason is AgentRuntimeSignalReason.TASK_AVAILABLE:
            if task.status is not TaskStatus.TODO:
                return self._fail_ready_gate(
                    claimed,
                    agent,
                    task,
                    summary=(
                        "TASK_AVAILABLE wakeup requires a TODO task; "
                        f"task {task.task_id} is {task.status.value}."
                    ),
                    teammate_status="task_not_ready",
                )
            if task.assigned_ref is not None:
                return self._fail_ready_gate(
                    claimed,
                    agent,
                    task,
                    summary=(
                        "TASK_AVAILABLE wakeup requires an unassigned task; "
                        f"task {task.task_id} is assigned to {task.assigned_ref}."
                    ),
                    teammate_status="task_already_assigned",
                )
            return None
        if claimed.reason is AgentRuntimeSignalReason.APPROVAL_RESOLVED:
            if task.assigned_ref != agent.agent_id:
                return self._fail_ready_gate(
                    claimed,
                    agent,
                    task,
                    summary=(
                        "Approval resume requires the focused task to be assigned "
                        f"to {agent.agent_id}."
                    ),
                    teammate_status="task_not_assigned_to_agent",
                )
            return None
        if task.status is TaskStatus.BLOCKED:
            return self._fail_ready_gate(
                claimed,
                agent,
                task,
                summary=(
                    f"Task {task.task_id} is BLOCKED; only an approval resume "
                    "can restart an assigned approval-blocked task."
                ),
                teammate_status="task_blocked",
            )
        if task.status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
            return self._fail_ready_gate(
                claimed,
                agent,
                task,
                summary=(
                    f"Task {task.task_id} is not executable from status "
                    f"{task.status.value}."
                ),
                teammate_status="task_not_ready",
            )
        return None

    def _complete_signal(self, claimed: AgentRuntimeSignal) -> tuple[AgentRuntimeSignal, bool]:
        completed = self.context.repositories.runtime_signals.complete(
            claimed.signal_id,
            **self._signal_lease_write_kwargs(),
        )
        if completed is None:
            current = self.context.repositories.runtime_signals.get(claimed.signal_id) or claimed
            self._emit_signal_fencing_rejected(current, attempted_status="completed")
            return current, False
        return completed, True

    def _fail_signal(
        self,
        claimed: AgentRuntimeSignal,
        *,
        error_message: str,
        retryable: bool = False,
        emit: bool = True,
    ) -> tuple[AgentRuntimeSignal, bool]:
        failed = self.context.repositories.runtime_signals.fail(
            claimed.signal_id,
            error_message=error_message,
            retryable=retryable,
            **self._signal_lease_write_kwargs(),
        )
        if failed is None:
            current = self.context.repositories.runtime_signals.get(claimed.signal_id) or claimed
            self._emit_signal_fencing_rejected(current, attempted_status="failed")
            return current, False
        if emit:
            event_type = (
                "signal.retry_scheduled"
                if failed.status is AgentRuntimeSignalStatus.PENDING
                else "signal.failed"
            )
            self.context.emit(
                event_type,
                {"signal_id": failed.signal_id, "error_message": failed.error_message},
            )
        return failed, True

    def _fail_ready_gate(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        task: Task,
        *,
        summary: str,
        teammate_status: str,
    ) -> AgentRuntimeOutcome:
        failed, _ = self._fail_signal(claimed, error_message=summary)
        updated_agent = self._update_agent(
            agent,
            status=AgentMemberStatus.IDLE,
            correlation_id=claimed.correlation_id,
            wakeup_reason=claimed.reason.value,
            runtime_state="idle",
            idle_since=utc_now_iso(),
        )
        return AgentRuntimeOutcome(
            signal=failed,
            task=task,
            agent=updated_agent,
            ok=False,
            summary=summary,
            teammate_status=teammate_status,
        )

    def _complete_stale_signal(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        task: Task,
        *,
        summary: str,
        teammate_status: str,
    ) -> AgentRuntimeOutcome:
        completed, signal_write_ok = self._complete_signal(claimed)
        updated_agent = self._update_agent(
            agent,
            status=AgentMemberStatus.IDLE,
            correlation_id=claimed.correlation_id,
            wakeup_reason=claimed.reason.value,
            runtime_state="idle",
            idle_since=utc_now_iso(),
        )
        self.context.emit(
            "signal.stale_consumed",
            {
                "signal_id": completed.signal_id,
                "agent_id": completed.agent_id,
                "task_id": task.task_id,
                "task_status": task.status.value,
            },
        )
        return AgentRuntimeOutcome(
            signal=completed,
            task=task,
            agent=updated_agent,
            ok=signal_write_ok,
            summary=summary
            if signal_write_ok
            else "session runtime lease fencing rejected; stale signal write was not applied",
            teammate_status=teammate_status
            if signal_write_ok
            else "stale_signal_write_rejected",
        )

    def _signal_lease_claim_kwargs(self) -> dict[str, Any]:
        lease = self.context.session_runtime_lease
        if lease is None:
            return {}
        return {
            "session_lease_token": lease.lease_token,
            "session_fencing_token": lease.fencing_token,
        }

    def _signal_lease_write_kwargs(self) -> dict[str, Any]:
        lease = self.context.session_runtime_lease
        if lease is None:
            return {}
        return {
            "expected_session_lease_token": lease.lease_token,
            "expected_session_fencing_token": lease.fencing_token,
        }

    def _emit_signal_fencing_rejected(
        self, signal: AgentRuntimeSignal, *, attempted_status: str
    ) -> None:
        lease = self.context.session_runtime_lease
        self.context.emit(
            "runtime.fencing_rejected",
            {
                "signal_id": signal.signal_id,
                "agent_id": signal.agent_id,
                "attempted_status": attempted_status,
                "current_status": signal.status.value,
                "signal_has_session_lease": signal.session_lease_token is not None,
                "signal_session_fencing_token": signal.session_fencing_token,
                "worker_has_session_lease": lease is not None,
                "worker_session_fencing_token": None if lease is None else lease.fencing_token,
            },
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

    def _instructions_for_signal(
        self,
        signal: AgentRuntimeSignal,
        task: Task,
        payload: dict[str, Any] | None,
    ) -> str:
        if signal.reason is AgentRuntimeSignalReason.APPROVAL_RESOLVED:
            invocation_id = self._execution_invocation_id_for_approval(signal.source_ref)
            failure = self._execution_failure_for_approval(signal.source_ref)
            status_line = (
                ""
            if invocation_id is None
            else f" Existing execution pipeline invocation: {invocation_id}."
        )
            lines = [
                f"Approval {signal.source_ref or signal.correlation_id or 'unknown'} was resolved for your assigned task.",
                "Continue the existing delegated work from the shared workspace state." + status_line,
                "Relevant execution invocation/status, captured artifacts, and sanitized failure evidence are available in the shared workspace.",
                "If the execution status includes sanitized failure evidence, use it as context for your own task decision.",
            ]
            if failure is not None:
                lines.extend(
                    [
                        "The approved pipeline has sanitized failure evidence attached.",
                        "Sanitized hpc_failure: "
                        + json.dumps(
                            failure.get("hpc_failure") or {},
                            ensure_ascii=False,
                            sort_keys=True,
                        ),
                    ]
                )
                if failure.get("hint"):
                    lines.append(f"Failure hint: {failure['hint']}")
                if failure.get("stderr_excerpt"):
                    lines.append(f"Pipeline stderr excerpt: {failure['stderr_excerpt']}")
            lines.append(f"Task {task.task_id}: {task.description or task.subject}")
            return "\n".join(lines)
        if payload is not None:
            instructions = payload.get("instructions")
            if instructions:
                return str(instructions)
        return task.description or task.subject

    def _continue_execution_after_approval_signal(
        self, signal: AgentRuntimeSignal
    ) -> None:
        if signal.reason is not AgentRuntimeSignalReason.APPROVAL_RESOLVED:
            return
        approval_id = signal.source_ref or signal.correlation_id
        if not approval_id or self.context.engine_registry is None:
            return
        approval = self.context.repositories.approvals.get(approval_id)
        if approval is None:
            return
        waiting = [
            invocation
            for invocation in self.context.repositories.invocations.list_by_session(
                signal.session_id
            )
            if invocation.engine_name == "execution"
            and invocation.approval_id == approval_id
            and invocation.status is EngineInvocationStatus.WAITING_APPROVAL
        ]
        if not waiting:
            return
        engine = self.context.engine_registry.get("execution")
        if engine is None or not hasattr(engine, "continue_after_approval"):
            return
        continuation = engine.continue_after_approval(  # type: ignore[attr-defined]
            invocation_id=waiting[0].invocation_id,
            resolution=approval.status.value,
        )
        self.context.emit(
            "execution.pipeline.completed"
            if continuation.invocation.status is EngineInvocationStatus.SUCCEEDED
            else "execution.pipeline.updated",
            {
                "invocation_id": continuation.invocation.invocation_id,
                "status": continuation.invocation.status.value,
                "approval_id": continuation.invocation.approval_id,
            },
        )

    def _enqueue_master_wakeup_after_teammate(
        self,
        *,
        session_id: str,
        source_signal: AgentRuntimeSignal,
        task: Task,
        correlation_id: str,
    ) -> None:
        if self.context.repositories.agents.get(session_id, "agent:master") is None:
            now = utc_now_iso()
            self.context.repositories.agents.save(
                AgentMember(
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
                )
            )
        self.enqueue_signal(
            session_id=session_id,
            agent_id="agent:master",
            task_id=task.task_id,
            lane_id=task.lane_id,
            correlation_id=correlation_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=source_signal.signal_id,
        )

    def _execution_invocation_id_for_approval(self, approval_id: str | None) -> str | None:
        if not approval_id:
            return None
        for invocation in self.context.repositories.invocations.list_by_session(
            self.context.snapshot.session.session_id
        ):
            if invocation.engine_name == "execution" and invocation.approval_id == approval_id:
                return invocation.invocation_id
        return None

    def _execution_failure_for_approval(self, approval_id: str | None) -> dict[str, Any] | None:
        if not approval_id:
            return None
        for invocation in self.context.repositories.invocations.list_by_session(
            self.context.snapshot.session.session_id
        ):
            if invocation.engine_name != "execution" or invocation.approval_id != approval_id:
                continue
            if not invocation.output_ref:
                continue
            document = self.context.repositories.engine_documents.get(invocation.output_ref)
            if document is None:
                continue
            payload = dict(document.payload)
            pipeline = payload.get("pipeline")
            if not isinstance(pipeline, dict):
                continue
            error = pipeline.get("error")
            if not isinstance(error, dict):
                continue
            if error.get("type") == "hpc_operation_failed":
                return error
        return None

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
            member_id=agent.member_id,
            nickname=agent.nickname,
            display_name=agent.display_name,
            handle=agent.handle,
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


def _is_retryable_runtime_error(exc: BaseException | None) -> bool:
    if exc is None:
        return False
    return classify_llm_provider_error(exc).retryable
