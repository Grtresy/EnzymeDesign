from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_host_api.app import create_app
from openzyme_host_api.demo import build_demo_foundation
from openzyme_host_api.demo import DemoExecutionAdapter


def test_demo_foundation_preloads_project() -> None:
    foundation = build_demo_foundation()

    project = foundation.repositories.projects.get("proj_001")

    assert project is not None
    assert project.name == "Thermostability demo project"


def test_app_can_mount_ui_when_dist_exists(tmp_path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>demo</body></html>")

    @dataclass(frozen=True, slots=True)
    class DummyDependencies:
        def build_projection_loader(self):
            raise AssertionError("not used in this test")

        def build_service(self):
            raise AssertionError("not used in this test")

    client = TestClient(create_app(DummyDependencies(), ui_dist_dir=dist_dir))  # type: ignore[arg-type]

    response = client.get("/", follow_redirects=False)

    assert response.status_code == 307
    assert response.headers["location"] == "/ui/"


def test_demo_execution_adapter_scopes_run_ids_per_episode_and_call_count() -> None:
    adapter = DemoExecutionAdapter()

    first = adapter.submit_execution("ep_demo", {})
    second = adapter.submit_execution("ep_demo", {})
    third = adapter.submit_execution("ep_other", {})

    assert first.run_id == "run_ep_demo_1"
    assert second.run_id == "run_ep_demo_2"
    assert third.run_id == "run_ep_other_1"
    assert first.status is RunStatus.SUCCEEDED
    assert first.remote_run_dir == "/demo/ep_demo/run_ep_demo_1"
    assert first.artifacts[0].kind is ArtifactKind.LOG
