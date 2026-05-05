from openzyme_research import ResearchUnit
from openzyme_research import TavilyResearchAdapter


def test_tavily_adapter_normalizes_search_results_without_provider_leakage() -> None:
    def fake_search(**_: object) -> dict[str, object]:
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

    adapter = TavilyResearchAdapter(search_callable=fake_search)

    result = adapter.conduct(
        episode_id="ep_001",
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


def test_tavily_adapter_normalizes_fetch_results() -> None:
    def fake_extract(**kwargs: object) -> dict[str, object]:
        assert kwargs["urls"] == ["https://example.org/article"]
        return {
            "results": [
                {
                    "title": "Article",
                    "url": "https://example.org/article",
                    "raw_content": "Extracted article content about enzyme design.",
                }
            ]
        }

    adapter = TavilyResearchAdapter(extract_callable=fake_extract)
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

    assert result.status == "failed"
    assert result.findings == ()
    assert "https://example.org/missing" in result.unresolved_gaps[0]
