from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Episode
from openzyme_domain import EvidenceRecord
from openzyme_domain import Project
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft
from openzyme_engines import ResearchUnitPlan
from openzyme_graph.design import build_phase_c_design_graph
from openzyme_runtime import DesignNextAction
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_runtime import RuntimeFoundation
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider


class FakeExecutionAdapter:
    def submit_execution(
        self, episode_id: str, payload: dict[str, object]
    ) -> ExecutionOutcome:
        del payload
        return ExecutionOutcome(
            run_id="run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir=f"/remote/{episode_id}/run_001",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={"status": "completed", "pockets_found": 1},
        )


class FakeResearchAdapter:
    def conduct(self, *, episode_id: str, research_brief: str, unit) -> object:
        del episode_id, research_brief
        return self.normalize_search_response(
            unit=unit,
            response=self.web_search(
                query=unit.query,
                max_results=3,
                topic=unit.topic,
                include_raw_content=True,
            ),
        )

    def web_search(
        self,
        *,
        query: str,
        max_results: int = 3,
        topic: str = "general",
        include_raw_content: bool = True,
    ) -> dict[str, object]:
        del max_results, include_raw_content
        return {
            "results": [
                {
                    "title": f"Source for {topic}",
                    "url": f"https://example.org/{topic.replace(' ', '-')}",
                    "content": f"Finding for {query}",
                }
            ]
        }

    def fetch_url(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> dict[str, object]:
        del query, extract_depth, format, include_images
        return {
            "results": [
                {
                    "title": "Fetched source",
                    "url": url,
                    "raw_content": "Fetched content.",
                }
            ]
        }

    def normalize_search_response(self, *, unit, response: dict[str, object]) -> object:
        from openzyme_research import ResearchFinding
        from openzyme_research import ResearchSource
        from openzyme_research import ResearchUnitResult

        results = list(response.get("results", []))
        result = dict(results[0]) if results else {}
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the design objective.",
            findings=(
                ResearchFinding(
                    summary=str(
                        result.get("content")
                        or result.get("raw_content")
                        or f"Finding for {unit.query}"
                    ),
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Source for {unit.unit_id}",
                            locator=str(
                                result.get("url")
                                or f"https://example.org/{unit.unit_id}"
                            ),
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need follow-up validation.",),
        )

    def normalize_fetch_response(
        self, *, url: str, query: str | None, response: dict[str, object]
    ) -> object:
        return self.normalize_search_response(
            unit=type(
                "ResearchUnit",
                (),
                {"unit_id": "web-fetch", "topic": "web fetch", "query": query or url},
            )(),
            response=response,
        )


class FakeStructuredInvoker:
    def __init__(
        self,
        responses: dict[str, object],
        calls: list[str],
        prompts: dict[str, str],
        payloads: dict[str, dict[str, object]],
        purpose: str,
    ) -> None:
        self._response = responses[purpose]
        self._calls = calls
        self._prompts = prompts
        self._payloads = payloads
        self._purpose = purpose

    def invoke_structured(
        self, *, schema, system_prompt: str, user_payload: dict[str, object]
    ):
        del schema
        self._calls.append(self._purpose)
        self._prompts[self._purpose] = system_prompt
        self._payloads[self._purpose] = user_payload
        if isinstance(self._response, list):
            index = self._factory_response_index()
            return self._response[min(index, len(self._response) - 1)]
        return self._response

    def _factory_response_index(self) -> int:
        key = f"__{self._purpose}_response_index"
        current = int(self._payloads.get(key, {}).get("index", 0))
        self._payloads[key] = {"index": current + 1}
        return current


class FakeToolCallingInvoker:
    def __init__(self) -> None:
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages, tools
        self.calls += 1
        if self.calls == 1:
            return {
                "tool_calls": [
                    {
                        "name": "web.search",
                        "id": "test-web-search-1",
                        "args": {
                            "query": "thermostability evidence",
                            "topic": "supporting evidence",
                            "max_results": 1,
                        },
                    }
                ]
            }
        return {"tool_calls": []}


class FakeModelFactory:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.calls: list[str] = []
        self.prompts: dict[str, str] = {}
        self.payloads: dict[str, dict[str, object]] = {}
        self.tool_invoker = FakeToolCallingInvoker()

    def create_structured_invoker(self, *, purpose: str) -> FakeStructuredInvoker:
        return FakeStructuredInvoker(
            self._responses,
            self.calls,
            self.prompts,
            self.payloads,
            purpose,
        )

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeToolCallingInvoker:
        self.calls.append(purpose)
        return self.tool_invoker


class RaisingStructuredInvoker:
    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del schema, system_prompt, user_payload
        raise RuntimeError("planner provider unavailable")


class RaisingModelFactory:
    calls: list[str]

    def __init__(self) -> None:
        self.calls = []

    def create_structured_invoker(self, *, purpose: str) -> RaisingStructuredInvoker:
        self.calls.append(purpose)
        return RaisingStructuredInvoker()


def _request_execution_model_factory() -> FakeModelFactory:
    return FakeModelFactory(
        {
            "design_next_action": DesignNextAction(
                action_kind="request_execution",
                summary="Use the execution-ready structure artifact.",
                rationale="The workspace already has an execution-ready artifact.",
                arguments={},
            ),
        }
    )


def _collect_research_model_factory() -> FakeModelFactory:
    return FakeModelFactory(
        {
            "design_next_action": [
                DesignNextAction(
                    action_kind="collect_research",
                    summary="Collect initial evidence for the objective.",
                    rationale="No canonical evidence exists yet.",
                    arguments={},
                ),
                DesignNextAction(
                    action_kind="request_execution",
                    summary="Use the curated research artifact for execution.",
                    rationale="Research collection produced execution-ready references.",
                    arguments={},
                ),
            ],
            "deep_research_brief": ResearchBriefDraft(
                research_brief="thermostability evidence"
            ),
            "deep_research_supervisor": ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="No usable finding exists yet.",
                unit_plan=ResearchUnitPlan(
                    units=[
                        ResearchUnitDraft(
                            unit_id="evidence",
                            topic="supporting evidence",
                            query="thermostability evidence",
                            rationale="Collect evidence for the design objective.",
                        )
                    ],
                    synthesis_goal="Support downstream design.",
                ),
            ),
            "deep_research_synthesis": EvidenceSynthesis(
                summary="Research evidence supports the design objective.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Thermostability evidence supports the scaffold.",
                        query="thermostability evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic source",
                                locator="https://example.org/source",
                                kind="web_page",
                            )
                        ],
                    )
                ],
                unresolved_gaps=[],
            ),
        }
    )


@contextmanager
def _memory_checkpointer_open(self: PostgresCheckpointerFactory):
    yield InMemorySaver()


def _build_foundation(
    *,
    with_research: bool = True,
    with_research_adapter: bool = False,
    model_factory: object | None = None,
) -> RuntimeFoundation:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    project = Project.create("proj_001", "Design project")
    repositories.projects.save(project)
    repositories.episodes.save(
        Episode.create(
            episode_id="ep_001",
            project_id=project.project_id,
            objective="Design a thermostable variant",
        )
    )
    if with_research:
        repositories.research_summaries.save(
            ResearchSummaryRecord(
                episode_id="ep_001",
                summary="Literature supports two promising scaffold directions.",
                created_at="2026-04-11T12:00:00+00:00",
                updated_at="2026-04-11T12:00:00+00:00",
            )
        )
        repositories.evidence_records.save(
            EvidenceRecord(
                evidence_id="ev_001",
                episode_id="ep_001",
                summary="Scaffold A is supported by thermostability evidence.",
                query="scaffold A evidence",
                created_at="2026-04-11T12:01:00+00:00",
            )
        )
        repositories.evidence_records.save(
            EvidenceRecord(
                evidence_id="ev_002",
                episode_id="ep_001",
                summary="Scaffold B has structure-backed homolog support.",
                query="scaffold B evidence",
                created_at="2026-04-11T12:02:00+00:00",
            )
        )
        repositories.artifact_records.save(
            ArtifactRecord(
                artifact_id="art_input_structure",
                episode_id="ep_001",
                kind=ArtifactKind.STRUCTURE,
                storage_uri="/tmp/input_structure.pdb",
                created_at="2026-04-11T12:03:00+00:00",
                title="Input structure",
                description="Local structure artifact for execution.",
                tags=("input", "structure"),
                availability={"local_readable": True, "execution_input": True},
                provenance={"source_type": "imported"},
            )
        )
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-c/design")
        ),
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
        research_adapter=FakeResearchAdapter() if with_research_adapter else None,
        model_factory=model_factory,
    )


def test_phase_c_design_graph_curates_artifacts_and_prepares_execution_handoff(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation(model_factory=_request_execution_model_factory())
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        first = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )
    assert first["status"] == "completed"
    assert first["recommended_next_phase"] == "execution"
    assert first["execution_handoff"]["required_artifact_ids"] == [
        "art_input_structure"
    ]
    assert first["artifact_workspace_summary"]["artifact_count"] >= 1


def test_phase_c_design_graph_routes_curated_artifacts_into_execution(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation(model_factory=_request_execution_model_factory())
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )

    assert result["status"] == "completed"
    assert result["recommended_next_phase"] == "execution"
    assert result["execution_handoff"]["required_artifact_ids"] == [
        "art_input_structure"
    ]
    assert (
        "art_input_structure"
        in result["artifact_workspace_summary"]["execution_ready_artifact_ids"]
    )


def test_phase_c_design_graph_collects_research_inside_design_when_missing(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation(
        with_research=False,
        with_research_adapter=True,
        model_factory=_collect_research_model_factory(),
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )

    assert result["recommended_next_phase"] == "execution"
    assert (
        foundation.repositories.research_summaries.get_by_episode("ep_001") is not None
    )
    assert len(foundation.repositories.evidence_records.list_by_episode("ep_001")) >= 1


def test_phase_c_design_graph_uses_structured_next_action_output(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    foundation = RuntimeFoundation(
        repositories=foundation.repositories,
        checkpointer_factory=foundation.checkpointer_factory,
        execution_adapter=foundation.execution_adapter,
        hpc_catalog_provider=foundation.hpc_catalog_provider,
        hpc_execution_registry=foundation.hpc_execution_registry,
        model_factory=FakeModelFactory(
            {
                "design_next_action": DesignNextAction(
                    action_kind="request_execution",
                    summary="Use the curated structure artifact for execution.",
                    rationale="The structure artifact is already marked execution-ready.",
                    arguments={
                        "execution_goal": "Run a fast structure-based evaluator.",
                        "preferred_stage_tags": ["execution", "evaluator"],
                    },
                ),
            }
        ),
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )

    assert result["execution_handoff"]["recommended_next_phase"] == "execution"
    assert result["execution_handoff"]["required_artifact_ids"] == [
        "art_input_structure"
    ]
    assert result["execution_handoff"]["preferred_stage_tags"] == [
        "execution",
        "evaluator",
    ]


def test_phase_c_design_graph_payload_blocks_redundant_research_after_evidence(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    model_factory = FakeModelFactory(
        {
            "design_next_action": DesignNextAction(
                action_kind="request_execution",
                summary="Use the execution-ready structure artifact.",
                rationale="The workspace already has an execution-ready artifact.",
                arguments={},
            ),
        }
    )
    foundation = _build_foundation()
    foundation = RuntimeFoundation(
        repositories=foundation.repositories,
        checkpointer_factory=foundation.checkpointer_factory,
        execution_adapter=foundation.execution_adapter,
        hpc_catalog_provider=foundation.hpc_catalog_provider,
        hpc_execution_registry=foundation.hpc_execution_registry,
        model_factory=model_factory,
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )

    assert model_factory.calls == ["design_next_action"]
    payload = model_factory.payloads["design_next_action"]
    assert "allowed_actions" in payload
    assert "blocked_actions" in payload
    assert "recommended_next_action" in payload
    assert "state_machine_guidance" in payload
    assert "allowed_actions only" in model_factory.prompts["design_next_action"]
    assert "collect_research" not in payload["allowed_actions"]
    assert "stop" not in payload["allowed_actions"]
    assert payload["recommended_next_action"] == "request_execution"
    assert (
        "art_input_structure"
        in payload["state_machine_guidance"]["execution_ready_artifact_ids"]
    )
    assert result["recommended_next_phase"] == "execution"
    assert result["execution_handoff"]["required_artifact_ids"] == [
        "art_input_structure"
    ]
    decisions = foundation.repositories.decisions.list_by_episode("ep_001")
    assert [decision.action_kind for decision in decisions] == ["request_execution"]


def test_phase_c_design_graph_fails_illegal_planner_action_without_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    model_factory = FakeModelFactory(
        {
            "design_next_action": DesignNextAction(
                action_kind="collect_research",
                summary="Collect more literature even though evidence exists.",
                rationale="The model returned an action outside the state contract.",
                arguments={},
            ),
        }
    )
    foundation = _build_foundation()
    foundation = RuntimeFoundation(
        repositories=foundation.repositories,
        checkpointer_factory=foundation.checkpointer_factory,
        execution_adapter=foundation.execution_adapter,
        hpc_catalog_provider=foundation.hpc_catalog_provider,
        hpc_execution_registry=foundation.hpc_execution_registry,
        model_factory=model_factory,
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )

    assert result["status"] == "completed"
    assert result["recommended_next_phase"] == "report_review"
    assert result["design_handoff"]["design_summary"]["outcome"] == "planner_failed"
    decisions = foundation.repositories.decisions.list_by_episode("ep_001")
    assert [decision.action_kind for decision in decisions] == ["collect_research"]
    assert decisions[0].status.value == "failed"
    violation = decisions[0].action_payload["planner_contract_violation"]
    assert violation["type"] == "planner_contract_violation"
    assert violation["original_action"]["action_kind"] == "collect_research"
    assert "recovery_action" not in violation
    assert "collect_research" not in violation["allowed_actions"]
    assert decisions[0].observation_payload == violation


def test_phase_c_design_graph_fails_planner_exception_without_fallback(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    model_factory = RaisingModelFactory()
    foundation = _build_foundation(model_factory=model_factory)
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )

    assert result["recommended_next_phase"] == "report_review"
    assert result["design_handoff"]["design_summary"]["outcome"] == "planner_failed"
    decisions = foundation.repositories.decisions.list_by_episode("ep_001")
    assert [decision.action_kind for decision in decisions] == ["stop"]
    assert decisions[0].status.value == "failed"
    assert decisions[0].observation_payload["type"] == "planner_failed"
    assert decisions[0].observation_payload["error_type"] == "RuntimeError"
