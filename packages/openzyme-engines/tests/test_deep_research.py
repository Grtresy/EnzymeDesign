from __future__ import annotations

import json

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import build_agent_step_context
from openzyme_core import connect_sqlite
from openzyme_core import engine_tool_descriptors
from openzyme_core import EngineRegistry
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import SourceRefKind
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_engines import DeepResearchEngine
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft
from openzyme_engines import ResearchDossier
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchTurnRecord
from openzyme_engines import ResearchUnitDraft
from openzyme_engines import ResearchUnitPlan
from openzyme_engines import NativeDeepResearchRunner
from openzyme_engines import register_deep_research_tools
from openzyme_engines.deep_research_graph import DeepResearchGraphInputs
from openzyme_engines.deep_research_graph import DefaultResearchGraphSettings
from openzyme_engines.deep_research_graph import build_deep_research_subgraph
from openzyme_engines.deep_research_graph import _select_tool_calls_for_budget
from openzyme_runtime import get_llm_debug_recorder
from openzyme_runtime import LangChainToolCallingInvoker
from openzyme_runtime import ToolSpec
from openzyme_runtime import ToolSideEffect
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnitResult


class RecordingSessionRuntimeContext(SessionRuntimeContext):
    __slots__ = ("workspace_files",)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.workspace_files: dict[str, dict] = {}

    def write_workspace_json(
        self,
        *,
        repository_path: str,
        payload: dict,
    ) -> dict[str, object]:
        self.workspace_files[repository_path] = payload
        encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
        return {
            "schema_version": "workspace_file_write_result@1",
            "workspace_id": "workspace_test",
            "workspace_generation": 1,
            "repository_path": repository_path,
            "size_bytes": len(encoded),
            "content_digest": "sha256:" + "a" * 64,
            "publication_required": True,
            "commit_performed": False,
            "publication_performed": False,
        }


class FailingWorkspaceSessionRuntimeContext(RecordingSessionRuntimeContext):
    __slots__ = ("write_calls",)

    def __init__(self, *args, **kwargs) -> None:
        super().__init__(*args, **kwargs)
        self.write_calls = 0

    def write_workspace_json(
        self,
        *,
        repository_path: str,
        payload: dict,
    ) -> dict[str, object]:
        self.write_calls += 1
        if self.write_calls == 3:
            raise RuntimeError("injected workspace write failure")
        return super().write_workspace_json(
            repository_path=repository_path,
            payload=payload,
        )


class CapturingDeepResearchInvoker:
    def __init__(self, factory: "CapturingDeepResearchModelFactory", purpose: str) -> None:
        self._factory = factory
        self._purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict):
        self._factory.calls.append(self._purpose)
        self._factory.prompts[self._purpose] = system_prompt
        self._factory.payloads[self._purpose] = user_payload
        if schema is ResearchBriefDraft:
            return ResearchBriefDraft(research_brief="thermostability evidence")
        if schema is ResearchSupervisorAction:
            return ResearchSupervisorAction(
                action_kind="complete",
                rationale="A usable finding already exists.",
            )
        if schema is EvidenceSynthesis:
            return EvidenceSynthesis(
                summary="Existing finding is enough for downstream design.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Existing finding supports the scaffold.",
                        query="thermostability",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Existing source",
                                locator="https://example.org/existing",
                                kind="web_page",
                            )
                        ],
                    )
                ],
                unresolved_gaps=[],
            )
        raise AssertionError(f"Unexpected schema {schema}")


class CapturingDeepResearchModelFactory:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}
        self.payloads: dict[str, dict] = {}

    def create_structured_invoker(self, *, purpose: str) -> CapturingDeepResearchInvoker:
        return CapturingDeepResearchInvoker(self, purpose)


class FailingSynthesisInvoker(CapturingDeepResearchInvoker):
    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict):
        if schema is EvidenceSynthesis:
            self._factory.calls.append(self._purpose)
            self._factory.prompts[self._purpose] = system_prompt
            self._factory.payloads[self._purpose] = user_payload
            raise RuntimeError("synthesis provider exploded")
        return super().invoke_structured(
            schema=schema,
            system_prompt=system_prompt,
            user_payload=user_payload,
        )


class FailingSynthesisModelFactory(CapturingDeepResearchModelFactory):
    def create_structured_invoker(self, *, purpose: str) -> CapturingDeepResearchInvoker:
        if purpose == "deep_research_synthesis":
            return FailingSynthesisInvoker(self, purpose)
        return super().create_structured_invoker(purpose=purpose)


class InvalidToolCallInvoker:
    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages, tools
        return {
            "tool_calls": [
                {
                    "name": "web.search",
                    "id": "invalid-web-search",
                    "args": {"topic": "general"},
                }
            ]
        }


class ValidToolCallInvoker:
    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages, tools
        return {
            "tool_calls": [
                {
                    "name": "web.search",
                    "id": "valid-web-search",
                    "args": {"query": "thermostability evidence", "topic": "general"},
                }
            ]
        }


class OverBudgetToolCallInvoker:
    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages, tools
        return {
            "tool_calls": [
                {
                    "name": "pubmed.search",
                    "id": "pubmed-first",
                    "args": {"query": "thermostability evidence"},
                },
                {
                    "name": "web.search",
                    "id": "web-second",
                    "args": {"query": "thermostability evidence", "topic": "general"},
                },
            ]
        }


class InvalidToolCallModelFactory:
    def create_structured_invoker(self, *, purpose: str):
        class StructuredInvoker:
            def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict):
                del system_prompt, user_payload
                if schema is ResearchBriefDraft:
                    return ResearchBriefDraft(research_brief="thermostability evidence")
                if schema is ResearchSupervisorAction:
                    return ResearchSupervisorAction(
                        action_kind="conduct_research",
                        rationale="Collect one unit.",
                        unit_plan=ResearchUnitPlan(
                            units=[
                                ResearchUnitDraft(
                                    unit_id="invalid_args",
                                    topic="supporting evidence",
                                    query="thermostability evidence",
                                    rationale="Exercise validation observations.",
                                )
                            ],
                            synthesis_goal="Exercise validation observations.",
                        ),
                    )
                raise AssertionError(f"Unexpected schema {schema}")

        del purpose
        return StructuredInvoker()

    def create_tool_calling_invoker(self, *, purpose: str) -> InvalidToolCallInvoker:
        del purpose
        return InvalidToolCallInvoker()


class ValidToolCallModelFactory(InvalidToolCallModelFactory):
    def create_tool_calling_invoker(self, *, purpose: str) -> ValidToolCallInvoker:
        del purpose
        return ValidToolCallInvoker()


class OverBudgetToolCallModelFactory(InvalidToolCallModelFactory):
    def create_tool_calling_invoker(self, *, purpose: str) -> OverBudgetToolCallInvoker:
        del purpose
        return OverBudgetToolCallInvoker()


class SingleSearchToolCallInvoker:
    def __init__(self, factory: "CompletingGraphModelFactory") -> None:
        self._factory = factory

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages
        assert all(isinstance(tool, ToolSpec) for tool in tools)
        assert "web.search" in {tool.tool_name for tool in tools}
        self._factory.calls.append("deep_research_researcher")
        if self._factory.tool_call_count:
            return {"content": "Search complete.", "tool_calls": []}
        self._factory.tool_call_count += 1
        return {
            "tool_calls": [
                {
                    "name": "web.search",
                    "id": "valid-web-search",
                    "args": {"query": "thermostability evidence", "topic": "general"},
                }
            ]
        }


class CompletingGraphInvoker:
    def __init__(self, factory: "CompletingGraphModelFactory", purpose: str) -> None:
        self._factory = factory
        self._purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict):
        del system_prompt
        self._factory.calls.append(self._purpose)
        if schema is ResearchBriefDraft:
            return ResearchBriefDraft(research_brief="thermostability evidence")
        if schema is ResearchSupervisorAction:
            if user_payload.get("unit_results"):
                return ResearchSupervisorAction(
                    action_kind="complete",
                    rationale="A usable finding exists.",
                )
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one focused evidence unit.",
                unit_plan=ResearchUnitPlan(
                    units=[
                        ResearchUnitDraft(
                            unit_id="unit_001",
                            topic="thermostability",
                            query="thermostability evidence",
                            rationale="Need one source-backed finding.",
                        )
                    ],
                    synthesis_goal="Summarize thermostability evidence.",
                ),
            )
        if schema is EvidenceSynthesis:
            if self._factory.fail_synthesis:
                raise RuntimeError("synthesis provider exploded")
            finding = user_payload["unit_results"][0]["findings"][0]
            return EvidenceSynthesis(
                summary="Thermostability evidence supports the scaffold.",
                evidence_items=[EvidenceSynthesisItem.model_validate(finding)],
                unresolved_gaps=[],
            )
        raise AssertionError(f"Unexpected schema {schema}")


class CompletingGraphModelFactory:
    def __init__(self, *, fail_synthesis: bool = False) -> None:
        self.fail_synthesis = fail_synthesis
        self.calls: list[str] = []
        self.tool_call_count = 0

    def create_structured_invoker(self, *, purpose: str) -> CompletingGraphInvoker:
        return CompletingGraphInvoker(self, purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> SingleSearchToolCallInvoker:
        del purpose
        return SingleSearchToolCallInvoker(self)


class FakeProviderStatusError(Exception):
    def __init__(self, status_code: int, message: str) -> None:
        super().__init__(message)
        self.status_code = status_code


class RetryingResearcherGraphModelFactory(CompletingGraphModelFactory):
    def __init__(self) -> None:
        super().__init__()
        self.provider_calls = 0

    def create_tool_calling_invoker(self, *, purpose: str):
        factory = self

        class FakeRunnable:
            def invoke(self, messages):
                del messages
                factory.provider_calls += 1
                if factory.provider_calls == 1:
                    raise FakeProviderStatusError(502, "bad gateway")
                factory.calls.append(purpose)
                if factory.tool_call_count:
                    return {"content": "Search complete.", "tool_calls": []}
                factory.tool_call_count += 1
                return {
                    "tool_calls": [
                        {
                            "name": "web.search",
                            "id": "valid-web-search",
                            "args": {
                                "query": "thermostability evidence",
                                "topic": "general",
                            },
                        }
                    ]
                }

        class FakeModel:
            def bind_tools(self, tools):
                del tools
                return FakeRunnable()

        return LangChainToolCallingInvoker(
            model=FakeModel(),
            purpose=purpose,
            max_attempts=2,
            retry_backoff_seconds=0.0,
        )


class ThinkOnlyToolCallInvoker:
    def __init__(self, factory: "NoEvidenceGraphModelFactory") -> None:
        self._factory = factory

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages, tools
        self._factory.calls.append("deep_research_researcher")
        if self._factory.tool_call_count:
            return {"content": "No source-backed evidence found.", "tool_calls": []}
        self._factory.tool_call_count += 1
        return {
            "tool_calls": [
                {
                    "name": "think_tool",
                    "id": "think-no-evidence",
                    "args": {"reflection": "No source-backed findings yet."},
                }
            ]
        }


class NoEvidenceGraphModelFactory(CompletingGraphModelFactory):
    def create_tool_calling_invoker(self, *, purpose: str) -> ThinkOnlyToolCallInvoker:
        del purpose
        return ThinkOnlyToolCallInvoker(self)


class MinimalWebResearchAdapter:
    def web_search(self, **kwargs):
        raise AssertionError(f"provider should not be called for invalid args: {kwargs}")

    def fetch_url(self, **kwargs):
        raise AssertionError(f"provider should not be called for invalid args: {kwargs}")

    def normalize_search_response(self, **kwargs):
        raise AssertionError(f"provider should not be called for invalid args: {kwargs}")

    def normalize_fetch_response(self, **kwargs):
        raise AssertionError(f"provider should not be called for invalid args: {kwargs}")


class RaisingWebResearchAdapter(MinimalWebResearchAdapter):
    def web_search(self, **kwargs):
        del kwargs
        raise RuntimeError("provider exploded")


class FindingWebResearchAdapter(MinimalWebResearchAdapter):
    def web_search(self, **kwargs):
        return {"query": kwargs["query"]}

    def normalize_search_response(self, *, unit, response):
        del response
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary="Found source-backed thermostability evidence.",
            findings=(
                ResearchFinding(
                    summary="A paper reports stabilizing mutations.",
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title="Thermostability paper",
                            locator="https://example.org/thermo",
                            kind=SourceRefKind.PAPER,
                            snippet="Stabilizing mutations improved activity retention.",
                        ),
                    ),
                ),
            ),
        )


class CompletedDeepResearchRunner:
    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> ResearchDossier:
        del invocation_id, objective, design_brief, resolution
        return ResearchDossier(
            status="completed",
            completion_reason="research_completed",
            clarification_question=None,
            research_brief=research_brief,
            summary="Catalytic papers support the selected scaffold family.",
            evidence_items=[
                EvidenceSynthesisItem(
                    summary="Paper evidence supports scaffold family A.",
                    query=research_brief,
                    confidence_label="high",
                    sources=[
                        ResearchSourceItem(
                            title="Paper A",
                            locator="https://example.org/paper-a",
                            kind="paper",
                            snippet="Thermostability signal",
                        )
                    ],
                )
            ],
            unresolved_gaps=["Need wet-lab validation"],
            raw_notes=["focused on scaffold family A"],
            recent_turns=[
                ResearchTurnRecord(
                    turn_index=1,
                    action_kind="conduct_research",
                    status="completed",
                    summary="Collected scaffold family evidence.",
                    rationale="The initial brief was sufficiently specific.",
                    tool_names=["web.search"],
                    observation_summary="One strong paper found.",
                    created_at="2026-04-20T10:05:00+00:00",
                )
            ],
        )


class ClarifyThenCompleteRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, str | None]] = []

    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> ResearchDossier:
        self.calls.append(
            {
                "invocation_id": invocation_id,
                "objective": objective,
                "design_brief": design_brief,
                "research_brief": research_brief,
                "resolution": resolution,
            }
        )
        if resolution is None:
            return ResearchDossier(
                status="needs_clarification",
                completion_reason="clarification_requested",
                clarification_question="Which scaffold family should the search prioritize?",
                research_brief=research_brief,
                summary="Research paused pending a narrower scaffold constraint.",
                evidence_items=[],
                unresolved_gaps=["Need scaffold family clarification."],
                raw_notes=[],
                recent_turns=[
                    ResearchTurnRecord(
                        turn_index=1,
                        action_kind="clarify_scope",
                        status="completed",
                        summary="Clarification required before evidence collection.",
                        rationale="Too many scaffold families remain in scope.",
                        created_at="2026-04-20T10:00:00+00:00",
                    )
                ],
            )
        return ResearchDossier(
            status="completed",
            completion_reason="research_completed",
            clarification_question=None,
            research_brief=research_brief,
            summary="Catalytic papers support the selected scaffold family.",
            evidence_items=[
                EvidenceSynthesisItem(
                    summary="Paper evidence supports scaffold family A.",
                    query=research_brief,
                    confidence_label="high",
                    sources=[
                        ResearchSourceItem(
                            title="Paper A",
                            locator="https://example.org/paper-a",
                            kind="paper",
                            snippet="Thermostability signal",
                        )
                    ],
                )
            ],
            unresolved_gaps=["Need wet-lab validation"],
            raw_notes=["focused on scaffold family A"],
            recent_turns=[
                ResearchTurnRecord(
                    turn_index=2,
                    action_kind="conduct_research",
                    status="completed",
                    summary="Collected scaffold family evidence.",
                    rationale="Resolution narrowed the search space.",
                    tool_names=["web.search"],
                    observation_summary="One strong paper found.",
                    created_at="2026-04-20T10:05:00+00:00",
                )
            ],
        )


class CompletedWithFileRunner:
    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> ResearchDossier:
        del objective, design_brief, resolution
        return ResearchDossier(
            status="completed",
            completion_reason="research_completed",
            clarification_question=None,
            research_brief=research_brief,
            summary="Research completed with one downloaded structure.",
            evidence_items=[],
            unresolved_gaps=[],
            files=[
                {
                    "external_id": "1ABC",
                    "provider": "rcsb_pdb",
                    "kind": "structure",
                    "format": "pdb",
                    "filename": "1ABC.pdb",
                    "title": "1ABC structure file",
                    "description": "Downloaded structure file from RCSB PDB.",
                    "source_locator": "https://files.rcsb.org/download/1ABC.pdb",
                    "metadata": {"pdb_id": "1ABC"},
                }
            ],
            raw_notes=[invocation_id],
            recent_turns=[],
        )


class RaisingDeepResearchRunner:
    def run(
        self,
        *,
        invocation_id: str,
        objective: str,
        design_brief: str,
        research_brief: str,
        resolution: str | None,
    ) -> ResearchDossier:
        del invocation_id, objective, design_brief, research_brief, resolution
        raise FakeProviderStatusError(400, "invalid request")


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Research",
        objective="Collect evidence",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-20T12:00:00+00:00",
        updated_at="2026-04-20T12:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Collect evidence",
            description="Run deep research",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:planner",
            created_at="2026-04-20T12:00:01+00:00",
            updated_at="2026-04-20T12:00:01+00:00",
        )
    )
    return session


def _researcher_step(context: SessionRuntimeContext):
    context.agent_id = "agent:researcher"
    context.actor_kind = "teammate"
    context.actor_role = "researcher"
    router = context.tool_registry.to_tool_router(context)
    step_context = build_agent_step_context(context, call_index=1)
    return router, step_context


def _build_graph_inputs(
    *,
    model_factory: object | None,
    research_adapter: object | None = None,
    llm_synthesis_enabled: bool = False,
) -> DeepResearchGraphInputs:
    return DeepResearchGraphInputs(
        session_id="sess_001",
        project_id="proj_001",
        research_adapter=research_adapter,
        research_tool_provider=None,
        model_factory=model_factory,
        limiter_registry=None,
        settings=DefaultResearchGraphSettings(
            allow_clarification=False,
            max_research_iterations=1,
            max_react_tool_calls=1,
            max_concurrent_research_units=1,
            llm_synthesis_enabled=llm_synthesis_enabled,
        ),
    )


def _invoke_deep_research_graph(inputs: DeepResearchGraphInputs) -> dict:
    graph = build_deep_research_subgraph(inputs)
    return graph.invoke(
        {
            "session_id": "sess_001",
            "project_id": "proj_001",
            "objective": "Investigate thermostability approaches with cited evidence.",
            "design_brief": "Find enough evidence to support downstream enzyme design.",
            "research_brief": "thermostability evidence",
        }
    )


def test_deep_research_graph_without_model_factory_propagates_runtime_failure() -> None:
    with pytest.raises(RuntimeError, match="model factory"):
        _invoke_deep_research_graph(
            _build_graph_inputs(model_factory=None, research_adapter=MinimalWebResearchAdapter())
        )


def test_deep_research_graph_tool_validation_error_returns_observation() -> None:
    result = _invoke_deep_research_graph(
        _build_graph_inputs(
            model_factory=InvalidToolCallModelFactory(),
            research_adapter=MinimalWebResearchAdapter(),
        )
    )

    dossier = result["research_dossier"]
    assert dossier["status"] == "partial"
    assert "Tool web.search received invalid arguments." in dossier["unresolved_gaps"]
    assert any(
        turn["action_kind"] == "web.search" and turn["status"] == "failed"
        for turn in dossier["recent_turns"]
    )


def test_deep_research_graph_provider_exception_propagates_runtime_failure() -> None:
    with pytest.raises(RuntimeError, match="provider exploded"):
        _invoke_deep_research_graph(
            _build_graph_inputs(
                model_factory=ValidToolCallModelFactory(),
                research_adapter=RaisingWebResearchAdapter(),
            )
        )


def test_deep_research_graph_truncates_over_budget_calls_to_available_evidence_tool() -> None:
    result = _invoke_deep_research_graph(
        _build_graph_inputs(
            model_factory=OverBudgetToolCallModelFactory(),
            research_adapter=FindingWebResearchAdapter(),
        )
    )

    dossier = result["research_dossier"]
    assert dossier["status"] == "completed"
    assert dossier["evidence_items"]
    assert any("budget truncated" in note for note in dossier["raw_notes"])
    assert any(
        turn["action_kind"] == "web.search" and turn["status"] == "completed"
        for turn in dossier["recent_turns"]
    )
    assert all(
        turn["action_kind"] != "pubmed.search"
        for turn in dossier["recent_turns"]
    )


def test_deep_research_budget_selection_prefers_rcsb_for_structure_queries() -> None:
    selected = _select_tool_calls_for_budget(
        [
            {"name": "web.search", "id": "web", "args": {"query": "PDB structure"}},
            {"name": "rcsb_pdb.search", "id": "rcsb", "args": {"query": "PDB structure"}},
        ],
        available_tool_names={"web.search", "rcsb_pdb.search"},
        remaining_budget=1,
    )

    assert selected == [
        {"name": "rcsb_pdb.search", "id": "rcsb", "args": {"query": "PDB structure"}}
    ]


def test_deep_research_graph_supervisor_completes_when_findings_exist() -> None:
    model_factory = CapturingDeepResearchModelFactory()
    graph = build_deep_research_subgraph(
        _build_graph_inputs(model_factory=model_factory)
    )
    result = graph.invoke(
        {
            "session_id": "sess_001",
            "project_id": "proj_001",
            "objective": "Investigate thermostability approaches with cited evidence.",
            "design_brief": "Find enough evidence to support downstream enzyme design.",
            "research_brief": "thermostability evidence",
            "unit_results": [
                {
                    "summary": "Existing source supports the scaffold.",
                    "findings": [
                        {
                            "summary": "Existing source supports the scaffold.",
                            "query": "thermostability",
                            "confidence_label": "high",
                            "sources": [
                                {
                                    "title": "Existing source",
                                    "locator": "https://example.org/existing",
                                    "kind": "web_page",
                                }
                            ],
                        }
                    ],
                    "status": "completed",
                }
            ],
        }
    )

    assert result["research_dossier"]["status"] == "completed"
    supervisor_payload = model_factory.payloads["deep_research_supervisor"]
    assert supervisor_payload["completion_guidance"]["findings_available"] is True
    assert supervisor_payload["completion_guidance"]["recommended_action"] == "complete"
    assert (
        "If any usable unit result or finding already exists"
        in model_factory.prompts["deep_research_supervisor"]
    )


def test_deep_research_graph_synthesis_model_exception_propagates_runtime_failure() -> None:
    graph = build_deep_research_subgraph(
        _build_graph_inputs(
            model_factory=FailingSynthesisModelFactory(),
            llm_synthesis_enabled=True,
        )
    )
    with pytest.raises(RuntimeError, match="synthesis provider exploded"):
        graph.invoke(
            {
                "session_id": "sess_001",
                "project_id": "proj_001",
                "objective": "Investigate thermostability approaches with cited evidence.",
                "design_brief": "Find enough evidence to support downstream enzyme design.",
                "research_brief": "thermostability evidence",
                "unit_results": [
                    {
                        "summary": "Existing source supports the scaffold.",
                        "findings": [
                            {
                                "summary": "Existing source supports the scaffold.",
                                "query": "thermostability",
                                "confidence_label": "high",
                                "sources": [
                                    {
                                        "title": "Existing source",
                                        "locator": "https://example.org/existing",
                                        "kind": "web_page",
                                    }
                                ],
                            }
                        ],
                        "status": "completed",
                    }
                ],
            }
        )


def test_native_deep_research_runner_returns_dossier_without_control_plane_copy() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    model_factory = CompletingGraphModelFactory()
    engine = DeepResearchEngine(
        repositories,
        NativeDeepResearchRunner(
            repositories=repositories,
            research_adapter=FindingWebResearchAdapter(),
            model_factory=model_factory,
        ),
    )

    started = engine.start_research(
        session_id=session.session_id,
        task_id="task_001",
        brief="protein stability determinants",
        invocation_id="inv_graph_native",
    )

    assert started.invocation.status is EngineInvocationStatus.RUNNING
    assert started.dossier.status == "completed"
    assert model_factory.calls == [
        "deep_research_brief",
        "deep_research_supervisor",
        "deep_research_researcher",
        "deep_research_researcher",
        "deep_research_supervisor",
    ]
    assert repositories.research_evidence.list_by_invocation(
        session.session_id, "inv_graph_native"
    ) == []
    assert started.invocation.output_ref is None


def test_native_deep_research_runner_retries_researcher_transient_provider_error() -> None:
    get_llm_debug_recorder().clear()
    repositories = _build_repositories()
    session = _seed_session(repositories)
    model_factory = RetryingResearcherGraphModelFactory()
    engine = DeepResearchEngine(
        repositories,
        NativeDeepResearchRunner(
            repositories=repositories,
            research_adapter=FindingWebResearchAdapter(),
            model_factory=model_factory,
        ),
    )

    started = engine.start_research(
        session_id=session.session_id,
        task_id="task_001",
        brief="protein stability determinants",
        invocation_id="inv_graph_retry",
    )

    records = get_llm_debug_recorder().list_records(
        limit=10,
        purpose="deep_research_researcher",
        kind="tool_calling",
    )
    assert started.invocation.status is EngineInvocationStatus.RUNNING
    assert started.dossier.status == "completed"
    assert model_factory.provider_calls == 3
    retry_record = next(
        record for record in records if record["final_status"] == "retrying"
    )
    assert retry_record["error_taxonomy"]["category"] == "transient_http"


def test_native_deep_research_runner_returns_partial_without_source_backed_evidence() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(
        repositories,
        NativeDeepResearchRunner(
            repositories=repositories,
            research_adapter=FindingWebResearchAdapter(),
            model_factory=NoEvidenceGraphModelFactory(),
        ),
    )

    started = engine.start_research(
        session_id=session.session_id,
        task_id="task_001",
        brief="protein stability determinants",
        invocation_id="inv_graph_no_evidence",
    )

    assert started.invocation.status is EngineInvocationStatus.RUNNING
    assert started.dossier.status == "partial"
    assert started.dossier.evidence_items == ()
    assert repositories.research_summaries.get_by_invocation(
        session.session_id, "inv_graph_no_evidence"
    ) is None


def test_deep_research_engine_marks_invocation_failed_when_runner_raises() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, RaisingDeepResearchRunner())

    with pytest.raises(RuntimeError, match="Deep research runtime failed"):
        engine.start_research(
            session_id=session.session_id,
            task_id="task_001",
            brief="protein stability determinants",
            invocation_id="inv_runner_failed",
        )

    invocation = repositories.invocations.get("inv_runner_failed")
    assert invocation is not None
    assert invocation.status is EngineInvocationStatus.FAILED
    assert invocation.output_ref is None
    documents = repositories.engine_documents.list_by_invocation(
        session.session_id, "inv_runner_failed"
    )
    assert [document.document_kind for document in documents] == [
        "deep_research_input"
    ]


def test_deep_research_engine_does_not_persist_duplicate_research_content() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedDeepResearchRunner())

    started = engine.start_research(
        session_id=session.session_id,
        task_id="task_001",
        brief="protein stability determinants",
        invocation_id="inv_001",
        idempotency_key="task_001:deep_research:test",
    )

    assert started.invocation.status is EngineInvocationStatus.RUNNING
    assert started.dossier.source_refs[0]["kind"] == "paper"
    assert repositories.engine_documents.list_by_invocation(
        session.session_id, "inv_001"
    )
    assert repositories.research_summaries.get_by_invocation(
        session.session_id, "inv_001"
    ) is None
    assert repositories.research_evidence.list_by_invocation(
        session.session_id, "inv_001"
    ) == []
    assert repositories.research_source_refs.list_by_invocation(
        session.session_id, "inv_001"
    ) == []
    assert repositories.research_gaps.list_by_invocation(
        session.session_id, "inv_001"
    ) == []
    assert started.invocation.output_ref is None


def test_deep_research_resume_returns_new_dossier_without_overwriting_content_rows() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    runner = ClarifyThenCompleteRunner()
    engine = DeepResearchEngine(repositories, runner)

    first = engine.start_research(
        session_id=session.session_id,
        task_id="task_001",
        brief="enzyme scaffold survey",
        invocation_id="inv_resume",
    )
    second = engine.resume_research(
        invocation_id="inv_resume",
        resolution="Focus on scaffold family A only.",
    )

    assert first.dossier.status == "needs_clarification"
    assert second.dossier.status == "completed"
    assert repositories.research_summaries.get_by_invocation(
        session.session_id, "inv_resume"
    ) is None
    assert repositories.research_evidence.list_by_invocation(
        session.session_id, "inv_resume"
    ) == []
    assert runner.calls[1]["resolution"] == "Focus on scaffold family A only."


def test_deep_research_tools_register_with_tool_registry() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedDeepResearchRunner())
    registry = ToolRegistry()
    register_deep_research_tools(registry, engine)
    context = RecordingSessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    master_router = registry.to_tool_router(context)
    master_step = build_agent_step_context(context, call_index=0)
    assert "deep_research.start" not in {
        spec.tool_name for spec in master_router.model_visible_specs(master_step)
    }
    router, step_context = _researcher_step(context)
    specs = {spec.tool_name: spec for spec in router.model_visible_specs(step_context)}
    governance = router.governance(step_context, "deep_research.start")

    assert set(engine.descriptor.tool_names) <= set(specs)
    assert specs["deep_research.start"].input_schema["required"] == [
        "task_id",
        "brief",
    ]
    assert governance is not None
    assert governance.side_effect is ToolSideEffect.EXTERNAL

    missing = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_missing",
            tool_name="deep_research.start",
            arguments={"task_id": "task_001"},
            task_id="task_001",
        ),
    )
    result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_001",
            tool_name="deep_research.start",
            arguments={"task_id": "task_001", "brief": "collect catalytic evidence"},
            task_id="task_001",
        ),
    )

    assert missing.status == "invalid_tool_arguments"
    assert result.ok is True
    payload = json.loads(result.content)
    assert payload["summary"] == "Catalytic papers support the selected scaffold family."
    assert payload["invocation_id"].startswith("inv_")
    assert payload["engine_status"] == "succeeded"
    assert len(payload["workspace_files"]) == 5
    assert payload["engine_document_body_created"] is False
    assert set(context.workspace_files) == {
        f"research/{payload['invocation_id']}/{filename}"
        for filename in (
            "source-snapshots.json",
            "citations.json",
            "notes.json",
            "analysis.json",
            "dossier.json",
        )
    }


def test_deep_research_workspace_write_failure_never_leaves_success_state() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedDeepResearchRunner())
    registry = ToolRegistry()
    register_deep_research_tools(registry, engine)
    context = FailingWorkspaceSessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    router, step_context = _researcher_step(context)

    with pytest.raises(RuntimeError, match="workspace file persistence failed"):
        router.dispatch(
            step_context,
            ToolInvocation(
                call_id="call_workspace_failure",
                tool_name="deep_research.start",
                arguments={"task_id": "task_001", "brief": "collect evidence"},
                task_id="task_001",
            ),
        )

    invocations = repositories.invocations.list_by_session(session.session_id)
    assert len(invocations) == 1
    assert invocations[0].status is EngineInvocationStatus.FAILED
    assert invocations[0].output_ref is None


def test_deep_research_dossier_requires_workspace_or_published_ref() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedDeepResearchRunner())
    registry = ToolRegistry()
    register_deep_research_tools(registry, engine)
    context = RecordingSessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )
    router, step_context = _researcher_step(context)

    start_result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_start",
            tool_name="deep_research.start",
            arguments={
                "task_id": "task_001",
                "brief": "download a supporting structure",
            },
            task_id="task_001",
        ),
    )
    start_payload = json.loads(start_result.content)
    invocation_id = str(start_payload["invocation_id"])
    dossier_result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_dossier",
            tool_name="deep_research.dossier",
            arguments={"invocation_id": invocation_id},
            task_id="task_001",
        ),
    )
    status_result = router.dispatch(
        step_context,
        ToolInvocation(
            call_id="call_status",
            tool_name="deep_research.status",
            arguments={"invocation_id": invocation_id},
            task_id="task_001",
        ),
    )

    status_payload = json.loads(status_result.content)
    assert start_result.ok is True
    assert dossier_result.ok is True
    assert status_result.ok is True
    dossier_payload = json.loads(dossier_result.content)
    assert dossier_payload["content_bytes_in_control_plane"] is False
    assert dossier_payload["workspace_layout"][-1].endswith("/dossier.json")
    assert len(start_payload["workspace_files"]) == 5
    assert status_payload["status"] == "succeeded"
    assert status_payload["engine_status"] == "succeeded"
    assert status_payload["legacy_research_content_read"] is False
    assert status_payload["workspace_layout"][-1].endswith("/dossier.json")


def test_deep_research_engine_tool_descriptors_derive_from_registered_runtimes() -> None:
    repositories = _build_repositories()
    _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedDeepResearchRunner())
    engine_registry = EngineRegistry()
    engine_registry.register(engine)

    descriptors = engine_tool_descriptors(engine_registry)

    assert [descriptor.tool_name for descriptor in descriptors] == list(
        engine.descriptor.tool_names
    )
    start = next(
        descriptor for descriptor in descriptors if descriptor.tool_name == "deep_research.start"
    )
    assert start.input_schema["required"] == ["task_id", "brief"]
    assert start.description == "Start deep research for the currently assigned task."


def test_deep_research_engine_rejects_file_era_dossier_manifests() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedWithFileRunner())

    with pytest.raises(RuntimeError, match="unstored file manifests"):
        engine.start_research(
            session_id=session.session_id,
            task_id="task_001",
            brief="download a supporting structure",
            invocation_id="inv_files",
        )
