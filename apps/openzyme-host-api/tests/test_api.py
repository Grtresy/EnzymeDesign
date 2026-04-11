from __future__ import annotations

import json
from contextlib import contextmanager

from fastapi.testclient import TestClient
from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import Project
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import create_app
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import PostgresCheckpointerConfig
from openzyme_runtime import PostgresCheckpointerFactory
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus


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


def _build_client(monkeypatch) -> TestClient:
    saver = InMemorySaver()

    @contextmanager
    def _shared_open(self: PostgresCheckpointerFactory):
        yield saver

    monkeypatch.setattr(
        "openzyme_runtime.bootstrap.PostgresCheckpointerFactory.open",
        _shared_open,
    )

    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    repositories.projects.save(Project.create("proj_001", "Thermostability project"))
    foundation = RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=PostgresCheckpointerFactory(
            PostgresCheckpointerConfig(conn_string="postgresql://phase-b/memory")
        ),
        execution_adapter=FakeExecutionAdapter(),
    )
    return TestClient(create_app(HostApiDependencies(foundation=foundation)))


def test_create_episode_projects_workspace_and_pending_actions(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    response = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"]["workflow"]["current_phase"] == "execution"
    assert payload["workspace"]["workflow"]["pending_interrupt"]["type"] == "approval"
    assert payload["workspace"]["pending_actions"][0]["status"] == "pending"
    assert {event["event_type"] for event in payload["events"]} >= {
        "workflow.phase_changed",
        "workflow.progress_updated",
        "workflow.interrupt_pending",
        "workflow.approval_pending",
    }

    episode_id = payload["episode_id"]
    workspace = client.get(f"/episodes/{episode_id}/workspace")
    assert workspace.status_code == 200
    assert workspace.json()["workflow"]["pending_approval"]["approval_id"].endswith("-execution-approval")


def test_resolve_approval_advances_episode_and_exposes_runs_and_artifacts(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    ).json()
    episode_id = created["episode_id"]
    approval_id = created["workspace"]["pending_actions"][0]["approval_id"]

    response = client.post(
        "/commands/resolve_approval",
        json={
            "episode_id": episode_id,
            "approval_id": approval_id,
            "decision": "approved",
        },
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["workspace"]["workflow"]["episode_status"] == "completed"
    assert payload["workspace"]["pending_actions"] == []
    assert len(payload["workspace"]["runs"]) == 1
    assert len(payload["workspace"]["artifacts"]) == 2
    assert {event["event_type"] for event in payload["events"]} >= {
        "workflow.progress_updated",
        "workflow.run_status_changed",
        "workflow.artifact_available",
    }

    runs = client.get(f"/episodes/{episode_id}/runs")
    artifacts = client.get(f"/episodes/{episode_id}/artifacts")
    pending = client.get(f"/episodes/{episode_id}/pending-actions")
    assert runs.json()[0]["status"] == "succeeded"
    assert len(artifacts.json()) == 2
    assert pending.json() == []


def test_resume_and_stream_endpoint_emit_projected_host_events(monkeypatch) -> None:
    client = _build_client(monkeypatch)

    created = client.post(
        "/commands/create_episode",
        json={"project_id": "proj_001", "objective": "Improve thermostability"},
    ).json()
    episode_id = created["episode_id"]

    resumed = client.post(
        "/commands/resume_episode",
        json={
            "episode_id": episode_id,
            "resume_payload": {"approved": True},
        },
    )
    assert resumed.status_code == 200

    stream_response = client.get(f"/episodes/{episode_id}/stream")
    assert stream_response.status_code == 200
    lines = [line for line in stream_response.text.splitlines() if line.startswith("data: ")]
    events = [json.loads(line[6:]) for line in lines]
    event_types = {event["event_type"] for event in events}

    assert "workflow.phase_changed" in event_types
    assert "workflow.progress_updated" in event_types
    assert "workflow.run_status_changed" in event_types
    assert "workflow.artifact_available" in event_types
