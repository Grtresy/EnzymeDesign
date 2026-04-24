from __future__ import annotations

from openzyme_research import DeterministicBioResearchService
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
    tools = {tool.name: tool for tool in build_bio_research_tools(DeterministicBioResearchService())}

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
    tools = {tool.name: tool for tool in build_bio_research_tools(DeterministicBioResearchService())}

    result = tools["uniprot.download_fasta"].invoke(
        args={"accession": "P12345"},
        context=_context(),
    )

    assert result.summary == result.payload["summary"]
    assert result.payload["findings"] == []
    assert result.payload["artifacts"][0]["kind"] == "sequence"
    assert result.payload["artifacts"][0]["storage_uri"]
