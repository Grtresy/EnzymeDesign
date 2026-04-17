from __future__ import annotations

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind
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
from openzyme_core import DelegationRequest
from openzyme_core import HarnessInput
from openzyme_core import HarnessStep
from openzyme_core import HarnessStatus
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import ResumeDecision
from openzyme_core import ResumeEnvelope
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import SkillRegistry
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import run_agent_harness_loop


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Harness",
        objective="Exercise the Session 03 kernel",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T09:00:00+00:00",
        updated_at="2026-04-17T09:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Primary task",
            description="Run the first harness step.",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="general",
            assigned_ref="agent:primary",
            created_at="2026-04-17T09:01:00+00:00",
            updated_at="2026-04-17T09:01:00+00:00",
        )
    )
    repositories.memory.save(
        MemoryEntry(
            memory_id="mem_session",
            session_id=session.session_id,
            scope_kind=MemoryScopeKind.SESSION,
            scope_ref=session.session_id,
            kind=MemoryKind.CONTINUITY,
            summary="Existing continuity memory.",
            source_range="seed",
            importance=5,
            created_at="2026-04-17T09:02:00+00:00",
        )
    )
    return session


def _seed_lane(repositories: CoreRepositories, session: Session) -> Lane:
    lane = Lane(
        lane_id="lane_001",
        session_id=session.session_id,
        name="analysis",
        status=LaneStatus.CLAIMED,
        cwd="/tmp/analysis",
        branch_name="wt/analysis",
        claimed_ref="agent:primary",
        created_at="2026-04-17T09:00:30+00:00",
        updated_at="2026-04-17T09:00:30+00:00",
    )
    repositories.lanes.save(lane)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=task.status,
            priority=task.priority,
            kind=task.kind,
            assigned_ref=task.assigned_ref,
            created_at=task.created_at,
            updated_at="2026-04-17T09:00:31+00:00",
            lane_id=lane.lane_id,
            blocked_by=task.blocked_by,
        )
    )
    return lane


def test_runtime_snapshot_loads_canonical_session_state() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    snapshot = SessionRuntimeSnapshot.load(repositories, session.session_id)

    assert snapshot.session.session_id == session.session_id
    assert [task.task_id for task in snapshot.tasks] == ["task_001"]
    assert [task.task_id for task in snapshot.ready_tasks] == ["task_001"]
    assert [memory.memory_id for memory in snapshot.memory] == ["mem_session"]
    assert snapshot.pending_approvals == ()
    assert snapshot.active_invocations == ()


def test_runtime_context_can_build_restore_context_with_skills() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    lane = _seed_lane(repositories, session)
    repositories.memory.save(
        MemoryEntry(
            memory_id="mem_lane",
            session_id=session.session_id,
            scope_kind=MemoryScopeKind.LANE,
            scope_ref=lane.lane_id,
            kind=MemoryKind.CONTINUITY,
            summary="Lane continuity summary.",
            source_range="seed",
            importance=5,
            created_at="2026-04-17T09:02:30+00:00",
        )
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(task_id="task_001", lane_id=lane.lane_id, skill_keys=("vina",)),
        active_skill_keys=("vina",),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    restore = context.restore_context

    assert restore.focused_lane_id == lane.lane_id
    assert restore.session_memory.continuity.memory_id == "mem_session"
    assert restore.lane_memory is not None
    assert restore.lane_memory.continuity.memory_id == "mem_lane"
    assert [skill.skill_key for skill in restore.skill_documents] == ["vina"]


class ToolLoopDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del harness_input
        snapshot = context.snapshot
        task = snapshot.tasks[0]
        if not tool_results:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_001",
                        tool_name="echo",
                        arguments={"text": "ready"},
                        task_id=task.task_id,
                    ),
                ),
                task_updates=(
                    Task(
                        task_id=task.task_id,
                        session_id=task.session_id,
                        subject=task.subject,
                        description=task.description,
                        status=TaskStatus.IN_PROGRESS,
                        priority=task.priority,
                        kind=task.kind,
                        assigned_ref=task.assigned_ref,
                        created_at=task.created_at,
                        updated_at="2026-04-17T09:03:00+00:00",
                    ),
                ),
            )

        result = tool_results[0]
        return HarnessStep(
            assistant_message=f"tool:{result.content}",
            task_updates=(
                Task(
                    task_id=task.task_id,
                    session_id=task.session_id,
                    subject=task.subject,
                    description=task.description,
                    status=TaskStatus.COMPLETED,
                    priority=task.priority,
                    kind=task.kind,
                    assigned_ref=task.assigned_ref,
                    created_at=task.created_at,
                    updated_at="2026-04-17T09:04:00+00:00",
                ),
            ),
            memory_entries=(
                MemoryEntry(
                    memory_id="mem_tool_result",
                    session_id=task.session_id,
                    scope_kind=MemoryScopeKind.TASK,
                    scope_ref=task.task_id,
                    kind=MemoryKind.SUMMARY,
                    summary=result.content,
                    source_range="tool:call_001",
                    importance=6,
                    created_at="2026-04-17T09:04:00+00:00",
                ),
            ),
        )


def test_harness_loop_dispatches_tool_calls_and_persists_updates() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    event_bus = MemoryEventBus()
    registry = ToolRegistry()
    registry.register("echo", lambda _context, invocation: str(invocation.arguments["text"]).upper())

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="start"),
        driver=ToolLoopDriver(),
        tool_registry=registry,
        event_sink=event_bus,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert result.outputs == ("tool:READY",)
    assert [tool_result.content for tool_result in result.tool_results] == ["READY"]
    assert repositories.tasks.get("task_001").status is TaskStatus.COMPLETED
    assert len(repositories.memory.list_by_session(session.session_id)) >= 3
    assert {event.event_type for event in result.events} >= {
        "message.received",
        "task.updated",
        "tool.invoked",
        "tool.completed",
        "memory.recorded",
        "memory.compacted",
        "message.sent",
    }


class ApprovalDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del tool_results
        snapshot = context.snapshot
        if harness_input.resume is None:
            task = snapshot.tasks[0]
            return HarnessStep(
                approval_requests=(
                    ApprovalRequest(
                        approval_id="appr_001",
                        session_id=task.session_id,
                        task_id=task.task_id,
                        lane_id=None,
                        kind="tool_use",
                        requested_action="Approve continuation",
                        status=ApprovalRequestStatus.PENDING,
                        request_ref="artifact://approvals/appr_001.json",
                        resolution_ref=None,
                        created_at="2026-04-17T09:05:00+00:00",
                    ),
                ),
            )
        return HarnessStep(assistant_message="approval resumed")


def test_harness_loop_waits_for_approval_and_resumes_cleanly() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    first = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="needs approval"),
        driver=ApprovalDriver(),
    )
    assert first.status is HarnessStatus.WAITING_APPROVAL
    assert first.pending_approval_id == "appr_001"
    assert repositories.approvals.get("appr_001").status is ApprovalRequestStatus.PENDING

    second = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            resume=ResumeEnvelope(
                approval_id="appr_001",
                decision=ResumeDecision.APPROVED,
                resolution_ref="artifact://approvals/appr_001-resolution.json",
            ),
        ),
        driver=ApprovalDriver(),
    )
    assert second.status is HarnessStatus.COMPLETED
    assert second.outputs == ("approval resumed",)
    assert repositories.approvals.get("appr_001").status is ApprovalRequestStatus.APPROVED
    assert "approval.resolved" in {event.event_type for event in second.events}


class DelegationDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input, tool_results
        return HarnessStep(
            delegation_requests=(
                DelegationRequest(
                    request_id="deleg_001",
                    session_id="sess_001",
                    recipient="agent:researcher",
                    payload_ref="artifact://delegations/deleg_001.json",
                    task_id="task_001",
                    correlation_id="corr_001",
                    recipient_kind=InboxParticipantKind.AGENT,
                ),
            ),
        )


def test_harness_loop_exposes_delegation_seam_via_inbox_and_handles() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="delegate"),
        driver=DelegationDriver(),
    )

    assert result.status is HarnessStatus.WAITING_DELEGATION
    assert result.delegations[0].request_id == "deleg_001"
    inbox_types = [message.message_type for message in repositories.inbox.list_by_session(session.session_id)]
    assert "delegation_request" in inbox_types
    assert repositories.agents.get("agent:researcher") is not None
    assert "agent.delegated" in {event.event_type for event in result.events}


class LaneAwareDriver:
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
                        call_id="call_lane",
                        tool_name="lane_echo",
                        arguments={},
                        task_id="task_001",
                    ),
                ),
                engine_invocations=(
                    EngineInvocation(
                        invocation_id="inv_lane",
                        session_id=context.snapshot.session.session_id,
                        task_id="task_001",
                        lane_id=None,
                        engine_name="deep_research",
                        status=EngineInvocationStatus.RUNNING,
                        input_ref="artifact://engine/inv_lane/input.json",
                        output_ref=None,
                        approval_id=None,
                        idempotency_key="task_001:deep_research:lane",
                        started_at="2026-04-17T09:10:00+00:00",
                    ),
                ),
            )
        return HarnessStep(assistant_message=str(tool_results[0].content))


def test_harness_infers_lane_from_bound_task_for_tools_and_engines() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    lane = _seed_lane(repositories, session)
    registry = ToolRegistry()
    registry.register("lane_echo", lambda _context, invocation: invocation.lane_id or "none")

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="run in lane"),
        driver=LaneAwareDriver(),
        tool_registry=registry,
    )

    assert result.outputs == (lane.lane_id,)
    assert result.tool_results[0].lane_id == lane.lane_id
    assert repositories.invocations.list_by_session(session.session_id)[0].lane_id == lane.lane_id


class SkillLoadingDriver:
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
                        call_id="call_skill",
                        tool_name="skill.load",
                        arguments={"skill_key": "vina"},
                        task_id="task_001",
                    ),
                ),
                next_focus=RestoreFocus(task_id="task_001", skill_keys=("vina",)),
            )
        assert context.restore_context is not None
        return HarnessStep(
            assistant_message="skills:" + ",".join(skill.skill_key for skill in context.restore_context.skill_documents)
        )


def test_harness_skill_load_updates_restore_context() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id),
        driver=SkillLoadingDriver(),
    )

    assert result.outputs == ("skills:vina",)
    assert "receptor_path" in result.tool_results[0].content


class ExplicitCompactionDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input
        if not tool_results:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_compact",
                        tool_name="memory.compact",
                        arguments={"scope_kind": "task", "task_id": "task_001"},
                        task_id="task_001",
                    ),
                )
            )
        return HarnessStep(assistant_message="compacted")


def test_harness_memory_compact_tool_writes_task_scope_summary() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, restore_focus=RestoreFocus(task_id="task_001")),
        driver=ExplicitCompactionDriver(),
    )

    task_memory = repositories.memory.list_by_scope(session.session_id, MemoryScopeKind.TASK, "task_001")
    assert any(entry.kind is MemoryKind.COMPACTION for entry in task_memory)
    assert result.outputs == ("compacted",)


def test_harness_auto_compaction_keeps_lane_restore_state() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    lane = _seed_lane(repositories, session)
    registry = ToolRegistry()
    registry.register("lane_echo", lambda _context, invocation: invocation.lane_id or "none")

    run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="run in lane"),
        driver=LaneAwareDriver(),
        tool_registry=registry,
    )
    second = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, restore_focus=RestoreFocus(task_id="task_001", lane_id=lane.lane_id)),
        driver=ApprovalDriver(),
    )

    lane_memory = repositories.memory.list_by_scope(session.session_id, MemoryScopeKind.LANE, lane.lane_id)
    assert any(entry.kind is MemoryKind.COMPACTION for entry in lane_memory)
    assert second.pending_approval_id == "appr_001"
