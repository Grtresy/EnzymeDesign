from __future__ import annotations

from dataclasses import dataclass

from fastapi.testclient import TestClient

from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_host_api.app import create_app
from openzyme_host_api.demo import build_demo_foundation
from openzyme_host_api.demo import build_model_factory_from_env
from openzyme_host_api.demo import DemoExecutionAdapter
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_BASE_URL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_MODEL
from openzyme_runtime import OpenAICompatibleChatModelFactory
from openzyme_runtime import reset_settings_cache


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


def test_build_model_factory_from_env_returns_none_without_api_key(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.delenv("OPENZYME_LLM_API_KEY", raising=False)
    monkeypatch.delenv("BIGMODEL_API_KEY", raising=False)
    monkeypatch.delenv("ZHIPUAI_API_KEY", raising=False)

    assert build_model_factory_from_env() is None


def test_build_model_factory_from_env_uses_bigmodel_defaults(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "test-key")
    monkeypatch.delenv("OPENZYME_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_BASE_URL", raising=False)

    factory = build_model_factory_from_env()

    assert isinstance(factory, OpenAICompatibleChatModelFactory)
    assert factory.model == DEFAULT_OPENAI_COMPAT_MODEL
    assert factory.base_url == DEFAULT_OPENAI_COMPAT_BASE_URL
    assert factory.api_key == "test-key"
    reset_settings_cache()


def test_demo_main_uses_host_api_bind_settings(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_HOST_API_HOST", "0.0.0.0")
    monkeypatch.setenv("OPENZYME_HOST_API_PORT", "9100")

    calls: dict[str, object] = {}

    def _fake_run(app, *, host: str, port: int, log_level: str) -> None:
        calls["app"] = app
        calls["host"] = host
        calls["port"] = port
        calls["log_level"] = log_level

    monkeypatch.setattr("openzyme_host_api.demo.uvicorn.run", _fake_run)

    from openzyme_host_api.demo import main

    main()

    assert calls["host"] == "0.0.0.0"
    assert calls["port"] == 9100
    assert calls["log_level"] == "info"
    reset_settings_cache()
