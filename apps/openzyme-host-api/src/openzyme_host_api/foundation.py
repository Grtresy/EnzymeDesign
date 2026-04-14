from __future__ import annotations

from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver
from openzyme_domain import ArtifactKind
from openzyme_domain import Project
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_execution import HpcRunnerExecutionAdapter
from openzyme_runtime import OpenAICompatibleChatModelFactory
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import PhaseBRepositories
from openzyme_runtime import RuntimeFoundation
from openzyme_runtime import DefaultResearchToolProvider
from openzyme_runtime import apply_sqlite_migrations
from openzyme_runtime import connect_sqlite
from openzyme_runtime import get_settings
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_research import TavilyResearchAdapter


DEFAULT_DEMO_PROJECT_ID = "proj_001"
DEFAULT_DEMO_PROJECT_NAME = "Thermostability demo project"
DEFAULT_DEMO_PROJECT_DESCRIPTION = "Preloaded project for the local Phase B workspace demo."


@dataclass(slots=True)
class DemoExecutionAdapter:
    _episode_call_counts: dict[str, int] = field(default_factory=dict)

    def submit_execution(self, episode_id: str, payload: dict[str, object]) -> ExecutionOutcome:
        call_count = self._episode_call_counts.get(episode_id, 0) + 1
        self._episode_call_counts[episode_id] = call_count
        run_id = f"run_{episode_id}_{call_count}"
        return ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            execution_mode="demo",
            remote_run_dir=f"/demo/{episode_id}/{run_id}",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/openzyme-demo/stdout.log",
                    relative_path="stdout.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri="/tmp/openzyme-demo/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={"status": "completed", "mode": "demo"},
        )


@dataclass(slots=True)
class DemoResearchAdapter:
    def conduct(self, *, episode_id: str, research_brief: str, unit: ResearchUnit) -> ResearchUnitResult:
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the demo objective.",
            findings=(
                ResearchFinding(
                    summary=f"Demo finding for {unit.query}",
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Demo source for {unit.unit_id}",
                            locator=f"https://example.org/demo/{unit.unit_id}",
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need wet-lab follow-up for the top hypothesis.",),
        )


class InMemoryCheckpointerFactory:
    def __init__(self) -> None:
        self._saver = InMemorySaver()

    @contextmanager
    def open(self):
        yield self._saver


def apply_live_llm_test_budget(settings: OpenZymeSettings) -> OpenZymeSettings:
    live_policy = settings.test.live_llm
    return replace(
        settings,
        llm=replace(
            settings.llm,
            max_tokens=300 if live_policy.max_tokens is None else live_policy.max_tokens,
            timeout=45.0 if live_policy.timeout is None else live_policy.timeout,
            max_retries=1 if live_policy.max_retries is None else max(1, live_policy.max_retries),
            structured_output_method=(
                "function_calling"
                if live_policy.structured_output_method is None
                else live_policy.structured_output_method
            ),
            structured_output_max_attempts=(
                1
                if live_policy.structured_output_max_attempts is None
                else live_policy.structured_output_max_attempts
            ),
            structured_output_retry_backoff_seconds=(
                0.5
                if live_policy.structured_output_retry_backoff_seconds is None
                else live_policy.structured_output_retry_backoff_seconds
            ),
            # Live-provider tests should use the explicit test budget consistently
            # across every LLM purpose instead of inheriting slower per-purpose prod overrides.
            purpose_policies={},
        ),
    )


def build_model_factory_from_settings(
    settings: OpenZymeSettings,
) -> OpenAICompatibleChatModelFactory | None:
    if not settings.llm.enabled or settings.llm.api_key is None:
        return None
    return OpenAICompatibleChatModelFactory(
        model=settings.llm.model,
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        extra_body=settings.llm.extra_body,
        max_tokens=settings.llm.max_tokens,
        temperature=settings.llm.temperature,
        timeout=settings.llm.timeout,
        max_retries=settings.llm.max_retries,
        structured_output_method=settings.llm.structured_output_method,
        structured_output_max_attempts=settings.llm.structured_output_max_attempts,
        structured_output_retry_backoff_seconds=settings.llm.structured_output_retry_backoff_seconds,
        purpose_policies={
            purpose: {
                "timeout": policy.timeout,
                "max_tokens": policy.max_tokens,
                "max_retries": policy.max_retries,
                "structured_output_method": policy.structured_output_method,
                "structured_output_max_attempts": policy.structured_output_max_attempts,
                "structured_output_retry_backoff_seconds": (
                    policy.structured_output_retry_backoff_seconds
                ),
            }
            for purpose, policy in settings.llm.purpose_policies.items()
        },
    )


def build_model_factory_from_env() -> OpenAICompatibleChatModelFactory | None:
    return build_model_factory_from_settings(get_settings())


def _connect_demo_database(sqlite_db_path: Path | None) -> PhaseBRepositories:
    db_path = sqlite_db_path
    if db_path is None:
        raise ValueError("sqlite_db_path is required for demo foundations")
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = connect_sqlite(str(db_path))
    apply_sqlite_migrations(connection)
    repositories = PhaseBRepositories.from_connection(connection)
    if repositories.projects.get(DEFAULT_DEMO_PROJECT_ID) is None:
        repositories.projects.save(
            Project.create(
                DEFAULT_DEMO_PROJECT_ID,
                DEFAULT_DEMO_PROJECT_NAME,
                DEFAULT_DEMO_PROJECT_DESCRIPTION,
            )
        )
    return repositories


def _build_execution_adapter(settings: OpenZymeSettings):
    if settings.execution.backend == "demo":
        return DemoExecutionAdapter()
    if settings.execution.backend == "hpc":
        return HpcRunnerExecutionAdapter(config_path=settings.execution.hpc_runner_config)
    raise ValueError(f"Unsupported execution backend: {settings.execution.backend}")


def _build_research_adapter(settings: OpenZymeSettings):
    if settings.research.tavily_enabled:
        return TavilyResearchAdapter(
            api_key=settings.research.tavily_api_key,
            max_results=settings.research.tavily_max_results,
            topic=settings.research.tavily_topic,
        )
    return DemoResearchAdapter()


def build_demo_foundation(
    *,
    sqlite_db_path: Path | None,
    settings: OpenZymeSettings | None = None,
) -> RuntimeFoundation:
    effective_settings = settings or get_settings()
    repositories = _connect_demo_database(sqlite_db_path)
    research_adapter = DemoResearchAdapter()
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=InMemoryCheckpointerFactory(),  # type: ignore[arg-type]
        execution_adapter=DemoExecutionAdapter(),
        research_adapter=research_adapter,
        research_tool_provider=DefaultResearchToolProvider(
            research_adapter,
            mcp_enabled=effective_settings.research.mcp_enabled,
            mcp_tool_allowlist=effective_settings.research.mcp_tool_allowlist,
        ),
        model_factory=build_model_factory_from_settings(effective_settings),
        settings=effective_settings,
    )


def build_configured_foundation(
    *,
    sqlite_db_path: Path | None,
    settings: OpenZymeSettings | None = None,
) -> RuntimeFoundation:
    effective_settings = settings or get_settings()
    if effective_settings.test.enable_live_e2e and effective_settings.llm.enabled:
        effective_settings = apply_live_llm_test_budget(effective_settings)
    repositories = _connect_demo_database(sqlite_db_path)
    research_adapter = _build_research_adapter(effective_settings)
    return RuntimeFoundation(
        repositories=repositories,
        checkpointer_factory=InMemoryCheckpointerFactory(),  # type: ignore[arg-type]
        execution_adapter=_build_execution_adapter(effective_settings),
        research_adapter=research_adapter,
        research_tool_provider=DefaultResearchToolProvider(
            research_adapter,
            mcp_enabled=effective_settings.research.mcp_enabled,
            mcp_tool_allowlist=effective_settings.research.mcp_tool_allowlist,
        ),
        model_factory=build_model_factory_from_settings(effective_settings),
        settings=effective_settings,
    )
