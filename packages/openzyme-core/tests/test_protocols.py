from __future__ import annotations

from openzyme_domain import AgentMemberStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import CorrelationStatus
from openzyme_core import ProtocolService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Protocols",
        objective="Exercise Session 06 protocol behavior",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T12:00:00+00:00",
        updated_at="2026-04-17T12:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name=None,
            claimed_ref="agent:planner",
            created_at="2026-04-17T12:00:01+00:00",
            updated_at="2026-04-17T12:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Analyze",
            description="Primary delegated task",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:planner",
            created_at="2026-04-17T12:00:02+00:00",
            updated_at="2026-04-17T12:00:02+00:00",
            lane_id="lane_001",
        )
    )
    return session


def test_protocol_service_builds_correlation_threads_for_delegation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)

    envelope = service.delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="delegate",
        payload_ref="artifact://delegations/deleg_001.json",
        task_id="task_001",
        correlation_id="corr_001",
    )
    response = service.reply(
        session_id=session.session_id,
        sender="agent:researcher",
        sender_kind=InboxParticipantKind.AGENT,
        recipient="harness",
        recipient_kind=InboxParticipantKind.HARNESS,
        message_type="delegation_result",
        correlation_id="corr_001",
        payload_ref="artifact://delegations/deleg_001-result.json",
    )
    thread = service.build_thread(session.session_id, "corr_001")

    assert envelope.agent.agent_id == "agent:researcher"
    assert envelope.request_message.message_type == "delegation_request"
    assert response.message_type == "delegation_result"
    assert thread.request is not None
    assert thread.request.message_type == "delegation_request"
    assert [message.message_type for message in thread.responses] == ["delegation_result"]
    assert thread.status is CorrelationStatus.RESPONDED


def test_background_completion_updates_agent_and_invocation_state() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    service.delegate(
        session_id=session.session_id,
        agent_id="agent:executor",
        name="Executor",
        role="delegate",
        payload_ref="artifact://delegations/deleg_002.json",
        task_id="task_001",
        correlation_id="corr_bg_001",
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref="artifact://engine/inv_001/input.json",
            output_ref=None,
            approval_id=None,
            idempotency_key="task_001:execution:1",
            started_at="2026-04-17T12:00:03+00:00",
        )
    )

    completion = service.complete_background_task(
        session_id=session.session_id,
        correlation_id="corr_bg_001",
        recipient="harness",
        payload_ref="artifact://engine/inv_001/output.json",
        invocation_id="inv_001",
        agent_id="agent:executor",
        success=True,
    )

    assert completion.notification.message_type == "background_completion"
    assert repositories.agents.get("agent:executor").status is AgentMemberStatus.COMPLETED
    assert repositories.invocations.get("inv_001").status is EngineInvocationStatus.SUCCEEDED
    assert service.build_thread(session.session_id, "corr_bg_001").status is CorrelationStatus.COMPLETED


def test_background_completion_preserves_existing_invocation_output_ref() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = ProtocolService(repositories)
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_002",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref="artifact://engine/inv_002/input.json",
            output_ref="artifact://engine/inv_002/existing-output.json",
            approval_id=None,
            idempotency_key="task_001:execution:2",
            started_at="2026-04-17T12:00:03+00:00",
        )
    )

    service.complete_background_task(
        session_id=session.session_id,
        correlation_id="corr_bg_002",
        recipient="harness",
        payload_ref="artifact://engine/inv_002/background-notification.json",
        invocation_id="inv_002",
        success=True,
    )

    assert repositories.invocations.get("inv_002").output_ref == "artifact://engine/inv_002/existing-output.json"
