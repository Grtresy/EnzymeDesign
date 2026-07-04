from __future__ import annotations

import json

import pytest

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import AgentRuntimeSignalReason
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
from openzyme_core import TaskBoardService
from openzyme_core import TaskMutation
from openzyme_core import ToolDescriptor
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
from openzyme_core import register_task_board_tools
from openzyme_core import register_subagent_tools
from openzyme_core import teammate_tool_descriptors
from openzyme_core import TeammateConversationDriver
from openzyme_core.agent_identity import create_agent_member
from openzyme_core.agent_identity import display_name_for_agent
from openzyme_core.agent_identity import handle_for_agent
from openzyme_core.harness import build_agent_step_context
from openzyme_core.harness import budget_tool_results_for_prompt
from openzyme_core.harness import ensure_prompt_budget_before_model_call
from openzyme_core.harness import PromptPayload
from openzyme_research import DeterministicBioResearchService
from openzyme_research import TavilyResearchAdapter
from openzyme_runtime import get_llm_debug_recorder
from openzyme_runtime import LangChainToolCallingInvoker
from openzyme_runtime import ToolGovernance
from openzyme_runtime import ToolSpec
from openzyme_runtime import ToolSideEffect


class RateLimitedBioResearchService(DeterministicBioResearchService):
    def search_semantic_scholar(self, *, query: str, limit: int = 5):
        del query, limit
        raise RuntimeError("HTTP Error 429: Too Many Requests")


class RecordingToolInvoker:
    def __init__(self, responses: list[dict[str, object]]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "messages": list(messages),
                "tools": list(tools),
            }
        )
        if not self.responses:
            return {"content": "done", "tool_calls": []}
        return self.responses.pop(0)


class BudgetTestModelFactory:
    def __init__(
        self,
        invoker: RecordingToolInvoker,
        *,
        context_window_tokens: int = 100_000,
        default_output_tokens: int = 0,
    ) -> None:
        self.model = "budget-test-model"
        self.context_window_tokens = context_window_tokens
        self.default_output_tokens = default_output_tokens
        self.invoker = invoker

    def create_tool_calling_invoker(self, *, purpose: str):
        del purpose
        return self.invoker


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


def _seed_agent(
    repositories: CoreRepositories,
    session: Session,
    *,
    role: str = "researcher",
    task_id: str | None = None,
    lane_id: str | None = None,
):
    return create_agent_member(
        repositories,
        session_id=session.session_id,
        role=role,  # type: ignore[arg-type]
        task_id=task_id,
        lane_id=lane_id,
    )


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


def test_llm_preflight_auto_compacts_before_provider_call(monkeypatch) -> None:
    monkeypatch.delenv("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS", raising=False)
    repositories = _build_repositories()
    session = _seed_session(repositories)
    invoker = RecordingToolInvoker([{"content": "done", "tool_calls": []}])
    factory = BudgetTestModelFactory(invoker)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            message="x" * 300_000,
            max_steps=1,
        ),
        driver=LlmConversationDriver(factory),
        model_factory=factory,
    )

    compactions = [
        memory
        for memory in repositories.memory.list_by_session(session.session_id)
        if memory.kind is MemoryKind.COMPACTION
        and memory.source_range == "auto:prompt_budget"
    ]
    assert result.status is HarnessStatus.COMPLETED
    assert len(invoker.calls) == 1
    assert compactions
    assert "auto_compact before model call" in compactions[-1].summary
    assert any(
        event.event_type == "llm.context_budget.after_compaction"
        for event in result.events
    )


def test_oversized_tool_result_is_artifactized_before_next_llm_prompt(monkeypatch) -> None:
    monkeypatch.delenv("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS", raising=False)
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=BudgetTestModelFactory(RecordingToolInvoker([])),
    )
    context.refresh_restore_context()
    original = ToolResult(
        call_id="call_huge",
        tool_name="huge.tool",
        ok=True,
        content=json.dumps({"tool_result": "x" * 340_000}),
        status="ok",
        summary="huge result completed",
    )
    budgeted = budget_tool_results_for_prompt(
        context,
        (original,),
        system_prompt="system",
        messages=[],
        tools=[],
    )

    artifacts = [
        artifact
        for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.kind is ArtifactKind.RESULT
        and artifact.relative_path == "tool_results/call_huge.json"
    ]
    observation = budgeted[0]
    observation_prompt = observation.to_tool_message_content()
    assert artifacts
    assert observation.ok is False
    assert observation.status == "tool_result_context_over_budget"
    assert observation.details["original_tool_ok"] is True
    assert "tool_result_context_over_budget" in observation_prompt
    assert artifacts[0].artifact_id in observation_prompt
    assert "x" * 1000 not in observation_prompt
    persisted = repositories.engine_documents.get(
        str(dict(artifacts[0].metadata or {})["output_ref"])
    )
    assert persisted is not None
    assert persisted.document_kind == "tool_result_full"
    assert persisted.payload["original_tool_ok"] is True


def test_tool_result_artifact_observation_survives_prompt_compaction_rebuild(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_WARN_RATIO", "0.45")
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO", "0.50")
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO", "0.95")
    repositories = _build_repositories()
    session = _seed_session(repositories)
    invoker = RecordingToolInvoker([])
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(),
        model_factory=BudgetTestModelFactory(invoker),
    )
    context.refresh_restore_context()
    marker = "raw-tool-payload-marker"
    original = ToolResult(
        call_id="call_huge_after_compaction",
        tool_name="huge.tool",
        ok=True,
        content=json.dumps({"tool_result": marker + ("x" * 340_000)}),
        status="ok",
        summary="huge result completed",
    )
    budgeted = budget_tool_results_for_prompt(
        context,
        (original,),
        system_prompt="system",
        messages=[],
        tools=[],
    )
    observation_content = budgeted[0].to_tool_message_content()
    messages = [
        {"role": "user", "content": "prior-large-context-" + ("y" * 260_000)},
        {
            "role": "tool",
            "name": budgeted[0].tool_name,
            "content": observation_content,
        },
    ]

    def rebuild_payload() -> PromptPayload:
        return PromptPayload(
            system_prompt="system after compaction",
            messages=[
                {
                    "role": "tool",
                    "name": budgeted[0].tool_name,
                    "content": observation_content,
                }
            ],
            tools=[],
        )

    preflight = ensure_prompt_budget_before_model_call(
        context,
        actor_ref="harness",
        system_prompt="system",
        messages=messages,
        tools=[],
        recent_tool_result=budgeted[0],
        rebuild_payload=rebuild_payload,
    )

    rebuilt_prompt = "\n".join(
        _message_content(message) for message in preflight.payload.messages
    )
    assert preflight.compacted is True
    assert preflight.final_decision.action.value == "ok"
    assert budgeted[0].details["original_tool_ok"] is True
    assert budgeted[0].details["artifact_id"] in rebuilt_prompt
    assert "read_hint" in rebuilt_prompt
    assert marker not in rebuilt_prompt
    assert "prior-large-context-" in rebuilt_prompt
    assert "y" * 2_000 not in rebuilt_prompt


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


class TerminalTaskFinishDriver:
    def __init__(self) -> None:
        self.calls = 0

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input, tool_results
        self.calls += 1
        if self.calls > 1:
            raise AssertionError("terminal task.finish result must not be fed back into another plan")
        return HarnessStep(
            tool_invocations=(
                ToolInvocation(
                    call_id="call_finish",
                    tool_name="task.finish",
                    arguments={
                        "task_id": "task_001",
                        "status": "completed",
                        "summary": "Primary task is complete.",
                    },
                    task_id="task_001",
                ),
                ToolInvocation(
                    call_id="call_after_finish",
                    tool_name="echo",
                    arguments={"text": "should not run"},
                    task_id="task_001",
                ),
            )
        )


def test_task_finish_completed_updates_task_and_terminates_loop_immediately() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    register_task_board_tools(registry)
    calls: list[str] = []
    registry.register(
        "echo",
        lambda _context, invocation: calls.append(invocation.tool_name) or "echoed",
    )
    driver = TerminalTaskFinishDriver()

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            max_steps=3,
            agent_id="agent:primary",
            actor_kind="teammate",
            actor_role="researcher",
        ),
        driver=driver,
        tool_registry=registry,
    )

    task = repositories.tasks.get("task_001")
    finish_docs = [
        document
        for document in repositories.engine_documents.list_by_session(session.session_id)
        if document.document_kind == "task_finish"
    ]
    assert result.status is HarnessStatus.COMPLETED
    assert driver.calls == 1
    assert calls == []
    assert task is not None
    assert task.status is TaskStatus.COMPLETED
    assert len(result.tool_results) == 1
    assert result.tool_results[0].tool_name == "task.finish"
    assert result.tool_results[0].terminal_action == "task.finish"
    assert result.tool_results[0].terminates_turn is True
    assert result.tool_results[0].envelope()["terminates_turn"] is True
    assert finish_docs
    assert finish_docs[0].payload["summary"] == "Primary task is complete."
    assert {event.event_type for event in result.events} >= {
        "task.updated",
        "task.finished",
        "harness.terminal_action",
    }


class MasterFinishesDelegatedTaskDriver:
    def __init__(self) -> None:
        self.calls = 0

    def plan(
        self,
        context: SessionRuntimeContext,
        harness_input: HarnessInput,
        tool_results: tuple[object, ...],
    ) -> HarnessStep:
        del context, harness_input
        self.calls += 1
        if self.calls == 1:
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_finish_delegated",
                        tool_name="task.finish",
                        arguments={
                            "task_id": "task_001",
                            "status": "completed",
                            "summary": "Delegated research task is complete.",
                        },
                        task_id="task_001",
                    ),
                )
            )
        if self.calls == 2:
            assert tool_results[-1].tool_name == "task.finish"
            return HarnessStep(
                tool_invocations=(
                    ToolInvocation(
                        call_id="call_continue_after_finish",
                        tool_name="echo",
                        arguments={"text": "continued"},
                    ),
                )
            )
        return HarnessStep(assistant_message="master continued")


def test_master_finishing_delegated_task_does_not_terminate_master_loop() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    delegated_agent = create_agent_member(
        repositories,
        session_id=session.session_id,
        role="researcher",
        task_id="task_001",
    )
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=TaskStatus.IN_PROGRESS,
            priority=task.priority,
            kind="research",
            assigned_ref=delegated_agent.agent_id,
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    echo_calls: list[str] = []
    registry.register(
        "echo",
        lambda _context, invocation: echo_calls.append(
            str(invocation.arguments["text"])
        )
        or "echoed",
    )
    driver = MasterFinishesDelegatedTaskDriver()

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            max_steps=4,
            agent_id="agent:master",
            actor_kind="master",
            actor_role="master",
        ),
        driver=driver,
        tool_registry=registry,
    )

    task = repositories.tasks.get("task_001")
    assert result.status is HarnessStatus.COMPLETED
    assert driver.calls == 3
    assert echo_calls == ["continued"]
    assert task.status is TaskStatus.COMPLETED
    assert result.tool_results[0].tool_name == "task.finish"
    assert result.tool_results[0].terminal_action == "task.finish"
    assert result.tool_results[0].terminates_turn is False
    assert "harness.terminal_action" not in {
        event.event_type for event in result.events
    }


def test_master_finishing_own_task_does_not_terminate_master_loop() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=TaskStatus.IN_PROGRESS,
            priority=task.priority,
            kind=task.kind,
            assigned_ref="agent:master",
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )
    registry = ToolRegistry()
    register_task_board_tools(registry)
    echo_calls: list[str] = []
    registry.register(
        "echo",
        lambda _context, invocation: echo_calls.append(
            str(invocation.arguments["text"])
        )
        or "echoed",
    )
    driver = MasterFinishesDelegatedTaskDriver()

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            max_steps=4,
            agent_id="agent:master",
            actor_kind="master",
            actor_role="master",
        ),
        driver=driver,
        tool_registry=registry,
    )

    task = repositories.tasks.get("task_001")
    assert result.status is HarnessStatus.COMPLETED
    assert driver.calls == 3
    assert echo_calls == ["continued"]
    assert task.status is TaskStatus.COMPLETED
    assert result.tool_results[0].tool_name == "task.finish"
    assert result.tool_results[0].terminal_action == "task.finish"
    assert result.tool_results[0].terminates_turn is False
    assert "harness.terminal_action" not in {
        event.event_type for event in result.events
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


class EngineSuccessWithoutFinishDriver:
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
                        call_id="call_registry",
                        tool_name="registry.echo",
                        arguments={"text": "ready"},
                        task_id="task_001",
                    ),
                )
            )
        return HarnessStep(assistant_message="should require a separate model decision")


def test_engine_tool_success_does_not_auto_complete_task() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine_registry = EngineRegistry()
    engine_registry.register(RegistryBackedEngine())

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, max_steps=1),
        driver=EngineSuccessWithoutFinishDriver(),
        engine_registry=engine_registry,
    )

    task = repositories.tasks.get("task_001")
    assert result.status is HarnessStatus.MAX_STEPS_EXCEEDED
    assert [tool_result.tool_name for tool_result in result.tool_results] == [
        "registry.echo"
    ]
    assert task is not None
    assert task.status is TaskStatus.TODO


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
    def __init__(self, doc_id: str = "hpc-vina") -> None:
        self.doc_id = doc_id

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
                        arguments={"doc_id": self.doc_id},
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


def test_harness_docs_read_exposes_aox_hmm_live_recipe() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id),
        driver=DocsReadDriver(doc_id="aox-hmm-live"),
    )

    assert result.outputs == ("docs:aox-hmm-live",)
    payload = json.loads(result.tool_results[0].content)
    content = payload["content"]
    assert "bio.ncbi_fetch_proteins" in content
    assert "bio_tools.hmmbuild" in content
    assert '"AAC72747.1"' in content
    assert '"CAQ19344.1"' in content
    assert "bio_tools/cdhit/clustered.fasta" in content
    assert "bio_tools/cdhit/clusters.csv" in content
    assert "bio_tools/mafft/alignment.fasta" in content
    assert "bio_tools/hmmbuild/model.hmm" in content
    assert "bio_tools/hmmalign/aligned.fasta" in content
    assert "aox_hmm/execution_summary.json" in content
    assert "adapter_result_envelope" in content
    assert "artifact_payload = artifacts.get(artifact_id)" in content
    assert 'artifact_payload.get("artifact") or artifact_payload' in content
    assert "INPUT_TMP = Path(\"/workspace/input/aox_hmm_tmp\")" in content
    assert "BIO_OUTPUT_BASE = f\"/workspace/output/bio/aox_hmm_runs/{RUN_TAG}\"" in content
    assert "Host artifact materialization creates" in content
    assert "TMP.mkdir" not in content
    assert "INPUT_TMP.mkdir" not in content
    assert "pseudo-HMMs" in content
    assert "dependency installs" in content
    assert "bio_tools/cdhit/reference90.fasta" not in content
    assert "bio_tools/mafft/AOX_ref21.aligned.fasta" not in content
    assert "bio_tools/hmmbuild/AOX_ref.hmm" not in content
    assert "bio_tools/hmmalign/AOX_ref21.hmmaligned.fasta" not in content


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


class NullScopeCompactionDriver:
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
                        call_id="call_compact_null_scope",
                        tool_name="memory.compact",
                        arguments={"scope_kind": None},
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


def test_harness_memory_compact_tool_defaults_null_scope_to_session() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id),
        driver=NullScopeCompactionDriver(),
    )

    session_memory = repositories.memory.list_by_scope(
        session.session_id, MemoryScopeKind.SESSION, session.session_id
    )
    assert any(entry.kind is MemoryKind.COMPACTION for entry in session_memory)
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
            assigned_ref=None,
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
                            "recipient": "@ada",
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
    assert not any(
        message.message_type == "assistant_message"
        for message in repositories.inbox.list_by_session(session.session_id)
    )


def test_harness_fails_turn_when_tool_provider_raises_runtime_error() -> None:
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

    assert result.status is HarnessStatus.FAILED
    assert result.tool_results == ()
    assert "HTTP Error 429" in result.outputs[0]
    failed_events = [event for event in result.events if event.event_type == "harness.failed"]
    assert failed_events
    assert failed_events[-1].payload["tool_name"] == "semantic_scholar.search"


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


def test_tool_registry_wraps_argument_errors_as_standard_envelope() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()

    def reject_bad_arguments(
        _context: SessionRuntimeContext, _invocation: ToolInvocation
    ) -> ToolResult:
        raise ValueError("missing task_id")

    registry.register("reject_args", reject_bad_arguments)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(call_id="call_reject_args", tool_name="reject_args", arguments={}),
    )

    envelope = result.envelope()
    assert result.ok is False
    assert result.status == "invalid_tool_arguments"
    assert envelope["error_code"] == "invalid_tool_arguments"
    assert envelope["details"] == {"exception_type": "ValueError"}
    assert "missing task_id" in envelope["summary"]


def test_tool_registry_propagates_runtime_handler_exceptions() -> None:
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

    with pytest.raises(RuntimeError, match="boom"):
        registry.dispatch(
            context,
            ToolInvocation(call_id="call_explode", tool_name="explode", arguments={}),
        )


def test_top_level_default_registry_can_send_protocol_diagnostic_request() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(
        repositories,
        session,
        role="researcher",
        task_id="task_001",
    )
    ProtocolService(repositories).delegate(
        session_id=session.session_id,
        agent_id=agent.agent_id,
        name=display_name_for_agent(agent),
        role="researcher",
        payload_ref=None,
        task_id="task_001",
        correlation_id="corr_original",
        nickname=agent.nickname,
        display_name=display_name_for_agent(agent),
        handle=handle_for_agent(agent),
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
    assert signal.agent_id == agent.agent_id
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
            assigned_ref=None,
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
    )

    delegated_task = repositories.tasks.get("task_001")
    assert result.outputs == ("delegated",)
    assert delegated_task.assigned_ref is not None
    assert delegated_task.status is TaskStatus.IN_PROGRESS
    agent = next(
        candidate
        for candidate in repositories.agents.list_by_session(session.session_id)
        if candidate.role == "researcher"
    )
    assert agent is not None
    assert delegated_task.assigned_ref == agent.agent_id
    assert agent.agent_id.startswith("agent:researcher:")
    assert agent.task_id == "task_001"
    assert agent.role == "researcher"
    assert agent.nickname == "Ada"
    assert agent.handle == "@ada"
    assert agent.wakeup_reason == AgentRuntimeSignalReason.DELEGATION_ASSIGNED.value
    inbox = repositories.inbox.list_by_session(session.session_id)
    inbox_types = [message.message_type for message in inbox]
    assert "delegation_request" in inbox_types
    assert "delegation_result" not in inbox_types
    delegation_message = next(
        message for message in inbox if message.message_type == "delegation_request"
    )
    assert delegation_message.recipient == agent.agent_id
    signals = repositories.runtime_signals.list_pending_by_session(session.session_id)
    assert len(signals) == 1
    assert signals[0].agent_id == agent.agent_id
    assert signals[0].task_id == "task_001"
    assert signals[0].reason is AgentRuntimeSignalReason.INBOX_UNREAD
    assert signals[0].source_ref == delegation_message.message_id
    assert "agent.delegated" in {event.event_type for event in result.events}


def test_task_delegate_creates_distinct_canonical_agents_for_same_role() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    for task_id in ("task_research_a", "task_research_b"):
        service.create_task(
            session_id=session.session_id,
            task_id=task_id,
            subject=f"Research {task_id}",
            description="Delegate to a researcher.",
            kind="research",
        )
    registry = ToolRegistry()
    register_subagent_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    results = [
        registry.dispatch(
            context,
            ToolInvocation(
                call_id=f"call_delegate_{task_id}",
                tool_name="task.delegate",
                arguments={"task_id": task_id, "agent_role": "researcher"},
            ),
        )
        for task_id in ("task_research_a", "task_research_b")
    ]

    task_a = repositories.tasks.get("task_research_a")
    task_b = repositories.tasks.get("task_research_b")
    agents = [
        agent
        for agent in repositories.agents.list_by_session(session.session_id)
        if agent.role == "researcher"
    ]
    assert [result.ok for result in results] == [True, True]
    assert task_a.assigned_ref != task_b.assigned_ref
    assert {task_a.assigned_ref, task_b.assigned_ref} == {
        agent.agent_id for agent in agents
    }
    assert all(agent.agent_id.startswith("agent:researcher:") for agent in agents)
    assert "agent:researcher" not in {task_a.assigned_ref, task_b.assigned_ref}
    assert [agent.nickname for agent in agents] == ["Ada", "Curie"]


def test_task_delegate_normalizes_blank_and_same_role_agent_ref() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    for task_id in ("task_blank_ref", "task_role_ref"):
        service.create_task(
            session_id=session.session_id,
            task_id=task_id,
            subject=f"Research {task_id}",
            description="Delegate to a researcher.",
            kind="research",
        )
    registry = ToolRegistry()
    register_subagent_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    blank_ref = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_blank_ref",
            tool_name="task.delegate",
            arguments={
                "task_id": "task_blank_ref",
                "agent_role": "researcher",
                "agent_ref": "",
            },
        ),
    )
    same_role_ref = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_same_role_ref",
            tool_name="task.delegate",
            arguments={
                "task_id": "task_role_ref",
                "agent_role": "researcher",
                "agent_ref": "researcher",
            },
        ),
    )

    blank_task = repositories.tasks.get("task_blank_ref")
    role_task = repositories.tasks.get("task_role_ref")
    assert blank_ref.ok is True
    assert same_role_ref.ok is True
    assert blank_task.assigned_ref is not None
    assert role_task.assigned_ref is not None
    assert blank_task.assigned_ref != "researcher"
    assert role_task.assigned_ref != "researcher"
    assert blank_task.assigned_ref != role_task.assigned_ref


def test_task_delegate_rejects_mismatched_role_alias_agent_ref() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    service = TaskBoardService(repositories)
    service.create_task(
        session_id=session.session_id,
        task_id="task_mismatch_ref",
        subject="Research mismatch",
        description="Delegate to a researcher.",
        kind="research",
    )
    registry = ToolRegistry()
    register_subagent_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_mismatch_ref",
            tool_name="task.delegate",
            arguments={
                "task_id": "task_mismatch_ref",
                "agent_role": "researcher",
                "agent_ref": "executor",
            },
        ),
    )

    task = repositories.tasks.get("task_mismatch_ref")
    assert result.ok is False
    assert result.error_code == "agent_ref_role_mismatch"
    assert task.assigned_ref is None
    assert task.status is TaskStatus.TODO


def test_delegate_executor_aox_task_persists_mandatory_recipe_instructions() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task = repositories.tasks.get("task_001")
    repositories.tasks.save(
        Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject="Run AOX/HMM mining pipeline",
            description="Execute AOX HMM refprot sequence-mining from fixed accessions.",
            status=TaskStatus.TODO,
            priority=task.priority,
            kind="execution",
            assigned_ref=None,
            created_at=task.created_at,
            updated_at=task.updated_at,
            lane_id=task.lane_id,
            blocked_by=task.blocked_by,
        )
    )

    class DelegateAoxExecutorDriver:
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
                            call_id="call_delegate_aox",
                            tool_name="task.delegate",
                            arguments={
                                "task_id": "task_001",
                                "agent_role": "executor",
                                "instructions": "Run the assigned computational workflow.",
                            },
                        ),
                    )
                )
            return HarnessStep(assistant_message="delegated")

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="delegate AOX execution"),
        driver=DelegateAoxExecutorDriver(),
    )

    assert result.outputs == ("delegated",)
    delegation_message = next(
        message
        for message in repositories.inbox.list_by_session(session.session_id)
        if message.message_type == "delegation_request"
    )
    assert delegation_message.payload_ref is not None
    payload = repositories.engine_documents.get(delegation_message.payload_ref).payload
    instructions = str(payload["instructions"])
    assert "Run the assigned computational workflow." in instructions
    assert 'docs.read doc_id="aox-hmm-live"' in instructions
    assert "sandbox.workspace.status" in instructions
    assert "sandbox.exec" in instructions
    assert "direct MAFFT/CD-HIT/HMMER binaries" in instructions
    assert "fixed aox_hmm/* deliverables are registered" in instructions


def test_delegate_tool_rejects_blocked_task_without_side_effects_then_succeeds_when_ready() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    task_service = TaskBoardService(repositories)
    task_service.create_task(
        session_id=session.session_id,
        task_id="task_upstream",
        subject="Upstream",
        description="Produce inputs.",
        status=TaskStatus.IN_PROGRESS,
    )
    task_service.create_task(
        session_id=session.session_id,
        task_id="task_downstream",
        subject="Downstream",
        description="Use upstream outputs.",
        kind="research",
        blocked_by=("task_upstream",),
    )
    registry = ToolRegistry()
    register_subagent_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    blocked = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_blocked_delegate",
            tool_name="task.delegate",
            arguments={
                "task_id": "task_downstream",
                "agent_role": "researcher",
                "correlation_id": "corr_blocked_delegate",
            },
        ),
    )

    assert blocked.ok is False
    assert blocked.status == "task_not_ready"
    assert blocked.error_code == "task_blocked"
    assert blocked.details["blocked_by_open_task_ids"] == ["task_upstream"]
    assert repositories.inbox.list_by_session(session.session_id) == []
    assert repositories.runtime_signals.list_by_session(session.session_id) == []

    task_service.update_task("task_upstream", TaskMutation(status=TaskStatus.COMPLETED))
    ready = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_ready_delegate",
            tool_name="task.delegate",
            arguments={
                "task_id": "task_downstream",
                "agent_role": "researcher",
                "correlation_id": "corr_ready_delegate",
            },
        ),
    )

    assert ready.ok is True
    assert ready.status == "wakeup_queued"
    assert any(
        message.message_type == "delegation_request"
        and message.correlation_id == "corr_ready_delegate"
        for message in repositories.inbox.list_by_session(session.session_id)
    )
    assert len(repositories.runtime_signals.list_by_session(session.session_id)) == 1


def test_delegate_tool_rejects_already_assigned_task_without_side_effects() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    register_subagent_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_assigned_delegate",
            tool_name="task.delegate",
            arguments={
                "task_id": "task_001",
                "agent_role": "researcher",
                "correlation_id": "corr_assigned_delegate",
            },
        ),
    )

    assert result.ok is False
    assert result.status == "task_not_ready"
    assert result.error_code == "task_already_assigned"
    assert repositories.inbox.list_by_session(session.session_id) == []
    assert repositories.runtime_signals.list_by_session(session.session_id) == []


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


def test_researcher_runtime_requires_deep_research_before_direct_open_research_tools() -> (
    None
):
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(repositories, session, role="researcher")
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {"results": []},
        extract_callable=lambda **_: {"results": []},
    )
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(task_id="task_001"),
        research_adapter=adapter,
    )
    driver = TeammateConversationDriver(
        model_factory=object(),
        role="researcher",
        agent_id=agent.agent_id,
        correlation_id="corr_001",
        task_id="task_001",
        instructions="Collect research evidence and identify source-backed findings.",
        research_adapter=adapter,
    )

    first_tool_names = {tool.tool_name for tool in driver._allowed_tools(context)}
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_deep_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id=None,
            engine_name="deep_research",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="task_001:deep_research:test",
            started_at="2026-04-20T12:00:00+00:00",
            finished_at="2026-04-20T12:01:00+00:00",
        )
    )

    second_tool_names = {tool.tool_name for tool in driver._allowed_tools(context)}

    assert "deep_research.start" in first_tool_names
    assert "web.search" not in first_tool_names
    assert "rcsb_pdb.download_structure" not in first_tool_names
    assert "web.search" in second_tool_names
    assert "rcsb_pdb.download_structure" in second_tool_names


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


def test_master_and_teammate_catalogs_expose_artifact_read_tools() -> None:
    expected = {
        "artifact.list",
        "artifact.create_text",
        "artifact.patch_text",
        "artifact.diff_text",
        "artifact.get",
        "artifact.preview",
        "artifact.read_text",
        "artifact.range",
    }

    master_names = {tool.tool_name for tool in top_level_tool_descriptors()}
    teammate_names = {tool.tool_name for tool in teammate_tool_descriptors(role="reporter")}

    assert expected <= master_names
    assert expected <= teammate_names


def test_master_and_teammate_prompts_do_not_request_host_paths() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=ToolRegistry(),
        restore_focus=RestoreFocus(task_id="task_001"),
    )
    context.refresh_restore_context()

    from openzyme_core.llm_driver import _build_system_prompt

    master_prompt = _build_system_prompt(context)
    teammate_prompt = TeammateConversationDriver(
        model_factory=None,
        agent_id="agent_reporter",
        role="reporter",
        correlation_id="corr_001",
        task_id="task_001",
        instructions="Inspect artifacts.",
    )._system_prompt(context)

    assert "artifact.list/get/preview/read_text/range/create_text/patch_text/diff_text" in master_prompt
    assert "artifact.create_text" in teammate_prompt
    assert "Never request or use Host local paths" in teammate_prompt
    assert "never request or use Host local paths" in master_prompt


def test_public_tool_args_redact_pipeline_source_content() -> None:
    from openzyme_core.llm_driver import _sanitize_public_args

    sanitized = _sanitize_public_args(
        {
            "filename": "pipeline.py",
            "code": "def legacy_inline():\n    pass\n",
            "code_artifact_id": "art_code_001",
            "source_code": "def current_source():\n    pass\n",
            "source_code_artifact_id": "art_code_002",
            "source_code_digest": "sha256:def456",
            "content": "def main():\n    return 'secret source'\n",
            "base_content_digest": "sha256:abc123",
        }
    )

    assert sanitized["filename"] == "pipeline.py"
    assert sanitized["code"] == "[redacted]"
    assert sanitized["code_artifact_id"] == "art_code_001"
    assert sanitized["source_code"] == "[redacted]"
    assert sanitized["source_code_artifact_id"] == "art_code_002"
    assert sanitized["source_code_digest"] == "sha256:def456"
    assert sanitized["content"] == "[redacted]"
    assert sanitized["base_content_digest"] == "sha256:abc123"
    assert "secret source" not in json.dumps(sanitized)


def test_executor_descriptor_exposes_sandbox_workspace_status() -> None:
    descriptor = next(
        item
        for item in teammate_tool_descriptors(role="executor")
        if item.tool_name == "sandbox.workspace.status"
    )

    tool_names = {item.tool_name for item in teammate_tool_descriptors(role="executor")}
    assert "sandbox_workspace_id" in descriptor.input_schema["properties"]
    assert {
        "sandbox.file.list",
        "sandbox.file.read",
        "sandbox.file.write",
        "sandbox.file.patch",
        "sandbox.file.delete",
        "sandbox.exec",
    }.issubset(tool_names)
    assert "execution.pipeline.start" not in tool_names
    assert "execution.pipeline.status" not in tool_names
    assert "persistent sandbox workspace" in descriptor.description


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
    assert "storage_uri" not in json.dumps(payload)
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


def test_research_teammate_web_fetch_rejects_rcsb_structure_page() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {"results": []},
        extract_callable=lambda **_: {
            "results": [
                {
                    "title": "RCSB page",
                    "url": "https://www.rcsb.org/structure/4A5T",
                    "raw_content": "RCSB structure page.",
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
            call_id="call_fetch_rcsb",
            tool_name="web.fetch",
            arguments={"url": "https://www.rcsb.org/structure/4A5T"},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.status == "wrong_tool_for_structure_download"
    assert result.error_code == "wrong_tool_for_structure_download"
    assert "rcsb_pdb.download_structure" in result.content
    assert result.details["pdb_id"] == "4A5T"
    assert repositories.invocations.list_by_session(session.session_id) == []


def test_research_teammate_web_fetch_rejects_rcsb_core_rest_metadata() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {"results": []},
        extract_callable=lambda **_: {"results": []},
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
            call_id="call_fetch_rcsb_rest",
            tool_name="web.fetch",
            arguments={"url": "https://data.rcsb.org/rest/v1/core/entry/3QI8"},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.status == "wrong_tool_for_structure_download"
    assert result.details["pdb_id"] == "3QI8"
    assert "rcsb_pdb.download_structure" in result.hint


def test_research_teammate_web_fetch_rejects_rcsb_experimental_page() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {"results": []},
        extract_callable=lambda **_: {"results": []},
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
            call_id="call_fetch_rcsb_experimental",
            tool_name="web.fetch",
            arguments={"url": "https://www.rcsb.org/experimental/7YDL"},
            task_id="task_001",
        ),
    )

    assert result.ok is False
    assert result.status == "wrong_tool_for_structure_download"
    assert result.details["pdb_id"] == "7YDL"
    assert "rcsb_pdb.download_structure" in result.hint


def test_research_teammate_direct_search_provider_429_propagates_runtime_failure() -> None:
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

    with pytest.raises(RuntimeError, match="HTTP Error 429"):
        registry.dispatch(
            context,
            ToolInvocation(
                call_id="call_semantic",
                tool_name="semantic_scholar.search",
                arguments={"query": "AI systems engineering", "limit": 3},
                task_id="task_001",
            ),
        )

    assert repositories.invocations.list_by_session(session.session_id) == []


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
            assigned_ref=None,
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

    assert delegation["agent"]["agent_id"].startswith("agent:researcher:")
    assert delegation["agent"]["nickname"] == "Ada"
    assert delegation["agent"]["handle"] == "@ada"
    assert delegation["latest_correlation_id"] is not None
    assert delegation["thread_summaries"][0]["status"] == "waiting"


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


def test_tool_router_exposes_descriptor_spec_and_dispatches_legacy_handler() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()

    def echo_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        assert context.snapshot.session.session_id == session.session_id
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=f"echo:{invocation.arguments['value']}",
            status="ok",
            summary="echoed",
        )

    registry.register("example.echo", echo_handler)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    descriptor = ToolDescriptor(
        tool_name="example.echo",
        description="Echo a value.",
        input_schema={
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": False,
        },
    )

    router = registry.to_tool_router(context, descriptors=(descriptor,))
    pre_step = build_agent_step_context(context, call_index=1)
    specs = router.model_visible_specs(pre_step)
    step_context = build_agent_step_context(
        context,
        call_index=1,
        tool_specs=specs,
    )

    assert [spec.tool_name for spec in specs] == ["example.echo"]
    assert specs[0].to_openai_tool() == descriptor.to_openai_tool()
    assert step_context.tool_catalog_digest is not None
    assert step_context.tool_catalog_digest.startswith("sha256:")
    result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_echo",
            tool_name="example.echo",
            arguments={"value": "ok"},
        ),
    )
    assert result.ok is True
    assert result.content == "echo:ok"

    unknown = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_missing",
            tool_name="example.missing",
            arguments={},
        ),
    )
    assert unknown.ok is False
    assert unknown.status == "unknown_tool"


def test_legacy_tool_runtime_uses_conservative_governance_defaults() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    registry.register("example.echo", lambda _context, _invocation: "ok")
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    descriptor = ToolDescriptor(
        tool_name="example.echo",
        description="Echo a value.",
        input_schema={"type": "object", "properties": {}},
    )

    router = registry.to_tool_router(context, descriptors=(descriptor,))
    step_context = build_agent_step_context(context, call_index=1)
    governance = router.governance(step_context, "example.echo")

    assert governance is not None
    assert governance.role_scope == ()
    assert governance.supports_parallel is False
    assert governance.side_effect is ToolSideEffect.WRITE
    assert governance.approval_required is False


def test_tool_registry_register_runtime_coexists_with_legacy_and_typed_wins() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    registry.register("example.legacy", lambda _context, _invocation: "legacy-only")
    registry.register("example.dupe", lambda _context, _invocation: "legacy-dupe")

    class TypedRuntime:
        tool_name = "example.dupe"

        def spec(self, step_context):
            del step_context
            return ToolDescriptor(
                tool_name=self.tool_name,
                description="Typed duplicate runtime.",
                input_schema={"type": "object", "properties": {}},
            ).to_tool_spec()

        def is_visible(self, step_context):
            del step_context
            return True

        def governance(self, step_context):
            del step_context
            return ToolGovernance(side_effect=ToolSideEffect.READ)

        def validate(self, step_context, invocation):
            del step_context, invocation
            return None

        def dispatch(self, step_context, invocation, runtime_context):
            del step_context, runtime_context
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=True,
                content="typed-dupe",
                status="ok",
            )

    registry.register_runtime(TypedRuntime())
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    descriptors = (
        ToolDescriptor(
            tool_name="example.legacy",
            description="Legacy only.",
            input_schema={"type": "object", "properties": {}},
        ),
        ToolDescriptor(
            tool_name="example.dupe",
            description="Legacy duplicate descriptor.",
            input_schema={"type": "object", "properties": {}},
        ),
    )
    router = registry.to_tool_router(context, descriptors=descriptors)
    step_context = build_agent_step_context(context, call_index=1)
    specs = {spec.tool_name: spec for spec in router.model_visible_specs(step_context)}
    legacy = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_legacy",
            tool_name="example.legacy",
            arguments={},
        ),
    )
    dupe = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_dupe",
            tool_name="example.dupe",
            arguments={},
        ),
    )

    assert specs["example.dupe"].description == "Typed duplicate runtime."
    assert specs["example.legacy"].description == "Legacy only."
    assert router.governance(step_context, "example.dupe").side_effect is ToolSideEffect.READ
    assert legacy.content == "legacy-only"
    assert dupe.content == "typed-dupe"


class RoleScopedRuntime:
    def __init__(self) -> None:
        self.dispatched = False

    def spec(self, step_context):
        del step_context
        return ToolDescriptor(
            tool_name="example.scoped",
            description="Scoped tool.",
            input_schema={"type": "object", "properties": {}},
        ).to_tool_spec()

    def is_visible(self, step_context):
        del step_context
        return True

    def governance(self, step_context):
        del step_context
        return ToolGovernance(
            role_scope=("researcher",),
            supports_parallel=True,
            side_effect=ToolSideEffect.READ,
            approval_required=False,
            result_budget_policy="compact",
        )

    def validate(self, step_context, invocation):
        del step_context, invocation
        return None

    def dispatch(self, step_context, invocation, runtime_context):
        del step_context, runtime_context
        self.dispatched = True
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content="visible",
            status="ok",
        )


def test_tool_router_dispatches_only_visible_tools() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    runtime = RoleScopedRuntime()
    registry = ToolRegistry()
    registry.register_runtime("example.scoped", runtime)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    router = registry.to_tool_router(context)
    master_step = build_agent_step_context(context, call_index=1)

    assert router.model_visible_specs(master_step) == ()
    hidden = router.dispatch(
        master_step,
        ToolInvocation(
            call_id="call_hidden",
            tool_name="example.scoped",
            arguments={},
        ),
    )

    assert hidden.ok is False
    assert hidden.status == "tool_not_visible"
    assert runtime.dispatched is False

    context.actor_kind = "teammate"
    context.actor_role = "researcher"
    researcher_step = build_agent_step_context(context, call_index=2)
    assert [spec.tool_name for spec in router.model_visible_specs(researcher_step)] == [
        "example.scoped"
    ]
    visible = router.dispatch(
        researcher_step,
        ToolInvocation(
            call_id="call_visible",
            tool_name="example.scoped",
            arguments={},
        ),
    )
    assert visible.ok is True
    assert runtime.dispatched is True


def test_tool_router_validates_required_and_enum_schema_before_dispatch() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    dispatched: list[dict[str, object]] = []

    def handler(_context: SessionRuntimeContext, invocation: ToolInvocation) -> str:
        dispatched.append(invocation.arguments)
        return "ok"

    registry.register("example.validate", handler)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    descriptor = ToolDescriptor(
        tool_name="example.validate",
        description="Validate arguments.",
        input_schema={
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "mode": {"type": "string", "enum": ["fast", "careful"]},
            },
            "required": ["name", "mode"],
            "additionalProperties": False,
        },
    )
    router = registry.to_tool_router(context, descriptors=(descriptor,))
    step_context = build_agent_step_context(context, call_index=1)

    missing = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_missing",
            tool_name="example.validate",
            arguments={"mode": "fast"},
        ),
    )
    invalid_enum = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_enum",
            tool_name="example.validate",
            arguments={"name": "x", "mode": "slow"},
        ),
    )
    valid = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_valid",
            tool_name="example.validate",
            arguments={"name": "x", "mode": "fast"},
        ),
    )

    assert missing.status == "invalid_tool_arguments"
    assert missing.details == {"missing": ["name"]}
    assert invalid_enum.status == "invalid_tool_arguments"
    assert invalid_enum.details == {
        "field": "mode",
        "value": "slow",
        "allowed": ["fast", "careful"],
    }
    assert valid.ok is True
    assert dispatched == [{"name": "x", "mode": "fast"}]


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
    assert "diagnostic_request" not in prompt
    assert "delegated work fails or returns an unclear result" in prompt
    assert "protocol.thread(correlation_id)" in prompt
    assert "Completed/failed/blocked delegated tasks:" in prompt
    assert "Protocol threads available via protocol.thread:" in prompt
    assert "Teammate agents are internal workers" in prompt
    assert "fpocket" in prompt
    assert 'docs.read doc_id="aox-hmm-live"' in prompt
    assert "controlled SDK recipe" in prompt
    assert "ClustalW" in prompt
    assert "MUSCLE" in prompt
    assert "direct MAFFT/CD-HIT/HMMER binaries" in prompt
    assert "synthetic hits" in prompt


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
    agent = _seed_agent(repositories, session, role="executor")
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
            assigned_ref=agent.agent_id,
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
    model_factory = FakeModelFactory(
        {
            "content": "Approval resolution was recorded for scheduler follow-up.",
            "tool_calls": [],
        }
    )

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
        "Approval resolution was recorded for scheduler follow-up.",
    )
    assert result.tool_results == ()
    assert model_factory.invokers["v3_harness_loop"].calls
    assert (
        repositories.approvals.get("appr_execution_resume").status
        is ApprovalRequestStatus.APPROVED
    )


def test_resume_without_executor_tool_does_not_report_internal_continuation() -> None:
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

    model_factory = FakeModelFactory({"content": "", "tool_calls": []})
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
        driver=LlmConversationDriver(model_factory),
        engine_registry=engine_registry,
    )

    assert result.status is HarnessStatus.COMPLETED
    assert result.outputs == ()
    assert result.tool_results == ()
    assert model_factory.invokers["v3_harness_loop"].calls


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


def test_master_driver_passes_canonical_tool_specs_to_invoker() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    model_factory = FakeModelFactory({"content": "I can help.", "tool_calls": []})

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="plan"),
        driver=LlmConversationDriver(model_factory),
    )

    assert result.status is HarnessStatus.COMPLETED
    tools = model_factory.invokers["v3_harness_loop"].calls[0]["tools"]
    assert tools
    assert all(isinstance(tool, ToolSpec) for tool in tools)
    assert "task.create" in {tool.tool_name for tool in tools}


@pytest.mark.parametrize("role", ["researcher", "executor", "reporter"])
def test_teammate_driver_passes_canonical_tool_specs_to_invoker(role: str) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(repositories, session, role=role)
    model_factory = FakeModelFactory({"content": "done", "tool_calls": []})
    driver = TeammateConversationDriver(
        model_factory=model_factory,
        role=role,
        agent_id=agent.agent_id,
        correlation_id=f"corr_{role}",
        task_id="task_001",
        instructions="Complete the assigned task.",
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            sender=agent.agent_id,
            sender_kind=InboxParticipantKind.AGENT,
            persist_conversation=False,
        ),
        driver=driver,
    )

    assert result.status is HarnessStatus.COMPLETED
    tools = model_factory.invokers[f"v3_teammate_loop:{role}"].calls[0]["tools"]
    assert tools
    assert all(isinstance(tool, ToolSpec) for tool in tools)
    assert "task.update" in {tool.tool_name for tool in tools}


def _message_tool_names(messages: list[object]) -> set[str]:
    names: set[str] = set()
    for message in messages:
        if isinstance(message, dict):
            if isinstance(message.get("name"), str):
                names.add(str(message["name"]))
            for tool_call in message.get("tool_calls") or []:
                if isinstance(tool_call, dict) and isinstance(
                    tool_call.get("name"), str
                ):
                    names.add(str(tool_call["name"]))
            continue
        if hasattr(message, "name"):
            name = getattr(message, "name")
            if isinstance(name, str):
                names.add(name)
        for tool_call in getattr(message, "tool_calls", None) or []:
            if isinstance(tool_call, dict) and isinstance(tool_call.get("name"), str):
                names.add(str(tool_call["name"]))
    return names


def test_micu_provider_alias_restores_canonical_names_before_harness_dispatch() -> None:
    get_llm_debug_recorder().clear()

    class MicuAliasModelFactory:
        def __init__(self) -> None:
            self.provider_invocations = 0
            self.bound_tool_names: list[list[str]] = []

        def create_tool_calling_invoker(
            self, *, purpose: str
        ) -> LangChainToolCallingInvoker:
            factory = self

            class _Runnable:
                def invoke(self, messages):
                    if factory.provider_invocations == 0:
                        factory.provider_invocations += 1
                        return {
                            "content": "",
                            "tool_calls": [
                                {
                                    "id": "call_task",
                                    "name": "task_create",
                                    "args": {"subject": "Canonical task"},
                                }
                            ],
                        }
                    assert "task_create" in _message_tool_names(list(messages))
                    factory.provider_invocations += 1
                    return {"content": "created canonical task", "tool_calls": []}

            class _Model:
                def bind_tools(self, tools):
                    factory.bound_tool_names.append(
                        [tool["function"]["name"] for tool in tools]
                    )
                    return _Runnable()

            return LangChainToolCallingInvoker(
                model=_Model(),
                purpose=purpose,
                model_name="debug-model",
                base_url="https://www.micuapi.ai/v1",
                dotted_tool_name_aliasing=True,
            )

    repositories = _build_repositories()
    session = _seed_session(repositories)
    model_factory = MicuAliasModelFactory()

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="create a task"),
        driver=LlmConversationDriver(model_factory),
    )

    assert result.status is HarnessStatus.COMPLETED
    assert model_factory.provider_invocations == 2
    assert all("task_create" in names for names in model_factory.bound_tool_names)
    assert result.tool_results[0].tool_name == "task.create"
    tool_events = [
        event
        for event in result.events
        if event.event_type in {"tool.invoked", "tool.completed"}
    ]
    assert {event.payload["tool_name"] for event in tool_events} == {"task.create"}

    trace_documents = [
        document
        for document in repositories.engine_documents.list_by_session(session.session_id)
        if document.document_kind == "llm_trace_step"
    ]
    trace_with_tool = next(
        document for document in trace_documents if document.payload["tool_calls"]
    )
    assert trace_with_tool.payload["tool_calls"][0]["tool_name"] == "task.create"

    workspace = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(session.session_id)
        .to_dict()
    )
    workspace_text = json.dumps(workspace, sort_keys=True)
    assert "task.create" in workspace_text
    assert "task_create" not in workspace_text

    records = get_llm_debug_recorder().list_records(
        limit=10,
        purpose="v3_harness_loop",
        kind="tool_calling",
    )
    tool_call_record = next(
        record for record in records if record["response"].get("tool_calls")
    )
    provider_tool_names = {
        tool["function"]["name"] for tool in tool_call_record["request"]["tools"]
    }
    assert "artifact_list" in provider_tool_names
    assert "task_create" in provider_tool_names
    assert (
        tool_call_record["request"]["tool_name_aliases"]["task.create"]
        == "task_create"
    )
    assert tool_call_record["response"]["tool_calls"][0]["name"] == "task.create"


def test_harness_loop_persists_master_llm_trace_and_public_tool_args() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    repositories.lanes.save(
        Lane(
            lane_id="lane_private",
            session_id=session.session_id,
            name="private",
            status=LaneStatus.CLAIMED,
            cwd="/home/user/private/workspace",
            branch_name="wt/private",
            claimed_ref="agent:primary",
            created_at="2026-04-17T09:03:00+00:00",
            updated_at="2026-04-17T09:03:00+00:00",
        )
    )
    repositories.memory.save(
        MemoryEntry(
            memory_id="mem_private",
            session_id=session.session_id,
            scope_kind=MemoryScopeKind.SESSION,
            scope_ref=session.session_id,
            kind=MemoryKind.CONTINUITY,
            summary="top-secret continuity from storage://private/session",
            source_range="/home/user/private/notes.md",
            importance=9,
            created_at="2026-04-17T09:03:10+00:00",
        )
    )
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
                            "secret_token": "abc123",
                            "local_path": "/home/user/private/input.pdb",
                            "pipeline_code": "print('private')",
                        },
                    },
                ],
            }
        )
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="plan work", max_steps=1),
        driver=driver,
    )

    assert result.status is HarnessStatus.MAX_STEPS_EXCEEDED
    assert any(event.event_type == "llm.response.created" for event in result.events)
    documents = [
        document
        for document in repositories.engine_documents.list_by_session(session.session_id)
        if document.document_kind == "llm_trace_step"
    ]
    assert len(documents) == 1
    payload = documents[0].payload
    assert payload["actor_ref"] == "harness"
    assert payload["actor_kind"] == "master"
    assert payload["tool_calls"][0]["tool_name"] == "task.create"
    args_public = payload["tool_calls"][0]["args_public"]
    assert args_public["task_id"] == "task_002"
    assert args_public["secret_token"] == "[redacted]"
    assert args_public["local_path"] == "[redacted]"
    assert args_public["pipeline_code"] == "[redacted]"
    assert payload["step_id"].startswith("agentstep_")
    assert payload["tool_catalog_digest"].startswith("sha256:")
    assert payload["restore_context_digest"].startswith("sha256:")
    assert payload["projection_schema_version"] == "v1"
    assert payload["agent_step"]["agent_id"] == "harness"
    assert payload["agent_step"]["actor_kind"] == "master"
    assert payload["agent_step"]["role"] == "master"
    assert payload["agent_step"]["call_index"] == 1
    assert payload["agent_step"]["tool_catalog_digest"] == payload["tool_catalog_digest"]
    assert (
        payload["agent_step"]["restore_context_digest"]
        == payload["restore_context_digest"]
    )
    payload_text = json.dumps(payload, sort_keys=True)
    assert "/home/user/private" not in payload_text
    assert "abc123" not in payload_text
    assert "top-secret" not in payload_text
    assert "storage://private" not in payload_text

    workspace = (
        SessionProjectionBuilder(repositories)
        .build_session_workspace(session.session_id)
        .to_dict()
    )
    projected = workspace["agent_traces"]["harness"][0]
    assert projected["step_id"] == payload["step_id"]
    assert projected["tool_catalog_digest"] == payload["tool_catalog_digest"]
    assert projected["restore_context_digest"] == payload["restore_context_digest"]


def test_teammate_loop_persists_trace_without_prompt_payload() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(repositories, session, role="researcher")
    driver = TeammateConversationDriver(
        model_factory=FakeModelFactory({"content": "I inspected the task.", "tool_calls": []}),
        role="researcher",
        agent_id=agent.agent_id,
        correlation_id="corr_001",
        task_id="task_001",
        instructions="Inspect the literature plan.",
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            sender=agent.agent_id,
            sender_kind=InboxParticipantKind.AGENT,
            persist_conversation=False,
        ),
        driver=driver,
    )

    assert result.outputs == ("I inspected the task.",)
    workspace = SessionProjectionBuilder(repositories).build_session_workspace(session.session_id).to_dict()
    traces = workspace["agent_traces"][agent.agent_id]
    assert traces[0]["actor_kind"] == "teammate"
    assert traces[0]["actor_ref"] == agent.agent_id
    assert traces[0]["display_name"] == display_name_for_agent(agent)
    assert traces[0]["agent_step"]["agent_id"] == agent.agent_id
    assert traces[0]["agent_step"]["actor_kind"] == "teammate"
    assert traces[0]["agent_step"]["role"] == "researcher"
    assert traces[0]["agent_step"]["correlation_id"] == "corr_001"
    assert traces[0]["response_text"] == "I inspected the task."
    assert traces[0]["projection_schema_version"] == "v1"
    assert "initial_prompt" not in traces[0]


def test_executor_prompt_uses_docs_driven_execution_contract() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(repositories, session, role="executor")
    model_factory = FakeModelFactory(
        {"content": "I inspected the execution task.", "tool_calls": []}
    )
    driver = TeammateConversationDriver(
        model_factory=model_factory,
        role="executor",
        agent_id=agent.agent_id,
        correlation_id="corr_001",
        task_id="task_001",
        instructions="Run the assigned computational execution.",
    )

    run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            sender=agent.agent_id,
            sender_kind=InboxParticipantKind.AGENT,
            persist_conversation=False,
        ),
        driver=driver,
    )

    prompt = str(
        model_factory.invokers["v3_teammate_loop:executor"].calls[0][
            "system_prompt"
        ]
    )
    assert "when the assigned task asks for fpocket" not in prompt
    assert "runner-backed hpc tool shorthand" not in prompt
    assert "first use docs.search or docs.read" in prompt
    assert "sandbox.workspace.status" in prompt
    assert "Author source with sandbox.file.* and run it with sandbox.exec" in prompt
    assert "Host-supervised SDK from inside that sandbox run" in prompt
    assert "Do not treat execution.pipeline.start as the required authoring path" in prompt
    assert 'docs.read doc_id="aox-hmm-live"' in prompt
    assert "fixed aox_hmm/* deliverables are registered" in prompt
    assert "never substitute sandbox-local pseudo-HMMs" in prompt
    assert "direct provider raw-file parsing" in prompt


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


def test_master_driver_routes_missing_delegate_task_id_to_router_validation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    driver = LlmConversationDriver(
        FakeModelFactory(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate",
                            "name": "task.delegate",
                            "args": {"agent_role": "researcher"},
                        },
                    ],
                },
                {"content": "handled invalid delegate", "tool_calls": []},
            ]
        )
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="start research"),
        driver=driver,
    )

    assert result.outputs == ("handled invalid delegate",)
    assert result.tool_results[0].status == "invalid_tool_arguments"
    assert "without task_id" in result.tool_results[0].content


def test_master_driver_routes_missing_delegate_role_to_router_validation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    driver = LlmConversationDriver(
        FakeModelFactory(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate",
                            "name": "task.delegate",
                            "args": {"task_id": "task_001"},
                        },
                    ],
                },
                {"content": "handled invalid delegate", "tool_calls": []},
            ]
        )
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="delegate task"),
        driver=driver,
    )

    assert result.outputs == ("handled invalid delegate",)
    assert result.tool_results[0].status == "invalid_tool_arguments"
    assert "without agent_role" in result.tool_results[0].content


def test_master_driver_routes_invalid_delegate_role_to_router_validation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    driver = LlmConversationDriver(
        FakeModelFactory(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_delegate",
                            "name": "task.delegate",
                            "args": {"task_id": "task_001", "agent_role": "worker"},
                        },
                    ],
                },
                {"content": "handled invalid delegate", "tool_calls": []},
            ]
        )
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="delegate task"),
        driver=driver,
    )

    assert result.outputs == ("handled invalid delegate",)
    assert result.tool_results[0].status == "invalid_tool_arguments"
    assert "invalid agent_role" in result.tool_results[0].content


def test_master_driver_does_not_prevalidate_unknown_tool_availability() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    driver = LlmConversationDriver(
        FakeModelFactory(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_unknown",
                            "name": "unknown.tool",
                            "args": {},
                        },
                    ],
                },
                {"content": "handled unknown tool", "tool_calls": []},
            ]
        )
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="use unknown tool"),
        driver=driver,
    )

    assert result.outputs == ("handled unknown tool",)
    assert result.tool_results[0].status == "unknown_tool"


def test_tool_router_dispatch_rejects_provider_alias_names() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    registry = ToolRegistry()
    register_task_board_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
        active_skill_keys=(),
        skill_registry=SkillRegistry(),
    )
    context.refresh_restore_context()
    router = context.tool_registry.to_tool_router(
        context,
        descriptors=top_level_tool_descriptors(None),
    )
    step_context = build_agent_step_context(
        context,
        call_index=1,
        tool_specs=router.model_visible_specs(build_agent_step_context(context, call_index=1)),
    )

    result = router.dispatch(
        step_context,
        ToolInvocation(call_id="call_alias", tool_name="task_create", arguments={}),
    )

    assert result.status == "unknown_tool"
    assert result.tool_name == "task_create"
    canonical_result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_canonical",
            tool_name="task.create",
            arguments={"subject": "canonical task"},
        ),
    )
    assert canonical_result.ok is True
    assert canonical_result.tool_name == "task.create"


def test_teammate_driver_uses_router_schema_validation() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_agent(repositories, session, role="researcher")
    driver = TeammateConversationDriver(
        model_factory=FakeModelFactory(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "call_update",
                            "name": "task.update",
                            "args": {"status": "in_progress"},
                        },
                    ],
                },
                {"content": "handled invalid teammate tool", "tool_calls": []},
            ]
        ),
        role="researcher",
        agent_id=agent.agent_id,
        correlation_id="corr_validation",
        task_id="task_001",
        instructions="Complete the assigned task.",
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(
            session_id=session.session_id,
            sender=agent.agent_id,
            sender_kind=InboxParticipantKind.AGENT,
            persist_conversation=False,
        ),
        driver=driver,
    )

    assert result.outputs == ("handled invalid teammate tool",)
    assert result.tool_results[0].status == "invalid_tool_arguments"
    assert result.tool_results[0].details == {"missing": ["task_id"]}


def test_tool_events_include_step_and_governance_metadata() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    driver = LlmConversationDriver(
        FakeModelFactory(
            [
                {
                    "content": "",
                    "tool_calls": [
                        {"id": "call_list", "name": "task.list", "args": {}},
                    ],
                },
                {"content": "listed tasks", "tool_calls": []},
            ]
        )
    )

    result = run_agent_harness_loop(
        repositories,
        HarnessInput(session_id=session.session_id, message="list tasks"),
        driver=driver,
    )

    invoked = next(event for event in result.events if event.event_type == "tool.invoked")
    completed = next(
        event for event in result.events if event.event_type == "tool.completed"
    )
    assert invoked.payload["step_id"].startswith("agentstep_")
    assert invoked.payload["agent_id"] == "harness"
    assert invoked.payload["actor_kind"] == "master"
    assert invoked.payload["role"] == "master"
    assert invoked.payload["call_index"] == 1
    assert invoked.payload["tool_catalog_digest"].startswith("sha256:")
    assert invoked.payload["restore_context_digest"].startswith("sha256:")
    assert invoked.payload["side_effect"] == "write"
    assert invoked.payload["supports_parallel"] is False
    assert completed.payload["step_id"] == invoked.payload["step_id"]
    assert completed.payload["agent_id"] == "harness"
    assert completed.payload["actor_kind"] == "master"
    assert completed.payload["role"] == "master"
    assert completed.payload["call_index"] == 1
    assert completed.payload["task_id"] is None
    assert completed.payload["lane_id"] is None
    assert completed.payload["side_effect"] == "write"
    assert completed.payload["supports_parallel"] is False
    assert completed.payload["ok"] is True
    assert completed.payload["status"] == "ok"
    assert completed.payload["error_code"] is None
    assert "content" not in completed.payload
    assert "result" not in completed.payload


def test_llm_conversation_driver_returns_tool_invocation_for_missing_delegate_task_id() -> (
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

    assert step.assistant_message is None
    assert len(step.tool_invocations) == 1
    assert step.tool_invocations[0].tool_name == "task.delegate"
    assert step.tool_invocations[0].arguments == {"agent_role": "researcher"}
