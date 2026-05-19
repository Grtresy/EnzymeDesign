from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import SourceRefKind
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_runtime import GraphAssemblyInputs
from openzyme_runtime import DefaultResearchToolProvider
from openzyme_runtime import OpenZymeHostToolbox
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import ResearchDossier
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_runtime import get_settings
from openzyme_engines import EvidenceSynthesis
from openzyme_engines import EvidenceSynthesisItem
from openzyme_engines import ResearchBriefDraft
from openzyme_engines import ResearchSourceItem
from openzyme_engines import ResearchSupervisorAction
from openzyme_engines import ResearchUnitDraft
from openzyme_engines import ResearchUnitPlan
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult

from openzyme_graph.deep_research import run_deep_research


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
                    "url": "https://example.org/overview",
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
                    "raw_content": "Fetched page content.",
                }
            ]
        }

    def normalize_search_response(
        self, *, unit: ResearchUnit, response: dict[str, object]
    ) -> ResearchUnitResult:
        result = dict(list(response["results"])[0])  # type: ignore[index]
        content = str(
            result.get("content")
            or result.get("raw_content")
            or f"Finding for {unit.query}"
        )
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} summary for {unit.query}",
            findings=(
                ResearchFinding(
                    summary=content,
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Source for {unit.unit_id}",
                            locator=str(result["url"]),
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need experimental validation.",),
        )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        unit = ResearchUnit(unit_id="web-fetch", topic="web fetch", query=query or url)
        return self.normalize_search_response(unit=unit, response=response)


class FakeDeepResearchStructuredInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict):
        del schema, system_prompt
        if self.purpose == "deep_research_brief":
            return ResearchBriefDraft(research_brief="Find evidence that can support downstream enzyme design.")
        if self.purpose == "deep_research_supervisor":
            unit_results = list(user_payload.get("unit_results") or [])
            if any(result.get("findings") for result in unit_results):
                return ResearchSupervisorAction(action_kind="complete", rationale="A finding exists.")
            return ResearchSupervisorAction(
                action_kind="conduct_research",
                rationale="Collect one evidence unit.",
                unit_plan=ResearchUnitPlan(
                    units=[
                        ResearchUnitDraft(
                            unit_id="evidence",
                            topic="supporting evidence",
                            query="thermostability approaches",
                            rationale="Collect evidence for downstream design.",
                        )
                    ],
                    synthesis_goal="Support downstream design.",
                ),
            )
        if self.purpose == "deep_research_synthesis":
            return EvidenceSynthesis(
                summary="Research evidence supports downstream enzyme design.",
                evidence_items=[
                    EvidenceSynthesisItem(
                        summary="Finding for thermostability approaches",
                        query="thermostability approaches",
                        confidence_label="high",
                        sources=[
                            ResearchSourceItem(
                                title="Source for evidence",
                                locator="https://example.org/overview",
                                kind="web_page",
                            )
                        ],
                    )
                ],
                unresolved_gaps=["Need experimental validation."],
            )
        raise AssertionError(f"Unexpected purpose {self.purpose}")


class FakeDeepResearchToolInvoker:
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
                        "id": "web-search-1",
                        "args": {
                            "query": "thermostability approaches",
                            "topic": "supporting evidence",
                            "max_results": 1,
                        },
                    }
                ]
            }
        return {"tool_calls": []}


class FakeDeepResearchModelFactory:
    def __init__(self) -> None:
        self.tool_invoker = FakeDeepResearchToolInvoker()

    def create_structured_invoker(self, *, purpose: str) -> FakeDeepResearchStructuredInvoker:
        return FakeDeepResearchStructuredInvoker(purpose)

    def create_tool_calling_invoker(self, *, purpose: str) -> FakeDeepResearchToolInvoker:
        del purpose
        return self.tool_invoker


def _build_foundation() -> RuntimeFoundation:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    project = Project.create("proj_001", "Deep research project")
    repositories.projects.save(project)
    repositories.episodes.save(
        Episode.create(
            episode_id="ep_001",
            project_id=project.project_id,
            objective="Investigate thermostability approaches",
        )
    )
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=None,  # type: ignore[arg-type]
        research_adapter=FakeResearchAdapter(),
    )


def test_run_deep_research_returns_normalized_dossier() -> None:
    foundation = _build_foundation()
    inputs = GraphAssemblyInputs(
        repositories=foundation.repositories,
        checkpointer=InMemorySaver(),
        execution_adapter=None,
        hpc_catalog_provider=None,
        hpc_execution_registry=None,
        research_adapter=foundation.research_adapter,
        research_tool_provider=DefaultResearchToolProvider(foundation.research_adapter),
        projection_loader=None,
        model_factory=FakeDeepResearchModelFactory(),
        host_toolbox=OpenZymeHostToolbox(foundation.repositories),
        settings=get_settings(),
    )
    dossier = run_deep_research(
        inputs,
        episode_id="ep_001",
        project_id="proj_001",
        objective="Investigate thermostability approaches",
        design_brief="Find evidence that can support downstream enzyme design.",
        research_brief=None,
    )

    assert isinstance(dossier, ResearchDossier)
    assert dossier.research_brief.startswith("Find evidence")
    assert dossier.summary
    assert len(dossier.evidence_items) >= 1
    assert (
        dossier.evidence_items[0].sources[0].locator.startswith("https://example.org/")
    )
    assert "Need experimental validation." in dossier.unresolved_gaps
    assert dossier.recent_turns[0].action_kind == "conduct_research"
