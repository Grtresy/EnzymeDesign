from openzyme_runtime import DEFAULT_HOST_BASE_URL
from openzyme_runtime import DEFAULT_HOST_API_BIND_HOST
from openzyme_runtime import DEFAULT_HOST_API_BIND_PORT
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_BASE_URL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_MODEL
from openzyme_runtime import get_settings
from openzyme_runtime import reset_settings_cache


def test_settings_use_defaults_when_env_missing(monkeypatch) -> None:
    for key in (
        "OPENZYME_LLM_API_KEY",
        "BIGMODEL_API_KEY",
        "ZHIPUAI_API_KEY",
        "OPENZYME_LLM_MODEL",
        "OPENZYME_LLM_BASE_URL",
        "OPENZYME_RESEARCH_MAX_UNITS",
        "OPENZYME_HOST_BASE_URL",
        "OPENZYME_LANGSMITH_TRACING",
        "LANGSMITH_TRACING",
    ):
        monkeypatch.delenv(key, raising=False)

    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.api_key is None
    assert settings.llm.model == DEFAULT_OPENAI_COMPAT_MODEL
    assert settings.llm.base_url == DEFAULT_OPENAI_COMPAT_BASE_URL
    assert settings.research.max_units == 3
    assert settings.host_cli.base_url == DEFAULT_HOST_BASE_URL
    assert settings.host_api.bind_host == DEFAULT_HOST_API_BIND_HOST
    assert settings.host_api.bind_port == DEFAULT_HOST_API_BIND_PORT
    assert settings.tracing.enabled is False


def test_settings_honor_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("OPENZYME_LLM_MODEL", "custom-model")
    monkeypatch.setenv("OPENZYME_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENZYME_LLM_TIMEOUT", "42")
    monkeypatch.setenv("OPENZYME_LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("OPENZYME_LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("OPENZYME_RESEARCH_MAX_UNITS", "7")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("OPENZYME_TAVILY_MAX_RESULTS", "9")
    monkeypatch.setenv("OPENZYME_TAVILY_TOPIC", "news")
    monkeypatch.setenv("OPENZYME_HOST_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("OPENZYME_PROJECT_ID", "proj_test")
    monkeypatch.setenv("OPENZYME_EPISODE_ID", "ep_test")
    monkeypatch.setenv("OPENZYME_OUTPUT_FORMAT", "json")
    monkeypatch.setenv("OPENZYME_HOST_API_HOST", "0.0.0.0")
    monkeypatch.setenv("OPENZYME_HOST_API_PORT", "9000")
    monkeypatch.setenv("OPENZYME_LANGSMITH_TRACING", "true")
    monkeypatch.setenv("OPENZYME_LANGSMITH_PROJECT", "openzyme-test")
    monkeypatch.setenv("OPENZYME_EXECUTION_BACKEND", "hpc")
    monkeypatch.setenv("OPENZYME_HPC_RUNNER_CONFIG", "/tmp/hpc.toml")

    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.api_key == "llm-key"
    assert settings.llm.model == "custom-model"
    assert settings.llm.base_url == "https://example.test/v1"
    assert settings.llm.timeout == 42.0
    assert settings.llm.max_retries == 5
    assert settings.llm.temperature == 0.25
    assert settings.research.max_units == 7
    assert settings.research.tavily_api_key == "tavily-key"
    assert settings.research.tavily_max_results == 9
    assert settings.research.tavily_topic == "news"
    assert settings.host_cli.base_url == "http://localhost:9999"
    assert settings.host_cli.project_id == "proj_test"
    assert settings.host_cli.episode_id == "ep_test"
    assert settings.host_cli.output_format == "json"
    assert settings.host_api.bind_host == "0.0.0.0"
    assert settings.host_api.bind_port == 9000
    assert settings.tracing.enabled is True
    assert settings.tracing.project_name == "openzyme-test"
    assert settings.execution.backend == "hpc"
    assert settings.execution.hpc_runner_config == "/tmp/hpc.toml"


def test_settings_cache_can_be_reset(monkeypatch) -> None:
    monkeypatch.setenv("OPENZYME_LLM_MODEL", "first")
    reset_settings_cache()
    assert get_settings().llm.model == "first"

    monkeypatch.setenv("OPENZYME_LLM_MODEL", "second")
    assert get_settings().llm.model == "first"

    reset_settings_cache()
    assert get_settings().llm.model == "second"
