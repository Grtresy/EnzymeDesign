from __future__ import annotations

from openzyme_domain import LaneStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import LaneManager
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
        title="Lane manager",
        objective="Exercise Session 07 lane behavior",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T10:00:00+00:00",
        updated_at="2026-04-17T10:00:00+00:00",
    )
    repositories.sessions.save(session)
    return session


def test_lane_manager_binds_tasks_and_builds_projection() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.tasks.save(
        Task(
            task_id="task_ready",
            session_id=session.session_id,
            subject="Ready task",
            description="Should be visible under lane",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-17T10:01:00+00:00",
            updated_at="2026-04-17T10:01:00+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_unassigned",
            session_id=session.session_id,
            subject="Unassigned task",
            description="Should remain unassigned",
            status=TaskStatus.TODO,
            priority=TaskPriority.NORMAL,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-17T10:02:00+00:00",
            updated_at="2026-04-17T10:02:00+00:00",
        )
    )
    manager = LaneManager(repositories)

    lane = manager.create_lane(
        session_id=session.session_id,
        lane_id="lane_001",
        name="analysis",
        cwd="/tmp/analysis",
        branch_name="wt/analysis",
    )
    claimed = manager.claim_lane(lane.lane_id, claimed_ref="agent:planner")
    bound = manager.bind_task_to_lane("task_ready", lane.lane_id)
    projection = manager.build_projection(session.session_id)

    assert claimed.status is LaneStatus.CLAIMED
    assert bound.lane_id == lane.lane_id
    assert projection.lanes[0].lane.lane_id == lane.lane_id
    assert [task.task_id for task in projection.lanes[0].tasks] == ["task_ready"]
    assert projection.lanes[0].ready_task_ids == ("task_ready",)
    assert [task.task_id for task in projection.unassigned_tasks] == ["task_unassigned"]
    event_types = [event.event_type for event in repositories.lane_events.list_by_lane(session.session_id, lane.lane_id)]
    assert event_types == ["lane.created", "lane.claimed", "task.bound_to_lane"]


def test_lane_remove_unbinds_non_terminal_tasks_and_keeps_terminal_history() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    manager = LaneManager(repositories)
    lane = manager.create_lane(
        session_id=session.session_id,
        lane_id="lane_001",
        name="execution",
        cwd="/tmp/execution",
    )
    repositories.tasks.save(
        Task(
            task_id="task_live",
            session_id=session.session_id,
            subject="Live task",
            description="Should be unbound",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-17T10:03:00+00:00",
            updated_at="2026-04-17T10:03:00+00:00",
            lane_id=lane.lane_id,
        )
    )
    repositories.tasks.seed_fixture(
        Task(
            task_id="task_blocked",
            session_id=session.session_id,
            subject="Blocked task",
            description="Should be unbound without changing blocked status",
            status=TaskStatus.BLOCKED,
            priority=TaskPriority.NORMAL,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-17T10:03:30+00:00",
            updated_at="2026-04-17T10:03:30+00:00",
            lane_id=lane.lane_id,
        )
    )
    repositories.tasks.seed_fixture(
        Task(
            task_id="task_done",
            session_id=session.session_id,
            subject="Done task",
            description="Should keep lane for history",
            status=TaskStatus.COMPLETED,
            priority=TaskPriority.NORMAL,
            kind="general",
            assigned_ref=None,
            created_at="2026-04-17T10:04:00+00:00",
            updated_at="2026-04-17T10:04:00+00:00",
            lane_id=lane.lane_id,
        )
    )

    removed = manager.remove_lane(lane.lane_id)

    assert removed.status is LaneStatus.REMOVED
    assert repositories.tasks.get("task_live").lane_id is None
    blocked = repositories.tasks.get("task_blocked")
    assert blocked is not None
    assert blocked.status is TaskStatus.BLOCKED
    assert blocked.lane_id is None
    assert repositories.tasks.get("task_done").lane_id == lane.lane_id
    event_types = [event.event_type for event in repositories.lane_events.list_by_lane(session.session_id, lane.lane_id)]
    assert "task.unbound_from_lane" in event_types
    assert event_types[-1] == "lane.removed"
