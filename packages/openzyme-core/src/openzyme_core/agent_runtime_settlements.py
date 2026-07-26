from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_domain import AgentMember
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import RetryEligibility
from openzyme_domain import Task
from openzyme_domain import TaskStatus


AGENT_RUNTIME_OUTCOME_SETTLEMENT_SCHEMA_VERSION = (
    "agent_runtime_outcome_settlement@1"
)


class AgentRuntimeSettlementDisposition(StrEnum):
    SIGNAL_COMPLETED = "signal_completed"
    SIGNAL_FAILED = "signal_failed"
    WAITING_APPROVAL = "waiting_approval"
    BUDGET_REPLAN_HANDOFF = "budget_replan_handoff"
    SCIENTIFIC_CLOSURE_NOTIFICATION_SETTLED = (
        "scientific_closure_notification_settled"
    )


def _require_identity(field_name: str, value: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty identity")


def _require_optional_identity(field_name: str, value: str | None) -> None:
    if value is not None:
        _require_identity(field_name, value)


@dataclass(frozen=True, slots=True)
class AgentRuntimeOutcomeSettlement:
    """Immutable Core truth for one bounded runtime-signal outcome."""

    disposition: AgentRuntimeSettlementDisposition
    source_signal_id: str
    source_signal_status: AgentRuntimeSignalStatus
    source_attempt_count: int
    session_id: str
    agent_id: str
    task_id: str | None
    lane_id: str | None
    source_correlation_id: str | None
    task_status: TaskStatus | None
    batch_barrier: bool = False
    source_error_code: str | None = None
    failure_observation_id: str | None = None
    failure_source_version: str | None = None
    failure_error_code: str | None = None
    successor_signal_id: str | None = None
    successor_signal_status: AgentRuntimeSignalStatus | None = None
    successor_agent_id: str | None = None
    successor_source_ref: str | None = None
    successor_task_id: str | None = None
    successor_lane_id: str | None = None
    successor_correlation_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(
            self.disposition,
            AgentRuntimeSettlementDisposition,
        ):
            raise TypeError("runtime outcome settlement disposition is invalid")
        if not isinstance(self.source_signal_status, AgentRuntimeSignalStatus):
            raise TypeError("runtime outcome source signal status is invalid")
        if (
            type(self.source_attempt_count) is not int
            or self.source_attempt_count < 0
        ):
            raise ValueError(
                "runtime outcome source attempt count must be non-negative"
            )
        if not isinstance(self.batch_barrier, bool):
            raise TypeError("runtime outcome batch barrier must be a boolean")
        _require_identity("source_signal_id", self.source_signal_id)
        _require_identity("session_id", self.session_id)
        _require_identity("agent_id", self.agent_id)
        for field_name, value in (
            ("task_id", self.task_id),
            ("lane_id", self.lane_id),
            ("source_correlation_id", self.source_correlation_id),
            ("source_error_code", self.source_error_code),
            ("failure_observation_id", self.failure_observation_id),
            ("failure_source_version", self.failure_source_version),
            ("failure_error_code", self.failure_error_code),
            ("successor_signal_id", self.successor_signal_id),
            ("successor_agent_id", self.successor_agent_id),
            ("successor_source_ref", self.successor_source_ref),
            ("successor_task_id", self.successor_task_id),
            ("successor_lane_id", self.successor_lane_id),
            ("successor_correlation_id", self.successor_correlation_id),
        ):
            _require_optional_identity(field_name, value)
        if self.task_status is not None and not isinstance(
            self.task_status,
            TaskStatus,
        ):
            raise TypeError("runtime outcome task status is invalid")
        if self.successor_signal_status is not None and not isinstance(
            self.successor_signal_status,
            AgentRuntimeSignalStatus,
        ):
            raise TypeError("runtime outcome successor signal status is invalid")
        if (
            self.disposition
            is AgentRuntimeSettlementDisposition.BUDGET_REPLAN_HANDOFF
        ):
            self._validate_budget_replan_handoff()
        elif (
            self.disposition
            in {
                AgentRuntimeSettlementDisposition.SIGNAL_COMPLETED,
                AgentRuntimeSettlementDisposition.WAITING_APPROVAL,
                AgentRuntimeSettlementDisposition
                .SCIENTIFIC_CLOSURE_NOTIFICATION_SETTLED,
            }
            and self.source_signal_status
            is not AgentRuntimeSignalStatus.COMPLETED
        ):
            raise ValueError(
                "successful runtime settlement requires a completed signal"
            )
        elif any(
            value is not None
            for value in (
                self.failure_observation_id,
                self.failure_source_version,
                self.failure_error_code,
                self.successor_signal_id,
                self.successor_signal_status,
                self.successor_agent_id,
                self.successor_source_ref,
                self.successor_task_id,
                self.successor_lane_id,
                self.successor_correlation_id,
            )
        ):
            raise ValueError(
                "non-handoff runtime settlement cannot carry handoff identities"
            )

    def _validate_budget_replan_handoff(self) -> None:
        if (
            not self.batch_barrier
            or self.source_signal_status is not AgentRuntimeSignalStatus.FAILED
            or self.source_attempt_count <= 0
            or self.source_error_code
            != AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
            or self.task_id is None
            or self.task_status is None
            or self.task_status.is_terminal
            or self.failure_observation_id is None
            or self.failure_source_version
            != f"attempt:{self.source_attempt_count}"
            or self.failure_error_code
            != AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
            or self.successor_signal_id is None
            or self.successor_signal_status
            is not AgentRuntimeSignalStatus.PENDING
            or self.successor_agent_id != "agent:master"
            or self.successor_source_ref != self.source_signal_id
            or self.successor_task_id != self.task_id
            or self.successor_lane_id != self.lane_id
            or self.successor_correlation_id is None
        ):
            raise ValueError(
                "budget-replan handoff settlement is not canonically closed"
            )
        if (
            self.source_correlation_id is not None
            and self.successor_correlation_id != self.source_correlation_id
        ):
            raise ValueError(
                "budget-replan successor correlation does not match the source"
            )

    @classmethod
    def from_signal_outcome(
        cls,
        *,
        signal: AgentRuntimeSignal,
        task: Task | None,
        disposition: AgentRuntimeSettlementDisposition,
        batch_barrier: bool = False,
    ) -> AgentRuntimeOutcomeSettlement:
        return cls(
            disposition=disposition,
            source_signal_id=signal.signal_id,
            source_signal_status=signal.status,
            source_attempt_count=signal.attempt_count,
            session_id=signal.session_id,
            agent_id=signal.agent_id,
            task_id=signal.task_id,
            lane_id=signal.lane_id,
            source_correlation_id=signal.correlation_id,
            task_status=None if task is None else task.status,
            batch_barrier=batch_barrier,
            source_error_code=signal.error_message,
        )

    @classmethod
    def budget_replan_handoff(
        cls,
        *,
        source_signal: AgentRuntimeSignal,
        task: Task,
        agent: AgentMember,
        failure: FailureObservation,
        successor: AgentRuntimeSignal,
    ) -> AgentRuntimeOutcomeSettlement:
        if (
            source_signal.session_id != task.session_id
            or source_signal.task_id != task.task_id
            or source_signal.lane_id != task.lane_id
            or source_signal.agent_id != agent.agent_id
            or agent.session_id != source_signal.session_id
            or agent.task_id != task.task_id
            or agent.lane_id != task.lane_id
            or task.assigned_ref != agent.agent_id
        ):
            raise ValueError(
                "budget-replan source signal, task, and agent identity drifted"
            )
        if (
            failure.session_id != source_signal.session_id
            or failure.task_id != task.task_id
            or failure.lane_id != task.lane_id
            or failure.agent_id != agent.agent_id
            or failure.source_kind != "runtime_signal"
            or failure.source_ref != source_signal.signal_id
            or failure.source_version
            != f"attempt:{source_signal.attempt_count}"
            or failure.phase != "runtime"
            or failure.failure_class is not FailureClass.RUNTIME
            or failure.recoverability
            is not FailureRecoverability.AGENT_CAN_REPLAN
            or failure.effect_certainty
            is not ExternalEffectCertainty.NO_EFFECT
            or failure.retry_eligibility is not RetryEligibility.TERMINAL
            or failure.actor_kind is not FailureActorKind.SYSTEM
            or failure.error_code
            != AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
            or failure.facts.get("signal_id") != source_signal.signal_id
            or failure.facts.get("attempt_count")
            != source_signal.attempt_count
            or failure.facts.get("effect_scope")
            != "runtime_signal_transition"
            or failure.facts.get("effect_scope_ref")
            != source_signal.signal_id
            or failure.facts.get("exact_signal_retry_eligible") is not False
            or failure.facts.get("controlled_operation_effects_preserved")
            is not True
            or type(failure.facts.get("max_steps")) is not int
            or int(failure.facts["max_steps"]) <= 0
        ):
            raise ValueError(
                "budget-replan failure observation is not canonically closed"
            )
        if (
            successor.session_id != source_signal.session_id
            or successor.agent_id != "agent:master"
            or successor.reason is not AgentRuntimeSignalReason.MANUAL_RESUME
            or successor.status is not AgentRuntimeSignalStatus.PENDING
            or successor.source_ref != source_signal.signal_id
            or successor.task_id != task.task_id
            or successor.lane_id != task.lane_id
            or successor.correlation_id is None
            or (
                source_signal.correlation_id is not None
                and successor.correlation_id
                != source_signal.correlation_id
            )
        ):
            raise ValueError(
                "budget-replan successor signal is not canonically closed"
            )
        return cls(
            disposition=(
                AgentRuntimeSettlementDisposition.BUDGET_REPLAN_HANDOFF
            ),
            source_signal_id=source_signal.signal_id,
            source_signal_status=source_signal.status,
            source_attempt_count=source_signal.attempt_count,
            session_id=source_signal.session_id,
            agent_id=source_signal.agent_id,
            task_id=source_signal.task_id,
            lane_id=source_signal.lane_id,
            source_correlation_id=source_signal.correlation_id,
            task_status=task.status,
            batch_barrier=True,
            source_error_code=source_signal.error_message,
            failure_observation_id=failure.failure_id,
            failure_source_version=failure.source_version,
            failure_error_code=failure.error_code,
            successor_signal_id=successor.signal_id,
            successor_signal_status=successor.status,
            successor_agent_id=successor.agent_id,
            successor_source_ref=successor.source_ref,
            successor_task_id=successor.task_id,
            successor_lane_id=successor.lane_id,
            successor_correlation_id=successor.correlation_id,
        )

    @classmethod
    def scientific_closure_notification(
        cls,
        *,
        signal: AgentRuntimeSignal,
        task: Task,
    ) -> AgentRuntimeOutcomeSettlement:
        return cls.from_signal_outcome(
            signal=signal,
            task=task,
            disposition=(
                AgentRuntimeSettlementDisposition
                .SCIENTIFIC_CLOSURE_NOTIFICATION_SETTLED
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": AGENT_RUNTIME_OUTCOME_SETTLEMENT_SCHEMA_VERSION,
            "disposition": self.disposition.value,
            "source_signal_id": self.source_signal_id,
            "source_signal_status": self.source_signal_status.value,
            "source_attempt_count": self.source_attempt_count,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "source_correlation_id": self.source_correlation_id,
            "task_status": (
                None if self.task_status is None else self.task_status.value
            ),
            "batch_barrier": self.batch_barrier,
            "source_error_code": self.source_error_code,
            "failure_observation_id": self.failure_observation_id,
            "failure_source_version": self.failure_source_version,
            "failure_error_code": self.failure_error_code,
            "successor_signal_id": self.successor_signal_id,
            "successor_signal_status": (
                None
                if self.successor_signal_status is None
                else self.successor_signal_status.value
            ),
            "successor_agent_id": self.successor_agent_id,
            "successor_source_ref": self.successor_source_ref,
            "successor_task_id": self.successor_task_id,
            "successor_lane_id": self.successor_lane_id,
            "successor_correlation_id": self.successor_correlation_id,
        }


__all__ = [
    "AGENT_RUNTIME_OUTCOME_SETTLEMENT_SCHEMA_VERSION",
    "AgentRuntimeOutcomeSettlement",
    "AgentRuntimeSettlementDisposition",
]
