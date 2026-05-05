from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import RunStatus
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_graph.execution import build_execution_subgraph
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider


class FakeExecutionAdapter:
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
        assert payload["tool_name"] == "exec.run"
        runspec = payload["runspec"]
        assert runspec["metadata"]["tool_contract"]["adapter_id"] == "fpocket"
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
            ),
            raw_result={"status": "completed", "pockets_found": 2},
        )


@contextmanager
def _memory_checkpointer_open(self: PostgresCheckpointerFactory):
    yield InMemorySaver()


def _build_foundation() -> RuntimeFoundation:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    project = Project.create("proj_001", "Execution project")
    repositories.projects.save(project)
    repositories.episodes.save(
        Episode.create(
            episode_id="ep_001",
            project_id=project.project_id,
            objective="Evaluate the selected candidate",
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
            PostgresCheckpointerConfig(conn_string="postgresql://phase-c/execution")
        ),
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider()),
    )


def test_execution_subgraph_discovers_fpocket_and_submits_after_approval(monkeypatch) -> None:
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
                "execution_handoff": {
                    "execution_goal": "Run a fast pocket evaluator",
                    "question_to_answer": "Which evaluator should run first?",
                    "required_artifact_ids": ["art_input_structure"],
                    "context_artifact_ids": [],
                    "preferred_stage_tags": ["execution", "evaluator"],
                    "preferred_capability_tags": ["pocket_detection"],
                    "recommended_next_phase": "execution",
                },
            },
            config,
        )
        result = graph.invoke(Command(resume={"approved": True}), config)

    assert first["__interrupt__"][0].value["phase"] == "execution"
    assert result["recommended_next_phase"] == "design"
    assert result["execution_result_handoff"]["catalog_tool_id"] == "fpocket"
    assert result["execution_result_handoff"]["output_artifact_ids"] == ["run_001-artifact-1"]
    assert result["execution_result_handoff"]["run_summary"]["run_id"] == "run_001"
    assert len(foundation.repositories.runs.list_by_episode("ep_001")) == 1
