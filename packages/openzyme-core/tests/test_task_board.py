from __future__ import annotations

import json
import sqlite3

import pytest

from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import Session
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
from openzyme_core import TaskDependencyCycleError
from openzyme_core import TaskExitStatusRequiresFinish
from openzyme_core import TaskFinishCommand
from openzyme_core import TaskMutation
from openzyme_core import TaskBoardService
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import register_task_board_tools
from openzyme_core import run_agent_harness_loop
from openzyme_core.agent_identity import create_agent_member


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


def _seed_agent(
    repositories: CoreRepositories,
    session: Session,
    *,
    role: str = "executor",
    agent_id: str | None = None,
    name: str | None = None,
) -> AgentMember:
    if agent_id is None and role in {"researcher", "executor", "reporter"}:
        return create_agent_member(
            repositories,
            session_id=session.session_id,
            role=role,  # type: ignore[arg-type]
        )
    resolved_agent_id = agent_id or f"agent:{role}:test"
    resolved_name = name or role.title()
    agent = AgentMember(
        agent_id=resolved_agent_id,
        session_id=session.session_id,
        lane_id=None,
        task_id=None,
        name=resolved_name,
        role=role,
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-04-17T10:00:00+00:00",
        updated_at="2026-04-17T10:00:00+00:00",
        nickname=resolved_name,
        display_name=resolved_name,
        handle=f"@{resolved_name.lower()}",
    )
    repositories.agents.save(agent)
    return agent


@pytest.mark.parametrize(
    "status",
    (
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    ),
)
def test_task_board_create_rejects_business_exit_statuses(status: TaskStatus) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    with pytest.raises(
        TaskExitStatusRequiresFinish,
        match="task.create cannot set business exit status",
    ):
        TaskBoardService(repositories).create_task(
            session_id=session.session_id,
            task_id=f"task_{status.value}",
            subject=status.value,
            description=status.value,
            status=status,
        )


@pytest.mark.parametrize(
    "status",
    (
        TaskStatus.BLOCKED,
        TaskStatus.COMPLETED,
        TaskStatus.FAILED,
        TaskStatus.CANCELLED,
    ),
)
def test_task_board_edit_rejects_business_exit_statuses(status: TaskStatus) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    task = service.create_task(
        session_id=session.session_id,
        task_id="task_edit",
        subject="Edit",
        description="Edit",
    )

    with pytest.raises(
        TaskExitStatusRequiresFinish,
        match="task.edit cannot set business exit status",
    ):
        service.edit_task(task.task_id, TaskMutation(status=status))


def test_task_board_finish_command_is_the_explicit_business_exit() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    task = service.create_task(
        session_id=session.session_id,
        task_id="task_finish_command",
        subject="Finish",
        description="Finish explicitly",
        status=TaskStatus.IN_PROGRESS,
    )

    outcome = service.finish_task(
        task.task_id,
        TaskFinishCommand(
            status=TaskStatus.COMPLETED,
            summary="Finished explicitly.",
            finished_by="agent:master",
        ),
    )

    assert outcome.task.status is TaskStatus.COMPLETED
    document = repositories.engine_documents.get(outcome.finish_ref)
    assert document is not None
    assert document.document_kind == "task_finish"
    assert document.payload["summary"] == "Finished explicitly."
    assert document.payload["finished_by"] == "agent:master"


def test_task_board_finish_rejects_a_second_exit_until_explicit_resume() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    task = service.create_task(
        session_id=session.session_id,
        task_id="task_blocked_exit",
        subject="Blocked",
        description="Blocked explicitly",
        status=TaskStatus.IN_PROGRESS,
    )
    first = service.finish_task(
        task.task_id,
        TaskFinishCommand(
            status=TaskStatus.BLOCKED,
            blocked_reason="Needs user input.",
            finished_by="agent:master",
        ),
    )

    with pytest.raises(ValueError, match="already reached business exit blocked"):
        service.finish_task(
            task.task_id,
            TaskFinishCommand(
                status=TaskStatus.COMPLETED,
                summary="Must resume first.",
                finished_by="agent:master",
            ),
        )

    saved = repositories.tasks.get(task.task_id)
    assert saved is not None
    assert saved.status is TaskStatus.BLOCKED
    assert len(
        [
            document
            for document in repositories.engine_documents.list_by_session(
                session.session_id
            )
            if document.document_kind == "task_finish"
        ]
    ) == 1
    assert first.task.status is TaskStatus.BLOCKED


def test_task_board_finish_rollback_does_not_emit_events() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    events: list[tuple[str, dict[str, object]]] = []
    service = TaskBoardService(
        repositories,
        event_emitter=lambda event_type, payload: events.append(
            (event_type, payload)
        ),
    )
    task = service.create_task(
        session_id=session.session_id,
        task_id="task_finish_rollback",
        subject="Rollback",
        description="Rollback",
        status=TaskStatus.IN_PROGRESS,
    )
    events.clear()
    repositories.tasks.connection.execute(
        """
        CREATE TRIGGER reject_test_task_finish
        BEFORE UPDATE OF status ON tasks
        WHEN NEW.status = 'completed'
        BEGIN
            SELECT RAISE(ABORT, 'reject_test_task_finish');
        END
        """
    )

    with pytest.raises(sqlite3.IntegrityError, match="reject_test_task_finish"):
        service.finish_task(
            task.task_id,
            TaskFinishCommand(
                status=TaskStatus.COMPLETED,
                summary="Must roll back.",
                finished_by="agent:master",
            ),
        )

    saved = repositories.tasks.get(task.task_id)
    assert saved is not None
    assert saved.status is TaskStatus.IN_PROGRESS
    assert not any(
        document.document_kind == "task_finish"
        for document in repositories.engine_documents.list_by_session(
            session.session_id
        )
    )
    assert events == []


def test_task_board_rejects_two_node_dependency_cycle() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    service.create_task(
        session_id=session.session_id,
        task_id="task_a",
        subject="A",
        description="A",
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_b",
        subject="B",
        description="B",
        blocked_by=("task_a",),
    )

    with pytest.raises(TaskDependencyCycleError, match="task_a -> task_b -> task_a"):
        service.edit_task("task_a", TaskMutation(blocked_by=("task_b",)))


def test_task_board_rejects_three_node_dependency_cycle() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    service.create_task(
        session_id=session.session_id,
        task_id="task_a",
        subject="A",
        description="A",
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_b",
        subject="B",
        description="B",
        blocked_by=("task_a",),
    )
    service.create_task(
        session_id=session.session_id,
        task_id="task_c",
        subject="C",
        description="C",
        blocked_by=("task_b",),
    )

    with pytest.raises(
        TaskDependencyCycleError,
        match="task_a -> task_c -> task_b -> task_a",
    ):
        service.edit_task("task_a", TaskMutation(blocked_by=("task_c",)))


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

    service.finish_task(
        "task_a",
        TaskFinishCommand(
            status=TaskStatus.COMPLETED,
            summary="Root task completed.",
            finished_by="agent:master",
        ),
    )
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

    service.finish_task(
        "task_a",
        TaskFinishCommand(
            status=TaskStatus.FAILED,
            finished_by="agent:master",
            failure_summary="Root task failed.",
        ),
    )
    projection = service.build_projection(session.session_id)

    assert projection.ready_tasks == ()
    assert [item.task.task_id for item in projection.blocked_tasks] == ["task_b"]
    assert projection.blocked_tasks[0].blocked_by_open_task_ids == ("task_a",)


def test_task_board_normalizes_pseudo_empty_assigned_refs() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    agent = _seed_agent(repositories, session)

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
        assigned_ref=agent.agent_id,
    )
    assert task.assigned_ref == agent.agent_id

    for value in ("null", "None", ""):
        updated = service.update_task(
            "task_update",
            TaskMutation(assigned_ref=value),
        )
        assert updated.assigned_ref is None
        service.update_task("task_update", TaskMutation(assigned_ref=agent.agent_id))


def test_task_board_rejects_teammate_role_assigned_refs() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)

    with pytest.raises(ValueError, match="role alias"):
        service.create_task(
            session_id=session.session_id,
            task_id="task_alias",
            subject="Alias",
            description="Reject teammate role alias.",
            assigned_ref="executor",
        )
    task = service.create_task(
        session_id=session.session_id,
        task_id="task_canonical",
        subject="Canonical",
        description="Canonical assignment.",
    )
    with pytest.raises(ValueError, match="role alias"):
        service.update_task(task.task_id, TaskMutation(assigned_ref="agent:reporter"))


def test_task_board_buckets_failed_task_as_terminal_failure() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)

    task = service.create_task(
        session_id=session.session_id,
        task_id="task_failed",
        subject="Failed",
        description="Execution attempt failed",
        status=TaskStatus.IN_PROGRESS,
    )
    failed = service.finish_task(
        task.task_id,
        TaskFinishCommand(
            status=TaskStatus.FAILED,
            finished_by="agent:master",
            failure_summary="Runner timed out",
            failure_ref="engine:inv_failed",
        ),
    ).task

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


def test_research_task_finish_does_not_hardcode_structure_artifact_gate() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(repositories, session, role="researcher")
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
            assigned_ref=agent.agent_id,
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
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="researcher",
    )

    completed = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_complete_without_structure",
            tool_name="task.finish",
            arguments={
                "task_id": "task_research",
                "status": "completed",
                "summary": "Research complete.",
            },
            task_id="task_research",
        ),
    )

    assert completed.ok is True
    assert "rcsb_pdb.download_structure" not in (completed.hint or "")


def test_task_finish_requires_failed_and_blocked_details() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    agent = _seed_agent(repositories, session, role="executor")
    service.create_task(
        session_id=session.session_id,
        task_id="task_finish",
        subject="Finish",
        description="Validate task.finish arguments.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=agent.agent_id,
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_finish"),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )

    failed = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_failed",
            tool_name="task.finish",
            arguments={
                "task_id": "task_finish",
                "status": "failed",
                "summary": "Could not complete.",
            },
            task_id="task_finish",
        ),
    )
    blocked = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_blocked",
            tool_name="task.finish",
            arguments={
                "task_id": "task_finish",
                "status": "blocked",
                "summary": "Need user input.",
            },
            task_id="task_finish",
        ),
    )

    task = repositories.tasks.get("task_finish")
    assert failed.ok is False
    assert failed.error_code == "task_finish_failure_required"
    assert blocked.ok is False
    assert blocked.error_code == "task_finish_blocked_reason_required"
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS


def test_task_finish_rejects_bare_evidence_id_with_canonical_contract() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    agent = _seed_agent(repositories, session, role="executor")
    service.create_task(
        session_id=session.session_id,
        task_id="task_finish_evidence",
        subject="Finish with evidence",
        description="Validate the public evidence reference contract.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=agent.agent_id,
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_finish_evidence"),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_finish_with_bare_evidence",
            tool_name="task.finish",
            arguments={
                "task_id": "task_finish_evidence",
                "status": "completed",
                "summary": "Evidence is available.",
                "evidence_refs": ["artifact_123"],
            },
            task_id="task_finish_evidence",
        ),
    )

    assert result.ok is False
    assert result.error_code == "invalid_task_finish_evidence_refs"
    assert result.details == {
        "task_id": "task_finish_evidence",
        "evidence_refs": ["artifact_123"],
        "expected_format": "<kind>:<id>",
        "supported_kinds": [
            "artifact",
            "document",
            "invocation",
            "message",
            "protocol",
            "report",
            "run",
            "sandbox_run",
            "scientific_closure",
        ],
        "examples": [
            "artifact:<artifact_id>",
            "report:<report_id>",
            "scientific_closure:<closure_id>",
        ],
    }
    assert result.hint is None
    task = repositories.tasks.get("task_finish_evidence")
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS


@pytest.mark.parametrize("status_value", ("completed", "failed", "blocked", "cancelled"))
def test_task_update_rejects_business_exit_statuses(status_value: str) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    agent = _seed_agent(repositories, session, role="executor")
    service.create_task(
        session_id=session.session_id,
        task_id="task_update_terminal",
        subject="Update",
        description="Validate task.update status guard.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=agent.agent_id,
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_update_terminal"),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id=f"call_update_{status_value}",
            tool_name="task.update",
            arguments={"task_id": "task_update_terminal", "status": status_value},
            task_id="task_update_terminal",
        ),
    )
    task = repositories.tasks.get("task_update_terminal")

    assert result.ok is False
    assert result.error_code == "task_terminal_status_requires_finish"
    assert task is not None
    assert task.status is TaskStatus.IN_PROGRESS


@pytest.mark.parametrize(
    ("status_value", "extra_arguments", "expected_status"),
    (
        ("completed", {"summary": "Completed explicitly."}, TaskStatus.COMPLETED),
        (
            "failed",
            {
                "summary": "Failed explicitly.",
                "failure_summary": "External dependency failed.",
            },
            TaskStatus.FAILED,
        ),
        (
            "blocked",
            {
                "summary": "Blocked explicitly.",
                "blocked_reason": "Need user input.",
            },
            TaskStatus.BLOCKED,
        ),
        ("cancelled", {"summary": "Cancelled explicitly."}, TaskStatus.CANCELLED),
    ),
)
def test_task_finish_writes_explicit_business_exit_statuses(
    status_value: str,
    extra_arguments: dict[str, str],
    expected_status: TaskStatus,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    agent = _seed_agent(repositories, session, role="executor")
    task_id = f"task_finish_{status_value}"
    service.create_task(
        session_id=session.session_id,
        task_id=task_id,
        subject="Finish",
        description="Validate task.finish terminal statuses.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=agent.agent_id,
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id=task_id),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id=f"call_finish_{status_value}",
            tool_name="task.finish",
            arguments={
                "task_id": task_id,
                "status": status_value,
                **extra_arguments,
            },
            task_id=task_id,
        ),
    )
    task = repositories.tasks.get(task_id)

    assert result.ok is True
    assert result.terminal_action == "task.finish"
    assert result.terminates_turn is True
    assert task is not None
    assert task.status is expected_status
    if expected_status is TaskStatus.FAILED:
        assert task.failure_summary == "External dependency failed."


def test_task_finish_rejects_role_alias_and_wrong_agent_id() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    owner = _seed_agent(repositories, session, role="executor")
    other = _seed_agent(repositories, session, role="reporter")
    service.create_task(
        session_id=session.session_id,
        task_id="task_finish_owner",
        subject="Finish owner",
        description="Validate canonical finish authorization.",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=owner.agent_id,
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)

    role_alias_context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_finish_owner"),
        agent_id="agent:executor",
        actor_kind="teammate",
        actor_role="executor",
    )
    wrong_agent_context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_finish_owner"),
        agent_id=other.agent_id,
        actor_kind="teammate",
        actor_role="reporter",
    )

    for index, context in enumerate((role_alias_context, wrong_agent_context)):
        result = registry.dispatch(
            context,
            ToolInvocation(
                call_id=f"call_finish_forbidden_{index}",
                tool_name="task.finish",
                arguments={
                    "task_id": "task_finish_owner",
                    "status": "completed",
                    "summary": "Should be rejected.",
                },
                task_id="task_finish_owner",
            ),
        )
        assert result.ok is False
        assert result.error_code == "task_finish_forbidden"

    task = repositories.tasks.get("task_finish_owner")
    assert task.status is TaskStatus.IN_PROGRESS
    assert task.assigned_ref == owner.agent_id


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
