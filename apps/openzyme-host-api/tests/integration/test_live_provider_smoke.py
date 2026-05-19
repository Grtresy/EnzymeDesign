from __future__ import annotations

import pytest
from pydantic import BaseModel

from openzyme_runtime.live_testing import LiveStageTimeout
from openzyme_runtime.live_testing import derive_live_stage_timeout_seconds
from openzyme_runtime.live_testing import log_live_phase
from openzyme_host_api.foundation import apply_live_llm_test_budget
from openzyme_host_api.foundation import build_model_factory_from_settings
from openzyme_research import TavilyResearchAdapter
from openzyme_runtime import get_settings


pytestmark = [pytest.mark.integration, pytest.mark.live_llm, pytest.mark.live_tavily]


class LiveProviderSmokeTimeoutError(TimeoutError):
    """Raised when a live provider smoke test exceeds its local timeout budget."""


class ProviderSmokeResult(BaseModel):
    status: str
    note: str


def test_live_llm_and_tavily_smoke_return_within_timeout() -> None:
    settings = apply_live_llm_test_budget(get_settings())

    log_live_phase("building live provider smoke LLM factory")
    factory = build_model_factory_from_settings(settings)
    assert factory is not None
    invoker = factory.create_structured_invoker(purpose="live_provider_smoke")
    llm_timeout_seconds = derive_live_stage_timeout_seconds(
        provider_timeout_seconds=settings.llm.timeout,
        attempts=settings.llm.structured_output_max_attempts,
        buffer_seconds=30,
        minimum_seconds=60,
    )

    with LiveStageTimeout(
        "invoking live LLM provider smoke",
        llm_timeout_seconds,
        timeout_type=LiveProviderSmokeTimeoutError,
    ):
        llm_result = invoker.invoke_structured(
            schema=ProviderSmokeResult,
            system_prompt=(
                "Return a tiny structured health check for a live provider smoke test."
            ),
            user_payload={"request": "respond with status ok and a short note"},
        )

    assert llm_result.status
    assert llm_result.note

    log_live_phase("building live provider smoke Tavily adapter")
    adapter = TavilyResearchAdapter(
        api_key=settings.research.tavily_api_key,
        max_results=1,
        topic=settings.research.tavily_topic,
        timeout_seconds=settings.research.tavily_timeout_seconds,
        diagnostic_label="live-provider-smoke",
    )
    tavily_timeout_seconds = derive_live_stage_timeout_seconds(
        provider_timeout_seconds=settings.research.tavily_timeout_seconds,
        attempts=1,
        buffer_seconds=15,
        minimum_seconds=45,
    )
    with LiveStageTimeout(
        "invoking Tavily web.search smoke",
        tavily_timeout_seconds,
        timeout_type=LiveProviderSmokeTimeoutError,
    ):
        search_response = adapter.web_search(
            query="thermostable enzyme engineering review",
            max_results=1,
            include_raw_content=False,
        )

    assert search_response.get("results")
    first_result = dict(list(search_response["results"])[0])
    first_url = str(first_result.get("url") or "https://en.wikipedia.org/wiki/Enzyme")

    with LiveStageTimeout(
        "invoking Tavily web.fetch smoke",
        tavily_timeout_seconds,
        timeout_type=LiveProviderSmokeTimeoutError,
    ):
        fetch_response = adapter.fetch_url(
            url=first_url,
            extract_depth="basic",
            format="markdown",
            include_images=False,
        )

    assert isinstance(fetch_response, dict)
    assert "results" in fetch_response or "failed_results" in fetch_response
