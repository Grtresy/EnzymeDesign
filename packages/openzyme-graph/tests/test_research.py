from contextlib import contextmanager

from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import Episode
from openzyme_domain import Project
from openzyme_domain import SourceRefKind
from openzyme_graph.research import build_phase_c_research_graph
from openzyme_runtime import EvidenceSynthesis
from openzyme_runtime import GraphRuntimeFacade
from openzyme_runtime import HostApiSettings
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import ResearchUnitDraft
from openzyme_runtime import ResearchSettings
from openzyme_runtime import ResearchUnitPlan
from openzyme_runtime import reset_settings_cache
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import LiveLlmTestSettings as RuntimeLiveLlmTestSettings
from openzyme_runtime import TestSettings as RuntimeTestSettings
from openzyme_runtime import LlmSettings
from openzyme_runtime import TracingSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import build_episode_graph_config
from openzyme_runtime import connect_sqlite
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult


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
    monkeypatch.setenv("OPENZYME_RESEARCH_MAX_UNITS", "3")
    reset_settings_cache()
    foundation, adapter = _build_foundation()
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    max_units = 3
    research_units = [
        {"unit_id": f"unit_{index}", "topic": f"topic {index}", "query": f"query {index}"}
        for index in range(1, max_units + 3)
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

    assert set(adapter.calls) == {f"unit_{index}" for index in range(1, max_units + 1)}
    assert len(adapter.calls) == max_units


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


def test_phase_c_research_graph_uses_structured_plan_and_synthesis(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    foundation, adapter = _build_foundation()
    foundation = RuntimeFoundation(
        repositories=foundation.repositories,
        checkpointer_factory=foundation.checkpointer_factory,
        research_adapter=adapter,
        model_factory=FakeModelFactory(
            {
                "research_plan": ResearchUnitPlan(
                    units=[
                        ResearchUnitDraft(
                            unit_id="plan_1",
                            topic="planned topic",
                            query="planned query",
                            rationale="planned rationale",
                        )
                    ],
                    synthesis_goal="planned synthesis",
                ),
                "research_synthesis": EvidenceSynthesis(
                    summary="Structured research summary",
                    unresolved_gaps=["Structured gap"],
                ),
            }
        ),
    )
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

    assert result["research_summary"]["summary"] == "Structured research summary"
    assert result["unresolved_gaps"][0]["summary"] == "Structured gap"
    assert adapter.calls == ["plan_1"]


def test_phase_c_research_graph_respects_settings_max_units(monkeypatch) -> None:
    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _memory_checkpointer_open,
    )
    reset_settings_cache()
    foundation, adapter = _build_foundation()
    foundation = RuntimeFoundation(
        repositories=foundation.repositories,
        checkpointer_factory=foundation.checkpointer_factory,
        research_adapter=adapter,
        settings=OpenZymeSettings(
            llm=LlmSettings(
                api_key=None,
                model="glm-5.1",
                base_url="https://open.bigmodel.cn/api/coding/paas/v4",
                extra_body=None,
                max_tokens=None,
                timeout=None,
                max_retries=1,
                temperature=0.0,
                structured_output_method="function_calling",
                structured_output_max_attempts=3,
                structured_output_retry_backoff_seconds=1.0,
                purpose_policies={},
            ),
            research=ResearchSettings(
                max_units=1,
                tavily_api_key=None,
                tavily_max_results=3,
                tavily_topic="general",
            ),
            tracing=TracingSettings(enabled=False, project_name="openzyme-v2"),
            host_cli=HostCliSettings(
                base_url="http://127.0.0.1:8000",
                project_id=None,
                episode_id=None,
                output_format="text",
            ),
            host_api=HostApiSettings(bind_host="127.0.0.1", bind_port=8000),
            execution=ExecutionSettings(backend="demo", hpc_runner_config=None),
            test=RuntimeTestSettings(
                enable_live_llm=False,
                enable_live_tavily=False,
                enable_live_hpc=False,
                enable_live_e2e=False,
                enable_quality_eval=False,
                upload_langsmith=False,
                live_llm=RuntimeLiveLlmTestSettings(
                    max_tokens=None,
                    timeout=None,
                    max_retries=None,
                    structured_output_method=None,
                    structured_output_max_attempts=None,
                    structured_output_retry_backoff_seconds=None,
                ),
            ),
        ),
    )
    facade = GraphRuntimeFacade(foundation)
    config = build_episode_graph_config("ep_001")

    with facade.compile_graph(build_phase_c_research_graph) as graph:
        graph.invoke(
            {
                "episode_id": "ep_001",
                "project_id": "proj_001",
                "objective": "Map enzyme thermostability evidence",
                "research_brief": "Bound worker count from settings.",
            },
            config,
        )

    assert adapter.calls == ["literature"]
