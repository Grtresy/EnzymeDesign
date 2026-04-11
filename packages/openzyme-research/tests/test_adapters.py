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
