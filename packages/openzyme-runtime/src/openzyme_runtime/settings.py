from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
import os
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[4]
DEFAULT_ENV_FILES = (".env", ".env.local")
DEFAULT_OPENAI_COMPAT_BASE_URL = "https://open.bigmodel.cn/api/coding/paas/v4"
DEFAULT_OPENAI_COMPAT_MODEL = "glm-5.1"
DEFAULT_HOST_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_HOST_API_BIND_HOST = "127.0.0.1"
DEFAULT_HOST_API_BIND_PORT = 8000


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
class LlmSettings:
    api_key: str | None
    model: str
    base_url: str
    timeout: float | None
    max_retries: int
    temperature: float

    @property
    def enabled(self) -> bool:
        return bool(self.api_key)

    @classmethod
    def from_env(cls) -> "LlmSettings":
        api_key = (
            os.getenv("OPENZYME_LLM_API_KEY")
            or os.getenv("BIGMODEL_API_KEY")
            or os.getenv("ZHIPUAI_API_KEY")
        )
        return cls(
            api_key=api_key,
            model=os.getenv("OPENZYME_LLM_MODEL", DEFAULT_OPENAI_COMPAT_MODEL),
            base_url=os.getenv("OPENZYME_LLM_BASE_URL", DEFAULT_OPENAI_COMPAT_BASE_URL),
            timeout=_parse_optional_float(os.getenv("OPENZYME_LLM_TIMEOUT")),
            max_retries=_parse_int(os.getenv("OPENZYME_LLM_MAX_RETRIES"), 1),
            temperature=_parse_float(os.getenv("OPENZYME_LLM_TEMPERATURE"), 0.0),
        )


@dataclass(frozen=True, slots=True)
class ResearchSettings:
    max_units: int
    tavily_api_key: str | None
    tavily_max_results: int
    tavily_topic: str

    @property
    def tavily_enabled(self) -> bool:
        return bool(self.tavily_api_key)

    @classmethod
    def from_env(cls) -> "ResearchSettings":
        return cls(
            max_units=_parse_int(os.getenv("OPENZYME_RESEARCH_MAX_UNITS"), 3),
            tavily_api_key=os.getenv("TAVILY_API_KEY"),
            tavily_max_results=_parse_int(os.getenv("OPENZYME_TAVILY_MAX_RESULTS"), 3),
            tavily_topic=os.getenv("OPENZYME_TAVILY_TOPIC", "general"),
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
                or "openzyme-v2"
            ),
        )


@dataclass(frozen=True, slots=True)
class HostCliSettings:
    base_url: str
    project_id: str | None
    episode_id: str | None
    output_format: str

    @classmethod
    def from_env(cls) -> "HostCliSettings":
        return cls(
            base_url=os.getenv("OPENZYME_HOST_BASE_URL", DEFAULT_HOST_BASE_URL),
            project_id=os.getenv("OPENZYME_PROJECT_ID") or None,
            episode_id=os.getenv("OPENZYME_EPISODE_ID") or None,
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
class ExecutionSettings:
    backend: str
    hpc_runner_config: str | None

    @classmethod
    def from_env(cls) -> "ExecutionSettings":
        return cls(
            backend=os.getenv("OPENZYME_EXECUTION_BACKEND", "demo"),
            hpc_runner_config=os.getenv("OPENZYME_HPC_RUNNER_CONFIG") or None,
        )


@dataclass(frozen=True, slots=True)
class OpenZymeSettings:
    llm: LlmSettings
    research: ResearchSettings
    tracing: TracingSettings
    host_cli: HostCliSettings
    host_api: HostApiSettings
    execution: ExecutionSettings

    @classmethod
    def from_env(cls) -> "OpenZymeSettings":
        load_env_files()
        return cls(
            llm=LlmSettings.from_env(),
            research=ResearchSettings.from_env(),
            tracing=TracingSettings.from_env(),
            host_cli=HostCliSettings.from_env(),
            host_api=HostApiSettings.from_env(),
            execution=ExecutionSettings.from_env(),
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
    "DEFAULT_OPENAI_COMPAT_BASE_URL",
    "DEFAULT_OPENAI_COMPAT_MODEL",
    "ExecutionSettings",
    "HostApiSettings",
    "HostCliSettings",
    "LlmSettings",
    "OpenZymeSettings",
    "REPO_ROOT",
    "ResearchSettings",
    "TracingSettings",
    "get_settings",
    "load_env_files",
    "reset_settings_cache",
]
