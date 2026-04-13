from __future__ import annotations

from dataclasses import replace

from openzyme_host_api.foundation import DemoExecutionAdapter
from openzyme_host_api.foundation import DemoResearchAdapter
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_configured_foundation
from openzyme_runtime import ExecutionSettings
from openzyme_runtime import HostApiSettings
from openzyme_runtime import HostCliSettings
from openzyme_runtime import LiveLlmTestSettings as RuntimeLiveLlmTestSettings
from openzyme_runtime import LlmPurposePolicy
from openzyme_runtime import LlmSettings
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import ResearchSettings
from openzyme_runtime import TestSettings as RuntimeTestSettings
from openzyme_runtime import TracingSettings
from openzyme_runtime import OpenAICompatibleChatModelFactory


def _settings() -> OpenZymeSettings:
    return OpenZymeSettings(
        llm=LlmSettings(
            api_key="llm-key",
            model="glm-5.1",
            base_url="https://open.bigmodel.cn/api/coding/paas/v4",
            extra_body={"provider": "bigmodel"},
            max_tokens=800,
            timeout=30.0,
            max_retries=1,
            temperature=0.0,
            structured_output_method="function_calling",
            structured_output_max_attempts=3,
            structured_output_retry_backoff_seconds=1.0,
            purpose_policies={},
        ),
        research=ResearchSettings(
            max_units=3,
            tavily_api_key=None,
            tavily_max_results=3,
            tavily_topic="general",
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

    assert isinstance(foundation.execution_adapter, DemoExecutionAdapter)
    assert isinstance(foundation.research_adapter, DemoResearchAdapter)
    assert isinstance(foundation.model_factory, OpenAICompatibleChatModelFactory)


def test_configured_foundation_uses_hpc_and_tavily_when_enabled(tmp_path, monkeypatch) -> None:
    configured_settings = replace(
        _settings(),
        research=ResearchSettings(
            max_units=5,
            tavily_api_key="tavily-key",
            tavily_max_results=4,
            tavily_topic="news",
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
    assert constrained.llm.max_retries == 1
    assert constrained.llm.structured_output_method == "function_calling"
    assert constrained.llm.structured_output_max_attempts == 2
    assert constrained.llm.structured_output_retry_backoff_seconds == 0.25
    assert constrained.llm.purpose_policies == {}
