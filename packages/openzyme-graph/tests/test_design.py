from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.types import Command
from openzyme_domain import ArtifactKind
from openzyme_domain import Episode
from openzyme_domain import EvidenceRecord
from openzyme_domain import Project
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import RunStatus
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_graph.design import build_phase_c_design_graph
from openzyme_runtime import CandidateComparison
from openzyme_runtime import CandidateDraft
from openzyme_runtime import CandidateDraftCollection
from openzyme_runtime import CandidateRankingDraft
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
            raw_result={"status": "completed"},
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


def _build_foundation(*, with_research: bool = True) -> RuntimeFoundation:
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
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-c/design")
        ),
        execution_adapter=FakeExecutionAdapter(),
    )


def test_phase_c_design_graph_persists_candidates_and_waits_for_review(monkeypatch) -> None:
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
        snapshot = graph.get_state(config)

    assert first["__interrupt__"][0].value["type"] == "approval"
    assert snapshot.values["current_phase"] == "design"
    assert snapshot.values["pending_interrupt"]["approval_id"].startswith("ep_001-design-approval-")
    assert len(foundation.repositories.candidates.list_by_episode("ep_001")) == 2
    assert len(foundation.repositories.candidate_rankings.list_by_episode("ep_001")) == 2


def test_phase_c_design_graph_resumes_review_executes_run_and_builds_report_handoff(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )
        result = graph.invoke(Command(resume={"approved": True}), config)

    assert result["status"] == "completed"
    assert result["recommended_next_phase"] == "report_review"
    assert result["candidate_plan"]["candidate_id"].startswith("ep_001-candidate-")
    assert result["run_request"]["runspec"]["metadata"]["candidate_id"] == result["candidate_plan"]["candidate_id"]
    assert result["run_summary"]["run_id"] == "run_001"
    assert result["design_handoff"]["run_summary"]["run_id"] == "run_001"
    assert foundation.repositories.selected_candidates.get_by_episode("ep_001") is not None


def test_phase_c_design_graph_collects_research_inside_design_when_missing(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation(with_research=False)
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

    assert result["__interrupt__"][0].value["type"] == "approval"
    assert foundation.repositories.research_summaries.get_by_episode("ep_001") is not None
    assert len(foundation.repositories.evidence_records.list_by_episode("ep_001")) >= 1


def test_phase_c_design_graph_uses_structured_candidate_outputs_and_deterministic_execution_request(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation = _build_foundation()
    foundation = RuntimeFoundation(
        repositories=foundation.repositories,
        checkpointer_factory=foundation.checkpointer_factory,
        execution_adapter=foundation.execution_adapter,
        model_factory=FakeModelFactory(
            {
                "design_candidates": CandidateDraftCollection(
                    candidates=[
                        CandidateDraft(
                            candidate_id="cand_structured",
                            title="Structured candidate",
                            summary="Structured candidate summary",
                            supporting_evidence_ids=["ev_001"],
                            rationale="Structured rationale",
                        )
                    ]
                ),
                "design_ranking": CandidateComparison(
                    selected_candidate_id="cand_structured",
                    selected_candidate_rationale="Structured selected rationale",
                    approval_summary="Approve structured candidate",
                    rankings=[
                        CandidateRankingDraft(
                            candidate_id="cand_structured",
                            rank=1,
                            rationale="Best structured option",
                        )
                    ],
                ),
            }
        ),
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_design_graph) as graph:
        graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Design a thermostable variant",
            },
            config,
        )
        result = graph.invoke(Command(resume={"approved": True}), config)

    assert result["candidate_plan"]["candidate_id"] == "cand_structured"
    assert result["run_request"]["tool_name"] == "exec.run"
    assert result["run_request"]["runspec"]["name"] == "execution-cand_structured"
    assert result["run_request"]["runspec"]["command"] == ["echo", "Structured candidate"]
    assert result["run_summary"]["run_id"] == "run_001"
