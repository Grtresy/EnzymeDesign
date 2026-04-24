from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

from fastapi.testclient import TestClient
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_host_api.app import create_app
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_host_api.foundation import build_local_eval_foundation
from openzyme_host_api.foundation import build_model_factory_from_env
from openzyme_host_api.foundation import DeterministicExecutionAdapter
from openzyme_host_api.foundation import DeterministicResearchAdapter
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_BASE_URL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_MODEL
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import HostApiSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import LiveLlmTestSettings as RuntimeLiveLlmTestSettings
from openzyme_runtime import LlmPurposePolicy
from openzyme_runtime import LlmSettings
from openzyme_runtime import OpenAICompatibleChatModelFactory
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import ResearchSettings
from openzyme_runtime import reset_settings_cache
from openzyme_runtime import TestSettings as RuntimeTestSettings
from openzyme_runtime import TracingSettings


def _settings() -> OpenZymeSettings:
    return OpenZymeSettings(
        llm=LlmSettings(
            api_key="llm-key",
            model="glm-5.1",
            base_url="https://open.bigmodel.cn/api/coding/paas/v4",
            extra_body={"provider": "bigmodel"},
            max_tokens=800,
            timeout=30.0,
            max_retries=5,
            temperature=0.0,
            structured_output_method="function_calling",
            structured_output_max_attempts=3,
            structured_output_retry_backoff_seconds=1.0,
            purpose_policies={},
        ),
        research=ResearchSettings(
            max_units=3,
            allow_clarification=False,
            max_research_iterations=3,
            max_react_tool_calls=4,
            max_concurrent_research_units=3,
            tavily_api_key=None,
            tavily_max_results=3,
            tavily_topic="general",
            mcp_enabled=False,
        ),
        tracing=TracingSettings(enabled=False, project_name="openzyme-test"),
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
    )


def test_configured_foundation_uses_demo_adapters_without_live_integrations(tmp_path) -> None:
    foundation = build_configured_foundation(
        sqlite_db_path=tmp_path / "foundation.sqlite3",
        settings=_settings(),
    )

    assert isinstance(foundation.execution_adapter, DeterministicExecutionAdapter)
    assert isinstance(foundation.research_adapter, DeterministicResearchAdapter)
    assert isinstance(foundation.model_factory, OpenAICompatibleChatModelFactory)


def test_configured_foundation_uses_hpc_and_tavily_when_enabled(tmp_path, monkeypatch) -> None:
    configured_settings = replace(
        _settings(),
        research=ResearchSettings(
            max_units=5,
            allow_clarification=False,
            max_research_iterations=3,
            max_react_tool_calls=4,
            max_concurrent_research_units=3,
            tavily_api_key="tavily-key",
            tavily_max_results=4,
            tavily_topic="news",
            mcp_enabled=False,
        ),
        execution=ExecutionSettings(backend="hpc", hpc_runner_config="/tmp/hpc.toml"),
    )
    calls: dict[str, object] = {}

    class FakeHpcRunnerExecutionAdapter:
        def __init__(self, config_path: str | None) -> None:
            calls["config_path"] = config_path

    monkeypatch.setattr(
        "openzyme_host_api.foundation.HpcRunnerExecutionAdapter",
        FakeHpcRunnerExecutionAdapter,
    )

    foundation = build_configured_foundation(
        sqlite_db_path=tmp_path / "foundation.sqlite3",
        settings=configured_settings,
    )

    assert calls["config_path"] == "/tmp/hpc.toml"
    assert type(foundation.execution_adapter).__name__ == "FakeHpcRunnerExecutionAdapter"
    assert type(foundation.research_adapter).__name__ == "TavilyResearchAdapter"


def test_apply_live_llm_test_budget_constrains_live_e2e_llm_settings() -> None:
    base = _settings()
    configured_settings = replace(
        base,
        llm=replace(
            base.llm,
            max_tokens=800,
            timeout=60.0,
            max_retries=2,
            structured_output_method="json_schema",
            structured_output_max_attempts=4,
            structured_output_retry_backoff_seconds=2.0,
            purpose_policies={"report_review": LlmPurposePolicy(timeout=90.0)},
        ),
        test=replace(
            base.test,
            enable_live_e2e=True,
            live_llm=RuntimeLiveLlmTestSettings(
                max_tokens=256,
                timeout=12.0,
                max_retries=0,
                structured_output_method="function_calling",
                structured_output_max_attempts=2,
                structured_output_retry_backoff_seconds=0.25,
            ),
        ),
    )

    constrained = apply_live_llm_test_budget(configured_settings)

    assert constrained.llm.max_tokens == 256
    assert constrained.llm.timeout == 12.0
    assert constrained.llm.max_retries == 0
    assert constrained.llm.structured_output_method == "function_calling"
    assert constrained.llm.structured_output_max_attempts == 2
    assert constrained.llm.structured_output_retry_backoff_seconds == 0.25
    assert constrained.llm.purpose_policies == {}


def test_local_eval_foundation_preloads_default_project(tmp_path) -> None:
    foundation = build_local_eval_foundation(sqlite_db_path=tmp_path / "eval.sqlite3")

    project = foundation.repositories.projects.get("proj_001")

    assert project is not None
    assert project.name == "Thermostability local project"


def test_app_can_mount_ui_when_dist_exists(tmp_path) -> None:
    dist_dir = tmp_path / "dist"
    dist_dir.mkdir()
    (dist_dir / "index.html").write_text("<html><body>ui</body></html>")
    (dist_dir / "debug.html").write_text("<html><body>debug</body></html>")

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
    assert client.get("/debug").text == "<html><body>debug</body></html>"


def test_deterministic_execution_adapter_scopes_run_ids_per_episode_and_call_count() -> None:
    adapter = DeterministicExecutionAdapter()

    first = adapter.submit_execution("ep_local", {})
    second = adapter.submit_execution("ep_local", {})
    third = adapter.submit_execution("ep_other", {})

    assert first.run_id == "run_ep_local_1"
    assert second.run_id == "run_ep_local_2"
    assert third.run_id == "run_ep_other_1"
    assert first.status is RunStatus.SUCCEEDED
    assert first.remote_run_dir == "/local/ep_local/run_ep_local_1"
    assert first.artifacts[0].kind is ArtifactKind.LOG


def test_build_model_factory_from_env_returns_none_without_api_key(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "")
    monkeypatch.setenv("BIGMODEL_API_KEY", "")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "")

    assert build_model_factory_from_env() is None


def test_build_model_factory_from_env_uses_bigmodel_defaults(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "test-key")
    monkeypatch.delenv("OPENZYME_LLM_MODEL", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_BASE_URL", raising=False)
    monkeypatch.delenv("OPENZYME_LLM_EXTRA_BODY", raising=False)
    monkeypatch.setenv("OPENZYME_LLM_MAX_RETRIES", "5")

    factory = build_model_factory_from_env()

    assert isinstance(factory, OpenAICompatibleChatModelFactory)
    assert factory.model == DEFAULT_OPENAI_COMPAT_MODEL
    assert factory.base_url == DEFAULT_OPENAI_COMPAT_BASE_URL
    assert factory.api_key == "test-key"
    assert factory.extra_body == {"provider": "bigmodel"}
    assert factory.max_retries == 5
    reset_settings_cache()
