from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_domain import RetryEligibility
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import classify_llm_provider_error
from openzyme_runtime import sanitize_public_diagnostic_text
from openzyme_runtime import record_failure_observation

from .harness import HarnessInput
from .harness import HarnessResult
from .harness import HarnessStatus
from .harness import RestoreFocus
from .harness import SessionRuntimeContext
from .harness import run_agent_harness_loop
from .agent_runtime_settlements import AgentRuntimeOutcomeSettlement
from .agent_runtime_settlements import AgentRuntimeSettlementDisposition
from .llm_driver import LlmConversationDriver
from .scientific_attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .scientific_attempt_lifecycle import ScientificAttemptLifecycleResolver
from .scientific_closure_notification import (
    ScientificClosureNotificationProof,
)
from .scientific_closure_notification import (
    ScientificClosureNotificationSettlementError,
)
from .scientific_closure_notification import ScientificClosureNotificationVerifier
from .task_board import TaskBoardService
from .teammate_roster import teammate_role_for_task_kind
from .teammates import finalize_teammate_result
from .teammates import run_teammate_loop


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def _require_consistent_harness_approval_wait(
    result: HarnessResult,
) -> None:
    if (result.status is HarnessStatus.WAITING_APPROVAL) != (
        result.pending_approval_id is not None
    ):
        raise ValueError(
            "harness waiting-approval status and durable pending "
            "approval identity disagree"
        )


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
    settlement: AgentRuntimeOutcomeSettlement | None = None

    def __post_init__(self) -> None:
        settlement = self.settlement
        if settlement is None:
            disposition = (
                AgentRuntimeSettlementDisposition.WAITING_APPROVAL
                if self.waiting_approval_id is not None
                else (
                    AgentRuntimeSettlementDisposition.SIGNAL_COMPLETED
                    if self.ok
                    else AgentRuntimeSettlementDisposition.SIGNAL_FAILED
                )
            )
            settlement = AgentRuntimeOutcomeSettlement.from_signal_outcome(
                signal=self.signal,
                task=self.task,
                disposition=disposition,
                batch_barrier=(
                    self.teammate_status == HarnessStatus.MAX_STEPS_EXCEEDED.value
                ),
            )
            object.__setattr__(self, "settlement", settlement)
        if (
            settlement.source_signal_id != self.signal.signal_id
            or settlement.source_signal_status is not self.signal.status
            or settlement.source_attempt_count != self.signal.attempt_count
            or settlement.session_id != self.signal.session_id
            or settlement.agent_id != self.signal.agent_id
            or settlement.task_id != self.signal.task_id
            or settlement.lane_id != self.signal.lane_id
            or settlement.source_correlation_id != self.signal.correlation_id
        ):
            raise ValueError(
                "runtime outcome settlement does not match its source signal"
            )
        if (
            self.teammate_status == HarnessStatus.MAX_STEPS_EXCEEDED.value
            and not settlement.batch_barrier
        ):
            raise ValueError(
                "max-step runtime outcome must terminate the scheduler batch"
            )
        if (
            settlement.disposition
            is AgentRuntimeSettlementDisposition.BUDGET_REPLAN_HANDOFF
            and (
                self.ok
                or self.waiting_approval_id is not None
                or self.teammate_status != HarnessStatus.MAX_STEPS_EXCEEDED.value
            )
        ):
            raise ValueError("budget-replan handoff does not match the runtime outcome")

    def to_dict(self) -> dict[str, Any]:
        assert self.settlement is not None
        return {
            "signal": self.signal.to_dict(),
            "task": None if self.task is None else self.task.to_dict(),
            "agent": None if self.agent is None else self.agent.to_dict(),
            "ok": self.ok,
            "summary": self.summary,
            "teammate_status": self.teammate_status,
            "outputs": list(self.outputs),
            "waiting_approval_id": self.waiting_approval_id,
            "settlement": self.settlement.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class RuntimeSignalFailureObservation:
    """Closed facts used to record one exact runtime-signal failure."""

    error_code: str
    recoverability: FailureRecoverability
    effect_certainty: ExternalEffectCertainty
    retry_eligibility: RetryEligibility
    safe_summary: str
    safe_hint: str
    facts: dict[str, Any]


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
        notify: bool = True,
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
            if notify:
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
        if notify:
            self._notify_signal(signal.session_id)
        return signal

    def _notify_signal(self, session_id: str) -> None:
        notifier = self.context.signal_notifier
        if notifier is not None and hasattr(notifier, "notify"):
            notifier.notify(session_id)

    def auto_enqueue_ready_tasks(
        self, session_id: str
    ) -> tuple[AgentRuntimeSignal, ...]:
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
            agent = next(
                (candidate for candidate in idle_agents if candidate.role == role), None
            )
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

    def wake_agent(
        self, signal: AgentRuntimeSignal, *, max_steps: int = 8
    ) -> AgentRuntimeOutcome:
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
                current = (
                    self.context.repositories.runtime_signals.get(signal.signal_id)
                    or signal
                )
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
            failed, _, _ = self._fail_signal(
                claimed,
                error_message="agent not found",
            )
            return AgentRuntimeOutcome(
                signal=failed,
                task=None,
                agent=None,
                ok=False,
                summary="agent not found",
            )
        closure_proof, closure_rejection = (
            self._scientific_closure_notification_preflight(
                claimed,
                agent,
            )
        )
        if closure_rejection is not None:
            return closure_rejection
        if closure_proof is not None:
            not_ready = self._task_not_ready_outcome(
                claimed,
                agent,
                closure_proof.task,
            )
            if not_ready is not None:
                return not_ready
        if agent.agent_id == "agent:master" or agent.role == "master":
            return self._wake_master(claimed, agent, max_steps=max_steps)

        payload = self._payload_for_signal(signal)
        task = self._resolve_task(signal, agent, payload)
        if task is None:
            summary = "Focused task required for wakeup."
            failed, _, _ = self._fail_signal(
                claimed,
                error_message=summary,
            )
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
        lane_id = signal.lane_id or (
            None if payload is None else payload.get("lane_id")
        )
        agent = self._update_agent(
            agent,
            status=AgentMemberStatus.WORKING,
            task_id=None if task is None else task.task_id,
            lane_id=str(lane_id)
            if lane_id is not None
            else (None if task is None else task.lane_id),
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
        for message in self.context.repositories.inbox.list_unread_for_recipient(
            agent.session_id, agent.agent_id
        ):
            consumed_message_ids.append(message.message_id)
            self.context.repositories.inbox.set_status(
                message.message_id, InboxStatus.DELIVERED
            )

        service = TaskBoardService(
            self.context.repositories,
            event_emitter=self.context.emit,
        )
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
                    {
                        "agent_id": agent.agent_id,
                        "task_id": task.task_id,
                        "signal_id": signal.signal_id,
                    },
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
        _require_consistent_harness_approval_wait(result)
        summary, final_status = finalize_teammate_result(
            self.context,
            agent_id=agent.agent_id,
            task_id=task.task_id,
            correlation_id=correlation_id,
            result=result,
        )
        if result.status is HarnessStatus.WAITING_APPROVAL:
            assert result.pending_approval_id is not None
            if not self._pending_approval_is_durable_continuation_owned(
                session_id=agent.session_id,
                task_id=task.task_id,
                approval_id=result.pending_approval_id,
            ):
                task = service.block_for_approval(task.task_id)
            ok = True
        elif final_status in {AgentMemberStatus.IDLE, AgentMemberStatus.BLOCKED}:
            ok = True
        else:
            ok = False

        budget_observation = (
            self._budget_exhaustion_observation(
                claimed,
                max_steps=max_steps,
            )
            if result.status is HarnessStatus.MAX_STEPS_EXCEEDED
            else None
        )
        failure_observation: FailureObservation | None = None
        successor: AgentRuntimeSignal | None = None
        settlement: AgentRuntimeOutcomeSettlement | None = None
        acknowledged_message_ids = set(consumed_message_ids)
        with self.context.repositories.atomic(
            prefix="agent_runtime_outcome_settlement"
        ):
            if ok:
                completed, signal_write_ok = self._complete_signal(claimed)
            else:
                (
                    completed,
                    signal_write_ok,
                    failure_observation,
                ) = self._fail_signal(
                    claimed,
                    error_message=(
                        AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
                        if budget_observation is not None
                        else summary
                    ),
                    retryable=(
                        False
                        if budget_observation is not None
                        else _is_retryable_runtime_error(result.error)
                    ),
                    emit=False,
                    observation=budget_observation,
                )
            if not signal_write_ok:
                ok = False
                summary = (
                    "session runtime lease fencing rejected; "
                    "signal write was not applied"
                )
            event_type = (
                "signal.completed"
                if ok and signal_write_ok
                else (
                    "signal.retry_scheduled"
                    if signal_write_ok
                    and completed.status is AgentRuntimeSignalStatus.PENDING
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
                self.context.repositories.inbox.set_status(
                    message_id,
                    InboxStatus.ACKNOWLEDGED,
                )
            for (
                pending_signal
            ) in self.context.repositories.runtime_signals.list_pending_by_session(
                agent.session_id
            ):
                if pending_signal.source_ref in acknowledged_message_ids:
                    self.context.repositories.runtime_signals.complete(
                        pending_signal.signal_id
                    )
            effective_final_status = (
                AgentMemberStatus.IDLE
                if not ok and completed.status is AgentRuntimeSignalStatus.PENDING
                else final_status
            )
            agent = self._update_agent(
                self.context.repositories.agents.get(
                    agent.session_id,
                    agent.agent_id,
                )
                or agent,
                status=effective_final_status,
                runtime_state=effective_final_status.value,
                last_active_at=utc_now_iso(),
                idle_since=(
                    utc_now_iso()
                    if effective_final_status is AgentMemberStatus.IDLE
                    else None
                ),
            )
            task = self.context.repositories.tasks.get(task.task_id) or task
            if effective_final_status is AgentMemberStatus.IDLE:
                self.context.emit(
                    "agent.idle",
                    {
                        "agent_id": agent.agent_id,
                        "signal_id": signal.signal_id,
                        "task_id": task.task_id,
                    },
                )
            if result.pending_approval_id is None:
                successor = self._enqueue_master_wakeup_after_teammate(
                    session_id=agent.session_id,
                    source_signal=completed,
                    task=task,
                    correlation_id=correlation_id,
                    notify=False,
                )
            if (
                budget_observation is not None
                and signal_write_ok
                and failure_observation is not None
                and successor is not None
            ):
                settlement = self._form_budget_replan_handoff_settlement(
                    source_signal=completed,
                    task=task,
                    agent=agent,
                    failure=failure_observation,
                    successor=successor,
                )
        if successor is not None and not successor.status.is_terminal:
            self._notify_signal(successor.session_id)
        return AgentRuntimeOutcome(
            signal=completed,
            task=task,
            agent=agent,
            ok=ok,
            summary=summary,
            teammate_status=result.status.value,
            outputs=tuple(result.outputs),
            waiting_approval_id=result.pending_approval_id,
            settlement=settlement,
        )

    def _form_budget_replan_handoff_settlement(
        self,
        *,
        source_signal: AgentRuntimeSignal,
        task: Task,
        agent: AgentMember,
        failure: FailureObservation,
        successor: AgentRuntimeSignal,
    ) -> AgentRuntimeOutcomeSettlement | None:
        matching_successors = [
            candidate
            for candidate in (
                self.context.repositories.runtime_signals.list_by_session(
                    source_signal.session_id
                )
            )
            if candidate.agent_id == "agent:master"
            and candidate.reason is AgentRuntimeSignalReason.MANUAL_RESUME
            and candidate.source_ref == source_signal.signal_id
        ]
        if (
            len(matching_successors) != 1
            or matching_successors[0].signal_id != successor.signal_id
        ):
            self.context.emit(
                "runtime.budget_handoff_incomplete",
                {
                    "signal_id": source_signal.signal_id,
                    "error_code": "budget_replan_successor_not_unique",
                    "successor_count": len(matching_successors),
                },
            )
            return None
        try:
            return AgentRuntimeOutcomeSettlement.budget_replan_handoff(
                source_signal=source_signal,
                task=task,
                agent=agent,
                failure=failure,
                successor=successor,
            )
        except ValueError:
            self.context.emit(
                "runtime.budget_handoff_incomplete",
                {
                    "signal_id": source_signal.signal_id,
                    "error_code": "budget_replan_identity_not_closed",
                    "successor_count": 1,
                },
            )
            return None

    def _pending_approval_is_durable_continuation_owned(
        self,
        *,
        session_id: str,
        task_id: str,
        approval_id: str,
    ) -> bool:
        """Keep a durable attached SDK suspension out of task business state."""

        operation_repository = self.context.repositories.controlled_operations
        operations = [
            operation
            for operation in operation_repository.list_by_session(session_id)
            if operation.approval_id == approval_id
        ]
        if not operations:
            return False
        if len(operations) != 1:
            raise ValueError(
                "pending approval is linked to an ambiguous controlled operation"
            )
        operation = operations[0]
        if operation.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1:
            return False
        continuation_repository = self.context.repositories.continuation_states
        continuations = [
            continuation
            for continuation in continuation_repository.list_by_session(session_id)
            if continuation.approval_id == approval_id
        ]
        if len(continuations) != 1:
            raise ValueError(
                "durable controlled operation lacks one exact continuation"
            )
        continuation = continuations[0]
        if (
            operation.session_id != session_id
            or operation.task_id != task_id
            or continuation.session_id != session_id
            or continuation.operation_id != operation.operation_id
            or continuation.sandbox_run_id != operation.sandbox_run_id
            or continuation.originating_task_id != task_id
        ):
            raise ValueError(
                "durable controlled operation continuation identity is inconsistent"
            )
        return True

    def _wake_master(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        *,
        max_steps: int,
    ) -> AgentRuntimeOutcome:
        skill_keys = self._master_skill_keys_for_signal(claimed)
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
                    skill_keys=skill_keys,
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
            scientific_workflow_contract_registry=(
                self.context.scientific_workflow_contract_registry
            ),
            sandbox_workspace_root=self.context.sandbox_workspace_root,
            artifact_blob_root=self.context.artifact_blob_root,
            signal_notifier=self.context.signal_notifier,
            reliability_shadow_observer=self.context.reliability_shadow_observer,
            reliability_settings=self.context.reliability_settings,
            durable_route_adapter_policy_ids=(
                self.context.durable_route_adapter_policy_ids
            ),
            tool_dispatch_precondition=(self.context.tool_dispatch_precondition),
            mutation_writer_scope_factory=(self.context.mutation_writer_scope_factory),
        )
        _require_consistent_harness_approval_wait(result)
        budget_observation = (
            self._budget_exhaustion_observation(
                claimed,
                max_steps=max_steps,
            )
            if result.status is HarnessStatus.MAX_STEPS_EXCEEDED
            else None
        )
        ok = result.status not in {
            HarnessStatus.FAILED,
            HarnessStatus.MAX_STEPS_EXCEEDED,
        }
        if ok:
            completed, signal_write_ok = self._complete_signal(claimed)
        else:
            completed, signal_write_ok, _ = self._fail_signal(
                claimed,
                error_message=(
                    AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
                    if budget_observation is not None
                    else (result.outputs[-1] if result.outputs else result.status.value)
                ),
                retryable=(
                    False
                    if budget_observation is not None
                    else _is_retryable_runtime_error(result.error)
                ),
                emit=False,
                observation=budget_observation,
            )
        if not signal_write_ok:
            ok = False
            summary = (
                "session runtime lease fencing rejected; signal write was not applied"
            )
        else:
            summary = result.outputs[-1] if result.outputs else result.status.value
        event_type = (
            "signal.completed"
            if ok and signal_write_ok
            else (
                "signal.retry_scheduled"
                if signal_write_ok
                and completed.status is AgentRuntimeSignalStatus.PENDING
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
            self.context.repositories.agents.get(agent.session_id, agent.agent_id)
            or agent,
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

    def _scientific_closure_notification_preflight(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
    ) -> tuple[
        ScientificClosureNotificationProof | None,
        AgentRuntimeOutcome | None,
    ]:
        try:
            proof = ScientificClosureNotificationVerifier(
                self.context.repositories
            ).verify(claimed)
        except ScientificClosureNotificationSettlementError as exc:
            failed, signal_write_ok, _ = self._fail_signal(
                claimed,
                error_message=exc.error_code,
                retryable=False,
                emit=False,
            )
            agent = self._update_agent(
                agent,
                status=AgentMemberStatus.IDLE,
                correlation_id=claimed.correlation_id,
                wakeup_reason=claimed.reason.value,
                runtime_state="idle",
                last_active_at=utc_now_iso(),
                idle_since=utc_now_iso(),
            )
            if signal_write_ok:
                self.context.emit(
                    "scientific.closure_notification.rejected",
                    {
                        "signal_id": failed.signal_id,
                        "agent_id": failed.agent_id,
                        "error_code": exc.error_code,
                        "reason": exc.reason.value,
                    },
                )
            return (
                None,
                AgentRuntimeOutcome(
                    signal=failed,
                    task=(
                        None
                        if failed.task_id is None
                        else self.context.repositories.tasks.get(failed.task_id)
                    ),
                    agent=agent,
                    ok=False,
                    summary=(
                        "scientific closure notification failed exact binding "
                        "verification"
                        if signal_write_ok
                        else (
                            "session runtime lease fencing rejected; scientific "
                            "closure notification write was not applied"
                        )
                    ),
                    teammate_status=(
                        "scientific_closure_notification_invalid"
                        if signal_write_ok
                        else "scientific_closure_notification_write_rejected"
                    ),
                ),
            )
        return proof, None

    def _task_not_ready_outcome(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        task: Task,
    ) -> AgentRuntimeOutcome | None:
        service = TaskBoardService(
            self.context.repositories, event_emitter=self.context.emit
        )
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

    def _complete_signal(
        self, claimed: AgentRuntimeSignal
    ) -> tuple[AgentRuntimeSignal, bool]:
        completed = self.context.repositories.runtime_signals.complete(
            claimed.signal_id,
            **self._signal_lease_write_kwargs(),
        )
        if completed is None:
            current = (
                self.context.repositories.runtime_signals.get(claimed.signal_id)
                or claimed
            )
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
        observation: RuntimeSignalFailureObservation | None = None,
    ) -> tuple[AgentRuntimeSignal, bool, FailureObservation]:
        public_error = sanitize_public_diagnostic_text(error_message)
        canonical_observation = observation or RuntimeSignalFailureObservation(
            error_code="runtime_signal_failed",
            recoverability=(
                FailureRecoverability.RUNTIME_RETRY
                if retryable
                else FailureRecoverability.TERMINAL
            ),
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=(
                RetryEligibility.SAME_PHASE_SAFE
                if retryable
                else RetryEligibility.TERMINAL
            ),
            safe_summary=(
                "The runtime signal failed without changing the business task."
            ),
            safe_hint=(
                "Restore runtime authority and let the agent inspect this "
                "failure before choosing recovery or explicit refusal."
            ),
            facts={},
        )
        source_version = f"attempt:{claimed.attempt_count}"
        existing_observation = (
            self.context.repositories.failure_observations.get_by_source(
                session_id=claimed.session_id,
                source_kind="runtime_signal",
                source_ref=claimed.signal_id,
                source_version=source_version,
                phase="runtime",
                error_code=canonical_observation.error_code,
            )
        )
        if existing_observation is None:
            task_id = (
                claimed.task_id
                if claimed.task_id is not None
                and self.context.repositories.tasks.get(claimed.task_id) is not None
                else None
            )
            lane_id = (
                claimed.lane_id
                if claimed.lane_id is not None
                and self.context.repositories.lanes.get(claimed.lane_id) is not None
                else None
            )
            failure_observation = record_failure_observation(
                self.context.repositories,
                session_id=claimed.session_id,
                task_id=task_id,
                lane_id=lane_id,
                agent_id=claimed.agent_id,
                source_kind="runtime_signal",
                source_ref=claimed.signal_id,
                source_version=source_version,
                phase="runtime",
                failure_class=FailureClass.RUNTIME,
                recoverability=canonical_observation.recoverability,
                effect_certainty=canonical_observation.effect_certainty,
                retry_eligibility=canonical_observation.retry_eligibility,
                actor_kind=FailureActorKind.SYSTEM,
                error_code=canonical_observation.error_code,
                safe_summary=canonical_observation.safe_summary,
                safe_hint=canonical_observation.safe_hint,
                facts={
                    "signal_id": claimed.signal_id,
                    "signal_reason": claimed.reason.value,
                    "attempt_count": claimed.attempt_count,
                    "retryable": retryable,
                    "public_error": public_error,
                    "agent_decision_produced": False,
                    **canonical_observation.facts,
                },
                private_diagnostic={
                    "error_code": canonical_observation.error_code,
                    "error_message": error_message,
                },
            )
        else:
            failure_observation = existing_observation
        failed = self.context.repositories.runtime_signals.fail(
            claimed.signal_id,
            error_message=public_error,
            retryable=retryable,
            **self._signal_lease_write_kwargs(),
        )
        if failed is None:
            current = (
                self.context.repositories.runtime_signals.get(claimed.signal_id)
                or claimed
            )
            self._emit_signal_fencing_rejected(current, attempted_status="failed")
            return current, False, failure_observation
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
        return failed, True, failure_observation

    def _budget_exhaustion_observation(
        self,
        claimed: AgentRuntimeSignal,
        *,
        max_steps: int,
    ) -> RuntimeSignalFailureObservation:
        executions = sorted(
            (
                execution
                for execution in (
                    self.context.repositories.controlled_operation_executions.list_by_session(
                        claimed.session_id
                    )
                )
                if execution.task_id == claimed.task_id
            ),
            key=lambda item: (item.created_at, item.execution_id),
        )
        return RuntimeSignalFailureObservation(
            error_code=AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
            recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.TERMINAL,
            safe_summary=(
                "The bounded agent turn exhausted its configured step budget; "
                "the exact signal ended while the business task stayed unchanged."
            ),
            safe_hint=(
                "Inspect the canonical failure and current scientific selection, "
                "then choose a new explicit turn or another recovery strategy. "
                "Do not replay this signal."
            ),
            facts={
                "max_steps": max_steps,
                "exact_signal_retry_eligible": False,
                "effect_scope": "runtime_signal_transition",
                "effect_scope_ref": claimed.signal_id,
                "controlled_operation_effects_preserved": True,
                "controlled_operation_execution_count": len(executions),
                "bounded_controlled_operation_execution_ids": [
                    execution.execution_id for execution in executions[-8:]
                ],
                "controlled_operation_executions_truncated": len(executions) > 8,
                "scientific_selection_recovery": (
                    self._scientific_selection_recovery_facts(claimed)
                ),
            },
        )

    def _scientific_selection_recovery_facts(
        self,
        claimed: AgentRuntimeSignal,
    ) -> dict[str, Any]:
        attempts = sorted(
            (
                attempt
                for attempt in (
                    self.context.repositories.scientific_attempts.list_by_session(
                        claimed.session_id
                    )
                )
                if attempt.task_id == claimed.task_id
            ),
            key=lambda item: (item.ordinal, item.created_at, item.attempt_id),
        )
        base: dict[str, Any] = {
            "task_id": claimed.task_id,
            "attempt_count": len(attempts),
            "bounded_attempt_ids": [attempt.attempt_id for attempt in attempts[-4:]],
            "attempts_truncated": len(attempts) > 4,
        }
        if not attempts:
            return {**base, "status": "not_applicable"}
        resolver = ScientificAttemptLifecycleResolver(self.context.repositories)
        try:
            lifecycles = [resolver.resolve(attempt) for attempt in attempts]
        except ScientificAttemptLifecycleIntegrityError as exc:
            return {
                **base,
                "status": "attempt_lifecycle_invalid",
                "error_code": exc.error_code,
                "integrity_reason": exc.reason_code,
                "attempt_id": exc.details["attempt_id"],
            }
        mutable_lifecycles = [
            lifecycle
            for lifecycle in lifecycles
            if lifecycle.accepts_scientific_mutation
        ]
        lifecycle = (mutable_lifecycles or lifecycles)[-1]
        attempt = lifecycle.attempt
        base.update(
            {
                "attempt_id": attempt.attempt_id,
                "attempt_status": lifecycle.effective_status.value,
                "attempt_record_status": lifecycle.record_status.value,
                "attempt_lifecycle_phase": lifecycle.phase.value,
                "closure_request_id": lifecycle.closure_request_id,
                "closure_id": lifecycle.closure_id,
                "accepts_scientific_mutation": (lifecycle.accepts_scientific_mutation),
            }
        )
        if lifecycle.is_closed:
            return {**base, "status": "closed"}
        if not lifecycle.accepts_scientific_mutation:
            return {**base, "status": lifecycle.phase.value}
        from .scientific_attempt_repositories import (
            ScientificSelectionIntegrityError,
        )

        try:
            resolved_head = (
                self.context.repositories.scientific_selections.resolve_head(
                    attempt.attempt_id
                )
            )
        except ScientificSelectionIntegrityError as exc:
            return {
                **base,
                "status": "selection_head_invalid",
                "error_code": exc.error_code,
                "integrity_reason": exc.reason_code,
            }
        if resolved_head is None:
            return {**base, "status": "selection_head_missing"}
        base.update(
            {
                "selection_id": resolved_head.head.selection_id,
                "selection_revision": resolved_head.head.revision,
                "selection_state": resolved_head.selection.state.value,
                "head_state_version": resolved_head.head.state_version,
            }
        )
        if self.context.scientific_workflow_contract_registry is None:
            return {**base, "status": "evaluation_registry_unavailable"}

        from .scientific_attempts import ScientificAttemptError
        from .scientific_attempts import ScientificAttemptService

        try:
            evaluation = ScientificAttemptService(
                self.context.repositories,
                workflow_contract_registry=(
                    self.context.scientific_workflow_contract_registry
                ),
            ).evaluate_selection(
                attempt_id=attempt.attempt_id,
                selection_id=resolved_head.head.selection_id,
            )
        except ScientificAttemptError as exc:
            return {
                **base,
                "status": "evaluation_blocked",
                "error_code": exc.error_code,
            }
        return {
            **base,
            "status": "evaluated",
            "evaluation": evaluation.summary(max_ids=8),
        }

    def _fail_ready_gate(
        self,
        claimed: AgentRuntimeSignal,
        agent: AgentMember,
        task: Task,
        *,
        summary: str,
        teammate_status: str,
    ) -> AgentRuntimeOutcome:
        failed, _, _ = self._fail_signal(
            claimed,
            error_message=summary,
        )
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
                "worker_session_fencing_token": None
                if lease is None
                else lease.fencing_token,
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

    def _master_skill_keys_for_signal(
        self, signal: AgentRuntimeSignal
    ) -> tuple[str, ...]:
        """Restore only the explicit focus bound to a canonical user message."""

        if signal.reason is not AgentRuntimeSignalReason.INBOX_UNREAD:
            return ()
        message = self._message_for_signal(signal)
        if message is None:
            raise ValueError("master inbox_unread signal source message is missing")
        if message.session_id != signal.session_id:
            raise ValueError(
                "master inbox_unread signal source message session does not match"
            )
        if (
            message.recipient_kind is InboxParticipantKind.AGENT
            and message.recipient == signal.agent_id
        ):
            return ()
        if (
            message.message_type != "user_message"
            or message.sender != "user"
            or message.sender_kind is not InboxParticipantKind.USER
            or message.recipient != "harness"
            or message.recipient_kind is not InboxParticipantKind.HARNESS
            or message.payload_ref is None
        ):
            raise ValueError("master inbox_unread signal source routing is invalid")
        document = self.context.repositories.engine_documents.get(message.payload_ref)
        if (
            document is None
            or document.session_id != signal.session_id
            or document.invocation_id is not None
            or document.document_kind != "conversation_message"
            or document.payload.get("message_id") != message.message_id
            or document.payload.get("role") != "user"
        ):
            raise ValueError("canonical user conversation document binding is invalid")
        raw_skill_keys = document.payload.get("skill_keys", [])
        if not isinstance(raw_skill_keys, list) or not all(
            isinstance(item, str) for item in raw_skill_keys
        ):
            raise ValueError(
                "user conversation focus skill_keys must be an array of strings"
            )
        return RestoreFocus(skill_keys=tuple(raw_skill_keys)).normalized().skill_keys

    def _message_for_signal(self, signal: AgentRuntimeSignal):
        if not signal.source_ref:
            return None
        return self.context.repositories.inbox.get(signal.source_ref)

    def _resolve_task(
        self,
        signal: AgentRuntimeSignal,
        agent: AgentMember,
        payload: dict[str, Any] | None,
    ) -> Task | None:
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
        if (
            signal.reason is AgentRuntimeSignalReason.ENGINE_COMPLETED
            and signal.source_ref
        ):
            failures = self.context.repositories.failure_observations.list_by_source(
                session_id=signal.session_id,
                source_kind="continuation",
                source_ref=signal.source_ref,
            )
            if failures:
                lines = [
                    "A controlled operation completed with failure evidence.",
                    "Harness facts: "
                    + json.dumps(
                        [failure.to_dict() for failure in failures],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    (
                        "Choose freely among a safe repair/replan, reconciliation, "
                        "requesting user or operator help, or "
                        "task.finish(status='blocked'). Use "
                        "task.finish(status='failed') only when the task itself is "
                        "genuinely impossible. Do not replay an unknown external "
                        "effect."
                    ),
                    f"Task {task.task_id}: {task.description or task.subject}",
                ]
                return "\n".join(lines)
        if signal.reason is AgentRuntimeSignalReason.APPROVAL_RESOLVED:
            invocation_id = self._execution_invocation_id_for_approval(
                signal.source_ref
            )
            failure = self._execution_failure_for_approval(signal.source_ref)
            status_line = (
                ""
                if invocation_id is None
                else f" Existing execution pipeline invocation: {invocation_id}."
            )
            lines = [
                f"Approval {signal.source_ref or signal.correlation_id or 'unknown'} was resolved for your assigned task.",
                "Continue the existing delegated work from the shared workspace state."
                + status_line,
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
                    lines.append(
                        f"Pipeline stderr excerpt: {failure['stderr_excerpt']}"
                    )
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
        notify: bool = True,
    ) -> AgentRuntimeSignal | None:
        existing = self.context.repositories.runtime_signals.find_source_signal(
            session_id=session_id,
            agent_id="agent:master",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=source_signal.signal_id,
        )
        if existing is not None:
            if notify and not existing.status.is_terminal:
                self._notify_signal(existing.session_id)
            return existing
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
        return self.enqueue_signal(
            session_id=session_id,
            agent_id="agent:master",
            task_id=task.task_id,
            lane_id=task.lane_id,
            correlation_id=correlation_id,
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            source_ref=source_signal.signal_id,
            notify=notify,
        )

    def _execution_invocation_id_for_approval(
        self, approval_id: str | None
    ) -> str | None:
        if not approval_id:
            return None
        for invocation in self.context.repositories.invocations.list_by_session(
            self.context.snapshot.session.session_id
        ):
            if (
                invocation.engine_name == "execution"
                and invocation.approval_id == approval_id
            ):
                return invocation.invocation_id
        return None

    def _execution_failure_for_approval(
        self, approval_id: str | None
    ) -> dict[str, Any] | None:
        if not approval_id:
            return None
        for invocation in self.context.repositories.invocations.list_by_session(
            self.context.snapshot.session.session_id
        ):
            if (
                invocation.engine_name != "execution"
                or invocation.approval_id != approval_id
            ):
                continue
            if not invocation.output_ref:
                continue
            document = self.context.repositories.engine_documents.get(
                invocation.output_ref
            )
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
            runtime_state=agent.runtime_state
            if runtime_state is ...
            else runtime_state,
            current_correlation_id=agent.current_correlation_id
            if correlation_id is ...
            else correlation_id,
            wakeup_reason=agent.wakeup_reason
            if wakeup_reason is ...
            else wakeup_reason,
            last_active_at=agent.last_active_at
            if last_active_at is ...
            else last_active_at,
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
