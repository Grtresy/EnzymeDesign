from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from openzyme_host_api.app import create_app
from openzyme_host_api.demo import build_demo_foundation


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
