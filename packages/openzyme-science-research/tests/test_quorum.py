from openzyme_research import ProviderAttempt
from openzyme_research import ProviderProvenance
from openzyme_research import completed_result
from openzyme_research import degraded_result

from openzyme_science_research import EvidenceQuorumStatus
from openzyme_science_research import LiteratureHit
from openzyme_science_research import evaluate_literature_quorum


def _provenance(provider: str, *, with_identity: bool = True) -> ProviderProvenance:
    return ProviderProvenance(
        provider=provider,
        operation="literature.search",
        endpoint_id=f"{provider}.search:v1",
        request_digest="sha256:" + "1" * 64,
        response_digest="sha256:" + "2" * 64,
        retrieved_at="2026-08-19T00:00:00+00:00",
        response_status=200,
        attempt_count=1,
        attempts=(
            ProviderAttempt(
                attempt=1,
                started_at="2026-08-19T00:00:00+00:00",
                finished_at="2026-08-19T00:00:01+00:00",
                outcome="completed",
                status_code=200,
            ),
        ),
        provider_identity=(
            (("identity_digest", "sha256:" + "3" * 64),) if with_identity else ()
        ),
    )


def test_pubmed_required_and_optional_enrichment_does_not_fallback() -> None:
    pubmed = completed_result(
        (
            LiteratureHit(
                provider="pubmed",
                external_id="PMID:12345",
                title="Evidence",
                summary="Source-bound evidence",
                locator="https://pubmed.ncbi.nlm.nih.gov/12345/",
                metadata={"pmid": "12345"},
            ),
        ),
        provenance=_provenance("pubmed"),
    )
    semantic = degraded_result(
        provenance=_provenance("semantic_scholar"),
        error_code="provider_rate_limited",
        message="rate limited",
        retryable=True,
    )

    result = evaluate_literature_quorum(
        pubmed=pubmed,
        semantic_scholar=semantic,
        tavily=None,
    )

    assert result.status is EvidenceQuorumStatus.DEGRADED
    assert result.cutover_eligible is True
    assert [member.provider for member in result.members] == [
        "pubmed",
        "semantic_scholar",
        "tavily",
    ]
    assert result.members[2].error_code == "provider_absent"


def test_missing_pubmed_fails_closed_even_when_optional_source_succeeds() -> None:
    semantic = completed_result(
        ({"paper_id": "s2"},),
        provenance=_provenance("semantic_scholar"),
    )

    result = evaluate_literature_quorum(
        pubmed=None,
        semantic_scholar=semantic,
        tavily=None,
    )

    assert result.status is EvidenceQuorumStatus.FAILED
    assert result.cutover_eligible is False
