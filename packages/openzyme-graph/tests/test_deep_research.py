from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import SourceRefKind
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_runtime import GraphAssemblyInputs
from openzyme_runtime import DefaultResearchToolProvider
from openzyme_runtime import OpenZymeHostToolbox
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_runtime import get_settings
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult

from openzyme_graph.deep_research import run_deep_research


class FakeResearchAdapter:
    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        del episode_id, research_brief
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} summary for {unit.query}",
            findings=(
                ResearchFinding(
                    summary=f"Finding for {unit.query}",
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Source for {unit.unit_id}",
                            locator=f"https://example.org/{unit.unit_id}",
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need experimental validation.",),
        )


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
        research_adapter=foundation.research_adapter,
        research_tool_provider=DefaultResearchToolProvider(foundation.research_adapter),
        projection_loader=None,
        model_factory=None,
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

    assert dossier.research_brief.startswith("Find evidence")
    assert dossier.summary
    assert len(dossier.evidence_items) >= 1
    assert dossier.evidence_items[0].sources[0].locator.startswith("https://example.org/")
    assert "Need experimental validation." in dossier.unresolved_gaps
    assert dossier.recent_turns[0].action_kind == "conduct_research"
