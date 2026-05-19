from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft as EngineResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft as EngineResearchUnitDraft
from openzyme_engines import ResearchUnitPlan as EngineResearchUnitPlan
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import DesignNextAction
from openzyme_runtime import ExecutionPlanDraft
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import ReportDraft
from openzyme_runtime import ResearchBriefDraft as RuntimeResearchBriefDraft
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_graph.supervisor import build_v2_supervisor_graph


def _nested_values(snapshot):
    nested = snapshot.tasks[0].state
    return nested.values if hasattr(nested, "values") else {}


class FakeExecutionAdapter:
    def submit_execution(
        self, episode_id: str, payload: dict[str, object]
    ) -> ExecutionOutcome:
        return ExecutionOutcome(
            run_id="run_001",
            status=RunStatus.SUCCEEDED,
            execution_mode="ssh",
            remote_run_dir=f"/remote/{episode_id}/run_001",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/stdout.log",
                    relative_path="stdout.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri="/tmp/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={"status": "completed", "pockets_found": 1},
        )


class FakeResearchAdapter:
    def conduct(
        self, *, episode_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
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

    def normalize_search_response(
        self,
        *,
        unit: ResearchUnit,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        results = list(response.get("results", []))
        result = dict(results[0]) if results else {}
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the research brief.",
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
            unresolved_gaps=(f"Need follow-up for {unit.unit_id}",),
        )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(
            unit=ResearchUnit(
                unit_id="web-fetch", topic="web fetch", query=query or url
            ),
            response=response,
        )


class FakeWorkflowStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del schema, system_prompt
        objective = str(user_payload.get("objective") or "Improve thermostability")
        if self.purpose == "intake_collect":
            return IntakePhaseOutput(
                clarification=IntakeClarification(),
                constraint_set=ConstraintSet(
                    objective_summary=objective,
                    constraints=[
                        ConstraintItem(
                            category="technical",
                            description="Prepare execution-ready artifacts.",
                        )
                    ],
                ),
                design_brief=DesignBriefDraft(
                    design_brief=f"Design brief for {objective}",
                    success_criteria=["Prepare execution-ready artifacts."],
                ),
                research_brief=RuntimeResearchBriefDraft(
                    research_brief=f"Research brief for {objective}",
                    focus_areas=["evidence"],
                    expected_outputs=["research summary"],
                ),
            )
        if self.purpose == "design_next_action":
            evidence_refs = list(user_payload.get("evidence_refs") or [])
            run_summary = dict(user_payload.get("run_summary") or {})
            if not evidence_refs:
                return DesignNextAction(
                    action_kind="collect_research",
                    summary="Collect evidence.",
                    rationale="No canonical evidence exists yet.",
                    arguments={},
                )
            if not run_summary:
                return DesignNextAction(
                    action_kind="request_execution",
                    summary="Request execution.",
                    rationale="Evidence and an execution-ready artifact are available.",
                    arguments={},
                )
            return DesignNextAction(
                action_kind="stop",
                summary="Stop and report.",
                rationale="The workflow has an execution result.",
                stop_reason="design_loop_complete",
                arguments={},
            )
        if self.purpose == "deep_research_brief":
            return EngineResearchBriefDraft(research_brief=f"Research brief for {objective}")
        if self.purpose == "deep_research_supervisor":
            unit_results = list(user_payload.get("unit_results") or [])
            if any(result.get("findings") for result in unit_results):
                return ResearchSupervisorAction(action_kind="complete", rationale="A finding exists.")
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one evidence unit.",
                unit_plan=EngineResearchUnitPlan(
                    units=[
                        EngineResearchUnitDraft(
                            unit_id="evidence",
                            topic="supporting evidence",
                            query=f"{objective} evidence",
                            rationale="Collect evidence for downstream design.",
                        )
                    ],
                    synthesis_goal="Support downstream design.",
                ),
            )
        if self.purpose == "deep_research_synthesis":
            return EvidenceSynthesis(
                summary="Research evidence supports the current objective.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Evidence supports the current scaffold direction.",
                        query=f"{objective} evidence",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic source",
                                locator="https://example.org/evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                    EvidenceSynthesisItem(
                        summary="Structure-backed evidence supports execution.",
                        query=f"{objective} structure evidence",
                        confidence_label="medium",
                        sources=[
                            ResearchSourceItem(
                                title="Synthetic structure source",
                                locator="https://example.org/structure-evidence",
                                kind="web_page",
                            )
                        ],
                    ),
                ],
                unresolved_gaps=["Need experimental validation."],
            )
        if self.purpose == "execution_plan":
            return ExecutionPlanDraft(
                catalog_tool_id="fpocket",
                rationale="Use the curated execution-ready structure artifact.",
                tool_inputs={},
                expected_result_summary="Run fpocket on the selected structure artifact.",
            )
        if self.purpose == "report_review":
            return ReportDraft(
                title="OpenZyme design report",
                summary="Workflow completed.",
                stage_summary="Research, execution, and report review completed.",
                key_decisions=["Proceed with the current scaffold direction."],
            )
        raise AssertionError(f"Unexpected purpose {self.purpose}")


class FakeWorkflowToolInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0

    def invoke_with_tools(self, *, system_prompt: str, messages: list[object], tools: list[object]):
        del system_prompt, messages, tools
        self.calls += 1
        if self.purpose == "deep_research_researcher" and self.calls == 1:
            return {
                "tool_calls": [
                    {
                        "name": "web.search",
                        "id": "web-search-1",
                        "args": {
                            "query": "thermostability evidence",
                            "topic": "supporting evidence",
                            "max_results": 1,
                        },
                    }
                ]
            }
        return {"tool_calls": []}


class FakeWorkflowModelFactory:
    def __init__(self) -> None:
        self.tool_invokers: dict[str, FakeWorkflowToolInvoker] = {}

    def create_structured_invoker(self, *, purpose: str) -> FakeWorkflowStructuredInvoker:
        return FakeWorkflowStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeWorkflowToolInvoker:
        if purpose not in self.tool_invokers:
            self.tool_invokers[purpose] = FakeWorkflowToolInvoker(purpose)
        return self.tool_invokers[purpose]


@contextmanager
def _memory_checkpointer_open(self: PostgresCheckpointerFactory):
    yield InMemorySaver()


def _build_foundation() -> RuntimeFoundation:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    project = Project.create("proj_001", "Thermostability project")
    repositories.projects.save(project)
    repositories.episodes.save(
        Episode.create(
            episode_id="ep_001",
            project_id=project.project_id,
            objective="Improve thermostability",
        )
    )
    repositories.artifact_records.save(
        ArtifactRecord(
            artifact_id="art_input_structure",
            episode_id="ep_001",
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/input_structure.pdb",
            created_at="2026-04-11T12:00:00+00:00",
            title="Input structure",
            tags=("input", "structure"),
            availability={"local_readable": True, "execution_input": True},
            provenance={"source_type": "imported"},
        )
    )
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-b/memory")
        ),
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
        research_adapter=FakeResearchAdapter(),
        model_factory=FakeWorkflowModelFactory(),
    )


def test_unified_supervisor_routes_design_execution_and_report_review_on_one_thread(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_v2_supervisor_graph) as graph:
        first = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Improve thermostability",
                "user_goal": "Research, design, and run the best candidate",
            },
            config,
        )
        first_snapshot = graph.get_state(config, subgraphs=True)
        second = graph.invoke(Command(resume={"approved": True}), config)

    assert first["recommended_next_phase"] == "execution"
    assert first_snapshot.values["current_phase"] == "execution"
    assert len(foundation.repositories.evidence_records.list_by_episode("ep_001")) == 2
    assert first["execution_handoff"]["required_artifact_ids"] == [
        "art_input_structure"
    ]
    assert second["status"] == "completed"
    assert second["current_phase"] == "report_review"
    assert second["run_summary"]["run_id"] == "run_001"
    assert len(second["artifact_refs"]) >= 3
    assert second["report_summary"]["report_id"] == "ep_001-report"
    assert foundation.repositories.reports.get("ep_001-report") is not None


def test_unified_supervisor_only_completes_after_report_review_finishes(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_v2_supervisor_graph) as graph:
        graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Improve thermostability",
                "user_goal": "Research, design, and run the best candidate",
            },
            config,
        )
        design_resume = graph.invoke(Command(resume={"approved": True}), config)
        final_snapshot = graph.get_state(config, subgraphs=True)

    assert design_resume["current_phase"] == "report_review"
    assert design_resume["status"] == "completed"
    assert design_resume["report_artifact_id"] == "ep_001-report-artifact"
    assert final_snapshot.values["current_phase"] == "report_review"
    assert final_snapshot.values["status"] == "completed"
    assert (
        foundation.repositories.reports.list_by_episode("ep_001")[0].artifact_id
        == "ep_001-report-artifact"
    )
