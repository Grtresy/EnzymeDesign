import json
from io import BytesIO
from urllib.error import HTTPError

import pytest

from openzyme_research import SourceRefKind

from openzyme_science_research.legacy_bio import DefaultLiteratureResearchService
from openzyme_research import BoundedHttpClient
from openzyme_research import ProviderOutcome
from openzyme_research import ProviderRequestError
from openzyme_research import provider_identity_digest
from openzyme_research import ResearchFileManifest
from openzyme_research import ResearchFinding
from openzyme_research import ResearchObservation
from openzyme_research import ResearchSource


class _JsonResponse:
    status = 200
    headers = {"Content-Type": "application/json", "X-Request-Id": "request-1"}

    def __init__(self, payload: dict[str, object]) -> None:
        self._body = json.dumps(payload).encode("utf-8")

    def __enter__(self) -> "_JsonResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None

    def read(self) -> bytes:
        return self._body


def _http_service(opener) -> DefaultLiteratureResearchService:
    return DefaultLiteratureResearchService(
        semantic_scholar_api_key="s2-secret",
        pubmed_api_key="pubmed-secret",
        pubmed_email="ncbi@example.org",
        http_client=BoundedHttpClient(
            opener=opener,
            sleeper=lambda delay: None,
            max_attempts=3,
        ),
    )


def test_pubmed_result_preserves_required_identifiers_and_safe_provenance() -> None:
    requests = []
    responses = iter(
        (
            {
                "esearchresult": {
                    "idlist": ["12345"],
                }
            },
            {
                "result": {
                    "uids": ["12345"],
                    "12345": {
                        "uid": "12345",
                        "title": "Alternative oxidase evidence",
                        "pubdate": "2024 Jan",
                        "fulljournalname": "Plant Physiology",
                        "authors": [{"name": "Doe J", "authtype": "Author"}],
                        "articleids": [
                            {"idtype": "pubmed", "value": "12345"},
                            {"idtype": "doi", "value": "10.1000/aox.1"},
                        ],
                    },
                }
            },
        )
    )

    def opener(request, timeout):
        requests.append(request)
        return _JsonResponse(next(responses))

    result = _http_service(opener).search_pubmed_result(
        query="alternative oxidase motif",
        limit=3,
    )

    assert result.outcome is ProviderOutcome.COMPLETED
    hit = result.items[0]
    assert hit.external_id == "PMID:12345"
    assert hit.year == 2024
    assert hit.metadata == {
        "pmid": "12345",
        "doi": "10.1000/aox.1",
        "authors": [{"name": "Doe J", "author_type": "Author"}],
        "venue": "Plant Physiology",
        "publication_date": "2024 Jan",
        "retrieved_at": result.provenance.retrieved_at,
        "response_digest": result.provenance.response_digest,
        "provider_provenance": result.provenance.to_dict(),
    }
    assert len(requests) == 2
    assert all("tool=openzyme" in request.full_url for request in requests)
    assert all("email=ncbi%40example.org" in request.full_url for request in requests)
    assert all("api_key=pubmed-secret" in request.full_url for request in requests)
    safe = json.dumps(result.provenance.to_dict(), sort_keys=True)
    assert "pubmed-secret" not in safe
    assert "ncbi@example.org" not in safe
    assert result.provenance.endpoint_id == "pubmed.esearch+esummary:v1"
    expected_identity_digest = provider_identity_digest(
        provider="ncbi",
        identity={
            "tool": "openzyme",
            "email": "ncbi@example.org",
            "api_key": "pubmed-secret",
        },
    )
    assert dict(result.provenance.provider_identity) == {
        "api_key_configured": "True",
        "email_configured": "True",
        "identity_digest": expected_identity_digest,
        "tool": "openzyme",
    }
    assert "ncbi@example.org" not in expected_identity_digest
    assert "pubmed-secret" not in expected_identity_digest


def test_pubmed_empty_result_is_distinct_from_schema_drift() -> None:
    empty_service = _http_service(
        lambda request, timeout: _JsonResponse({"esearchresult": {"idlist": []}})
    )

    empty = empty_service.search_pubmed_result(query="no such AOX paper")

    assert empty.outcome is ProviderOutcome.EMPTY
    assert empty.items == ()

    drift_service = _http_service(
        lambda request, timeout: _JsonResponse({"unexpected": {}})
    )
    with pytest.raises(ProviderRequestError) as error:
        drift_service.search_pubmed_result(query="alternative oxidase")
    assert error.value.error_code == "provider_schema_drift"


def test_semantic_scholar_rate_limit_is_typed_and_bounded() -> None:
    calls = 0

    def opener(request, timeout):
        nonlocal calls
        calls += 1
        raise HTTPError(
            request.full_url,
            429,
            "rate limited",
            {"Retry-After": "0"},
            BytesIO(),
        )

    result = _http_service(opener).search_semantic_scholar_result(
        query="alternative oxidase"
    )

    assert calls == 3
    assert result.outcome is ProviderOutcome.DEGRADED
    assert result.failure is not None
    assert result.failure.error_code == "provider_rate_limited"
    assert result.provenance.attempt_count == 3


def test_semantic_scholar_missing_data_is_schema_drift() -> None:
    service = _http_service(lambda request, timeout: _JsonResponse({"total": 0}))

    result = service.search_semantic_scholar_result(query="alternative oxidase")

    assert result.outcome is ProviderOutcome.DEGRADED
    assert result.failure is not None
    assert result.failure.error_code == "provider_schema_drift"


def test_research_observation_serializes_stable_normalized_fields() -> None:
    observation = ResearchObservation.completed(
        summary="Collected evidence.",
        findings=(
            ResearchFinding(
                summary="Finding summary",
                query="enzyme query",
                confidence_label="high",
                sources=(
                    ResearchSource(
                        title="Paper A",
                        locator="https://example.org/a",
                        kind=SourceRefKind.PAPER,
                        snippet="Evidence snippet",
                    ),
                ),
            ),
            {
                "summary": "Dict finding",
                "query": "enzyme query",
                "confidence_label": "medium",
                "sources": [
                    {
                        "title": "Dataset A",
                        "locator": "https://example.org/dataset-a",
                        "kind": SourceRefKind.DATASET,
                    }
                ],
            },
        ),
        unresolved_gaps=("Need validation",),
        files=(
            ResearchFileManifest(
                external_id="P12345",
                provider="uniprot",
                kind="sequence",
                format="fasta",
                filename="P12345.fasta",
                title="P12345 FASTA",
            ),
        ),
        provider="pubmed",
    )

    payload = observation.to_dict()

    assert list(payload.keys()) == [
        "status",
        "summary",
        "findings",
        "unresolved_gaps",
        "files",
        "provider",
        "raw_ref",
    ]
    assert payload["findings"][0]["sources"][0]["kind"] == "paper"
    assert payload["findings"][1]["sources"][0]["kind"] == "dataset"
    assert payload["files"][0]["kind"] == "sequence"
