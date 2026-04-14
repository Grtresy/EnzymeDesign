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
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
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
        from openzyme_research import ResearchFinding
        from openzyme_research import ResearchSource
        from openzyme_research import ResearchUnitResult

        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the design objective.",
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
            unresolved_gaps=("Need follow-up validation.",),
        )


class FakeStructuredInvoker:
    def __init__(self, responses: dict[str, object], calls: list[str], purpose: str) -> None:
        self._response = responses[purpose]
        self._calls = calls
        self._purpose = purpose

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del schema, system_prompt, user_payload
        self._calls.append(self._purpose)
        return self._response


class FakeModelFactory:
    def __init__(self, responses: dict[str, object]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def create_structured_invoker(self, *, purpose: str) -> FakeStructuredInvoker:
        return FakeStructuredInvoker(self._responses, self.calls, purpose)


@contextmanager
def _memory_checkpointer_open(self: PostgresCheckpointerFactory):
    yield InMemorySaver()


def _build_foundation(*, with_research: bool = True, with_research_adapter: bool = False) -> RuntimeFoundation:
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
        hpc_execution_registry=DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider()),
        research_adapter=FakeResearchAdapter() if with_research_adapter else None,
    )


def test_phase_c_design_graph_curates_artifacts_and_prepares_execution_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
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
    assert first["execution_handoff"]["required_artifact_ids"] == ["art_input_structure"]
    assert first["artifact_workspace_summary"]["artifact_count"] >= 1


def test_phase_c_design_graph_routes_curated_artifacts_into_execution(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
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
    assert result["execution_handoff"]["required_artifact_ids"] == ["art_input_structure"]
    assert "art_input_structure" in result["artifact_workspace_summary"]["execution_ready_artifact_ids"]


def test_phase_c_design_graph_collects_research_inside_design_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation(with_research=False, with_research_adapter=True)
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
    assert foundation.repositories.research_summaries.get_by_episode("ep_001") is not None
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
    assert result["execution_handoff"]["required_artifact_ids"] == ["art_input_structure"]
    assert result["execution_handoff"]["preferred_stage_tags"] == ["execution", "evaluator"]
