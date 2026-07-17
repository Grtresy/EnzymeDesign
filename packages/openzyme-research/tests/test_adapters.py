from io import BytesIO
from urllib.error import HTTPError

from openzyme_research import BoundedCallableClient
from openzyme_research import ProviderOutcome
from openzyme_research import ResearchUnit
from openzyme_research import TavilyResearchAdapter


def test_tavily_adapter_normalizes_search_results_without_provider_leakage() -> None:
    observed: dict[str, object] = {}

    def fake_search(**_: object) -> dict[str, object]:
        observed.update(_)
        return {
            "results": [
                {
                    "title": "Thermostable catalase paper",
                    "url": "https://example.org/paper",
                    "content": "A homolog family remains active above 60C in wet-lab assays.",
                    "raw_content": "A homolog family remains active above 60C in wet-lab assays.",
                }
            ]
        }

    adapter = TavilyResearchAdapter(search_callable=fake_search, timeout_seconds=12.5)

    result = adapter.conduct(
        session_id="sess_001",
        research_brief="Find evidence for thermostable catalase scaffolds.",
        unit=ResearchUnit(
            unit_id="unit_001",
            topic="thermostable catalase homologs",
            query="thermostable catalase homolog activity 60C",
        ),
    )

    assert result.status == "completed"
    assert result.summary.startswith("thermostable catalase homologs:")
    assert result.findings[0].query == "thermostable catalase homolog activity 60C"
    assert result.findings[0].sources[0].locator == "https://example.org/paper"
    assert observed["timeout"] == 12.5
    assert observed["topic"] == "general"


def test_tavily_adapter_normalizes_fetch_results() -> None:
    def fake_extract(**kwargs: object) -> dict[str, object]:
        assert kwargs["urls"] == ["https://example.org/article"]
        assert kwargs["timeout"] == 9.0
        return {
            "results": [
                {
                    "title": "Article",
                    "url": "https://example.org/article",
                    "raw_content": "Extracted article content about enzyme design.",
                }
            ]
        }

    adapter = TavilyResearchAdapter(extract_callable=fake_extract, timeout_seconds=9.0)
    raw_response = adapter.fetch_url(url="https://example.org/article")
    result = adapter.normalize_fetch_response(
        url="https://example.org/article",
        query="enzyme design",
        response=raw_response,
    )

    assert result.status == "completed"
    assert (
        result.findings[0].summary == "Extracted article content about enzyme design."
    )
    assert result.findings[0].query == "enzyme design"
    assert result.findings[0].sources[0].locator == "https://example.org/article"


def test_tavily_adapter_reports_failed_fetch_results() -> None:
    adapter = TavilyResearchAdapter(
        extract_callable=lambda **_: {
            "results": [],
            "failed_results": [{"url": "https://example.org/missing"}],
        }
    )

    result = adapter.normalize_fetch_response(
        url="https://example.org/missing",
        query=None,
        response=adapter.fetch_url(url="https://example.org/missing"),
    )

    assert result.status == "partial"
    assert result.provider_outcome == "degraded"
    assert result.findings == ()
    assert "https://example.org/missing" not in result.unresolved_gaps[0]
    assert result.provider_call["failure"]["error_code"] == "provider_empty"


def test_tavily_rate_limit_is_bounded_and_persisted_as_degraded() -> None:
    calls = 0

    def fake_search(**_: object) -> dict[str, object]:
        nonlocal calls
        calls += 1
        raise HTTPError(
            "https://api.tavily.com/search?api_key=secret",
            429,
            "rate limited",
            {"Retry-After": "0"},
            BytesIO(),
        )

    adapter = TavilyResearchAdapter(
        search_callable=fake_search,
        callable_client=BoundedCallableClient(
            sleeper=lambda delay: None,
            max_attempts=2,
        ),
    )

    result = adapter.web_search_result(query="alternative oxidase")

    assert calls == 2
    assert result.outcome is ProviderOutcome.DEGRADED
    assert result.failure is not None
    assert result.failure.error_code == "provider_rate_limited"
    assert result.provenance.attempt_count == 2
    assert "secret" not in str(result.to_dict())


def test_tavily_private_source_is_not_projected_or_replaced() -> None:
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {
            "results": [
                {
                    "title": "Private source",
                    "url": "http://127.0.0.1/private?token=secret",
                    "content": "internal",
                }
            ]
        }
    )

    result = adapter.conduct(
        session_id="sess_001",
        research_brief="AOX",
        unit=ResearchUnit(
            unit_id="unit_private",
            topic="AOX",
            query="alternative oxidase",
        ),
    )

    assert result.status == "partial"
    assert result.findings == ()
    assert "127.0.0.1" not in str(result.to_dict())
    assert "secret" not in str(result.to_dict())
