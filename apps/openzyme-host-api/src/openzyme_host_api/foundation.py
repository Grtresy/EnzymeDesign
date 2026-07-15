from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace

from mcp_hpc_runner.server import MCPHpcServer
from openzyme_domain import ArtifactKind
from openzyme_domain import RunStatus
from openzyme_domain import SourceRefKind
from openzyme_execution import ExecutionArtifactRef
from openzyme_execution import ExecutionOutcome
from openzyme_execution import HpcRunnerExecutionAdapter
from openzyme_runtime import OpenAICompatibleChatModelFactory
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import RuntimeFoundation
from openzyme_tools import DefaultHpcExecutionRegistry
from openzyme_tools import RepoBackedHpcCatalogProvider
from openzyme_runtime import DefaultResearchToolProvider
from openzyme_runtime import get_settings
from openzyme_research import ResearchFinding
from openzyme_research import ResearchSource
from openzyme_research import ResearchUnit
from openzyme_research import ResearchUnitResult
from openzyme_research import TavilyResearchAdapter
from openzyme_research import BioResearchService
from openzyme_research import DefaultBioResearchService
from openzyme_research import DeterministicBioResearchService
from openzyme_runtime import build_bio_research_tools

from .eval_support import DeterministicLocalModelFactory


@dataclass(slots=True)
class DeterministicExecutionAdapter:
    _session_call_counts: dict[str, int] = field(default_factory=dict)

    def submit_execution(
        self, session_id: str, payload: dict[str, object]
    ) -> ExecutionOutcome:
        call_count = self._session_call_counts.get(session_id, 0) + 1
        self._session_call_counts[session_id] = call_count
        run_id = f"run_{session_id}_{call_count}"
        return ExecutionOutcome(
            run_id=run_id,
            status=RunStatus.SUCCEEDED,
            execution_mode="demo",
            remote_run_dir=f"/local/{session_id}/{run_id}",
            artifacts=(
                ExecutionArtifactRef(
                    storage_uri="/tmp/openzyme-local/stdout.log",
                    relative_path="stdout.log",
                    kind=ArtifactKind.LOG,
                ),
                ExecutionArtifactRef(
                    storage_uri="/tmp/openzyme-local/result.json",
                    relative_path="result.json",
                    kind=ArtifactKind.RESULT,
                ),
            ),
            raw_result={"status": "completed", "mode": "demo"},
        )


@dataclass(slots=True)
class DeterministicResearchAdapter:
    def conduct(
        self, *, session_id: str, research_brief: str, unit: ResearchUnit
    ) -> ResearchUnitResult:
        del session_id, research_brief
        return self.normalize_search_response(
            unit=unit,
            response=self.web_search(
                query=unit.query,
                max_results=3,
                topic=unit.topic,
                include_raw_content=True,
            ),
        )

    def web_search(
        self,
        *,
        query: str,
        max_results: int = 3,
        topic: str = "general",
        include_raw_content: bool = True,
    ) -> dict[str, object]:
        del max_results, include_raw_content
        return {
            "results": [
                {
                    "title": f"Reference source for {topic}",
                    "url": f"https://example.org/reference/{topic.replace(' ', '-')}",
                    "content": f"Deterministic finding for {query}",
                }
            ]
        }

    def fetch_url(
        self,
        *,
        url: str,
        query: str | None = None,
        extract_depth: str = "basic",
        format: str = "markdown",
        include_images: bool = False,
    ) -> dict[str, object]:
        del query, extract_depth, format, include_images
        return {
            "results": [
                {
                    "title": "Deterministic web page",
                    "url": url,
                    "raw_content": f"Deterministic extracted content for {url}",
                }
            ]
        }

    def normalize_search_response(
        self, *, unit: ResearchUnit, response: dict[str, object]
    ) -> ResearchUnitResult:
        results = list(response.get("results", []))
        result = dict(results[0]) if results else {}
        locator = str(
            result.get("url") or f"https://example.org/reference/{unit.unit_id}"
        )
        summary = str(
            result.get("content")
            or result.get("raw_content")
            or f"Deterministic finding for {unit.query}"
        )
        return ResearchUnitResult(
            unit_id=unit.unit_id,
            summary=f"{unit.topic} supports the current design objective.",
            findings=(
                ResearchFinding(
                    summary=summary,
                    query=unit.query,
                    confidence_label="high",
                    sources=(
                        ResearchSource(
                            title=f"Reference source for {unit.unit_id}",
                            locator=locator,
                            kind=SourceRefKind.WEB_PAGE,
                        ),
                    ),
                ),
            ),
            unresolved_gaps=("Need wet-lab follow-up for the top hypothesis.",),
        )

    def normalize_fetch_response(
        self,
        *,
        url: str,
        query: str | None,
        response: dict[str, object],
    ) -> ResearchUnitResult:
        return self.normalize_search_response(
            unit=ResearchUnit(
                unit_id="web-fetch", topic="web fetch", query=query or url
            ),
            response=response,
        )


def apply_live_llm_test_budget(settings: OpenZymeSettings) -> OpenZymeSettings:
    live_policy = settings.test.live_llm
    return replace(
        settings,
        llm=replace(
            settings.llm,
            max_tokens=300
            if live_policy.max_tokens is None
            else live_policy.max_tokens,
            timeout=45.0 if live_policy.timeout is None else live_policy.timeout,
            max_retries=5
            if live_policy.max_retries is None
            else max(0, live_policy.max_retries),
            structured_output_method=(
                "function_calling"
                if live_policy.structured_output_method is None
                else live_policy.structured_output_method
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
    limiter_registry: LimiterRegistry | None = None,
) -> OpenAICompatibleChatModelFactory | None:
    if not settings.llm.enabled or settings.llm.api_key is None:
        return None
    return OpenAICompatibleChatModelFactory(
        model=settings.llm.model,
        api_key=settings.llm.api_key,
        base_url=settings.llm.base_url,
        extra_body=settings.llm.extra_body,
        default_headers=settings.llm.default_headers,
        use_responses_api=settings.llm.use_responses_api,
        max_tokens=settings.llm.max_tokens,
        temperature=settings.llm.temperature,
        timeout=settings.llm.timeout,
        max_retries=settings.llm.max_retries,
        structured_output_method=settings.llm.structured_output_method,
        structured_output_retry_backoff_seconds=settings.llm.structured_output_retry_backoff_seconds,
        context_window_tokens=settings.llm.context_window_tokens,
        default_output_tokens=settings.llm.default_output_tokens,
        tokenizer_enabled=settings.llm.tokenizer_enabled,
        purpose_policies={
            purpose: {
                "timeout": policy.timeout,
                "max_tokens": policy.max_tokens,
                "max_retries": policy.max_retries,
                "structured_output_method": policy.structured_output_method,
                "structured_output_retry_backoff_seconds": (
                    policy.structured_output_retry_backoff_seconds
                ),
            }
            for purpose, policy in settings.llm.purpose_policies.items()
        },
        limiter_registry=limiter_registry,
        diagnostic_label=(
            "live-provider"
            if settings.test.enable_live_llm or settings.test.enable_live_e2e
            else None
        ),
    )


def build_model_factory_from_env() -> OpenAICompatibleChatModelFactory | None:
    settings = get_settings()
    return build_model_factory_from_settings(
        settings,
        LimiterRegistry(dict(settings.limits.provider_limits)),
    )


def _build_execution_adapter(
    settings: OpenZymeSettings,
    limiter_registry: LimiterRegistry,
):
    if settings.execution.backend == "demo":
        return DeterministicExecutionAdapter()
    if settings.execution.backend == "hpc":
        return HpcRunnerExecutionAdapter(
            config_path=settings.execution.hpc_runner_config,
            server=MCPHpcServer(settings.execution.hpc_runner_config),
            limiter_registry=limiter_registry,
        )
    raise ValueError(f"Unsupported execution backend: {settings.execution.backend}")


def _build_research_adapter(settings: OpenZymeSettings):
    if settings.research.tavily_enabled:
        return TavilyResearchAdapter(
            api_key=settings.research.tavily_api_key,
            max_results=settings.research.tavily_max_results,
            topic=settings.research.tavily_topic,
            timeout_seconds=settings.research.tavily_timeout_seconds,
            diagnostic_label=(
                "live-provider"
                if settings.test.enable_live_llm
                or settings.test.enable_live_tavily
                or settings.test.enable_live_e2e
                else None
            ),
        )
    return DeterministicResearchAdapter()


def _build_bio_research_service(settings: OpenZymeSettings) -> BioResearchService:
    del settings
    return DefaultBioResearchService()


def build_local_eval_foundation(
    *,
    settings: OpenZymeSettings | None = None,
) -> RuntimeFoundation:
    effective_settings = settings or get_settings()
    limiter_registry = LimiterRegistry(dict(effective_settings.limits.provider_limits))
    research_adapter = DeterministicResearchAdapter()
    bio_research_service = DeterministicBioResearchService()
    return RuntimeFoundation(
        execution_adapter=DeterministicExecutionAdapter(),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
        research_adapter=research_adapter,
        research_tool_provider=DefaultResearchToolProvider(
            research_adapter,
            mcp_tools=build_bio_research_tools(bio_research_service),
            mcp_enabled=True,
            mcp_tool_allowlist=effective_settings.research.mcp_tool_allowlist,
            limiter_registry=limiter_registry,
        ),
        bio_research_service=bio_research_service,
        model_factory=DeterministicLocalModelFactory(),
        limiter_registry=limiter_registry,
        settings=effective_settings,
    )


def build_configured_foundation(
    *,
    settings: OpenZymeSettings | None = None,
) -> RuntimeFoundation:
    effective_settings = settings or get_settings()
    if effective_settings.test.enable_live_e2e and effective_settings.llm.enabled:
        effective_settings = apply_live_llm_test_budget(effective_settings)
    limiter_registry = LimiterRegistry(dict(effective_settings.limits.provider_limits))
    research_adapter = _build_research_adapter(effective_settings)
    bio_research_service = _build_bio_research_service(effective_settings)
    return RuntimeFoundation(
        execution_adapter=_build_execution_adapter(effective_settings, limiter_registry),
        hpc_catalog_provider=RepoBackedHpcCatalogProvider(),
        hpc_execution_registry=DefaultHpcExecutionRegistry(
            RepoBackedHpcCatalogProvider()
        ),
        research_adapter=research_adapter,
        research_tool_provider=DefaultResearchToolProvider(
            research_adapter,
            mcp_tools=build_bio_research_tools(bio_research_service),
            mcp_enabled=True,
            mcp_tool_allowlist=effective_settings.research.mcp_tool_allowlist,
            limiter_registry=limiter_registry,
        ),
        bio_research_service=bio_research_service,
        model_factory=build_model_factory_from_settings(
            effective_settings,
            limiter_registry,
        ),
        limiter_registry=limiter_registry,
        settings=effective_settings,
    )
