from __future__ import annotations

import pytest

from openzyme_runtime import get_settings
from openzyme_research import ResearchUnit
from openzyme_research import TavilyResearchAdapter


pytestmark = [pytest.mark.integration, pytest.mark.live_tavily]


def test_live_tavily_adapter_returns_normalized_results() -> None:
    settings = get_settings()
    adapter = TavilyResearchAdapter(
        api_key=settings.research.tavily_api_key,
        max_results=settings.research.tavily_max_results,
        topic=settings.research.tavily_topic,
    )
    unit = ResearchUnit(
        unit_id="unit_live_001",
        topic="thermostable enzyme engineering",
        query="thermostable enzyme engineering review directed evolution",
    )
    raw_response = adapter.search(unit.query)
    assert raw_response.get("results")

    result = adapter.normalize_response(
        unit=unit,
        response=raw_response,
    )

    assert result.status == "completed"
    assert result.findings
    assert result.findings[0].sources
    assert result.findings[0].sources[0].locator
