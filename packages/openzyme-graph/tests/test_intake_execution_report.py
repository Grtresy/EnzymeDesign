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
from openzyme_graph.intake import build_intake_subgraph
from openzyme_graph.report_review import build_report_review_subgraph
from openzyme_runtime import ConstraintItem
from openzyme_runtime import ConstraintSet
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import IntakeClarification
from openzyme_runtime import IntakePhaseOutput
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import DesignBriefDraft
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_runtime import ReportDraft
from openzyme_runtime import ResearchBriefDraft


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


class FakeStructuredInvoker:
    def __init__(self, response_by_purpose: dict[str, object], calls: list[str]) -> None:
        self._response_by_purpose = response_by_purpose
        self._calls = calls

    def invoke_structured(self, *, schema, system_prompt: str, user_payload: dict[str, object]):
        del schema, system_prompt, user_payload
        self._calls.append("called")
        return self._response_by_purpose.popitem()[1]


class FakeModelFactory:
    def __init__(self, response_by_purpose: dict[str, object]) -> None:
        self._response_by_purpose = response_by_purpose
        self.calls: list[str] = []

    def create_structured_invoker(self, *, purpose: str) -> FakeStructuredInvoker:
        return FakeStructuredInvoker({purpose: self._response_by_purpose[purpose]}, self.calls)


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
    assert result["intake_handoff"]["recommended_next_phase"] == "design"
    assert result["intake_handoff"]["design_brief"].startswith("Design brief")


def test_intake_subgraph_uses_structured_model_output_when_available(monkeypatch) -> None:
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
                "intake_collect": IntakePhaseOutput(
                    clarification=IntakeClarification(needs_clarification=False),
                    constraint_set=ConstraintSet(
                        objective_summary="Structured objective",
                        constraints=[ConstraintItem(description="Keep the change bounded.")],
                    ),
                    design_brief=DesignBriefDraft(design_brief="Structured design brief"),
                    research_brief=ResearchBriefDraft(research_brief="Structured research brief"),
                )
            }
        ),
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_intake_subgraph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Use structured intake",
            },
            config,
        )

    assert result["design_brief"] == "Structured design brief"
    assert result["research_brief"] == "Structured research brief"
    assert result["constraint_set"]["objective_summary"] == "Structured objective"


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
                "design_handoff": {
                    "artifact_workspace_summary": {"artifact_count": 1, "execution_ready_artifact_ids": ["art_001"]},
                    "run_summary": {"run_id": "run_001", "execution_mode": "ssh"},
                    "artifact_refs": [{"artifact_id": "art_001"}],
                    "design_summary": {
                        "message": "Design loop completed.",
                        "research_summary": {"summary": "Research completed."},
                    },
                    "recommended_next_phase": "report_review",
                },
            },
            config,
        )

    assert result["status"] == "completed"
    assert result["report_summary"]["report_id"] == "ep_001-report"
    assert result["report_artifact_id"] == "ep_001-report-artifact"


def test_report_review_subgraph_uses_structured_report_draft(monkeypatch) -> None:
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
                "report_review": ReportDraft(
                    title="Structured final report",
                    summary="Structured summary",
                    stage_summary="Structured stage summary",
                    key_decisions=["approve candidate"],
                )
            }
        ),
    )
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
                "objective": "Structured report",
                "design_handoff": {
                    "artifact_workspace_summary": {"artifact_count": 1, "execution_ready_artifact_ids": ["art_001"]},
                    "run_summary": {"run_id": "run_001", "execution_mode": "ssh"},
                    "artifact_refs": [{"artifact_id": "art_001"}],
                    "design_summary": {
                        "message": "Design loop completed.",
                        "research_summary": {"summary": "Research completed."},
                    },
                    "recommended_next_phase": "report_review",
                },
            },
            config,
        )

    assert result["report_summary"]["title"] == "Structured final report"
    assert result["report_draft"]["summary"] == "Structured summary"
