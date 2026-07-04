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
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain import TaskStatus


NOW = "2026-04-16T10:00:00+00:00"


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
            assigned_ref="agent:executor",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:executor",
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


def test_signal_and_agent_turn_failures_do_not_mark_business_task_failed() -> None:
    repositories = _repositories()
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_max_steps",
            session_id="sess_consistency",
            agent_id="agent:executor",
            task_id="task_consistency",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            status=AgentRuntimeSignalStatus.FAILED,
            created_at=NOW,
            completed_at=NOW,
            error_message="max_steps_exceeded",
            last_error="executor exceeded the delegated work step budget.",
        )
    )
    agent = repositories.agents.get("sess_consistency", "agent:executor")
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


def test_running_invocation_with_terminal_agent_produces_attention_only() -> None:
    repositories = _repositories()
    agent = repositories.agents.get("sess_consistency", "agent:executor")
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


def test_terminal_invocation_awaits_explicit_task_finish_without_completion() -> None:
    repositories = _repositories()
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_succeeded",
            session_id="sess_consistency",
            task_id="task_consistency",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="task_consistency:execution:succeeded",
            started_at=NOW,
            finished_at="2026-04-16T10:02:00+00:00",
        )
    )

    audit = RuntimeConsistencyService(repositories).audit_session("sess_consistency")
    task = repositories.tasks.get("task_consistency")

    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS
    assert "invocation_terminal_awaiting_task_finish" in _codes(audit)
    attention = audit.to_dict()["task_attention"][0]
    assert attention["awaiting_task_finish"] is True
    assert attention["needs_attention"] is False


def test_in_progress_task_with_failed_runtime_work_gets_attention_only() -> None:
    repositories = _repositories()
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_failed",
            session_id="sess_consistency",
            agent_id="agent:executor",
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
