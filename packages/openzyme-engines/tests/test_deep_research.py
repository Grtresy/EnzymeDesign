from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import MemoryScopeKind
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_domain import ArtifactKind
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
from openzyme_engines import build_deep_research_subgraph
from openzyme_engines import register_deep_research_tools
from openzyme_runtime import GraphAssemblyInputs
from openzyme_runtime import OpenZymeHostToolbox
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import apply_sqlite_migrations as apply_phase_b_sqlite_migrations
from openzyme_runtime import connect_sqlite as connect_phase_b_sqlite
from openzyme_runtime import get_settings


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


class CompletedWithArtifactRunner:
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
            artifacts=[
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


def _build_phase_b_inputs(*, model_factory: object | None, research_adapter: object | None = None) -> GraphAssemblyInputs:
    connection = connect_phase_b_sqlite(":memory:")
    apply_phase_b_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    settings = get_settings()
    settings = replace(
        settings,
        research=replace(
            settings.research,
            allow_clarification=False,
            max_research_iterations=1,
            max_react_tool_calls=1,
            max_concurrent_research_units=1,
        ),
    )
    return GraphAssemblyInputs(
        repositories=repositories,
        checkpointer=None,
        execution_adapter=None,
        hpc_catalog_provider=None,
        hpc_execution_registry=None,
        research_adapter=research_adapter,
        research_tool_provider=None,
        projection_loader=None,
        model_factory=model_factory,
        host_toolbox=OpenZymeHostToolbox(repositories),
        settings=settings,
    )


def test_deep_research_without_model_factory_returns_failed_dossier() -> None:
    graph = build_deep_research_subgraph(_build_phase_b_inputs(model_factory=None))

    result = graph.invoke(
        {
            "episode_id": "ep_001",
            "project_id": "proj_001",
            "objective": "Investigate thermostability approaches with cited evidence.",
            "design_brief": "Find enough evidence to support downstream enzyme design.",
            "research_brief": "thermostability evidence",
        }
    )

    assert result["research_dossier"]["status"] == "failed"
    assert result["research_dossier"]["completion_reason"] == "missing_model_factory"
    assert "model factory" in result["research_dossier"]["summary"]


def test_deep_research_tool_validation_error_returns_observation() -> None:
    graph = build_deep_research_subgraph(
        _build_phase_b_inputs(
            model_factory=InvalidToolCallModelFactory(),
            research_adapter=MinimalWebResearchAdapter(),
        )
    )

    result = graph.invoke(
        {
            "episode_id": "ep_001",
            "project_id": "proj_001",
            "objective": "Investigate thermostability approaches with cited evidence.",
            "design_brief": "Find enough evidence to support downstream enzyme design.",
            "research_brief": "thermostability evidence",
        }
    )

    dossier = result["research_dossier"]
    assert dossier["status"] == "failed"
    assert "Tool web.search received invalid arguments." in dossier["unresolved_gaps"]
    assert any(
        turn["action_kind"] == "web.search" and turn["status"] == "failed"
        for turn in dossier["recent_turns"]
    )


def test_deep_research_unexpected_tool_exception_raises() -> None:
    graph = build_deep_research_subgraph(
        _build_phase_b_inputs(
            model_factory=ValidToolCallModelFactory(),
            research_adapter=RaisingWebResearchAdapter(),
        )
    )

    with pytest.raises(RuntimeError, match="provider exploded"):
        graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Investigate thermostability approaches with cited evidence.",
                "design_brief": "Find enough evidence to support downstream enzyme design.",
                "research_brief": "thermostability evidence",
            }
        )


def test_deep_research_supervisor_completes_when_findings_exist() -> None:
    state = {
        "unit_results": [
            {
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
        ]
    }
    connection = connect_phase_b_sqlite(":memory:")
    apply_phase_b_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    model_factory = CapturingDeepResearchModelFactory()
    settings = get_settings()
    settings = replace(
        settings,
        research=replace(settings.research, allow_clarification=False),
    )
    inputs = GraphAssemblyInputs(
        repositories=repositories,
        checkpointer=None,
        execution_adapter=None,
        hpc_catalog_provider=None,
        hpc_execution_registry=None,
        research_adapter=None,
        research_tool_provider=None,
        projection_loader=None,
        model_factory=model_factory,
        host_toolbox=OpenZymeHostToolbox(repositories),
        settings=settings,
    )

    graph = build_deep_research_subgraph(inputs)
    result = graph.invoke(
        {
            "episode_id": "ep_001",
            "project_id": "proj_001",
            "objective": "Investigate thermostability approaches with cited evidence.",
            "design_brief": "Find enough evidence to support downstream enzyme design.",
            "research_brief": "thermostability evidence",
            "unit_results": state["unit_results"],
        }
    )

    assert result["research_dossier"]["status"] == "completed"
    supervisor_payload = model_factory.payloads["deep_research_supervisor"]
    assert supervisor_payload["completion_guidance"]["findings_available"] is True
    assert (
        supervisor_payload["completion_guidance"]["recommended_action"] == "complete"
    )
    assert "If any usable unit result or finding already exists" in model_factory.prompts[
        "deep_research_supervisor"
    ]


def test_deep_research_synthesis_model_exception_returns_failed_dossier() -> None:
    connection = connect_phase_b_sqlite(":memory:")
    apply_phase_b_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    model_factory = FailingSynthesisModelFactory()
    settings = get_settings()
    settings = replace(
        settings,
        research=replace(settings.research, allow_clarification=False),
    )
    inputs = GraphAssemblyInputs(
        repositories=repositories,
        checkpointer=None,
        execution_adapter=None,
        hpc_catalog_provider=None,
        hpc_execution_registry=None,
        research_adapter=None,
        research_tool_provider=None,
        projection_loader=None,
        model_factory=model_factory,
        host_toolbox=OpenZymeHostToolbox(repositories),
        settings=settings,
    )

    graph = build_deep_research_subgraph(inputs)
    result = graph.invoke(
        {
            "episode_id": "ep_001",
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

    dossier = result["research_dossier"]
    assert dossier["status"] == "failed"
    assert dossier["completion_reason"] == "synthesis_model_failed"
    assert dossier["evidence_items"] == []
    assert any("RuntimeError" in gap for gap in dossier["unresolved_gaps"])
    assert any("synthesis provider exploded" in note for note in dossier["raw_notes"])


def test_deep_research_engine_persists_v3_canonical_research_rows() -> None:
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

    assert started.invocation.status.value == "succeeded"
    assert started.dossier.source_refs[0]["kind"] == "paper"
    assert repositories.engine_documents.list_by_invocation(
        session.session_id, "inv_001"
    )
    assert (
        repositories.research_summaries.get_by_invocation(
            session.session_id, "inv_001"
        ).status
        is ResearchSummaryStatus.COMPLETED
    )
    assert (
        repositories.research_evidence.list_by_invocation(
            session.session_id, "inv_001"
        )[0].confidence_label
        == "high"
    )
    assert repositories.research_source_refs.list_by_invocation(
        session.session_id, "inv_001"
    )[0].locator.endswith("paper-a")
    assert (
        repositories.research_gaps.list_by_invocation(session.session_id, "inv_001")[
            0
        ].summary
        == "Need wet-lab validation"
    )
    dossier_artifact = repositories.artifacts.get("inv_001:dossier")
    assert dossier_artifact.kind is ArtifactKind.RESEARCH_DOSSIER
    assert (
        dossier_artifact.storage_uri
        == f"engine-document://{started.invocation.output_ref}"
    )
    assert dossier_artifact.relative_path == "deep-research/inv_001/dossier.json"
    assert dossier_artifact.metadata["evidence_count"] == 1
    assert dossier_artifact.metadata["source_ref_count"] == 1
    assert dossier_artifact.metadata["gap_count"] == 1
    assert repositories.memory.list_by_scope(
        session.session_id,
        scope_kind=MemoryScopeKind.TASK,
        scope_ref="task_001",
    )


def test_deep_research_resume_overwrites_canonical_rows_for_same_invocation() -> None:
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
    summary = repositories.research_summaries.get_by_invocation(
        session.session_id, "inv_resume"
    )
    evidence = repositories.research_evidence.list_by_invocation(
        session.session_id, "inv_resume"
    )
    assert summary.status is ResearchSummaryStatus.COMPLETED
    assert summary.clarification_question is None
    assert len(evidence) == 1
    assert runner.calls[1]["resolution"] == "Focus on scaffold family A only."


def test_deep_research_tools_register_with_tool_registry() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedDeepResearchRunner())
    registry = ToolRegistry()
    register_deep_research_tools(registry, engine)
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
            call_id="call_001",
            tool_name="deep_research.start",
            arguments={"task_id": "task_001", "brief": "collect catalytic evidence"},
            task_id="task_001",
        ),
    )

    assert result.ok is True
    assert "collect catalytic evidence" in result.content


def test_deep_research_engine_persists_artifacts_from_dossier() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    engine = DeepResearchEngine(repositories, CompletedWithArtifactRunner())

    result = engine.start_research(
        session_id=session.session_id,
        task_id="task_001",
        brief="download a supporting structure",
        invocation_id="inv_artifacts",
    )

    artifacts = repositories.artifacts.list_by_invocation(
        session.session_id, "inv_artifacts"
    )
    artifacts_by_id = {artifact.artifact_id: artifact for artifact in artifacts}
    assert result.invocation.status.value == "succeeded"
    assert len(artifacts) == 2
    assert (
        artifacts_by_id["inv_artifacts:dossier"].kind is ArtifactKind.RESEARCH_DOSSIER
    )
    assert artifacts_by_id["inv_artifacts:artifact:1"].kind is ArtifactKind.STRUCTURE
    assert (
        artifacts_by_id["inv_artifacts:artifact:1"].metadata["provider"] == "rcsb_pdb"
    )
