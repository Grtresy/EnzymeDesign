from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_core import AGENT_RUNTIME_OUTCOME_SETTLEMENT_SCHEMA_VERSION
from openzyme_core import AgentRuntimeOutcome
from openzyme_core import AgentRuntimeOutcomeSettlement
from openzyme_core import AgentRuntimeSettlementDisposition
from openzyme_core import HarnessStatus
from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
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


def _closed_budget_handoff_facts() -> tuple[
    AgentRuntimeSignal,
    Task,
    AgentMember,
    FailureObservation,
    AgentRuntimeSignal,
]:
    source = AgentRuntimeSignal(
        signal_id="sig_budget_source",
        session_id="sess_budget",
        agent_id="agent:executor:budget",
        task_id="task_budget",
        lane_id="lane_budget",
        correlation_id="corr_budget",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.FAILED,
        created_at="2026-07-24T12:00:00+00:00",
        attempt_count=2,
        completed_at="2026-07-24T12:01:00+00:00",
        error_message=AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
    )
    task = Task.create(
        task_id="task_budget",
        session_id="sess_budget",
        subject="Budget handoff",
        description="Preserve the business task.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref="agent:executor:budget",
        lane_id="lane_budget",
    )
    agent = AgentMember(
        agent_id="agent:executor:budget",
        session_id="sess_budget",
        lane_id="lane_budget",
        task_id="task_budget",
        name="Grace",
        role="executor",
        status=AgentMemberStatus.FAILED,
        parent_agent_id="agent:master",
        created_at="2026-07-24T11:59:00+00:00",
        updated_at="2026-07-24T12:01:00+00:00",
        runtime_state="failed",
        current_correlation_id="corr_budget",
    )
    failure = FailureObservation(
        failure_id="failure_budget",
        session_id="sess_budget",
        task_id="task_budget",
        lane_id="lane_budget",
        agent_id="agent:executor:budget",
        source_kind="runtime_signal",
        source_ref="sig_budget_source",
        source_version="attempt:2",
        phase="runtime",
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code=AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
        safe_summary="The exact turn exhausted its budget.",
        facts={
            "signal_id": "sig_budget_source",
            "attempt_count": 2,
            "max_steps": 16,
            "effect_scope": "runtime_signal_transition",
            "effect_scope_ref": "sig_budget_source",
            "exact_signal_retry_eligible": False,
            "controlled_operation_effects_preserved": True,
        },
        likely_causes=(),
        evidence_refs=(),
        created_at="2026-07-24T12:01:00+00:00",
    )
    successor = AgentRuntimeSignal(
        signal_id="sig_budget_successor",
        session_id="sess_budget",
        agent_id="agent:master",
        task_id="task_budget",
        lane_id="lane_budget",
        correlation_id="corr_budget",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        source_ref="sig_budget_source",
        status=AgentRuntimeSignalStatus.PENDING,
        created_at="2026-07-24T12:01:00+00:00",
    )
    return source, task, agent, failure, successor


def test_budget_replan_handoff_is_typed_and_serializable() -> None:
    source, task, agent, failure, successor = _closed_budget_handoff_facts()

    settlement = AgentRuntimeOutcomeSettlement.budget_replan_handoff(
        source_signal=source,
        task=task,
        agent=agent,
        failure=failure,
        successor=successor,
    )
    outcome = AgentRuntimeOutcome(
        signal=source,
        task=task,
        agent=agent,
        ok=False,
        summary="The exact signal ended; master can replan.",
        teammate_status=HarnessStatus.MAX_STEPS_EXCEEDED.value,
        settlement=settlement,
    )

    payload = outcome.to_dict()
    assert settlement.disposition is (
        AgentRuntimeSettlementDisposition.BUDGET_REPLAN_HANDOFF
    )
    assert settlement.batch_barrier is True
    assert payload["settlement"] == {
        "schema_version": AGENT_RUNTIME_OUTCOME_SETTLEMENT_SCHEMA_VERSION,
        "disposition": "budget_replan_handoff",
        "source_signal_id": "sig_budget_source",
        "source_signal_status": "failed",
        "source_attempt_count": 2,
        "session_id": "sess_budget",
        "agent_id": "agent:executor:budget",
        "task_id": "task_budget",
        "lane_id": "lane_budget",
        "source_correlation_id": "corr_budget",
        "task_status": "in_progress",
        "batch_barrier": True,
        "source_error_code": AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
        "failure_observation_id": "failure_budget",
        "failure_source_version": "attempt:2",
        "failure_error_code": AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
        "successor_signal_id": "sig_budget_successor",
        "successor_signal_status": "pending",
        "successor_agent_id": "agent:master",
        "successor_source_ref": "sig_budget_source",
        "successor_task_id": "task_budget",
        "successor_lane_id": "lane_budget",
        "successor_correlation_id": "corr_budget",
    }


@pytest.mark.parametrize(
    ("fact_name", "replacement"),
    (
        (
            "terminal_task",
            lambda source, task, agent, failure, successor: (
                source,
                replace(task, status=TaskStatus.FAILED),
                agent,
                failure,
                successor,
            ),
        ),
        (
            "task_lane_drift",
            lambda source, task, agent, failure, successor: (
                source,
                replace(task, lane_id="lane_other"),
                agent,
                failure,
                successor,
            ),
        ),
        (
            "agent_task_drift",
            lambda source, task, agent, failure, successor: (
                source,
                task,
                replace(agent, task_id="task_other"),
                failure,
                successor,
            ),
        ),
        (
            "failure_agent_drift",
            lambda source, task, agent, failure, successor: (
                source,
                task,
                agent,
                replace(failure, agent_id="agent:executor:other"),
                successor,
            ),
        ),
        (
            "cancelled_successor",
            lambda source, task, agent, failure, successor: (
                source,
                task,
                agent,
                failure,
                replace(
                    successor,
                    status=AgentRuntimeSignalStatus.CANCELLED,
                ),
            ),
        ),
        (
            "successor_correlation_drift",
            lambda source, task, agent, failure, successor: (
                source,
                task,
                agent,
                failure,
                replace(successor, correlation_id="corr_other"),
            ),
        ),
    ),
)
def test_budget_replan_handoff_rejects_identity_drift(
    fact_name: str,
    replacement,  # type: ignore[no-untyped-def]
) -> None:
    del fact_name
    facts = replacement(*_closed_budget_handoff_facts())

    with pytest.raises(ValueError):
        AgentRuntimeOutcomeSettlement.budget_replan_handoff(
            source_signal=facts[0],
            task=facts[1],
            agent=facts[2],
            failure=facts[3],
            successor=facts[4],
        )
