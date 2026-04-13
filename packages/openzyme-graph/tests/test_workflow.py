from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openzyme_domain import ArtifactKind
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_graph.supervisor import build_v2_supervisor_graph


def _nested_values(snapshot):
    nested = snapshot.tasks[0].state
    return nested.values if hasattr(nested, "values") else {}


class FakeExecutionAdapter:
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
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
            raw_result={"status": "completed"},
        )


class FakeResearchAdapter:
    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the research brief.",
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
            unresolved_gaps=(f"Need follow-up for {unit.unit_id}",),
        )


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
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-b/memory")
        ),
        execution_adapter=FakeExecutionAdapter(),
        research_adapter=FakeResearchAdapter(),
    )


def test_unified_supervisor_routes_design_and_report_review_on_one_thread(monkeypatch) -> None:
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

    assert first["__interrupt__"][0].value["phase"] == "design"
    assert first_snapshot.values["current_phase"] == "design"
    assert _nested_values(first_snapshot)["pending_interrupt"]["approval_id"].startswith("ep_001-design-approval-")
    assert len(foundation.repositories.evidence_records.list_by_episode("ep_001")) == 2
    assert len(foundation.repositories.candidates.list_by_episode("ep_001")) == 2

    assert foundation.repositories.selected_candidates.get_by_episode("ep_001") is not None
    assert second["status"] == "completed"
    assert second["current_phase"] == "report_review"
    assert second["run_summary"]["run_id"] == "run_001"
    assert len(second["artifact_refs"]) == 2
    assert second["report_summary"]["report_id"] == "ep_001-report"
    assert foundation.repositories.reports.get("ep_001-report") is not None


def test_unified_supervisor_only_completes_after_report_review_finishes(monkeypatch) -> None:
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
    assert foundation.repositories.reports.list_by_episode("ep_001")[0].artifact_id == "ep_001-report-artifact"
