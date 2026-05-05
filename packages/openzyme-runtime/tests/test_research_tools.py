from __future__ import annotations

from openzyme_research import DeterministicBioResearchService
from openzyme_research import TavilyResearchAdapter
from openzyme_runtime.research_tools import DefaultResearchToolProvider
from openzyme_runtime.research_tools import build_bio_research_tools
from openzyme_runtime.seams import ResearchToolContext


def _context() -> ResearchToolContext:
    return ResearchToolContext(
        episode_id="ep_001",
        project_id="proj_001",
        objective="Test objective",
        design_brief=None,
        research_brief="Collect evidence.",
        tool_call_iterations=0,
    )


def test_bio_research_search_tools_return_research_observation_payloads() -> None:
    tools = {
        tool.name: tool
        for tool in build_bio_research_tools(DeterministicBioResearchService())
    }

    result = tools["pubmed.search"].invoke(
        args={"query": "enzyme engineering", "limit": 3},
        context=_context(),
    )

    assert result.summary == result.payload["summary"]
    assert set(result.payload) == {
        "status",
        "summary",
        "findings",
        "unresolved_gaps",
        "artifacts",
        "provider",
        "raw_ref",
    }
    assert result.payload["provider"] == "pubmed"
    assert result.payload["findings"][0]["sources"][0]["kind"] == "paper"
    assert result.payload["artifacts"] == []


def test_bio_research_download_tools_return_artifact_manifests() -> None:
    tools = {
        tool.name: tool
        for tool in build_bio_research_tools(DeterministicBioResearchService())
    }

    result = tools["uniprot.download_fasta"].invoke(
        args={"accession": "P12345"},
        context=_context(),
    )

    assert result.summary == result.payload["summary"]
    assert result.payload["findings"] == []
    assert result.payload["artifacts"][0]["kind"] == "sequence"
    assert result.payload["artifacts"][0]["storage_uri"]


def test_default_research_tools_expose_web_tools_without_search_collect() -> None:
    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: {
            "results": [
                {
                    "title": "Result",
                    "url": "https://example.org/result",
                    "content": "Search result content.",
                }
            ]
        },
        extract_callable=lambda **_: {
            "results": [
                {
                    "title": "Fetched",
                    "url": "https://example.org/page",
                    "raw_content": "Fetched page content.",
                }
            ]
        },
    )
    tools = {
        tool.name: tool
        for tool in DefaultResearchToolProvider(adapter).list_tools(_context())
    }

    assert "web.search" in tools
    assert "web.fetch" in tools
    assert "search.collect" not in tools

    search_result = tools["web.search"].invoke(
        args={"query": "enzyme design", "max_results": 1},
        context=_context(),
    )
    fetch_result = tools["web.fetch"].invoke(
        args={"url": "https://example.org/page"},
        context=_context(),
    )

    assert search_result.payload["provider"] == "web"
    assert (
        search_result.payload["findings"][0]["sources"][0]["locator"]
        == "https://example.org/result"
    )
    assert fetch_result.payload["findings"][0]["summary"] == "Fetched page content."
