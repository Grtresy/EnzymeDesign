from __future__ import annotations

import json

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
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
from openzyme_core import DeepResearchTaskPlanner
from openzyme_core import DelegationRequest
from openzyme_core import HarnessInput
from openzyme_core import LlmConversationDriver
from openzyme_core import HarnessStep
from openzyme_core import HarnessStatus
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import ResumeDecision
from openzyme_core import ResumeEnvelope
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SkillRegistry
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import ToolResult
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import run_agent_harness_loop
from openzyme_core import EngineDescriptor
from openzyme_core import EngineRegistry
from openzyme_core import builtin_tool_descriptors
from openzyme_core import top_level_tool_descriptors
from openzyme_core import build_teammate_registry
from openzyme_core import ProtocolService
from openzyme_core import teammate_tool_descriptors
from openzyme_research import DeterministicBioResearchService
from openzyme_research import TavilyResearchAdapter


class RateLimitedBioResearchService(DeterministicBioResearchService):
    def search_semantic_scholar(self, *, query: str, limit: int = 5):
        del query, limit
        raise RuntimeError("HTTP Error 429: Too Many Requests")


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
        restore_focus=RestoreFocus(
            task_id="task_001", lane_id=lane.lane_id, skill_keys=("vina",)
        ),
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
    registry.register(
        "echo", lambda _context, invocation: str(invocation.arguments["text"]).upper()
    )

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


class RegistryBackedEngine:
    descriptor = EngineDescriptor(
        engine_name="registry_engine",
        tool_names=("registry.echo",),
        input_schema={"type": "object", "required": ["text"]},
        output_schema={"type": "object", "required": ["value"]},
        requires_approval=False,
        supports_background=False,
        idempotency_key_shape="{task_id}:registry:{nonce}",
        produces_artifact_types=(),
        capability_key="registry",
    )

    def register_tools(self, registry: ToolRegistry) -> None:
        registry.register(
            "registry.echo",
            lambda _context, invocation: f"engine:{invocation.arguments['text']}",
        )


class RegistryToolDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del harness_input
        task = context.snapshot.tasks[0]
        if not tool_results:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_registry",
                        tool_name="registry.echo",
                        arguments={"text": "ready"},
                        task_id=task.task_id,
                    ),
                ),
            )
        return HarnessStep(assistant_message=str(tool_results[0].content))


def test_harness_loop_registers_engine_tools_from_engine_registry() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine_registry = EngineRegistry()
    engine_registry.register(RegistryBackedEngine())

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="start"),
        driver=RegistryToolDriver(),
        engine_registry=engine_registry,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert result.outputs == ("engine:ready",)
    assert [tool_result.tool_name for tool_result in result.tool_results] == [
        "registry.echo"
    ]


class ToolCreatedApprovalDriver:
    def __init__(self) -> None:
        self.calls = 0

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        self.calls += 1
        del context, harness_input
        if not tool_results:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_approval",
                        tool_name="approval_tool",
                        arguments={},
                        task_id="task_001",
                    ),
                    ToolInvocation(
                        call_id="call_after_approval",
                        tool_name="after_approval_tool",
                        arguments={},
                        task_id="task_001",
                    ),
                )
            )
        return HarnessStep(assistant_message="approval requested")


def test_harness_returns_waiting_approval_when_tool_creates_pending_approval() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    calls: list[str] = []
    driver = ToolCreatedApprovalDriver()

    def approval_tool(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> str:
        calls.append(invocation.tool_name)
        context.repositories.approvals.save(
            ApprovalRequest(
                approval_id="appr_tool_001",
                session_id=session.session_id,
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
                kind="tool_gate",
                requested_action="Approve the tool action.",
                status=ApprovalRequestStatus.PENDING,
                request_ref=None,
                resolution_ref=None,
                created_at="2026-04-17T09:05:00+00:00",
            )
        )
        return "pending approval"

    registry.register("approval_tool", approval_tool)
    registry.register(
        "after_approval_tool",
        lambda _context, invocation: calls.append(invocation.tool_name) or "late",
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id),
        driver=driver,
        tool_registry=registry,
    )

    assert result.status is HarnessStatus.WAITING_APPROVAL
    assert result.pending_approval_id == "appr_tool_001"
    assert result.snapshot.pending_approvals[0].approval_id == "appr_tool_001"
    assert result.outputs == ()
    assert [tool_result.call_id for tool_result in result.tool_results] == [
        "call_approval"
    ]
    assert calls == ["approval_tool"]
    assert driver.calls == 1


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
    assert (
        repositories.approvals.get("appr_001").status is ApprovalRequestStatus.PENDING
    )

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
    assert (
        repositories.approvals.get("appr_001").status is ApprovalRequestStatus.APPROVED
    )
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
    inbox_types = [
        message.message_type
        for message in repositories.inbox.list_by_session(session.session_id)
    ]
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
    registry.register(
        "lane_echo", lambda _context, invocation: invocation.lane_id or "none"
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="run in lane"),
        driver=LaneAwareDriver(),
        tool_registry=registry,
    )

    assert result.outputs == (lane.lane_id,)
    assert result.tool_results[0].lane_id == lane.lane_id
    assert (
        repositories.invocations.list_by_session(session.session_id)[0].lane_id
        == lane.lane_id
    )


class DocsReadDriver:
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
                        call_id="call_docs",
                        tool_name="docs.read",
                        arguments={"doc_id": "hpc-vina"},
                        task_id="task_001",
                    ),
                ),
                next_focus=RestoreFocus(task_id="task_001"),
            )
        payload = json.loads(tool_results[0].content)
        return HarnessStep(assistant_message=f"docs:{payload['doc_id']}")


def test_harness_docs_read_uses_controlled_registry() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id),
        driver=DocsReadDriver(),
    )

    assert result.outputs == ("docs:hpc-vina",)
    assert "openzyme_pipeline" in result.tool_results[0].content


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
        HarnessInput(
            session_id=session.session_id,
            restore_focus=RestoreFocus(task_id="task_001"),
        ),
        driver=ExplicitCompactionDriver(),
    )

    task_memory = repositories.memory.list_by_scope(
        session.session_id, MemoryScopeKind.TASK, "task_001"
    )
    assert any(entry.kind is MemoryKind.COMPACTION for entry in task_memory)
    assert result.outputs == ("compacted",)


def test_harness_auto_compaction_keeps_lane_restore_state() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    lane = _seed_lane(repositories, session)
    registry = ToolRegistry()
    registry.register(
        "lane_echo", lambda _context, invocation: invocation.lane_id or "none"
    )

    run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="run in lane"),
        driver=LaneAwareDriver(),
        tool_registry=registry,
    )
    second = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            restore_focus=RestoreFocus(task_id="task_001", lane_id=lane.lane_id),
        ),
        driver=ApprovalDriver(),
    )

    lane_memory = repositories.memory.list_by_scope(
        session.session_id, MemoryScopeKind.LANE, lane.lane_id
    )
    assert any(entry.kind is MemoryKind.COMPACTION for entry in lane_memory)
    assert second.pending_approval_id == "appr_001"


class DeepResearchPlanningDriver:
    def __init__(self) -> None:
        self.planner = DeepResearchTaskPlanner()

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del harness_input
        if not tool_results:
            planned = self.planner.plan_task(context)
            assert planned is not None
            return planned
        return HarnessStep(assistant_message=str(tool_results[0].content))


def test_harness_can_dispatch_research_task_via_deep_research_planner() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=task.status,
            priority=task.priority,
            kind="research",
            assigned_ref=task.assigned_ref,
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )
    registry = ToolRegistry()
    registry.register(
        "deep_research.start",
        lambda _context, invocation: invocation.arguments["brief"],
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id),
        driver=DeepResearchPlanningDriver(),
        tool_registry=registry,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert "Session objective: Exercise the Session 03 kernel" in result.outputs[0]
    assert repositories.tasks.get("task_001").status is TaskStatus.IN_PROGRESS


class BuiltinTaskLaneToolDriver:
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
                        call_id="call_create_lane",
                        tool_name="lane.create",
                        arguments={
                            "lane_id": "lane_builtin",
                            "name": "builtin",
                            "cwd": "/tmp/builtin",
                        },
                    ),
                    ToolInvocation(
                        call_id="call_create_task",
                        tool_name="task.create",
                        arguments={
                            "task_id": "task_builtin",
                            "subject": "Builtin task",
                            "description": "Created through default harness registry.",
                        },
                    ),
                )
            )
        if len(tool_results) == 2:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_bind_task",
                        tool_name="lane.bind_task",
                        arguments={
                            "task_id": "task_builtin",
                            "lane_id": "lane_builtin",
                        },
                    ),
                )
            )
        return HarnessStep(assistant_message="builtin tools ready")


def test_harness_default_registry_includes_task_and_lane_tools() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="use builtins"),
        driver=BuiltinTaskLaneToolDriver(),
    )

    task = repositories.tasks.get("task_builtin")
    lane = repositories.lanes.get("lane_builtin")
    assert result.outputs == ("builtin tools ready",)
    assert task is not None
    assert task.lane_id == "lane_builtin"
    assert lane is not None
    assert lane.cwd == "/tmp/builtin"
    assert {event.event_type for event in result.events} >= {
        "task.created",
        "lane.created",
        "task.bound_to_lane",
        "tool.completed",
    }


class BuiltinDelegationDriver:
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
                        call_id="call_delegate_task",
                        tool_name="task.delegate",
                        arguments={"task_id": "task_001", "agent_role": "researcher"},
                    ),
                )
            )
        return HarnessStep(assistant_message="delegated")


class FailingDriver:
    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input, tool_results
        raise RuntimeError("HTTP Error 429: Too Many Requests")


class ToolFailureDriver:
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
                        call_id="call_search",
                        tool_name="semantic_scholar.search",
                        arguments={"query": "AI systems engineering"},
                    ),
                )
            )
        result = tool_results[0]
        return HarnessStep(assistant_message=f"Observed tool failure: {result.content}")


class ProtocolSendDriver:
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
                        call_id="call_protocol_send",
                        tool_name="protocol.send",
                        arguments={
                            "recipient": "agent:researcher",
                            "message_type": "diagnostic_request",
                            "correlation_id": "corr_diag_001",
                            "task_id": "task_001",
                            "payload": {
                                "task_id": "task_001",
                                "question": "Why did delegation fail?",
                                "instructions": "Explain the blocking issue.",
                                "failed_summary": "step budget exhausted",
                                "expected_response": "diagnostic_response with root cause",
                            },
                        },
                        task_id="task_001",
                    ),
                )
            )
        return HarnessStep(assistant_message="diagnostic requested")


def test_harness_returns_failed_result_when_driver_provider_is_rate_limited() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="search"),
        driver=FailingDriver(),
        tool_registry=ToolRegistry(),
    )

    assert result.status is HarnessStatus.FAILED
    assert "HTTP Error 429" in result.outputs[0]
    assert "harness.failed" in {event.event_type for event in result.events}


def test_harness_wraps_tool_provider_errors_as_tool_results() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()

    def fail_search(
        _context: SessionRuntimeContext, _invocation: ToolInvocation
    ) -> ToolResult:
        raise RuntimeError("HTTP Error 429: Too Many Requests")

    registry.register("semantic_scholar.search", fail_search)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="search"),
        driver=ToolFailureDriver(),
        tool_registry=registry,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert result.tool_results[0].ok is False
    assert "HTTP Error 429" in result.tool_results[0].content
    assert "Observed tool failure" in result.outputs[0]


def test_tool_registry_returns_standard_envelope_for_unknown_tool() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
    )

    result = context.tool_registry.dispatch(
        context,
        ToolInvocation(call_id="call_missing", tool_name="missing.tool", arguments={}),
    )

    envelope = result.envelope()
    assert result.ok is False
    assert result.status == "unknown_tool"
    assert envelope["error_code"] == "unknown_tool"
    assert envelope["summary"] == "Tool 'missing.tool' is not registered."


def test_tool_registry_wraps_handler_exception_as_standard_envelope() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()

    def explode(
        _context: SessionRuntimeContext, _invocation: ToolInvocation
    ) -> ToolResult:
        raise RuntimeError("boom")

    registry.register("explode", explode)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(call_id="call_explode", tool_name="explode", arguments={}),
    )

    envelope = result.envelope()
    assert result.ok is False
    assert result.status == "handler_exception"
    assert envelope["error_code"] == "handler_exception"
    assert envelope["details"] == {"exception_type": "RuntimeError"}
    assert "boom" in envelope["summary"]


def test_top_level_default_registry_can_send_protocol_diagnostic_request() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    ProtocolService(repositories).delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="researcher",
        payload_ref=None,
        task_id="task_001",
        correlation_id="corr_original",
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="diagnose"),
        driver=ProtocolSendDriver(),
    )

    sent = json.loads(result.tool_results[0].content)
    message = repositories.inbox.get(sent["message"]["message_id"])
    signal = next(
        signal
        for signal in repositories.runtime_signals.list_by_session(session.session_id)
        if signal.source_ref == message.message_id
    )
    thread = (
        ProtocolService(repositories)
        .build_thread(session.session_id, "corr_diag_001")
        .to_dict()
    )
    assert result.status is HarnessStatus.COMPLETED
    assert message.status.value == "unread"
    assert signal.reason.value == "inbox_unread"
    assert signal.task_id == "task_001"
    assert thread["request"]["payload"]["question"] == "Why did delegation fail?"


def test_harness_default_registry_can_delegate_research_task_to_builtin_subagent() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=task.status,
            priority=task.priority,
            kind="research",
            assigned_ref=task.assigned_ref,
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )

    registry = ToolRegistry()
    registry.register(
        "deep_research.start",
        lambda _context, invocation: json.dumps(
            {"brief": invocation.arguments["brief"]}
        ),
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="delegate research"),
        driver=BuiltinDelegationDriver(),
        tool_registry=registry,
        model_factory=FakeModelFactory(
            {
                "v3_teammate_loop:researcher": [
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_research",
                                "name": "deep_research.start",
                                "args": {
                                    "task_id": "task_001",
                                    "brief": "Run the first harness step.",
                                },
                            }
                        ],
                    },
                    {"content": "Research task completed.", "tool_calls": []},
                ]
            }
        ),
    )

    delegated_task = repositories.tasks.get("task_001")
    assert result.outputs == ("delegated",)
    assert delegated_task.assigned_ref == "agent:researcher"
    assert delegated_task.status is TaskStatus.COMPLETED
    assert repositories.agents.get("agent:researcher") is not None
    inbox_types = [
        message.message_type
        for message in repositories.inbox.list_by_session(session.session_id)
    ]
    assert "delegation_request" in inbox_types
    assert "delegation_result" in inbox_types


def test_researcher_tool_descriptors_include_direct_bio_research_tools() -> None:
    tool_names = {
        descriptor.tool_name
        for descriptor in teammate_tool_descriptors(role="researcher")
    }

    assert {
        "deep_research.start",
        "deep_research.resume",
        "deep_research.status",
        "deep_research.dossier",
        "pubmed.search",
        "semantic_scholar.search",
        "uniprot.lookup",
        "uniprot.download_fasta",
        "rcsb_pdb.search",
        "rcsb_pdb.download_structure",
        "interpro.query",
    }.issubset(tool_names)
    assert "web.search" not in tool_names
    assert "web.fetch" not in tool_names


def test_researcher_tool_descriptors_include_web_tools_when_adapter_supports_them() -> (
    None
):
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {"results": []},
        extract_callable=lambda **_: {"results": []},
    )
    tool_names = {
        descriptor.tool_name
        for descriptor in teammate_tool_descriptors(
            role="researcher", research_adapter=adapter
        )
    }

    assert "web.search" in tool_names
    assert "web.fetch" in tool_names


def test_reporter_artifact_get_descriptor_exposes_large_field_pagination() -> None:
    descriptor = next(
        item
        for item in teammate_tool_descriptors(role="reporter")
        if item.tool_name == "artifact.get"
    )

    properties = descriptor.input_schema["properties"]
    assert {"artifact_id", "path", "offset", "limit", "include_full"} <= set(properties)
    assert properties["limit"]["maximum"] == 50
    assert "read_hint" in descriptor.description
    assert "large dict" in descriptor.description
    assert "pageable keys" in descriptor.description


def test_research_teammate_direct_download_persists_workspace_artifact() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = build_teammate_registry(
        bio_research_service=DeterministicBioResearchService()
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_fasta",
            tool_name="uniprot.download_fasta",
            arguments={"accession": "P12345"},
            task_id="task_001",
        ),
    )

    artifact_records = repositories.artifacts.list_by_task(
        session.session_id, "task_001"
    )
    payload = json.loads(result.content)
    assert result.ok is True
    assert artifact_records
    assert payload["status"] == "completed"
    assert payload["artifacts"][0]["artifact_id"] == artifact_records[0].artifact_id
    assert artifact_records[0].kind is ArtifactKind.SEQUENCE
    assert artifact_records[0].invocation_id is not None
    assert artifact_records[0].metadata["provider"] == "uniprot"
    invocation = repositories.invocations.get(artifact_records[0].invocation_id)
    assert invocation.engine_name == "research_tool"


def test_research_teammate_direct_search_returns_observation_and_persists_canonical_rows() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = build_teammate_registry(
        bio_research_service=DeterministicBioResearchService()
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_pubmed",
            tool_name="pubmed.search",
            arguments={"query": "enzyme engineering", "limit": 3},
            task_id="task_001",
        ),
    )

    payload = json.loads(result.content)
    invocations = [
        invocation
        for invocation in repositories.invocations.list_by_session(session.session_id)
        if invocation.engine_name == "research_tool"
    ]
    invocation = invocations[0]
    workspace = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(session.session_id)
        .to_dict()
    )

    assert result.ok is True
    assert payload["provider"] == "pubmed"
    assert payload["findings"][0]["sources"][0]["kind"] == "paper"
    assert (
        repositories.research_summaries.get_by_invocation(
            session.session_id, invocation.invocation_id
        ).summary
        == (payload["summary"])
    )
    assert repositories.research_evidence.list_by_invocation(
        session.session_id, invocation.invocation_id
    )
    assert repositories.research_source_refs.list_by_invocation(
        session.session_id, invocation.invocation_id
    )
    assert (
        workspace["capabilities"]["research_tool"][0]["canonical_summary"]["summary"]
        == payload["summary"]
    )
    assert (
        workspace["capabilities"]["research_tool"][0]["source_refs"][0]["kind"]
        == "paper"
    )


def test_research_teammate_direct_web_fetch_persists_canonical_rows() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {"results": []},
        extract_callable=lambda **_: {
            "results": [
                {
                    "title": "Fetched article",
                    "url": "https://example.org/article",
                    "raw_content": "Fetched article content.",
                }
            ]
        },
    )
    registry = build_teammate_registry(research_adapter=adapter)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
        research_adapter=adapter,
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_fetch",
            tool_name="web.fetch",
            arguments={"url": "https://example.org/article"},
            task_id="task_001",
        ),
    )

    payload = json.loads(result.content)
    invocations = [
        invocation
        for invocation in repositories.invocations.list_by_session(session.session_id)
        if invocation.engine_name == "research_tool"
    ]
    invocation = invocations[0]

    assert result.ok is True
    assert payload["provider"] == "web"
    assert payload["findings"][0]["summary"] == "Fetched article content."
    assert payload["findings"][0]["sources"][0]["kind"] == "web_page"
    assert repositories.research_evidence.list_by_invocation(
        session.session_id, invocation.invocation_id
    )
    assert repositories.research_source_refs.list_by_invocation(
        session.session_id, invocation.invocation_id
    )


def test_research_teammate_direct_search_provider_429_returns_failed_observation() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = build_teammate_registry(
        bio_research_service=RateLimitedBioResearchService()
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_001"),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_semantic",
            tool_name="semantic_scholar.search",
            arguments={"query": "AI systems engineering", "limit": 3},
            task_id="task_001",
        ),
    )

    payload = json.loads(result.content)
    invocation = repositories.invocations.list_by_session(session.session_id)[0]
    summary = repositories.research_summaries.get_by_invocation(
        session.session_id, invocation.invocation_id
    )
    gaps = repositories.research_gaps.list_by_invocation(
        session.session_id, invocation.invocation_id
    )

    assert result.ok is False
    assert payload["status"] == "failed"
    assert "HTTP Error 429" in payload["unresolved_gaps"][0]
    assert invocation.status is EngineInvocationStatus.FAILED
    assert summary.status.value == "failed"
    assert "HTTP Error 429" in gaps[0].summary


def test_session_workspace_projection_exposes_delegation_threads() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=task.status,
            priority=task.priority,
            kind="research",
            assigned_ref=task.assigned_ref,
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )
    registry = ToolRegistry()
    registry.register(
        "deep_research.start",
        lambda _context, invocation: json.dumps(
            {"brief": invocation.arguments["brief"]}
        ),
    )

    run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="delegate research"),
        driver=BuiltinDelegationDriver(),
        tool_registry=registry,
        model_factory=FakeModelFactory(
            {
                "v3_teammate_loop:researcher": [
                    {
                        "content": "",
                        "tool_calls": [
                            {
                                "id": "call_research",
                                "name": "deep_research.start",
                                "args": {
                                    "task_id": "task_001",
                                    "brief": "Run the first harness step.",
                                },
                            }
                        ],
                    },
                    {"content": "Research task completed.", "tool_calls": []},
                ]
            }
        ),
    )

    workspace = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(session.session_id)
        .to_dict()
    )
    delegation = workspace["delegation"]["agents"][0]

    assert delegation["agent"]["agent_id"] == "agent:researcher"
    assert delegation["latest_correlation_id"] is not None
    assert delegation["thread_summaries"][0]["status"] == "responded"


class FakeToolCallingInvoker:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, object]] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> object:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        if isinstance(self.response, list):
            index = min(len(self.calls) - 1, len(self.response) - 1)
            return self.response[index]
        return self.response


class FakeModelFactory:
    def __init__(self, response: object | dict[str, object]) -> None:
        self.response = response
        self.invokers: dict[str, FakeToolCallingInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeToolCallingInvoker:
        if purpose not in self.invokers:
            if isinstance(self.response, dict) and purpose in self.response:
                response = self.response[purpose]
            else:
                response = self.response
            self.invokers[purpose] = FakeToolCallingInvoker(response)
        return self.invokers[purpose]


class ResumeAwareInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls: list[dict[str, object]] = []

    def invoke_with_tools(
        self, *, system_prompt: str, messages: list[object], tools: list[object]
    ) -> dict[str, object]:
        del system_prompt, tools
        self.calls.append({"messages": list(messages)})
        if self.purpose == "v3_teammate_loop:executor":
            return {"content": "", "tool_calls": []}
        tool_payload = json.loads(_message_content(messages[-1]))
        payload = tool_payload["payload"]
        summary = payload["summary"]
        return {"content": f"Execution finished: {summary}", "tool_calls": []}


class ResumeAwareModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, ResumeAwareInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> ResumeAwareInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = ResumeAwareInvoker(purpose)
        return self.invokers[purpose]


class FakeExecutionPipelineEngine:
    descriptor = EngineDescriptor(
        engine_name="execution",
        tool_names=("execution.pipeline.start", "execution.pipeline.status"),
        input_schema={},
        output_schema={},
        requires_approval=True,
        supports_background=False,
        idempotency_key_shape="",
        produces_artifact_types=(),
        capability_key="execution",
    )

    def __init__(self, repositories: CoreRepositories) -> None:
        self.repositories = repositories

    def register_tools(self, registry: ToolRegistry) -> None:
        del registry


class FakeEngine:
    def __init__(self, descriptor: EngineDescriptor) -> None:
        self.descriptor = descriptor

    def register_tools(self, registry: ToolRegistry) -> None:
        del registry


def _message_role(message: object) -> str | None:
    if isinstance(message, dict):
        return None if message.get("role") is None else str(message["role"])
    message_type = type(message).__name__
    if message_type == "HumanMessage":
        return "user"
    if message_type == "AIMessage":
        return "assistant"
    if message_type == "ToolMessage":
        return "tool"
    return None


def _message_content(message: object) -> str:
    if isinstance(message, dict):
        return str(message.get("content") or "")
    return str(getattr(message, "content", "") or "")


def test_builtin_tool_catalog_exposes_top_level_mutating_tools() -> None:
    tool_names = {descriptor.tool_name for descriptor in builtin_tool_descriptors()}
    assert {
        "task.create",
        "task.update",
        "task.delegate",
        "protocol.thread",
        "protocol.send",
        "lane.create",
        "lane.bind_task",
        "memory.compact",
        "docs.search",
        "docs.read",
    } <= tool_names


def test_top_level_tool_catalog_hides_direct_engine_start_tools() -> None:
    tool_names = {descriptor.tool_name for descriptor in top_level_tool_descriptors()}
    assert "deep_research.start" not in tool_names
    assert "execution.start" not in tool_names
    assert "execution.resume" not in tool_names
    assert "execution.status" not in tool_names
    assert "reporting.start" not in tool_names


def test_top_level_delegate_tool_documents_real_teammate_roles() -> None:
    delegate = next(
        descriptor
        for descriptor in builtin_tool_descriptors()
        if descriptor.tool_name == "task.delegate"
    )

    assert delegate.input_schema["properties"]["agent_role"]["enum"] == [
        "researcher",
        "executor",
        "reporter",
    ]
    assert delegate.input_schema["required"] == ["task_id", "agent_role"]
    assert "fpocket" not in delegate.description
    assert "AutoDock" not in delegate.description
    assert "AlphaFold" not in delegate.description


def test_llm_conversation_driver_system_prompt_lists_teammates_not_capability_tools() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    model_factory = FakeModelFactory(
        {"content": "There are researcher, executor, and reporter teammates."}
    )
    driver = LlmConversationDriver(model_factory)

    driver.plan(
        context,
        HarnessInput(session_id=session.session_id, message="你有哪些teammate"),
        (),
    )

    prompt = str(model_factory.invokers["v3_harness_loop"].calls[0]["system_prompt"])
    assert "researcher for literature and data research" in prompt
    assert "executor for approved computational execution" in prompt
    assert "reporter for report drafting and publishing" in prompt
    assert "answer only with researcher, executor, reporter" in prompt
    assert "Do not describe provider tools or capability engines" in prompt
    assert "diagnostic_request" in prompt
    assert "Completed/failed/blocked delegated tasks:" in prompt
    assert "Protocol threads available via protocol.thread:" in prompt
    assert "Teammate agents are internal workers" in prompt
    assert "fpocket" in prompt


def test_llm_conversation_driver_does_not_duplicate_current_user_message_in_harness_loop() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    model_factory = FakeModelFactory({"content": "I can help.", "tool_calls": []})
    driver = LlmConversationDriver(model_factory)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="你是什么模型"),
        driver=driver,
    )

    assert result.outputs == ("I can help.",)
    messages = model_factory.invokers["v3_harness_loop"].calls[0]["messages"]
    user_messages = [
        _message_content(message)
        for message in messages
        if _message_role(message) == "user"
    ]
    assert user_messages == ["你是什么模型"]


def test_llm_conversation_driver_sends_tool_result_envelope_to_model() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    model_factory = FakeModelFactory({"content": "handled", "tool_calls": []})
    driver = LlmConversationDriver(model_factory)

    driver.plan(
        context, HarnessInput(session_id=session.session_id, message="start"), ()
    )
    driver.plan(
        context,
        HarnessInput(session_id=session.session_id, message="start"),
        (
            ToolResult(
                call_id="call_1",
                tool_name="example",
                ok=False,
                content="failed raw content",
                status="runtime_failed",
                summary="The tool did not finish.",
                error_code="runtime_failed",
                hint="Inspect details.",
                details={"reason": "test"},
            ),
        ),
    )

    messages = model_factory.invokers["v3_harness_loop"].calls[1]["messages"]
    envelope = json.loads(_message_content(messages[-1]))
    assert envelope["ok"] is False
    assert envelope["status"] == "runtime_failed"
    assert envelope["summary"] == "The tool did not finish."
    assert envelope["error_code"] == "runtime_failed"
    assert envelope["hint"] == "Inspect details."
    assert envelope["details"] == {"reason": "test"}
    assert envelope["content"] == "failed raw content"


def test_approval_resume_does_not_expose_execution_resume_tool() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=TaskStatus.BLOCKED,
            priority=task.priority,
            kind="execution",
            assigned_ref="agent:executor",
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_execution_resume",
            session_id=session.session_id,
            task_id="task_001",
            lane_id=None,
            kind="execution_launch",
            requested_action="Run fpocket",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_execution_resume.json",
            resolution_ref=None,
            created_at="2026-04-17T09:02:00+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_execution_resume",
            session_id=session.session_id,
            task_id="task_001",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.WAITING_APPROVAL,
            input_ref="doc_input",
            output_ref=None,
            approval_id="appr_execution_resume",
            idempotency_key="resume:inv_execution_resume",
            started_at="2026-04-17T09:03:00+00:00",
            finished_at=None,
        )
    )
    engine_registry = EngineRegistry()
    engine_registry.register(FakeExecutionPipelineEngine(repositories))
    model_factory = ResumeAwareModelFactory()

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            resume=ResumeEnvelope(
                approval_id="appr_execution_resume",
                decision=ResumeDecision.APPROVED,
                actor_ref="tester",
            ),
        ),
        driver=LlmConversationDriver(model_factory),
        engine_registry=engine_registry,
        model_factory=model_factory,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert result.outputs == (
        "Approval was resolved. The execution supervisor will continue the pipeline internally.",
    )
    assert result.tool_results == ()
    assert (
        repositories.approvals.get("appr_execution_resume").status
        is ApprovalRequestStatus.APPROVED
    )


def test_resume_without_executor_tool_reports_internal_continuation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_direct_resume",
            session_id=session.session_id,
            task_id="task_001",
            lane_id=None,
            kind="execution_launch",
            requested_action="Run fpocket",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_direct_resume.json",
            resolution_ref=None,
            created_at="2026-04-17T09:02:00+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_direct_resume",
            session_id=session.session_id,
            task_id="task_001",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.WAITING_APPROVAL,
            input_ref="doc_input",
            output_ref=None,
            approval_id="appr_direct_resume",
            idempotency_key="resume:inv_direct_resume",
            started_at="2026-04-17T09:03:00+00:00",
            finished_at=None,
        )
    )
    engine_registry = EngineRegistry()
    engine_registry.register(FakeExecutionPipelineEngine(repositories))

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            resume=ResumeEnvelope(
                approval_id="appr_direct_resume",
                decision=ResumeDecision.APPROVED,
                actor_ref="tester",
            ),
        ),
        driver=LlmConversationDriver(
            FakeModelFactory({"content": "", "tool_calls": []})
        ),
        engine_registry=engine_registry,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert result.outputs == (
        "Approval was resolved. The execution supervisor will continue the pipeline internally.",
    )
    assert result.tool_results == ()


def test_llm_conversation_driver_translates_tool_calls_to_invocations() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    driver = LlmConversationDriver(
        FakeModelFactory(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_002",
                            "subject": "Plan",
                            "description": "Plan next step",
                        },
                    },
                ],
            }
        )
    )

    step = driver.plan(
        context, HarnessInput(session_id=session.session_id, message="plan work"), ()
    )

    assert step.assistant_message is None
    assert step.tool_invocations[0].tool_name == "task.create"
    assert step.tool_invocations[0].arguments["task_id"] == "task_002"


def test_llm_conversation_driver_backfills_delegate_task_id_from_same_turn_task_create() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    driver = LlmConversationDriver(
        FakeModelFactory(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_research_001",
                            "subject": "Deep research",
                            "description": "Survey AI in systems engineering",
                            "kind": "research",
                        },
                    },
                    {
                        "id": "call_delegate",
                        "name": "task.delegate",
                        "args": {
                            "agent_role": "researcher",
                        },
                    },
                ],
            }
        )
    )

    step = driver.plan(
        context,
        HarnessInput(session_id=session.session_id, message="start research"),
        (),
    )

    assert step.assistant_message is None
    assert [invocation.tool_name for invocation in step.tool_invocations] == [
        "task.create",
        "task.delegate",
    ]
    assert step.tool_invocations[1].arguments["task_id"] == "task_research_001"
    assert (
        step.tool_invocations[1].arguments["instructions"]
        == "Survey AI in systems engineering"
    )


def test_llm_conversation_driver_backfills_delegate_role_from_created_task_kind() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    driver = LlmConversationDriver(
        FakeModelFactory(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_task",
                        "name": "task.create",
                        "args": {
                            "task_id": "task_report_001",
                            "subject": "Write report",
                            "description": "Publish the final report",
                            "kind": "reporting",
                        },
                    },
                    {"id": "call_delegate", "name": "task.delegate", "args": {}},
                ],
            }
        )
    )

    step = driver.plan(
        context, HarnessInput(session_id=session.session_id, message="write report"), ()
    )

    assert step.assistant_message is None
    assert step.tool_invocations[1].arguments["task_id"] == "task_report_001"
    assert step.tool_invocations[1].arguments["agent_role"] == "reporter"


def test_llm_conversation_driver_returns_friendly_message_when_delegate_lacks_task_id() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    driver = LlmConversationDriver(
        FakeModelFactory(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_delegate",
                        "name": "task.delegate",
                        "args": {"agent_role": "researcher"},
                    },
                ],
            }
        )
    )

    step = driver.plan(
        context,
        HarnessInput(session_id=session.session_id, message="start research"),
        (),
    )

    assert step.tool_invocations == ()
    assert "without task_id" in str(step.assistant_message)


def test_llm_conversation_driver_rejects_delegate_without_agent_role() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    driver = LlmConversationDriver(
        FakeModelFactory(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_delegate",
                        "name": "task.delegate",
                        "args": {"task_id": "task_001"},
                    },
                ],
            }
        )
    )

    step = driver.plan(
        context,
        HarnessInput(session_id=session.session_id, message="delegate task"),
        (),
    )

    assert step.tool_invocations == ()
    assert "without agent_role" in str(step.assistant_message)


def test_llm_conversation_driver_rejects_unknown_delegate_role() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    driver = LlmConversationDriver(
        FakeModelFactory(
            {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_delegate",
                        "name": "task.delegate",
                        "args": {"task_id": "task_001", "agent_role": "worker"},
                    },
                ],
            }
        )
    )

    step = driver.plan(
        context,
        HarnessInput(session_id=session.session_id, message="delegate task"),
        (),
    )

    assert step.tool_invocations == ()
    assert "invalid agent_role" in str(step.assistant_message)
