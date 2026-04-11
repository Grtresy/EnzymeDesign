from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import SourceRefKind
from openzyme_graph.research import MAX_RESEARCH_UNITS
from openzyme_graph.research import build_phase_c_research_graph
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


class FakeResearchAdapter:
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.mode = "success"

    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        self.calls.append(unit.unit_id)
        if self.mode == "failure":
            return ResearchUnitResult(
                unit_id=unit.unit_id,
                summary="",
                findings=(),
                unresolved_gaps=(f"retry {unit.query}",),
                error_message="upstream timeout",
            )
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


def _build_foundation() -> tuple[RuntimeFoundation, FakeResearchAdapter]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    project = Project.create("proj_001", "Research project")
    repositories.projects.save(project)
    repositories.episodes.save(
        Episode.create(
            episode_id="ep_001",
            project_id=project.project_id,
            objective="Map enzyme thermostability evidence",
        )
    )
    adapter = FakeResearchAdapter()
    foundation = RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-c/memory")
        ),
        research_adapter=adapter,
    )
    return foundation, adapter


def test_phase_c_research_graph_fans_out_and_persists_canonical_outputs(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation, adapter = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_research_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Map enzyme thermostability evidence",
                "research_brief": "Find public evidence and unresolved questions.",
            },
            config,
        )
        snapshot = graph.get_state(config)

    assert result["status"] == "completed"
    assert result["recommended_next_phase"] == "design"
    assert len(adapter.calls) == 2
    assert snapshot.values["current_phase"] == "research"
    assert snapshot.values["progress"]["phase"] == "research"

    evidence = foundation.repositories.evidence_records.list_by_episode("ep_001")
    source_refs = foundation.repositories.source_refs.list_by_episode("ep_001")
    summary = foundation.repositories.research_summaries.get_by_episode("ep_001")
    gaps = foundation.repositories.unresolved_gaps.list_by_episode("ep_001")

    assert len(evidence) == 2
    assert len(source_refs) == 2
    assert summary is not None
    assert summary.summary.startswith("literature evidence supports")
    assert len(gaps) == 2


def test_phase_c_research_graph_bounds_parallel_worker_count(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation, adapter = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    research_units = [
        {"unit_id": f"unit_{index}", "topic": f"topic {index}", "query": f"query {index}"}
        for index in range(1, MAX_RESEARCH_UNITS + 3)
    ]

    with facade.compile_graph(build_phase_c_research_graph) as graph:
        graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Map enzyme thermostability evidence",
                "research_brief": "Bound worker count.",
                "research_units": research_units,
            },
            config,
        )

    assert set(adapter.calls) == {f"unit_{index}" for index in range(1, MAX_RESEARCH_UNITS + 1)}
    assert len(adapter.calls) == MAX_RESEARCH_UNITS


def test_phase_c_research_graph_projects_recoverable_failures_on_same_episode_thread(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation, adapter = _build_foundation()
    adapter.mode = "failure"
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_research_graph) as graph:
        result = graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Map enzyme thermostability evidence",
                "research_brief": "Force recoverable failure.",
            },
            config,
        )
        snapshot = graph.get_state(config)

    assert result["status"] == "interrupted"
    assert result["pending_interrupt"]["type"] == "recoverable_failure"
    assert snapshot.values["pending_interrupt"]["episode_id"] == "ep_001"
    assert foundation.repositories.evidence_records.list_by_episode("ep_001") == []
