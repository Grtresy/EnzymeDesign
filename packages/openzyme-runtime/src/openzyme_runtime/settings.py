from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
import json
import os
from pathlib import Path
from typing import Any

from .limits import DEFAULT_PROVIDER_LIMITS


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_FILES = (".env", ".env.local")
DEFAULT_OPENAI_COMPAT_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_OPENAI_COMPAT_MODEL = "glm-5.1"
DEFAULT_OPENAI_COMPAT_EXTRA_BODY = {"provider": "bigmodel"}
DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD = "function_calling"
DEFAULT_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS = 3
DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS = 1.0
DEFAULT_HOST_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_HOST_API_BIND_HOST = "127.0.0.1"
DEFAULT_HOST_API_BIND_PORT = 8000
LIMIT_ENV_VARS = {
    "global": "OPENZYME_LIMIT_GLOBAL_CONCURRENCY",
    "session": "OPENZYME_LIMIT_SESSION_CONCURRENCY",
    "agent": "OPENZYME_LIMIT_AGENT_CONCURRENCY",
    "llm_provider": "OPENZYME_LIMIT_LLM_PROVIDER_CONCURRENCY",
    "research_provider": "OPENZYME_LIMIT_RESEARCH_PROVIDER_CONCURRENCY",
    "execution_provider": "OPENZYME_LIMIT_EXECUTION_PROVIDER_CONCURRENCY",
}
LLM_PURPOSES = (
    "intake",
    "research",
    "design",
    "report_review",
    "deep_research_brief",
    "deep_research_supervisor",
    "deep_research_researcher",
    "deep_research_synthesis",
)


def _parse_bool(value: str | None, default: bool = False) -> bool:
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on", "local"}


def _parse_int(value: str | None, default: int) -> int:
    if value in {None, ""}:
        return default
    return int(value)


def _parse_float(value: str | None, default: float) -> float:
    if value in {None, ""}:
        return default
    return float(value)


def _parse_optional_float(value: str | None) -> float | None:
    if value in {None, ""}:
        return None
    return float(value)


def _parse_json_object(value: str | None) -> dict[str, Any] | None:
    if value in {None, ""}:
        return None
    parsed = json.loads(value)
    if not isinstance(parsed, dict):
        raise ValueError("Expected a JSON object.")
    return parsed


def _default_llm_extra_body(*, model: str, base_url: str) -> dict[str, Any] | None:
    if "open.bigmodel.cn" in base_url or model.startswith("glm-"):
        return dict(DEFAULT_OPENAI_COMPAT_EXTRA_BODY)
    return None


def _parse_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].strip()
        if "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def load_env_files(file_names: tuple[str, ...] = DEFAULT_ENV_FILES) -> None:
    original_env_keys = set(os.environ)
    loaded_values: dict[str, str] = {}
    for file_name in file_names:
        path = REPO_ROOT / file_name
        if not path.exists():
            continue
        for key, value in _parse_env_file(path).items():
            if key in original_env_keys:
                continue
            loaded_values[key] = value
    os.environ.update(loaded_values)


@dataclass(frozen=True, slots=True)
class ResolvedLlmPolicy:
    max_tokens: int | None
    timeout: float | None
    max_retries: int
    structured_output_method: str
    structured_output_max_attempts: int
    structured_output_retry_backoff_seconds: float


@dataclass(frozen=True, slots=True)
class LlmPurposePolicy:
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    structured_output_method: str | None = None
    structured_output_max_attempts: int | None = None
    structured_output_retry_backoff_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class LlmSettings:
    api_key: str | None
    model: str
    base_url: str
    extra_body: dict[str, Any] | None
    max_tokens: int | None
    timeout: float | None
    max_retries: int
    temperature: float
    structured_output_method: str
    structured_output_max_attempts: int
    structured_output_retry_backoff_seconds: float
    purpose_policies: dict[str, LlmPurposePolicy]

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    def policy_for_purpose(self, purpose: str | None) -> ResolvedLlmPolicy:
        override = self.purpose_policies.get(purpose or "", LlmPurposePolicy())
        return ResolvedLlmPolicy(
            max_tokens=self.max_tokens if override.max_tokens is None else override.max_tokens,
            timeout=self.timeout if override.timeout is None else override.timeout,
            max_retries=self.max_retries if override.max_retries is None else override.max_retries,
            structured_output_method=(
                self.structured_output_method
                if override.structured_output_method is None
                else override.structured_output_method
            ),
            structured_output_max_attempts=(
                self.structured_output_max_attempts
                if override.structured_output_max_attempts is None
                else override.structured_output_max_attempts
            ),
            structured_output_retry_backoff_seconds=(
                self.structured_output_retry_backoff_seconds
                if override.structured_output_retry_backoff_seconds is None
                else override.structured_output_retry_backoff_seconds
            ),
        )

    @classmethod
    def from_env(cls) -> "LlmSettings":
        api_key = (
            os.getenv("OPENZYME_LLM_API_KEY")
            or os.getenv("BIGMODEL_API_KEY")
            or os.getenv("ZHIPUAI_API_KEY")
            or None
        )
        model = os.getenv("OPENZYME_LLM_MODEL", DEFAULT_OPENAI_COMPAT_MODEL)
        base_url = os.getenv("OPENZYME_LLM_BASE_URL", DEFAULT_OPENAI_COMPAT_BASE_URL)
        extra_body = _parse_json_object(os.getenv("OPENZYME_LLM_EXTRA_BODY"))
        if extra_body is None:
            extra_body = _default_llm_extra_body(model=model, base_url=base_url)
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            extra_body=extra_body,
            max_tokens=(
                None
                if os.getenv("OPENZYME_LLM_MAX_TOKENS") in {None, ""}
                else _parse_int(os.getenv("OPENZYME_LLM_MAX_TOKENS"), 0)
            ),
            timeout=_parse_optional_float(os.getenv("OPENZYME_LLM_TIMEOUT")),
            max_retries=_parse_int(os.getenv("OPENZYME_LLM_MAX_RETRIES"), 5),
            temperature=_parse_float(os.getenv("OPENZYME_LLM_TEMPERATURE"), 0.0),
            structured_output_method=os.getenv(
                "OPENZYME_LLM_STRUCTURED_OUTPUT_METHOD",
                DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD,
            ),
            structured_output_max_attempts=_parse_int(
                os.getenv("OPENZYME_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS"),
                DEFAULT_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS,
            ),
            structured_output_retry_backoff_seconds=_parse_float(
                os.getenv("OPENZYME_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS"),
                DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS,
            ),
            purpose_policies=_load_llm_purpose_policies(),
        )


def _load_llm_purpose_policies() -> dict[str, LlmPurposePolicy]:
    policies: dict[str, LlmPurposePolicy] = {}
    for purpose in LLM_PURPOSES:
        env_prefix = f"OPENZYME_LLM_{purpose.upper()}_"
        policy = LlmPurposePolicy(
            max_tokens=(
                None
                if os.getenv(f"{env_prefix}MAX_TOKENS") in {None, ""}
                else _parse_int(os.getenv(f"{env_prefix}MAX_TOKENS"), 0)
            ),
            timeout=_parse_optional_float(os.getenv(f"{env_prefix}TIMEOUT")),
            max_retries=(
                None
                if os.getenv(f"{env_prefix}MAX_RETRIES") in {None, ""}
                else _parse_int(os.getenv(f"{env_prefix}MAX_RETRIES"), 0)
            ),
            structured_output_method=os.getenv(f"{env_prefix}STRUCTURED_OUTPUT_METHOD") or None,
            structured_output_max_attempts=(
                None
                if os.getenv(f"{env_prefix}STRUCTURED_OUTPUT_MAX_ATTEMPTS") in {None, ""}
                else _parse_int(os.getenv(f"{env_prefix}STRUCTURED_OUTPUT_MAX_ATTEMPTS"), 0)
            ),
            structured_output_retry_backoff_seconds=(
                None
                if os.getenv(f"{env_prefix}STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS") in {None, ""}
                else _parse_float(
                    os.getenv(f"{env_prefix}STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS"),
                    0.0,
                )
            ),
        )
        if any(
            value is not None
            for value in (
                policy.timeout,
                policy.max_tokens,
                policy.max_retries,
                policy.structured_output_method,
                policy.structured_output_max_attempts,
                policy.structured_output_retry_backoff_seconds,
            )
        ):
            policies[purpose] = policy
    return policies


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    max_units: int
    allow_clarification: bool
    max_research_iterations: int
    max_react_tool_calls: int
    max_concurrent_research_units: int
    tavily_api_key: str | None
    tavily_max_results: int
    tavily_topic: str
    mcp_enabled: bool
    mcp_tool_allowlist: tuple[str, ...] = ()
    tavily_timeout_seconds: float = 30.0

    @property
    def tavily_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @classmethod
    def from_env(cls) -> "ResearchSettings":
        return cls(
            max_units=_parse_int(os.getenv("OPENZYME_RESEARCH_MAX_UNITS"), 3),
            allow_clarification=_parse_bool(os.getenv("OPENZYME_RESEARCH_ALLOW_CLARIFICATION"), False),
            max_research_iterations=_parse_int(os.getenv("OPENZYME_RESEARCH_MAX_ITERATIONS"), 3),
            max_react_tool_calls=_parse_int(os.getenv("OPENZYME_RESEARCH_MAX_REACT_TOOL_CALLS"), 4),
            max_concurrent_research_units=_parse_int(os.getenv("OPENZYME_RESEARCH_MAX_CONCURRENT_UNITS"), 3),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            tavily_max_results=_parse_int(os.getenv("OPENZYME_TAVILY_MAX_RESULTS"), 3),
            tavily_topic=os.getenv("OPENZYME_TAVILY_TOPIC", "general"),
            mcp_enabled=_parse_bool(os.getenv("OPENZYME_RESEARCH_MCP_ENABLED"), False),
            mcp_tool_allowlist=tuple(
                item.strip()
                for item in (os.getenv("OPENZYME_RESEARCH_MCP_TOOL_ALLOWLIST") or "").split(",")
                if item.strip()
            ),
            tavily_timeout_seconds=_parse_float(
                os.getenv("OPENZYME_TAVILY_TIMEOUT_SECONDS"),
                30.0,
            ),
        )


@dataclass(frozen=True, slots=True)
class TracingSettings:
    enabled: bool
    project_name: str

    @classmethod
    def from_env(cls) -> "TracingSettings":
        return cls(
            enabled=_parse_bool(
                os.getenv("OPENZYME_LANGSMITH_TRACING") or os.getenv("LANGSMITH_TRACING"),
                default=False,
            ),
            project_name=(
                os.getenv("OPENZYME_LANGSMITH_PROJECT")
                or os.getenv("LANGSMITH_PROJECT")
                or "openzyme-v3"
            ),
        )


@dataclass(frozen=True, slots=True)
class HostCliSettings:
    base_url: str
    project_id: str | None
    output_format: str

    @classmethod
    def from_env(cls) -> "HostCliSettings":
        return cls(
            base_url=os.getenv("OPENZYME_HOST_BASE_URL", DEFAULT_HOST_BASE_URL),
            project_id=os.getenv("OPENZYME_PROJECT_ID") or None,
            output_format=os.getenv("OPENZYME_OUTPUT_FORMAT", "text"),
        )


@dataclass(frozen=True, slots=True)
class HostApiSettings:
    bind_host: str
    bind_port: int

    @classmethod
    def from_env(cls) -> "HostApiSettings":
        return cls(
            bind_host=os.getenv("OPENZYME_HOST_API_HOST", DEFAULT_HOST_API_BIND_HOST),
            bind_port=_parse_int(os.getenv("OPENZYME_HOST_API_PORT"), DEFAULT_HOST_API_BIND_PORT),
        )


@dataclass(frozen=True, slots=True)
class V3BackgroundRuntimeSettings:
    enabled: bool
    poll_interval_seconds: float
    max_signals_per_tick: int
    max_steps_per_agent: int
    shutdown_timeout_seconds: float

    @classmethod
    def from_env(cls) -> "V3BackgroundRuntimeSettings":
        max_signals_per_tick = _parse_int(
            os.getenv("OPENZYME_V3_BACKGROUND_RUNTIME_MAX_SIGNALS_PER_TICK"),
            3,
        )
        max_steps_per_agent = _parse_int(
            os.getenv("OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT"),
            8,
        )
        if max_signals_per_tick <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_MAX_SIGNALS_PER_TICK must be positive"
            )
        if max_steps_per_agent <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_MAX_STEPS_PER_AGENT must be positive"
            )
        poll_interval_seconds = _parse_float(
            os.getenv("OPENZYME_V3_BACKGROUND_RUNTIME_POLL_INTERVAL_SECONDS"),
            2.0,
        )
        shutdown_timeout_seconds = _parse_float(
            os.getenv("OPENZYME_V3_BACKGROUND_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS"),
            10.0,
        )
        if poll_interval_seconds <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_POLL_INTERVAL_SECONDS must be positive"
            )
        if shutdown_timeout_seconds <= 0:
            raise ValueError(
                "OPENZYME_V3_BACKGROUND_RUNTIME_SHUTDOWN_TIMEOUT_SECONDS must be positive"
            )
        return cls(
            enabled=_parse_bool(
                os.getenv("OPENZYME_V3_BACKGROUND_RUNTIME_ENABLED"),
                default=True,
            ),
            poll_interval_seconds=poll_interval_seconds,
            max_signals_per_tick=max_signals_per_tick,
            max_steps_per_agent=max_steps_per_agent,
            shutdown_timeout_seconds=shutdown_timeout_seconds,
        )


@dataclass(frozen=True, slots=True)
class ExecutionSettings:
    backend: str
    hpc_runner_config: str | None

    @classmethod
    def from_env(cls) -> "ExecutionSettings":
        return cls(
            backend=os.getenv("OPENZYME_EXECUTION_BACKEND", "demo"),
            hpc_runner_config=(
                os.getenv("OPENZYME_HPC_RUNNER_CONFIG")
                or os.getenv("HPC_RUNNER_CONFIG")
                or None
            ),
        )


@dataclass(frozen=True, slots=True)
class LimiterSettings:
    provider_limits: dict[str, int]

    @classmethod
    def from_env(cls) -> "LimiterSettings":
        limits: dict[str, int] = {}
        for name, default in DEFAULT_PROVIDER_LIMITS.items():
            value = _parse_int(os.getenv(LIMIT_ENV_VARS[name]), default)
            if value <= 0:
                raise ValueError(f"{LIMIT_ENV_VARS[name]} must be positive")
            limits[name] = value
        return cls(provider_limits=limits)


def _default_limiter_settings() -> LimiterSettings:
    return LimiterSettings(provider_limits=dict(DEFAULT_PROVIDER_LIMITS))


@dataclass(frozen=True, slots=True)
class LiveLlmTestSettings:
    max_tokens: int | None
    timeout: float | None
    max_retries: int | None
    structured_output_method: str | None
    structured_output_max_attempts: int | None
    structured_output_retry_backoff_seconds: float | None

    @classmethod
    def from_env(cls) -> "LiveLlmTestSettings":
        return cls(
            max_tokens=(
                None
                if os.getenv("OPENZYME_TEST_LIVE_LLM_MAX_TOKENS") in {None, ""}
                else _parse_int(os.getenv("OPENZYME_TEST_LIVE_LLM_MAX_TOKENS"), 0)
            ),
            timeout=_parse_optional_float(os.getenv("OPENZYME_TEST_LIVE_LLM_TIMEOUT")),
            max_retries=(
                None
                if os.getenv("OPENZYME_TEST_LIVE_LLM_MAX_RETRIES") in {None, ""}
                else _parse_int(os.getenv("OPENZYME_TEST_LIVE_LLM_MAX_RETRIES"), 0)
            ),
            structured_output_method=(
                os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_METHOD") or None
            ),
            structured_output_max_attempts=(
                None
                if os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS") in {None, ""}
                else _parse_int(os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS"), 0)
            ),
            structured_output_retry_backoff_seconds=(
                None
                if os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS")
                in {None, ""}
                else _parse_float(
                    os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS"),
                    0.0,
                )
            ),
        )


@dataclass(frozen=True, slots=True)
class TestSettings:
    enable_live_llm: bool
    enable_live_tavily: bool
    enable_live_hpc: bool
    enable_live_e2e: bool
    enable_quality_eval: bool
    upload_langsmith: bool
    live_llm: LiveLlmTestSettings

    @classmethod
    def from_env(cls) -> "TestSettings":
        return cls(
            enable_live_llm=_parse_bool(os.getenv("OPENZYME_TEST_ENABLE_LIVE_LLM")),
            enable_live_tavily=_parse_bool(os.getenv("OPENZYME_TEST_ENABLE_LIVE_TAVILY")),
            enable_live_hpc=_parse_bool(os.getenv("OPENZYME_TEST_ENABLE_LIVE_HPC")),
            enable_live_e2e=_parse_bool(os.getenv("OPENZYME_TEST_ENABLE_LIVE_E2E")),
            enable_quality_eval=_parse_bool(os.getenv("OPENZYME_TEST_ENABLE_QUALITY_EVAL")),
            upload_langsmith=_parse_bool(os.getenv("OPENZYME_TEST_UPLOAD_LANGSMITH")),
            live_llm=LiveLlmTestSettings.from_env(),
        )


@dataclass(frozen=True, slots=True)
class OpenZymeSettings:
    llm: LlmSettings
    research: ResearchSettings
    tracing: TracingSettings
    host_cli: HostCliSettings
    host_api: HostApiSettings
    v3_background_runtime: V3BackgroundRuntimeSettings
    execution: ExecutionSettings
    test: TestSettings
    limits: LimiterSettings = field(default_factory=_default_limiter_settings)

    @classmethod
    def from_env(cls) -> "OpenZymeSettings":
        load_env_files()
        return cls(
            llm=LlmSettings.from_env(),
            research=ResearchSettings.from_env(),
            tracing=TracingSettings.from_env(),
            host_cli=HostCliSettings.from_env(),
            host_api=HostApiSettings.from_env(),
            v3_background_runtime=V3BackgroundRuntimeSettings.from_env(),
            execution=ExecutionSettings.from_env(),
            limits=LimiterSettings.from_env(),
            test=TestSettings.from_env(),
        )


@lru_cache(maxsize=1)
def get_settings() -> OpenZymeSettings:
    return OpenZymeSettings.from_env()


def reset_settings_cache() -> None:
    get_settings.cache_clear()


__all__ = [
    "DEFAULT_HOST_BASE_URL",
    "DEFAULT_HOST_API_BIND_HOST",
    "DEFAULT_HOST_API_BIND_PORT",
    "DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD",
    "DEFAULT_LLM_STRUCTURED_OUTPUT_MAX_ATTEMPTS",
    "DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_OPENAI_COMPAT_BASE_URL",
    "DEFAULT_OPENAI_COMPAT_MODEL",
    "ExecutionSettings",
    "HostApiSettings",
    "HostCliSettings",
    "LiveLlmTestSettings",
    "LimiterSettings",
    "LlmPurposePolicy",
    "LlmSettings",
    "OpenZymeSettings",
    "REPO_ROOT",
    "ResolvedLlmPolicy",
    "ResearchSettings",
    "TracingSettings",
    "V3BackgroundRuntimeSettings",
    "get_settings",
    "load_env_files",
    "reset_settings_cache",
]
