from __future__ import annotations

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import ProtocolService
from openzyme_core import SessionProjectionBuilder
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
        title="Workspace projection",
        objective="Assemble Session 06 read models",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T13:00:00+00:00",
        updated_at="2026-04-17T13:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name="wt/analysis",
            claimed_ref="agent:planner",
            created_at="2026-04-17T13:00:01+00:00",
            updated_at="2026-04-17T13:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Research target",
            description="Start analysis",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:planner",
            created_at="2026-04-17T13:00:02+00:00",
            updated_at="2026-04-17T13:00:02+00:00",
            lane_id="lane_001",
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            kind="execution_launch",
            requested_action="Approve launch",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_001.json",
            resolution_ref=None,
            created_at="2026-04-17T13:00:03+00:00",
        )
    )
    repositories.memory.save(
        MemoryEntry(
            memory_id="mem_001",
            session_id=session.session_id,
            scope_kind=MemoryScopeKind.SESSION,
            scope_ref=session.session_id,
            kind=MemoryKind.COMPACTION,
            summary="Compressed continuity",
            source_range="auto:harness_run",
            importance=8,
            created_at="2026-04-17T13:00:04+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="deep_research",
            status=EngineInvocationStatus.RUNNING,
            input_ref="artifact://engine/inv_001/input.json",
            output_ref=None,
            approval_id=None,
            idempotency_key="task_001:deep_research:1",
            started_at="2026-04-17T13:00:05+00:00",
        )
    )
    service = ProtocolService(repositories)
    service.delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="delegate",
        payload_ref="artifact://delegations/deleg_001.json",
        task_id="task_001",
        correlation_id="corr_001",
    )
    return session


def test_session_projection_builder_assembles_workspace_sections() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    workspace = SessionProjectionBuilder(repositories).build_session_workspace(session.session_id).to_dict()

    assert workspace["session"]["session_id"] == session.session_id
    assert workspace["task_board"]["next_task_id"] == "task_001"
    assert workspace["lane_board"]["lanes"][0]["lane"]["lane_id"] == "lane_001"
    assert workspace["pending_approvals"][0]["approval_id"] == "appr_001"
    assert workspace["delegation"]["agents"][0]["agent"]["agent_id"] == "agent:researcher"
    assert "deep_research" in workspace["capabilities"]
    assert any(item["event_type"] == "approval.requested" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "agent.spawned" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "engine.invocation.started" for item in workspace["activity_feed"])
