from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openzyme_domain import ArtifactKind
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_graph.execution import build_execution_subgraph
from openzyme_graph.intake import build_intake_subgraph
from openzyme_graph.report_review import build_report_review_subgraph
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite


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


@contextmanager
def _memory_checkpointer_open(self: PostgresCheckpointerFactory):
    yield InMemorySaver()


def _build_foundation() -> RuntimeFoundation:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    project = Project.create("proj_001", "Step 1 extraction")
    repositories.projects.save(project)
    repositories.episodes.save(
        Episode.create(
            episode_id="ep_001",
            project_id=project.project_id,
            objective="Extract specialist subgraphs",
        )
    )
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://step1/subgraphs")
        ),
        execution_adapter=FakeExecutionAdapter(),
    )


def test_intake_subgraph_emits_explicit_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_intake_subgraph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Extract specialist subgraphs",
                "user_goal": "Research and design the best candidate",
            },
            config,
        )

    assert result["status"] == "active"
    assert result["intake_handoff"]["recommended_next_phase"] == "research"
    assert result["intake_handoff"]["design_brief"].startswith("Design brief")


def test_execution_subgraph_approves_and_emits_execution_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_execution_subgraph) as graph:
        first = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "candidate_plan": {"candidate_id": "cand_001"},
                "run_request": {"tool_name": "exec.run", "runspec": {"name": "test", "command": ["echo", "ok"]}},
            },
            config,
        )
        result = graph.invoke(Command(resume={"approved": True}), config)

    assert first["__interrupt__"][0].value["type"] == "approval"
    assert result["status"] == "completed"
    assert result["execution_handoff"]["latest_run_id"] == "run_001"
    assert result["execution_handoff"]["recommended_next_phase"] == "report_review"


def test_report_review_subgraph_persists_final_report(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_report_review_subgraph) as graph:
        foundation.repositories.runs.save(
            Run(
                run_id="run_001",
                episode_id="ep_001",
                approval_id=None,
                status=RunStatus.SUCCEEDED,
                execution_mode="ssh",
                created_at="2026-04-12T00:00:00+00:00",
                completed_at="2026-04-12T00:05:00+00:00",
            )
        )
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "objective": "Extract specialist subgraphs",
                "selected_candidate_id": "cand_001",
                "research_summary": {"summary": "Research completed."},
                "run_summary": {"run_id": "run_001", "execution_mode": "ssh"},
                "artifact_refs": [{"artifact_id": "art_001"}],
            },
            config,
        )

    assert result["status"] == "completed"
    assert result["report_summary"]["report_id"] == "ep_001-report"
    assert result["report_artifact_id"] == "ep_001-report-artifact"
