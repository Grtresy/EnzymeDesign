from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from functools import lru_cache
import hashlib
import json
import os
from pathlib import Path
from typing import Any

from .limits import DEFAULT_PROVIDER_LIMITS
from .live_token_ledger import DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH
from .live_token_ledger import configured_live_micu_token_ledger_path


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_FILES = (".env", ".env.local")
DEFAULT_OPENAI_COMPAT_BASE_URL = "https://www.micuapi.ai/v1"
DEFAULT_OPENAI_COMPAT_MODEL = "gpt-5.4-mini"
DEFAULT_OPENAI_COMPAT_EXTRA_BODY: dict[str, Any] | None = None
_BIGMODEL_EXTRA_BODY = {"provider": "bigmodel"}
DEFAULT_OPENAI_COMPAT_USER_AGENT = (
    "codex_cli_rs/0.77.0 (Windows 10.0.26100; x86_64) WindowsTerminal"
)
DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API = True
DEFAULT_LLM_STRUCTURED_OUTPUT_METHOD = "function_calling"
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
    "v3_harness_loop",
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
        return dict(_BIGMODEL_EXTRA_BODY)
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
    structured_output_retry_backoff_seconds: float


@dataclass(frozen=True, slots=True)
class LlmPurposePolicy:
    max_tokens: int | None = None
    timeout: float | None = None
    max_retries: int | None = None
    structured_output_method: str | None = None
    structured_output_retry_backoff_seconds: float | None = None


@dataclass(frozen=True, slots=True)
class LlmSettings:
    api_key: str | None
    model: str
    base_url: str
    extra_body: dict[str, Any] | None
    default_headers: dict[str, str] | None
    use_responses_api: bool
    max_tokens: int | None
    timeout: float | None
    max_retries: int
    temperature: float
    structured_output_method: str
    structured_output_retry_backoff_seconds: float
    purpose_policies: dict[str, LlmPurposePolicy]
    context_window_tokens: int | None = None
    default_output_tokens: int | None = None
    context_warn_ratio: float = 0.80
    context_auto_compact_ratio: float = 0.85
    context_emergency_ratio: float = 0.90
    tokenizer_enabled: bool = False

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
            structured_output_retry_backoff_seconds=(
                self.structured_output_retry_backoff_seconds
                if override.structured_output_retry_backoff_seconds is None
                else override.structured_output_retry_backoff_seconds
            ),
        )

    @classmethod
    def from_env(cls) -> "LlmSettings":
        user_agent_raw = os.getenv("OPENZYME_LLM_USER_AGENT")
        user_agent = (
            DEFAULT_OPENAI_COMPAT_USER_AGENT
            if user_agent_raw is None
            else user_agent_raw.strip() or None
        )
        api_key = (
            os.getenv("OPENZYME_LLM_API_KEY")
            or os.getenv("MICU_API_KEY")
            or None
        )
        model = os.getenv("OPENZYME_LLM_MODEL") or DEFAULT_OPENAI_COMPAT_MODEL
        base_url = os.getenv("OPENZYME_LLM_BASE_URL") or DEFAULT_OPENAI_COMPAT_BASE_URL
        extra_body = _parse_json_object(os.getenv("OPENZYME_LLM_EXTRA_BODY"))
        if extra_body is None:
            extra_body = _default_llm_extra_body(model=model, base_url=base_url)
        return cls(
            api_key=api_key,
            model=model,
            base_url=base_url,
            extra_body=extra_body,
            default_headers={"User-Agent": user_agent} if user_agent is not None else None,
            use_responses_api=_parse_bool(
                os.getenv("OPENZYME_LLM_USE_RESPONSES_API"),
                DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API,
            ),
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
            structured_output_retry_backoff_seconds=_parse_float(
                os.getenv("OPENZYME_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS"),
                DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS,
            ),
            purpose_policies=_load_llm_purpose_policies(),
            context_window_tokens=(
                None
                if os.getenv("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS") in {None, ""}
                else _parse_int(os.getenv("OPENZYME_LLM_CONTEXT_WINDOW_TOKENS"), 0)
            ),
            default_output_tokens=(
                None
                if os.getenv("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS") in {None, ""}
                else _parse_int(os.getenv("OPENZYME_LLM_DEFAULT_OUTPUT_TOKENS"), 0)
            ),
            context_warn_ratio=_parse_float(
                os.getenv("OPENZYME_LLM_CONTEXT_WARN_RATIO"),
                0.80,
            ),
            context_auto_compact_ratio=_parse_float(
                os.getenv("OPENZYME_LLM_CONTEXT_AUTO_COMPACT_RATIO"),
                0.85,
            ),
            context_emergency_ratio=_parse_float(
                os.getenv("OPENZYME_LLM_CONTEXT_EMERGENCY_RATIO"),
                0.90,
            ),
            tokenizer_enabled=_parse_bool(
                os.getenv("OPENZYME_LLM_TOKENIZER_ENABLED"),
                False,
            ),
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
    auth_token: str | None = field(default=None, repr=False)

    @classmethod
    def from_env(cls) -> "HostCliSettings":
        return cls(
            base_url=os.getenv("OPENZYME_HOST_BASE_URL", DEFAULT_HOST_BASE_URL),
            project_id=os.getenv("OPENZYME_PROJECT_ID") or None,
            output_format=os.getenv("OPENZYME_OUTPUT_FORMAT", "text"),
            auth_token=os.getenv("OPENZYME_HOST_AUTH_TOKEN") or None,
        )


@dataclass(frozen=True, slots=True)
class HostApiPrincipalSettings:
    principal_id: str
    token_sha256: str = field(repr=False)
    roles: frozenset[str]
    project_ids: frozenset[str]


@dataclass(frozen=True, slots=True)
class HostApiSettings:
    bind_host: str
    bind_port: int
    deployment_profile: str = "local-dev"
    principals: tuple[HostApiPrincipalSettings, ...] = ()
    debug_enabled: bool = False

    def __post_init__(self) -> None:
        if self.deployment_profile not in {"local-dev", "shared"}:
            raise ValueError(
                "OPENZYME_HOST_DEPLOYMENT_PROFILE must be 'local-dev' or 'shared'"
            )
        if self.deployment_profile == "local-dev" and self.bind_host not in {
            "127.0.0.1",
            "localhost",
            "::1",
        }:
            raise ValueError(
                "local-dev Host API must bind to a loopback address; use the "
                "shared profile for a remotely reachable service"
            )
        if self.deployment_profile == "shared" and not self.principals:
            raise ValueError(
                "shared Host API requires OPENZYME_HOST_AUTH_PRINCIPALS_JSON"
            )
        principal_ids = [item.principal_id for item in self.principals]
        token_digests = [item.token_sha256 for item in self.principals]
        if len(principal_ids) != len(set(principal_ids)):
            raise ValueError("Host API principal_id values must be unique")
        if len(token_digests) != len(set(token_digests)):
            raise ValueError("Host API bearer tokens must be unique")

    @classmethod
    def from_env(cls) -> "HostApiSettings":
        deployment_profile = os.getenv(
            "OPENZYME_HOST_DEPLOYMENT_PROFILE", "local-dev"
        ).strip()
        return cls(
            bind_host=os.getenv("OPENZYME_HOST_API_HOST", DEFAULT_HOST_API_BIND_HOST),
            bind_port=_parse_int(os.getenv("OPENZYME_HOST_API_PORT"), DEFAULT_HOST_API_BIND_PORT),
            deployment_profile=deployment_profile,
            principals=_parse_host_api_principals(
                os.getenv("OPENZYME_HOST_AUTH_PRINCIPALS_JSON")
            ),
            debug_enabled=_parse_bool(
                os.getenv("OPENZYME_HOST_DEBUG_ENABLED"), default=False
            ),
        )


def _parse_host_api_principals(
    value: str | None,
) -> tuple[HostApiPrincipalSettings, ...]:
    if value in {None, ""}:
        return ()
    parsed = json.loads(value)
    if not isinstance(parsed, list):
        raise ValueError("OPENZYME_HOST_AUTH_PRINCIPALS_JSON must be a JSON array")
    principals: list[HostApiPrincipalSettings] = []
    valid_roles = {"user", "operator", "admin"}
    for index, item in enumerate(parsed):
        if not isinstance(item, dict):
            raise ValueError(f"Host API principal at index {index} must be an object")
        principal_id = str(item.get("principal_id") or "").strip()
        token = str(item.get("token") or "")
        roles_raw = item.get("roles")
        projects_raw = item.get("project_ids")
        if len(principal_id) <= len("user:") or not principal_id.startswith("user:"):
            raise ValueError(
                "Host API principal_id must be non-empty and start with 'user:'"
            )
        if len(token) < 32:
            raise ValueError("Host API bearer tokens must contain at least 32 characters")
        if token != token.strip() or any(char.isspace() for char in token):
            raise ValueError("Host API bearer tokens cannot contain whitespace")
        if not isinstance(roles_raw, list) or not roles_raw:
            raise ValueError("Host API principal roles must be a non-empty array")
        if not isinstance(projects_raw, list) or not projects_raw:
            raise ValueError("Host API principal project_ids must be a non-empty array")
        roles = frozenset(str(role).strip() for role in roles_raw)
        project_ids = frozenset(str(project_id).strip() for project_id in projects_raw)
        if not roles <= valid_roles:
            raise ValueError(
                f"unsupported Host API principal role: {sorted(roles - valid_roles)[0]}"
            )
        if "" in project_ids:
            raise ValueError("Host API principal project_ids cannot contain empty values")
        principals.append(
            HostApiPrincipalSettings(
                principal_id=principal_id,
                token_sha256=hashlib.sha256(token.encode("utf-8")).hexdigest(),
                roles=roles,
                project_ids=project_ids,
            )
        )
    return tuple(principals)


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
            12,
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
            backend=os.getenv("OPENZYME_EXECUTION_BACKEND", "disabled"),
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
    structured_output_retry_backoff_seconds: float | None
    token_ledger_path: str = str(DEFAULT_LIVE_MICU_TOKEN_LEDGER_PATH)

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
            structured_output_retry_backoff_seconds=(
                None
                if os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS")
                in {None, ""}
                else _parse_float(
                    os.getenv("OPENZYME_TEST_LIVE_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS"),
                    0.0,
                )
            ),
            token_ledger_path=(
                str(configured_live_micu_token_ledger_path())
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
    "DEFAULT_LLM_STRUCTURED_OUTPUT_RETRY_BACKOFF_SECONDS",
    "DEFAULT_OPENAI_COMPAT_BASE_URL",
    "DEFAULT_OPENAI_COMPAT_EXTRA_BODY",
    "DEFAULT_OPENAI_COMPAT_MODEL",
    "DEFAULT_OPENAI_COMPAT_USER_AGENT",
    "DEFAULT_OPENAI_COMPAT_USE_RESPONSES_API",
    "ExecutionSettings",
    "HostApiSettings",
    "HostApiPrincipalSettings",
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
