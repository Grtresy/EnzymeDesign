from __future__ import annotations

from contextlib import contextmanager

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import Project
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_host_api.app import HostApiDependencies
from openzyme_host_api.app import create_app
from openzyme_host_api.demo import DemoResearchAdapter
from openzyme_host_api.tracing import build_trace_metadata
from openzyme_host_api.tracing import build_trace_tags
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import reset_settings_cache
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider


class FakeExecutionAdapter:
    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> dict[str, object]:
        return {"episode_id": episode_id, "payload": payload}


class RecordingTrace:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @contextmanager
    def trace(self, name: str, **kwargs):
        record = {"name": name, **kwargs}
        self.calls.append(record)

        class Run:
            def end(self, outputs=None):
                record["outputs"] = outputs

        yield Run()


class RecordingTracingContext:
    def __init__(self) -> None:
        self.calls: list[dict[str, object]] = []

    @contextmanager
    def tracing_context(self, **kwargs):
        self.calls.append(kwargs)
        yield


def _build_client(monkeypatch, recorder: RecordingTrace, tracing_recorder: RecordingTracingContext) -> TestClient:
    saver = InMemorySaver()

    @contextmanager
    def _shared_open(self: PostgresCheckpointerFactory):
        yield saver

    monkeypatch.setenv("OPENZYME_LANGSMITH_TRACING", "true")
    reset_settings_cache()
    monkeypatch.setattr("openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open", _shared_open)
    monkeypatch.setattr("openzyme_host_api.tracing.trace", recorder.trace)
    monkeypatch.setattr("openzyme_host_api.tracing.tracing_context", tracing_recorder.tracing_context)

    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    repositories.projects.save(Project.create("proj_001", "Tracing demo project"))
    foundation = RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://tracing/test")
        ),
        execution_adapter=FakeExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(RepoBackedHpcCatalogProvider()),
        research_adapter=DemoResearchAdapter(),
    )
    return TestClient(
        create_app(
            HostApiDependencies(
                foundation=foundation,
                graph_builder=build_v2_supervisor_graph,
            )
        )
    )


def test_trace_helpers_include_episode_scoped_metadata() -> None:
    assert build_trace_tags(
        action="resolve_approval",
        project_id="proj_001",
        episode_id="ep_001",
        phase="design",
        approval_id="approval_001",
    ) == [
        "action:resolve_approval",
        "project:proj_001",
        "episode:ep_001",
        "phase:design",
        "approval:approval_001",
    ]
    assert build_trace_metadata(
        action="create_episode",
        project_id="proj_001",
        episode_id="ep_001",
        phase="design",
        request_method="POST",
        request_path="/commands/create_episode",
    ) == {
        "action": "create_episode",
        "project_id": "proj_001",
        "episode_id": "ep_001",
        "phase": "design",
        "request_method": "POST",
        "request_path": "/commands/create_episode",
    }


def test_tracing_hooks_do_not_break_create_episode_flow(monkeypatch) -> None:
    recorder = RecordingTrace()
    tracing_recorder = RecordingTracingContext()
    client = _build_client(monkeypatch, recorder, tracing_recorder)

    response = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Trace this routed workflow"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"]["workflow"]["current_phase"] in {"design", "execution", "report_review"}
    assert any(call["name"] == "host.create_episode" for call in recorder.calls)
    assert any(call["metadata"]["request_path"] == "/commands/create_episode" for call in tracing_recorder.calls)
    reset_settings_cache()
