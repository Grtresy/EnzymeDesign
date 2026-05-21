from __future__ import annotations

import json

from openzyme_domain import ArtifactKind
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import HarnessInput
from openzyme_core import HarnessStep
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import TaskBoardBucket
from openzyme_core import TaskMutation
from openzyme_core import TaskBoardService
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_task_board_tools
from openzyme_core import run_agent_harness_loop


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Task board",
        objective="Exercise Session 04 task board behavior",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T10:00:00+00:00",
        updated_at="2026-04-17T10:00:00+00:00",
    )
    repositories.sessions.save(session)
    return session


def test_task_board_projection_separates_ready_and_blocked_tasks() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)

    service.create_task(
        session_id=session.session_id,
        task_id="task_root",
        subject="Root",
        description="Complete the first task",
        priority=TaskPriority.HIGH,
        status=TaskStatus.IN_PROGRESS,
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_ready",
        subject="Ready",
        description="Available immediately",
        priority=TaskPriority.URGENT,
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_blocked",
        subject="Blocked",
        description="Depends on root",
        blocked_by=("task_root",),
    )

    projection = service.build_projection(session.session_id)

    assert projection.next_task_id == "task_ready"
    assert [item.task.task_id for item in projection.ready_tasks] == ["task_ready"]
    assert [item.task.task_id for item in projection.blocked_tasks] == ["task_blocked"]
    blocked_item = next(item for item in projection.items if item.task.task_id == "task_blocked")
    assert blocked_item.bucket is TaskBoardBucket.BLOCKED
    assert blocked_item.blocked_by_open_task_ids == ("task_root",)


def test_task_board_update_promotes_newly_unblocked_task() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    service.create_task(
        session_id=session.session_id,
        task_id="task_a",
        subject="A",
        description="Root",
        status=TaskStatus.IN_PROGRESS,
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_b",
        subject="B",
        description="Depends on A",
        blocked_by=("task_a",),
    )

    updated = service.update_task("task_a", mutation=TaskMutation(status=TaskStatus.COMPLETED))
    del updated
    projection = service.build_projection(session.session_id)

    assert projection.next_task_id == "task_b"
    assert [item.task.task_id for item in projection.ready_tasks] == ["task_b"]
    assert projection.blocked_tasks == ()


def test_failed_or_cancelled_blocker_does_not_make_downstream_ready() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    service.create_task(
        session_id=session.session_id,
        task_id="task_a",
        subject="A",
        description="Root",
        status=TaskStatus.IN_PROGRESS,
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_b",
        subject="B",
        description="Depends on A",
        blocked_by=("task_a",),
    )

    service.update_task("task_a", mutation=TaskMutation(status=TaskStatus.FAILED))
    projection = service.build_projection(session.session_id)

    assert projection.ready_tasks == ()
    assert [item.task.task_id for item in projection.blocked_tasks] == ["task_b"]
    assert projection.blocked_tasks[0].blocked_by_open_task_ids == ("task_a",)


def test_task_board_normalizes_pseudo_empty_assigned_refs() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)

    for index, value in enumerate(("null", "None", "")):
        created = service.create_task(
            session_id=session.session_id,
            task_id=f"task_create_{index}",
            subject="Create",
            description="Pseudo-empty assigned_ref",
            assigned_ref=value,
        )
        assert created.assigned_ref is None

    task = service.create_task(
        session_id=session.session_id,
        task_id="task_update",
        subject="Update",
        description="Clear assigned_ref through task.update",
        assigned_ref="agent:executor",
    )
    assert task.assigned_ref == "agent:executor"

    for value in ("null", "None", ""):
        updated = service.update_task(
            "task_update",
            TaskMutation(assigned_ref=value),
        )
        assert updated.assigned_ref is None
        service.update_task("task_update", TaskMutation(assigned_ref="agent:executor"))


def test_task_board_normalizes_teammate_role_assigned_refs() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)

    task = service.create_task(
        session_id=session.session_id,
        task_id="task_alias",
        subject="Alias",
        description="Normalize teammate role alias.",
        assigned_ref="executor",
    )
    updated = service.update_task("task_alias", TaskMutation(assigned_ref="reporter"))

    assert task.assigned_ref == "agent:executor"
    assert updated.assigned_ref == "agent:reporter"


def test_task_board_buckets_failed_task_as_terminal_failure() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)

    failed = service.create_task(
        session_id=session.session_id,
        task_id="task_failed",
        subject="Failed",
        description="Execution attempt failed",
        status=TaskStatus.FAILED,
        failure_summary="Runner timed out",
        failure_ref="engine:inv_failed",
    )

    projection = service.build_projection(session.session_id)
    item = next(item for item in projection.items if item.task.task_id == failed.task_id)

    assert item.bucket is TaskBoardBucket.FAILED
    assert projection.ready_tasks == ()
    assert projection.blocked_tasks == ()
    assert item.task.failure_summary == "Runner timed out"
    assert item.task.failure_ref == "engine:inv_failed"


def test_task_board_can_filter_and_select_tasks_by_lane() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name=None,
            claimed_ref="agent:primary",
            created_at="2026-04-17T10:00:00+00:00",
            updated_at="2026-04-17T10:00:00+00:00",
        )
    )
    service = TaskBoardService(repositories)
    service.create_task(
        session_id=session.session_id,
        task_id="task_lane",
        subject="Lane task",
        description="Bound to lane",
        priority=TaskPriority.HIGH,
        lane_id="lane_001",
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_global",
        subject="Global task",
        description="No lane",
        priority=TaskPriority.URGENT,
    )

    projection = service.build_projection(session.session_id, lane_id="lane_001")
    next_task = service.select_next_task(session.session_id, lane_id="lane_001")

    assert [item.task.task_id for item in projection.items] == ["task_lane"]
    assert projection.lane_id == "lane_001"
    assert next_task.task_id == "task_lane"


def test_research_task_cannot_complete_before_required_structure_artifact() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.sessions.save(
        Session(
            session_id=session.session_id,
            project_id=session.project_id,
            title=session.title,
            objective="Find a real RCSB PDB structure artifact and run fpocket execution.",
            status=session.status,
            created_at=session.created_at,
            updated_at=session.updated_at,
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_research",
            session_id=session.session_id,
            subject="Collect evidence",
            description="Identify evidence and a PDB structure artifact.",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:researcher",
            created_at="2026-04-17T10:01:00+00:00",
            updated_at="2026-04-17T10:01:00+00:00",
        )
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_research"),
    )

    missing = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_missing_structure",
            tool_name="task.update",
            arguments={"task_id": "task_research", "status": "completed"},
            task_id="task_research",
        ),
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_structure",
            session_id=session.session_id,
            task_id="task_research",
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/structure.pdb",
            relative_path="structure.pdb",
            created_at="2026-04-17T10:02:00+00:00",
            title="structure.pdb",
        )
    )
    completed = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_has_structure",
            tool_name="task.update",
            arguments={"task_id": "task_research", "status": "completed"},
            task_id="task_research",
        ),
    )

    assert missing.ok is False
    assert missing.error_code == "required_structure_artifact_missing"
    assert "rcsb_pdb.download_structure" in missing.hint
    assert completed.ok is True


class TaskToolDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del harness_input
        if not tool_results:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_create",
                        tool_name="task.create",
                        arguments={
                            "task_id": "task_secondary",
                            "subject": "Secondary task",
                            "description": "Follow-up work",
                            "priority": "urgent",
                            "blocked_by": ["task_primary"],
                        },
                    ),
                    ToolInvocation(
                        call_id="call_next",
                        tool_name="task.next",
                        arguments={},
                    ),
                )
            )

        service = TaskBoardService(context.repositories)
        selected = service.select_next_task(context.snapshot.session.session_id)
        return HarnessStep(assistant_message=f"next:{selected.task_id if selected else 'none'}")


def test_harness_task_tools_and_task_board_selection_work_together() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.tasks.save(
        Task(
            task_id="task_primary",
            session_id=session.session_id,
            subject="Primary task",
            description="Already ready",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="general",
            assigned_ref="agent:primary",
            created_at="2026-04-17T10:01:00+00:00",
            updated_at="2026-04-17T10:01:00+00:00",
        )
    )
    event_bus = MemoryEventBus()
    registry = ToolRegistry()
    register_task_board_tools(registry)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="plan next task"),
        driver=TaskToolDriver(),
        tool_registry=registry,
        event_sink=event_bus,
    )

    created = repositories.tasks.get("task_secondary")
    assert created is not None
    assert created.blocked_by == ("task_primary",)
    assert result.outputs == ("next:task_primary",)
    payloads = [json.loads(tool_result.content) for tool_result in result.tool_results]
    assert payloads[1]["task_id"] == "task_primary"
    assert {event.event_type for event in result.events} >= {
        "task.created",
        "task.blocked",
        "message.sent",
        "tool.completed",
    }
