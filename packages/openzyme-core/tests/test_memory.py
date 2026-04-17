from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import MemoryService
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
        title="Memory restore",
        objective="Exercise Session 05 behavior",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T11:00:00+00:00",
        updated_at="2026-04-17T11:00:00+00:00",
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
            created_at="2026-04-17T11:00:01+00:00",
            updated_at="2026-04-17T11:00:01+00:00",
        )
    )
    repositories.lanes.save(
        Lane(
            lane_id="lane_002",
            session_id=session.session_id,
            name="execution",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/execution",
            branch_name=None,
            claimed_ref="agent:executor",
            created_at="2026-04-17T11:00:02+00:00",
            updated_at="2026-04-17T11:00:02+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Analyze scaffold",
            description="Lane-bound ready task",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:planner",
            created_at="2026-04-17T11:00:03+00:00",
            updated_at="2026-04-17T11:00:03+00:00",
            lane_id="lane_001",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_002",
            session_id=session.session_id,
            subject="Blocked task",
            description="Waits on analysis",
            status=TaskStatus.TODO,
            priority=TaskPriority.NORMAL,
            kind="execution",
            assigned_ref="agent:executor",
            created_at="2026-04-17T11:00:04+00:00",
            updated_at="2026-04-17T11:00:04+00:00",
            lane_id="lane_002",
            blocked_by=("task_001",),
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            kind="tool_use",
            requested_action="Approve research step",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_001.json",
            resolution_ref=None,
            created_at="2026-04-17T11:00:05+00:00",
        )
    )
    repositories.inbox.save(
        InboxMessage(
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
            created_at="2026-04-17T11:00:06+00:00",
        )
    )
    return session


def test_memory_service_records_continuity_and_compaction_events() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    events: list[tuple[str, dict[str, object]]] = []
    service = MemoryService(repositories, event_emitter=lambda event_type, payload: events.append((event_type, payload)))

    continuity = service.record_continuity(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.SESSION,
        scope_ref=session.session_id,
        summary="Session continuity summary",
        memory_id="mem_cont",
    )
    compaction = service.compact_scope(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.SESSION,
        scope_ref=session.session_id,
        summary="Compressed context snapshot",
        memory_id="mem_compact",
    )

    assert continuity.kind is MemoryKind.CONTINUITY
    assert compaction.kind is MemoryKind.COMPACTION
    assert {
        entry.memory_id
        for entry in repositories.memory.list_by_scope(session.session_id, MemoryScopeKind.SESSION, session.session_id)
    } == {"mem_cont", "mem_compact"}
    assert [event_type for event_type, _payload in events] == [
        "memory.recorded",
        "memory.recorded",
        "memory.compacted",
    ]


def test_restore_context_preserves_canonical_state_and_scope_isolation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = MemoryService(repositories)

    service.record_continuity(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.SESSION,
        scope_ref=session.session_id,
        summary="Global continuity",
        memory_id="mem_session",
    )
    service.compact_scope(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.LANE,
        scope_ref="lane_001",
        summary="Lane 001 compacted state",
        memory_id="mem_lane_1",
    )
    service.compact_scope(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.LANE,
        scope_ref="lane_002",
        summary="Lane 002 compacted state",
        memory_id="mem_lane_2",
    )
    service.record_memory(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.TASK,
        scope_ref="task_001",
        kind=MemoryKind.SUMMARY,
        summary="Task summary for lane 001",
        memory_id="mem_task",
    )

    context = service.build_restore_context(
        session.session_id,
        lane_id="lane_001",
        task_id="task_001",
    )

    assert context.session.session_id == session.session_id
    assert [task.task_id for task in context.ready_tasks] == ["task_001"]
    assert context.pending_approvals[0].approval_id == "appr_001"
    assert context.session_memory.continuity.memory_id == "mem_session"
    assert context.lane_memory is not None
    assert context.lane_memory.compaction.memory_id == "mem_lane_1"
    assert context.lane_memory.compaction.summary == "Lane 001 compacted state"
    assert context.task_memory is not None
    assert [entry.memory_id for entry in context.task_memory.entries] == ["mem_task"]


def test_restore_context_infers_lane_from_task_binding() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = MemoryService(repositories)
    service.compact_scope(
        session_id=session.session_id,
        scope_kind=MemoryScopeKind.LANE,
        scope_ref="lane_001",
        summary="Lane 001 compacted state",
        memory_id="mem_lane_1",
    )

    context = service.build_restore_context(session.session_id, task_id="task_001")

    assert context.focused_lane_id == "lane_001"
    assert context.lane_memory is not None
    assert context.lane_memory.compaction.memory_id == "mem_lane_1"
