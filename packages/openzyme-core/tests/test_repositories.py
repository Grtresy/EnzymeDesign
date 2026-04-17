from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
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
from openzyme_core import LaneLifecycleEventRecord
from openzyme_core import OwnershipError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite


def test_core_repositories_persist_v3_control_plane_records() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Thermostability redesign",
        objective="Move V3 control-plane work forward",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-16T10:00:00+00:00",
        updated_at="2026-04-16T10:00:00+00:00",
    )
    root_task = Task(
        task_id="task_root",
        session_id=session.session_id,
        subject="Research scaffold",
        description="Collect the first scaffold shortlist.",
        status=TaskStatus.COMPLETED,
        priority=TaskPriority.HIGH,
        kind="research",
        assigned_ref="agent:host",
        created_at="2026-04-16T10:01:00+00:00",
        updated_at="2026-04-16T10:02:00+00:00",
    )
    child_task = Task(
        task_id="task_exec",
        session_id=session.session_id,
        subject="Prepare execution handoff",
        description="Turn the shortlist into an execution plan.",
        status=TaskStatus.TODO,
        priority=TaskPriority.NORMAL,
        kind="execution",
        assigned_ref="agent:planner",
        created_at="2026-04-16T10:03:00+00:00",
        updated_at="2026-04-16T10:03:00+00:00",
        lane_id="lane_001",
        blocked_by=(root_task.task_id,),
    )
    lane = Lane(
        lane_id="lane_001",
        session_id=session.session_id,
        name="analysis",
        status=LaneStatus.CLAIMED,
        cwd="/tmp/lane_001",
        branch_name="v3/session-02",
        claimed_ref="agent:planner",
        created_at="2026-04-16T10:04:00+00:00",
        updated_at="2026-04-16T10:04:00+00:00",
    )
    approval = ApprovalRequest(
        approval_id="appr_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        kind="execution_launch",
        requested_action="Approve the first HPC launch",
        status=ApprovalRequestStatus.PENDING,
        request_ref="artifact://approval/appr_001/request.json",
        resolution_ref=None,
        created_at="2026-04-16T10:05:00+00:00",
    )
    inbox = InboxMessage(
        message_id="msg_001",
        session_id=session.session_id,
        sender="user:alice",
        sender_kind=InboxParticipantKind.USER,
        recipient="agent:planner",
        recipient_kind=InboxParticipantKind.AGENT,
        message_type="task_update",
        correlation_id="corr_001",
        payload_ref="artifact://messages/msg_001.json",
        status=InboxStatus.DELIVERED,
        created_at="2026-04-16T10:06:00+00:00",
    )
    memory = MemoryEntry(
        memory_id="mem_001",
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.TASK,
        scope_ref=child_task.task_id,
        kind=MemoryKind.SUMMARY,
        summary="Execution should wait for scaffold evidence sign-off.",
        source_range="turns:1-3",
        importance=7,
        created_at="2026-04-16T10:07:00+00:00",
    )
    agent = AgentMember(
        agent_id="agent_001",
        session_id=session.session_id,
        lane_id=lane.lane_id,
        task_id=child_task.task_id,
        name="Planner",
        role="execution_planner",
        status=AgentMemberStatus.ACTIVE,
        parent_agent_id=None,
        created_at="2026-04-16T10:08:00+00:00",
        updated_at="2026-04-16T10:08:00+00:00",
    )
    invocation = EngineInvocation(
        invocation_id="inv_001",
        session_id=session.session_id,
        task_id=child_task.task_id,
        lane_id=lane.lane_id,
        engine_name="deep_research",
        status=EngineInvocationStatus.WAITING_APPROVAL,
        input_ref="artifact://engine/inv_001/input.json",
        output_ref=None,
        approval_id=approval.approval_id,
        idempotency_key="task_exec:deep_research:v1",
        started_at="2026-04-16T10:09:00+00:00",
    )
    lane_event = LaneLifecycleEventRecord(
        event_id="lane_evt_001",
        session_id=session.session_id,
        lane_id=lane.lane_id,
        task_id=child_task.task_id,
        event_type="task.bound_to_lane",
        created_at="2026-04-16T10:09:30+00:00",
        payload={"task_id": child_task.task_id},
    )

    repositories.sessions.save(session)
    repositories.tasks.save(root_task)
    repositories.lanes.save(lane)
    repositories.tasks.save(child_task)
    repositories.approvals.save(approval)
    repositories.inbox.save(inbox)
    repositories.memory.save(memory)
    repositories.agents.save(agent)
    repositories.invocations.save(invocation)
    repositories.lane_events.save(lane_event)

    assert repositories.sessions.get(session.session_id) == session
    assert repositories.tasks.list_by_session(session.session_id) == [root_task, child_task]
    assert repositories.tasks.list_by_lane(session.session_id, lane.lane_id) == [child_task]
    assert repositories.tasks.get(child_task.task_id) == child_task
    assert repositories.lane_events.list_by_lane(session.session_id, lane.lane_id) == [lane_event]
    assert repositories.approvals.list_pending_by_session(session.session_id) == [approval]
    assert repositories.inbox.list_by_session(session.session_id) == [inbox]
    assert repositories.memory.list_by_scope(
        session.session_id, MemoryScopeKind.TASK, child_task.task_id
    ) == [memory]
    assert repositories.agents.list_by_session(session.session_id) == [agent]
    assert repositories.invocations.list_by_session(session.session_id) == [invocation]
    assert repositories.invocations.list_active_by_session(session.session_id) == [invocation]


def test_task_ready_query_filters_out_blocked_work() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session.create(
        session_id="sess_001",
        project_id="proj_001",
        title="Ready query",
        objective="Check ready tasks",
    )
    repositories.sessions.save(session)
    repositories.tasks.save(
        Task.create(
            task_id="task_a",
            session_id=session.session_id,
            subject="A",
            description="done blocker",
            status=TaskStatus.COMPLETED,
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_b",
            session_id=session.session_id,
            subject="B",
            description="ready work",
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_c",
            session_id=session.session_id,
            subject="C",
            description="blocked work",
            blocked_by=("task_a",),
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_d",
            session_id=session.session_id,
            subject="D",
            description="still blocked",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_e",
            session_id=session.session_id,
            subject="E",
            description="blocks another task",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.NORMAL,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-16T10:00:05+00:00",
            updated_at="2026-04-16T10:00:05+00:00",
        )
    )
    repositories.tasks.save(
        Task.create(
            task_id="task_f",
            session_id=session.session_id,
            subject="F",
            description="blocked on active task",
            blocked_by=("task_e",),
        )
    )

    ready_ids = [task.task_id for task in repositories.tasks.list_ready_by_session(session.session_id)]
    assert ready_ids == ["task_b", "task_c", "task_d"]


def test_task_repository_rejects_cross_session_lane_binding() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    repositories.sessions.save(Session.create("sess_a", "proj_001", "A", "A"))
    repositories.sessions.save(Session.create("sess_b", "proj_001", "B", "B"))
    repositories.lanes.save(
        Lane(
            lane_id="lane_a",
            session_id="sess_a",
            name="lane a",
            status=LaneStatus.IDLE,
            cwd="/tmp/lane_a",
            branch_name=None,
            claimed_ref=None,
            created_at="2026-04-16T10:00:00+00:00",
            updated_at="2026-04-16T10:00:00+00:00",
        )
    )

    try:
        repositories.tasks.save(Task.create("task_b", "sess_b", "B", "B", lane_id="lane_a"))
    except OwnershipError as exc:
        assert "belongs to session 'sess_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_repository_ownership_checks_reject_cross_session_links() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    repositories.sessions.save(Session.create("sess_a", "proj_001", "A", "A"))
    repositories.sessions.save(Session.create("sess_b", "proj_001", "B", "B"))
    repositories.tasks.save(
        Task.create("task_a", "sess_a", "A", "A")
    )

    try:
        repositories.tasks.save(
            Task.create(
                "task_b",
                "sess_b",
                "B",
                "B",
                blocked_by=("task_a",),
            )
        )
    except OwnershipError as exc:
        assert "belongs to session 'sess_a'" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")


def test_memory_scope_checks_require_existing_scope_records() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)

    session = Session.create("sess_001", "proj_001", "Memory", "Memory")
    repositories.sessions.save(session)

    try:
        repositories.memory.save(
            MemoryEntry(
                memory_id="mem_missing",
                session_id=session.session_id,
                scope_kind=MemoryScopeKind.LANE,
                scope_ref="lane_missing",
                kind=MemoryKind.COMPACTION,
                summary="Missing lane",
                source_range=None,
                importance=3,
                created_at="2026-04-16T10:00:00+00:00",
            )
        )
    except OwnershipError as exc:
        assert "lanes.lane_id='lane_missing' does not exist" in str(exc)
    else:
        raise AssertionError("expected OwnershipError")
