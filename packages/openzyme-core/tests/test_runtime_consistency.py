import pytest

from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_core import CoreRepositories
from openzyme_core import RuntimeConsistencyService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureRecoverability
from openzyme_domain import RetryEligibility
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus
from openzyme_runtime import record_failure_observation


NOW = "2026-04-16T10:00:00+00:00"
EXECUTOR_AGENT_ID = "agent:executor:consistency"


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create("sess_consistency", "proj_001", "Consistency", "Consistency")
    )
    repositories.tasks.save(
        Task.create(
            "task_consistency",
            "sess_consistency",
            "Run work",
            "Run work.",
            kind="execution",
            status=TaskStatus.IN_PROGRESS,
            assigned_ref=EXECUTOR_AGENT_ID,
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id=EXECUTOR_AGENT_ID,
            session_id="sess_consistency",
            lane_id=None,
            task_id="task_consistency",
            name="Executor",
            role="executor",
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=NOW,
            updated_at=NOW,
        )
    )
    return repositories


def _codes(audit) -> set[str]:
    return {warning.code for warning in audit.warnings}


def test_historical_text_only_agent_turn_failure_keeps_task_unchanged() -> None:
    repositories = _repositories()
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_max_steps",
            session_id="sess_consistency",
            agent_id=EXECUTOR_AGENT_ID,
            task_id="task_consistency",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.FAILED,
            created_at=NOW,
            completed_at=NOW,
            error_message="max_steps_exceeded",
            last_error="executor exceeded the delegated work step budget.",
        )
    )
    agent = repositories.agents.get("sess_consistency", EXECUTOR_AGENT_ID)
    assert agent is not None
    repositories.agents.save(
        AgentMember(
            **{
                **agent.to_dict(),
                "status": AgentMemberStatus.FAILED,
                "updated_at": "2026-04-16T10:01:00+00:00",
            }
        )
    )

    audit = RuntimeConsistencyService(repositories).audit_session("sess_consistency")
    task = repositories.tasks.get("task_consistency")

    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.failure_summary is None
    assert "agent_turn_failed" in _codes(audit)
    attention = audit.to_dict()["task_attention"][0]
    assert attention["task_failed"] is False
    assert attention["runtime_signal_failed"] is True
    assert attention["agent_turn_failed"] is True
    assert attention["needs_attention"] is True


def test_structured_budget_failure_classifies_without_error_text_matching() -> None:
    repositories = _repositories()
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_structured_budget",
            session_id="sess_consistency",
            agent_id=EXECUTOR_AGENT_ID,
            task_id="task_consistency",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.FAILED,
            created_at=NOW,
            completed_at=NOW,
            attempt_count=1,
            error_message="opaque terminal signal",
        )
    )
    observation = record_failure_observation(
        repositories,
        session_id="sess_consistency",
        task_id="task_consistency",
        agent_id=EXECUTOR_AGENT_ID,
        source_kind="runtime_signal",
        source_ref="sig_structured_budget",
        source_version="attempt:1",
        phase="runtime",
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.AGENT_CAN_REPLAN,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code=AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE,
        safe_summary="The bounded agent turn exhausted its step budget.",
        facts={
            "effect_scope": "runtime_signal_transition",
            "effect_scope_ref": "sig_structured_budget",
        },
    )

    audit = RuntimeConsistencyService(repositories).audit_session(
        "sess_consistency"
    )
    task = repositories.tasks.get("task_consistency")
    codes = _codes(audit)
    attention = audit.to_dict()["task_attention"][0]

    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.failure_summary is None
    assert AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE in codes
    assert "agent_turn_failed" not in codes
    assert observation.failure_id in attention["failure_observation_ids"]
    assert attention["runtime_signal_failed"] is True
    assert attention["agent_turn_failed"] is True
    assert AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE in attention["reasons"]


def test_structured_generic_failure_ignores_legacy_max_step_text() -> None:
    repositories = _repositories()
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_structured_generic",
            session_id="sess_consistency",
            agent_id=EXECUTOR_AGENT_ID,
            task_id="task_consistency",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.FAILED,
            created_at=NOW,
            completed_at=NOW,
            attempt_count=1,
            error_message="max_steps_exceeded",
        )
    )
    record_failure_observation(
        repositories,
        session_id="sess_consistency",
        task_id="task_consistency",
        agent_id=EXECUTOR_AGENT_ID,
        source_kind="runtime_signal",
        source_ref="sig_structured_generic",
        source_version="attempt:1",
        phase="runtime",
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="runtime_signal_failed",
        safe_summary="The runtime signal failed.",
    )

    audit = RuntimeConsistencyService(repositories).audit_session(
        "sess_consistency"
    )
    codes = _codes(audit)
    attention = audit.to_dict()["task_attention"][0]

    assert "runtime_signal_failed" in codes
    assert AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE not in codes
    assert "agent_turn_failed" not in codes
    assert attention["runtime_signal_failed"] is True
    assert attention["agent_turn_failed"] is False


def test_running_invocation_with_terminal_agent_produces_attention_only() -> None:
    repositories = _repositories()
    agent = repositories.agents.get("sess_consistency", EXECUTOR_AGENT_ID)
    assert agent is not None
    repositories.agents.save(
        AgentMember(
            **{
                **agent.to_dict(),
                "status": AgentMemberStatus.FAILED,
                "updated_at": "2026-04-16T10:01:00+00:00",
            }
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_running",
            session_id="sess_consistency",
            task_id="task_consistency",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="task_consistency:execution:running",
            started_at=NOW,
        )
    )

    audit = RuntimeConsistencyService(repositories).audit_session("sess_consistency")
    task = repositories.tasks.get("task_consistency")

    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert "active_invocation_agent_terminal" in _codes(audit)
    attention = audit.to_dict()["task_attention"][0]
    assert attention["needs_attention"] is True
    assert "active_invocation_agent_terminal" in attention["reasons"]


@pytest.mark.parametrize(
    "status",
    (
        EngineInvocationStatus.SUCCEEDED,
        EngineInvocationStatus.FAILED,
        EngineInvocationStatus.CANCELLED,
    ),
)
def test_terminal_invocation_leaves_unconsumed_capability_outcome_without_task_completion(
    status: EngineInvocationStatus,
) -> None:
    repositories = _repositories()
    repositories.invocations.save(
        EngineInvocation(
            invocation_id=f"inv_{status.value}",
            session_id="sess_consistency",
            task_id="task_consistency",
            lane_id=None,
            engine_name="execution",
            status=status,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key=f"task_consistency:execution:{status.value}",
            started_at=NOW,
            finished_at="2026-04-16T10:02:00+00:00",
        )
    )

    audit = RuntimeConsistencyService(repositories).audit_session("sess_consistency")
    task = repositories.tasks.get("task_consistency")

    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert "terminal_capability_outcome_unconsumed" in _codes(audit)
    assert "invocation_terminal_awaiting_task_finish" not in _codes(audit)
    attention = audit.to_dict()["task_attention"][0]
    assert "awaiting_task_finish" not in attention
    assert attention["capability_outcome_ready"] is True
    assert attention["outcome_unconsumed"] is True
    if status is EngineInvocationStatus.SUCCEEDED:
        assert attention["needs_attention"] is False


def test_in_progress_task_with_failed_runtime_work_gets_attention_only() -> None:
    repositories = _repositories()
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_failed",
            session_id="sess_consistency",
            agent_id=EXECUTOR_AGENT_ID,
            task_id="task_consistency",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.FAILED,
            created_at=NOW,
            completed_at=NOW,
            error_message="runtime_exception",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_failed",
            session_id="sess_consistency",
            task_id="task_consistency",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.FAILED,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="task_consistency:execution:failed",
            started_at=NOW,
            finished_at="2026-04-16T10:02:00+00:00",
        )
    )

    audit = RuntimeConsistencyService(repositories).audit_session("sess_consistency")
    task = repositories.tasks.get("task_consistency")

    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert "runtime_signal_failed" in _codes(audit)
    assert "task_runtime_attention" in _codes(audit)
    attention = audit.to_dict()["task_attention"][0]
    assert attention["runtime_attention"] is True
    assert attention["needs_attention"] is True
    assert attention["task_failed"] is False
