from __future__ import annotations

import asyncio
import threading
import time
from urllib.error import HTTPError

from openzyme_research import DeterministicBioResearchService
from openzyme_research import ProviderAttempt
from openzyme_research import ProviderProvenance
from openzyme_research import TavilyResearchAdapter
from openzyme_research import failed_result
from openzyme_runtime import LimiterRegistry
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime.research_tools import DefaultResearchToolProvider
from openzyme_runtime.research_tools import build_bio_research_tools
from openzyme_runtime.seams import ResearchToolContext


def _context() -> ResearchToolContext:
    return ResearchToolContext(
        session_id="sess_001",
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
    assert result.payload["status"] == "failed"
    assert result.payload["raw_ref"]["call_local_literature_quorum"][
        "cutover_eligible"
    ] is False
    assert result.payload["findings"] == []
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
    assert result.payload["artifacts"][0]["content_digest"].startswith("sha256:")
    assert (
        result.payload["artifacts"][0]["sealed_digest"]
        == result.payload["artifacts"][0]["content_digest"]
    )
    assert result.payload["artifacts"][0]["retrieved_at"]
    provenance = result.payload["artifacts"][0]["provenance"]
    assert provenance["provider"] == "uniprot"
    assert provenance["external_id"] == "P12345"
    assert provenance["format"] == "fasta"
    assert provenance["digest"] == result.payload["artifacts"][0]["content_digest"]


def test_rcsb_download_structure_provider_route_policy_is_registered() -> None:
    policy = S12_ROUTE_POLICIES["rcsb_pdb.download_structure.provider:v1"]

    assert policy["sdk_module"] == "rcsb_pdb"
    assert policy["function_name"] == "download_structure"
    assert policy["selected_backend"] == "provider_http"
    assert policy["runtime_packaging_id"] == "provider_http:v1"
    assert policy["provider_config_digest"] == "provider_config:rcsb_pdb:v1"
    assert policy["evidence_ref"]
    assert policy["parameter_inventory_ref"]
    assert policy["approval_requirement"] == {"required": True}
    assert policy["status"] == "ok"


def test_bio_provider_route_policy_config_identities_track_corrective_semantics() -> None:
    uniprot = S12_ROUTE_POLICIES["bio.uniprot_fetch.provider:v1"]
    hmmer = S12_ROUTE_POLICIES["bio.hmmer_search.provider:v1"]

    assert uniprot["provider_config_digest"] == "provider_config:uniprot:v3"
    assert hmmer["provider_config_digest"] == "provider_config:ebi_hmmer:v3"
    assert uniprot["runtime_packaging_id"] == "provider_http:v1"
    assert hmmer["runtime_packaging_id"] == "provider_http:v1"


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


def test_default_research_tool_provider_limits_web_and_bio_provider_calls() -> None:
    active = 0
    observed_max = 0
    lock = threading.Lock()

    def provider_call(result):
        nonlocal active, observed_max
        with lock:
            active += 1
            observed_max = max(observed_max, active)
        try:
            time.sleep(0.01)
            return result
        finally:
            with lock:
                active -= 1

    class FakeBioService:
        def search_pubmed(self, *, query: str, limit: int):
            del query, limit
            return provider_call([])

    adapter = TavilyResearchAdapter(
        search_callable=lambda **_: provider_call(
            {
                "results": [
                    {
                        "title": "Result",
                        "url": "https://example.org/result",
                        "content": "Search result content.",
                    }
                ]
            }
        ),
        extract_callable=lambda **_: {"results": []},
    )
    registry = LimiterRegistry({"research_provider": 3})
    tools = {
        tool.name: tool
        for tool in DefaultResearchToolProvider(
            adapter,
            mcp_tools=build_bio_research_tools(FakeBioService()),  # type: ignore[arg-type]
            mcp_enabled=True,
            limiter_registry=registry,
        ).list_tools(_context())
    }

    async def run_calls() -> None:
        await asyncio.gather(
            *(
                asyncio.to_thread(
                    tools["web.search"].invoke,
                    args={"query": f"enzyme design {index}", "max_results": 1},
                    context=_context(),
                )
                if index % 2 == 0
                else asyncio.to_thread(
                    tools["pubmed.search"].invoke,
                    args={"query": f"enzyme design {index}", "limit": 1},
                    context=_context(),
                )
                for index in range(10)
            )
        )

    asyncio.run(run_calls())

    assert observed_max <= 3


def test_bio_provider_http_failure_returns_explicit_failed_observation() -> None:
    class RateLimitedBioService:
        def search_semantic_scholar(self, *, query: str, limit: int):
            del query, limit
            raise HTTPError(
                url="https://api.semanticscholar.org/",
                code=429,
                msg="rate limited",
                hdrs=None,
                fp=None,
            )

    tools = {
        tool.name: tool
        for tool in build_bio_research_tools(RateLimitedBioService())  # type: ignore[arg-type]
    }

    result = tools["semantic_scholar.search"].invoke(
        args={"query": "enzyme engineering", "limit": 1},
        context=_context(),
    )

    assert result.payload["status"] == "failed"
    assert result.payload["provider"] == "semantic_scholar"
    assert result.payload["findings"] == []
    assert result.payload["raw_ref"] == {
        "provider": "semantic_scholar",
        "outcome": "failed",
        "error_code": "provider_unavailable",
        "typed_provider_outcome": False,
        "exception_type": "HTTPError",
    }


def test_typed_failed_provider_result_is_not_reported_completed() -> None:
    class TypedFailedBioService(DeterministicBioResearchService):
        def search_pubmed_result(self, *, query: str, limit: int):
            del query, limit
            timestamp = "2026-07-17T00:00:00+00:00"
            return failed_result(
                provenance=ProviderProvenance(
                    provider="pubmed",
                    operation="literature.search",
                    endpoint_id="pubmed.esearch:v1",
                    request_digest="sha256:" + "1" * 64,
                    retrieved_at=timestamp,
                    attempt_count=1,
                    attempts=(
                        ProviderAttempt(
                            attempt=1,
                            started_at=timestamp,
                            finished_at=timestamp,
                            outcome="failed",
                            status_code=503,
                            error_code="provider_unavailable",
                        ),
                    ),
                    response_status=503,
                ),
                error_code="provider_unavailable",
                message="pubmed is unavailable",
                retryable=True,
                status_code=503,
            )

    tools = {
        tool.name: tool
        for tool in build_bio_research_tools(TypedFailedBioService())
    }

    result = tools["pubmed.search"].invoke(
        args={"query": "alternative oxidase", "limit": 1},
        context=_context(),
    )

    assert result.payload["status"] == "failed"
    assert result.payload["findings"] == []
    assert result.payload["raw_ref"]["provider_call"]["outcome"] == "failed"
    assert result.payload["raw_ref"]["call_local_literature_quorum"][
        "cutover_eligible"
    ] is False
