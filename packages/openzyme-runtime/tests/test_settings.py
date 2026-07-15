from openzyme_runtime import DEFAULT_HOST_BASE_URL
from openzyme_runtime import DEFAULT_HOST_API_BIND_HOST
from openzyme_runtime import DEFAULT_HOST_API_BIND_PORT
from openzyme_runtime import DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD
from openzyme_runtime import DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_BASE_URL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_EXTRA_BODY
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_MODEL
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_USER_AGENT
from openzyme_runtime import DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API
from openzyme_runtime import DEFAULT_PROVIDER_LIMITS
from openzyme_runtime import get_settings
from openzyme_runtime import reset_settings_cache


def _disable_env_file_loading(monkeypatch) -> None:
    monkeypatch.setattr("openzyme_runtime.settings.load_env_files", lambda: None)


def test_settings_use_defaults_when_env_missing(monkeypatch) -> None:
    _disable_env_file_loading(monkeypatch)
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "")
    monkeypatch.setenv("MICU_API_KEY", "")
    monkeypatch.setenv("BIGMODEL_API_KEY", "")
    monkeypatch.setenv("ZHIPUAI_API_KEY", "")
    for key in (
        "OPENZYME_LLM_MODEL",
        "OPENZYME_LLM_BASE_URL",
        "OPENZYME_LLM_USER_AGENT",
        "OPENZYME_LLM_USE_RESPONSES_API",
        "OPENZYME_LLM_TIMEOUT",
        "OPENZYME_LLM_MAX_TOKENS",
        "OPENZYME_LLM_MAX_RETRIES",
        "OPENZYME_LLM_TEMPERATURE",
        "OPENZYME_LLM_EXTRA_BODY",
        "OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD",
        "OPENZYME_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
        "OPENZYME_LLM_CONTEXT_WINDOW_TOKENS",
        "OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS",
        "OPENZYME_LLM_CONTEXT_WARN_RATIO",
        "OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO",
        "OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO",
        "OPENZYME_LLM_TOKENIZER_ENABLED",
        "OPENZYME_LLM_REPORT_REVIEW_TIMEOUT",
        "OPENZYME_LLM_REPORT_REVIEW_MAX_TOKENS",
        "OPENZYME_LLM_REPORT_REVIEW_STRUCTURED_OUTPUT_METHOD",
        "OPENZYME_LLM_V3_HARNESS_LOOP_MAX_RETRIES",
        "OPENZYME_RESEARCH_MAX_UNITS",
        "OPENZYME_TAVILY_TIMEOUT_SECONDS",
        "OPENZYME_HOST_BASE_URL",
        "OPENZYME_LANGSMITH_TRACING",
        "LANGSMITH_TRACING",
        "OPENZYME_TEST_ENABLE_LIVE_LLM",
        "OPENZYME_TEST_ENABLE_LIVE_TAVILY",
        "OPENZYME_TEST_ENABLE_LIVE_HPC",
        "OPENZYME_TEST_ENABLE_LIVE_E2E",
        "OPENZYME_TEST_ENABLE_QUALITY_EVAL",
        "OPENZYME_TEST_UPLOAD_LANGSMITH",
        "OPENZYME_TEST_LIVE_LLM_TIMEOUT",
        "OPENZYME_TEST_LIVE_LLM_MAX_TOKENS",
        "OPENZYME_TEST_LIVE_LLM_MAX_RETRIES",
        "OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_METHOD",
        "OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
        "OPENZYME_LIMIT_GLOBAL_CONCURRENCY",
        "OPENZYME_LIMIT_SESSION_CONCURRENCY",
        "OPENZYME_LIMIT_AGENT_CONCURRENCY",
        "OPENZYME_LIMIT_LLM_PROVIDER_CONCURRENCY",
        "OPENZYME_LIMIT_RESEARCH_PROVIDER_CONCURRENCY",
        "OPENZYME_LIMIT_EXECUTION_PROVIDER_CONCURRENCY",
        "OPENZYME_V3_BACKGROUND_RUNTIME_ENABLED",
        "OPENZYME_V3_BACKGROUND_RUNTIME_POLL_INTERVAL_SECONDS",
        "OPENZYME_V3_BACKGROUND_RUNTIME_MAX_SIGNALS_PER_TICK",
        "OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT",
        "OPENZYME_V3_BACKGROUND_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS",
    ):
        monkeypatch.delenv(key, raising=False)
    for key in (
        "OPENZYME_TEST_ENABLE_LIVE_LLM",
        "OPENZYME_TEST_ENABLE_LIVE_TAVILY",
        "OPENZYME_TEST_ENABLE_LIVE_HPC",
        "OPENZYME_TEST_ENABLE_LIVE_E2E",
        "OPENZYME_TEST_ENABLE_QUALITY_EVAL",
        "OPENZYME_TEST_UPLOAD_LANGSMITH",
    ):
        monkeypatch.setenv(key, "false")
    for key in (
        "OPENZYME_TEST_LIVE_LLM_TIMEOUT",
        "OPENZYME_TEST_LIVE_LLM_MAX_TOKENS",
        "OPENZYME_TEST_LIVE_LLM_MAX_RETRIES",
        "OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_METHOD",
        "OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
    ):
        monkeypatch.setenv(key, "")

    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.api_key is None
    assert settings.llm.model == DEFAULT_OPENAI_COMPAT_MODEL
    assert settings.llm.base_url == DEFAULT_OPENAI_COMPAT_BASE_URL
    assert settings.llm.extra_body == DEFAULT_OPENAI_COMPAT_EXTRA_BODY
    assert settings.llm.default_headers == {"User-Agent": DEFAULT_OPENAI_COMPAT_USER_AGENT}
    assert settings.llm.use_responses_api is DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API
    assert settings.llm.max_tokens is None
    assert settings.llm.structured_output_method == DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD
    assert (
        settings.llm.structured_output_retry_backoff_seconds
        == DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS
    )
    assert settings.llm.purpose_policies == {}
    assert settings.llm.context_window_tokens is None
    assert settings.llm.default_output_tokens is None
    assert settings.llm.context_warn_ratio == 0.80
    assert settings.llm.context_auto_compact_ratio == 0.85
    assert settings.llm.context_emergency_ratio == 0.90
    assert settings.llm.tokenizer_enabled is False
    assert settings.research.max_units == 3
    assert settings.research.tavily_timeout_seconds == 30.0
    assert settings.host_cli.base_url == DEFAULT_HOST_BASE_URL
    assert settings.limits.provider_limits == DEFAULT_PROVIDER_LIMITS
    assert settings.host_api.bind_host == DEFAULT_HOST_API_BIND_HOST
    assert settings.host_api.bind_port == DEFAULT_HOST_API_BIND_PORT
    assert settings.v3_background_runtime.enabled is True
    assert settings.v3_background_runtime.poll_interval_seconds == 2.0
    assert settings.v3_background_runtime.max_signals_per_tick == 3
    assert settings.v3_background_runtime.max_steps_per_agent == 12
    assert settings.v3_background_runtime.shutdown_timeout_seconds == 10.0
    assert settings.tracing.enabled is False
    assert settings.test.enable_live_llm is False
    assert settings.test.enable_live_tavily is False
    assert settings.test.enable_live_hpc is False
    assert settings.test.enable_live_e2e is False
    assert settings.test.enable_quality_eval is False
    assert settings.test.upload_langsmith is False
    assert settings.test.live_llm.max_tokens is None
    assert settings.test.live_llm.timeout is None
    assert settings.test.live_llm.max_retries is None


def test_settings_honor_env_overrides(monkeypatch) -> None:
    _disable_env_file_loading(monkeypatch)
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("OPENZYME_LLM_MODEL", "custom-model")
    monkeypatch.setenv("OPENZYME_LLM_BASE_URL", "https://example.test/v1")
    monkeypatch.setenv("OPENZYME_LLM_USER_AGENT", "openzyme-test-agent")
    monkeypatch.setenv("OPENZYME_LLM_USE_RESPONSES_API", "false")
    monkeypatch.setenv("OPENZYME_LLM_EXTRA_BODY", '{"provider":"bigmodel","reasoning":{"enabled":true}}')
    monkeypatch.setenv("OPENZYME_LLM_MAX_TOKENS", "900")
    monkeypatch.setenv("OPENZYME_LLM_TIMEOUT", "42")
    monkeypatch.setenv("OPENZYME_LLM_MAX_RETRIES", "5")
    monkeypatch.setenv("OPENZYME_LLM_TEMPERATURE", "0.25")
    monkeypatch.setenv("OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD", "json_mode")
    monkeypatch.setenv("OPENZYME_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS", "2.5")
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS", "123456")
    monkeypatch.setenv("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS", "6543")
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_WARN_RATIO", "0.70")
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO", "0.75")
    monkeypatch.setenv("OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO", "0.80")
    monkeypatch.setenv("OPENZYME_LLM_TOKENIZER_ENABLED", "true")
    monkeypatch.setenv("OPENZYME_LLM_REPORT_REVIEW_TIMEOUT", "90")
    monkeypatch.setenv("OPENZYME_LLM_REPORT_REVIEW_MAX_TOKENS", "300")
    monkeypatch.setenv("OPENZYME_LLM_REPORT_REVIEW_STRUCTURED_OUTPUT_METHOD", "function_calling")
    monkeypatch.setenv("OPENZYME_LLM_V3_HARNESS_LOOP_MAX_RETRIES", "2")
    monkeypatch.setenv("OPENZYME_RESEARCH_MAX_UNITS", "7")
    monkeypatch.setenv("TAVILY_API_KEY", "tavily-key")
    monkeypatch.setenv("OPENZYME_TAVILY_MAX_RESULTS", "9")
    monkeypatch.setenv("OPENZYME_TAVILY_TOPIC", "news")
    monkeypatch.setenv("OPENZYME_TAVILY_TIMEOUT_SECONDS", "12.5")
    monkeypatch.setenv("OPENZYME_HOST_BASE_URL", "http://localhost:9999")
    monkeypatch.setenv("OPENZYME_PROJECT_ID", "proj_test")
    monkeypatch.setenv("OPENZYME_EPISODE_ID", "ep_test")
    monkeypatch.setenv("OPENZYME_OUTPUT_FORMAT", "json")
    monkeypatch.setenv("OPENZYME_HOST_API_HOST", "0.0.0.0")
    monkeypatch.setenv("OPENZYME_HOST_API_PORT", "9000")
    monkeypatch.setenv("OPENZYME_V3_BACKGROUND_RUNTIME_ENABLED", "false")
    monkeypatch.setenv("OPENZYME_V3_BACKGROUND_RUNTIME_POLL_INTERVAL_SECONDS", "0.25")
    monkeypatch.setenv("OPENZYME_V3_BACKGROUND_RUNTIME_MAX_SIGNALS_PER_TICK", "5")
    monkeypatch.setenv("OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT", "6")
    monkeypatch.setenv("OPENZYME_V3_BACKGROUND_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS", "1.5")
    monkeypatch.setenv("OPENZYME_LANGSMITH_TRACING", "true")
    monkeypatch.setenv("OPENZYME_LANGSMITH_PROJECT", "openzyme-test")
    monkeypatch.setenv("OPENZYME_EXECUTION_BACKEND", "hpc")
    monkeypatch.setenv("OPENZYME_HPC_RUNNER_CONFIG", "/tmp/hpc.toml")
    monkeypatch.setenv("OPENZYME_LIMIT_GLOBAL_CONCURRENCY", "11")
    monkeypatch.setenv("OPENZYME_LIMIT_SESSION_CONCURRENCY", "12")
    monkeypatch.setenv("OPENZYME_LIMIT_AGENT_CONCURRENCY", "13")
    monkeypatch.setenv("OPENZYME_LIMIT_LLM_PROVIDER_CONCURRENCY", "14")
    monkeypatch.setenv("OPENZYME_LIMIT_RESEARCH_PROVIDER_CONCURRENCY", "15")
    monkeypatch.setenv("OPENZYME_LIMIT_EXECUTION_PROVIDER_CONCURRENCY", "16")
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_LLM", "true")
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_TAVILY", "true")
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_HPC", "true")
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_LIVE_E2E", "true")
    monkeypatch.setenv("OPENZYME_TEST_ENABLE_QUALITY_EVAL", "true")
    monkeypatch.setenv("OPENZYME_TEST_UPLOAD_LANGSMITH", "true")
    monkeypatch.setenv("OPENZYME_TEST_LIVE_LLM_TIMEOUT", "120")
    monkeypatch.setenv("OPENZYME_TEST_LIVE_LLM_MAX_TOKENS", "500")
    monkeypatch.setenv("OPENZYME_TEST_LIVE_LLM_MAX_RETRIES", "0")
    monkeypatch.setenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_METHOD", "function_calling")
    monkeypatch.setenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS", "0.5")

    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.api_key == "llm-key"
    assert settings.llm.model == "custom-model"
    assert settings.llm.base_url == "https://example.test/v1"
    assert settings.llm.extra_body == {"provider": "bigmodel", "reasoning": {"enabled": True}}
    assert settings.llm.default_headers == {"User-Agent": "openzyme-test-agent"}
    assert settings.llm.use_responses_api is False
    assert settings.llm.max_tokens == 900
    assert settings.llm.timeout == 42.0
    assert settings.llm.max_retries == 5
    assert settings.llm.temperature == 0.25
    assert settings.llm.structured_output_method == "json_mode"
    assert settings.llm.structured_output_retry_backoff_seconds == 2.5
    assert settings.llm.context_window_tokens == 123456
    assert settings.llm.default_output_tokens == 6543
    assert settings.llm.context_warn_ratio == 0.70
    assert settings.llm.context_auto_compact_ratio == 0.75
    assert settings.llm.context_emergency_ratio == 0.80
    assert settings.llm.tokenizer_enabled is True
    report_review_policy = settings.llm.policy_for_purpose("report_review")
    assert report_review_policy.max_tokens == 300
    assert report_review_policy.timeout == 90.0
    assert report_review_policy.structured_output_method == "function_calling"
    assert settings.llm.policy_for_purpose("v3_harness_loop").max_retries == 2
    assert settings.research.max_units == 7
    assert settings.research.tavily_api_key == "tavily-key"
    assert settings.research.tavily_max_results == 9
    assert settings.research.tavily_topic == "news"
    assert settings.research.tavily_timeout_seconds == 12.5
    assert settings.host_cli.base_url == "http://localhost:9999"
    assert settings.host_cli.project_id == "proj_test"
    assert settings.host_cli.output_format == "json"
    assert settings.host_api.bind_host == "0.0.0.0"
    assert settings.host_api.bind_port == 9000
    assert settings.v3_background_runtime.enabled is False
    assert settings.v3_background_runtime.poll_interval_seconds == 0.25
    assert settings.v3_background_runtime.max_signals_per_tick == 5
    assert settings.v3_background_runtime.max_steps_per_agent == 6
    assert settings.v3_background_runtime.shutdown_timeout_seconds == 1.5
    assert settings.tracing.enabled is True
    assert settings.tracing.project_name == "openzyme-test"
    assert settings.execution.backend == "hpc"
    assert settings.execution.hpc_runner_config == "/tmp/hpc.toml"
    assert settings.limits.provider_limits == {
        "global": 11,
        "session": 12,
        "agent": 13,
        "llm_provider": 14,
        "research_provider": 15,
        "execution_provider": 16,
    }
    assert settings.test.enable_live_llm is True
    assert settings.test.enable_live_tavily is True
    assert settings.test.enable_live_hpc is True
    assert settings.test.enable_live_e2e is True
    assert settings.test.enable_quality_eval is True
    assert settings.test.upload_langsmith is True
    assert settings.test.live_llm.max_tokens == 500
    assert settings.test.live_llm.timeout == 120.0
    assert settings.test.live_llm.max_retries == 0
    assert settings.test.live_llm.structured_output_method == "function_calling"
    assert settings.test.live_llm.structured_output_retry_backoff_seconds == 0.5


def test_settings_default_bigmodel_extra_body_can_be_overridden(monkeypatch) -> None:
    _disable_env_file_loading(monkeypatch)
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("OPENZYME_LLM_MODEL", "glm-5.1")
    monkeypatch.setenv("OPENZYME_LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    monkeypatch.setenv("OPENZYME_LLM_EXTRA_BODY", '{"provider":"custom","mode":"strict"}')

    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.extra_body == {"provider": "custom", "mode": "strict"}


def test_settings_default_bigmodel_extra_body_for_explicit_glm(monkeypatch) -> None:
    _disable_env_file_loading(monkeypatch)
    monkeypatch.setenv("OPENZYME_LLM_API_KEY", "llm-key")
    monkeypatch.setenv("OPENZYME_LLM_MODEL", "glm-5.1")
    monkeypatch.setenv("OPENZYME_LLM_BASE_URL", "https://open.bigmodel.cn/api/coding/paas/v4")
    monkeypatch.delenv("OPENZYME_LLM_EXTRA_BODY", raising=False)

    reset_settings_cache()
    settings = get_settings()

    assert settings.llm.extra_body == {"provider": "bigmodel"}


def test_settings_reject_non_positive_limiter_values(monkeypatch) -> None:
    _disable_env_file_loading(monkeypatch)
    monkeypatch.setenv("OPENZYME_LIMIT_LLM_PROVIDER_CONCURRENCY", "0")

    reset_settings_cache()
    try:
        get_settings()
    except ValueError as exc:
        assert "OPENZYME_LIMIT_LLM_PROVIDER_CONCURRENCY must be positive" == str(exc)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError")


def test_settings_cache_can_be_reset(monkeypatch) -> None:
    _disable_env_file_loading(monkeypatch)
    monkeypatch.setenv("OPENZYME_LLM_MODEL", "first")
    reset_settings_cache()
    assert get_settings().llm.model == "first"

    monkeypatch.setenv("OPENZYME_LLM_MODEL", "second")
    assert get_settings().llm.model == "first"

    reset_settings_cache()
    assert get_settings().llm.model == "second"
