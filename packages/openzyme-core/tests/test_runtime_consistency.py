import pytest

from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_core import AgentCapabilityLeaseService
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
            member_id="member_executor_consistency",
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
    AgentCapabilityLeaseService(repositories).reserve_and_issue(
        session_id="sess_consistency",
        agent_id=EXECUTOR_AGENT_ID,
        idempotency_key="runtime-consistency:executor:generation-1",
        actor_ref="test:runtime-consistency-capability",
    )
    return repositories


def _runtime_signal_binding(repositories: CoreRepositories) -> dict[str, object]:
    leases = repositories.agent_capability_leases.list_by_session(
        "sess_consistency"
    )
    assert len(leases) == 1
    return {
        "capability_lease_id": leases[0].lease_id,
        "workspace_generation": leases[0].workspace_generation,
    }


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
            **_runtime_signal_binding(repositories),
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
            **_runtime_signal_binding(repositories),
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
            **_runtime_signal_binding(repositories),
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


@pytest.mark.parametrize(
    ("actor_kind", "recoverability", "effect_certainty"),
    (
        (
            FailureActorKind.HARNESS,
            FailureRecoverability.AGENT_CAN_REPLAN,
            ExternalEffectCertainty.NO_EFFECT,
        ),
        (
            FailureActorKind.AGENT,
            FailureRecoverability.AGENT_CAN_REPLAN,
            ExternalEffectCertainty.EFFECT_KNOWN,
        ),
        (
            FailureActorKind.HARNESS,
            FailureRecoverability.TERMINAL,
            ExternalEffectCertainty.TERMINAL_KNOWN,
        ),
    ),
)
def test_effect_known_ordinary_failure_remains_observable_without_runtime_attention(
    actor_kind: FailureActorKind,
    recoverability: FailureRecoverability,
    effect_certainty: ExternalEffectCertainty,
) -> None:
    repositories = _repositories()
    observation = record_failure_observation(
        repositories,
        session_id="sess_consistency",
        task_id="task_consistency",
        agent_id=EXECUTOR_AGENT_ID,
        source_kind="tool_invocation",
        source_ref=f"ordinary_{actor_kind.value}_{recoverability.value}",
        source_version="agentstep:1",
        phase="validation",
        failure_class=FailureClass.VALIDATION,
        recoverability=recoverability,
        effect_certainty=effect_certainty,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=actor_kind,
        error_code="ordinary_action_rejected",
        safe_summary="The ordinary action was rejected with a known effect state.",
    )

    audit = RuntimeConsistencyService(repositories).audit_session(
        "sess_consistency"
    )

    assert observation in repositories.failure_observations.list_by_session(
        "sess_consistency"
    )
    assert "failure_reconciliation_required" not in _codes(audit)
    assert audit.to_dict()["task_attention"] == []
    assert audit.to_dict()["needs_attention_count"] == 0


@pytest.mark.parametrize(
    (
        "case_id",
        "actor_kind",
        "recoverability",
        "effect_certainty",
        "retry_eligibility",
        "expected_code",
    ),
    (
        (
            "system",
            FailureActorKind.SYSTEM,
            FailureRecoverability.AGENT_CAN_REPLAN,
            ExternalEffectCertainty.NO_EFFECT,
            RetryEligibility.SAME_PHASE_SAFE,
            "system_runtime_failure",
        ),
        (
            "reconciliation",
            FailureActorKind.HARNESS,
            FailureRecoverability.RECONCILIATION_REQUIRED,
            ExternalEffectCertainty.NO_EFFECT,
            RetryEligibility.RECONCILE_REQUIRED,
            "failure_reconciliation_required",
        ),
        (
            "authorization",
            FailureActorKind.HARNESS,
            FailureRecoverability.AUTHORIZATION_REQUIRED,
            ExternalEffectCertainty.NO_EFFECT,
            RetryEligibility.TERMINAL,
            "failure_authorization_required",
        ),
        (
            "runtime-retry",
            FailureActorKind.AGENT,
            FailureRecoverability.RUNTIME_RETRY,
            ExternalEffectCertainty.EFFECT_KNOWN,
            RetryEligibility.VERIFY_THEN_RETRY,
            "failure_runtime_retry_required",
        ),
        (
            "unknown-effect",
            FailureActorKind.HARNESS,
            FailureRecoverability.AGENT_CAN_REPLAN,
            ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            RetryEligibility.VERIFY_THEN_RETRY,
            "failure_reconciliation_required",
        ),
    ),
)
def test_true_runtime_boundaries_retain_precise_attention(
    case_id: str,
    actor_kind: FailureActorKind,
    recoverability: FailureRecoverability,
    effect_certainty: ExternalEffectCertainty,
    retry_eligibility: RetryEligibility,
    expected_code: str,
) -> None:
    repositories = _repositories()
    observation = record_failure_observation(
        repositories,
        session_id="sess_consistency",
        task_id="task_consistency",
        agent_id=EXECUTOR_AGENT_ID,
        source_kind="runtime_boundary",
        source_ref=f"boundary_{case_id}",
        source_version="attempt:1",
        phase="runtime",
        failure_class=FailureClass.RUNTIME,
        recoverability=recoverability,
        effect_certainty=effect_certainty,
        retry_eligibility=retry_eligibility,
        actor_kind=actor_kind,
        error_code=f"{case_id}_failure",
        safe_summary="A typed runtime boundary requires attention.",
    )

    audit = RuntimeConsistencyService(repositories).audit_session(
        "sess_consistency"
    )
    attention = audit.to_dict()["task_attention"][0]

    assert expected_code in _codes(audit)
    assert attention["runtime_attention"] is True
    assert attention["needs_attention"] is True
    assert attention["failure_observation_ids"] == [observation.failure_id]


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
            **_runtime_signal_binding(repositories),
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
