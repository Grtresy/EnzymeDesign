import pytest

from openzyme_research import EvidenceQuorumStatus
from openzyme_research import DeterministicBioResearchService
from openzyme_research import LiteratureHit
from openzyme_research import ProviderAttempt
from openzyme_research import ProviderProvenance
from openzyme_research import completed_result
from openzyme_research import degraded_result
from openzyme_research import evaluate_literature_quorum
from openzyme_research import failed_result


def _provenance(
    provider: str,
    *,
    with_identity: bool = True,
    cache_status: str = "disabled",
) -> ProviderProvenance:
    return ProviderProvenance(
        provider=provider,
        operation="literature.search",
        endpoint_id=f"{provider}.search:v1",
        request_digest="sha256:" + "1" * 64,
        response_digest="sha256:" + "2" * 64,
        retrieved_at="2026-07-17T12:00:00+00:00",
        response_status=200,
        attempt_count=1,
        attempts=(
            ProviderAttempt(
                attempt=1,
                started_at="2026-07-17T12:00:00+00:00",
                finished_at="2026-07-17T12:00:01+00:00",
                outcome="completed",
                status_code=200,
            ),
        ),
        cache_status=cache_status,
        provider_identity=(
            (
                ("identity_digest", "sha256:" + "3" * 64),
                ("tool", "openzyme"),
            )
            if provider == "pubmed" and with_identity
            else ()
        ),
    )


def _pubmed_hit(**overrides: object) -> LiteratureHit:
    values: dict[str, object] = {
        "provider": "pubmed",
        "external_id": "PMID:12345",
        "title": "Alternative oxidase evidence",
        "summary": "Curated PubMed evidence.",
        "locator": "https://pubmed.ncbi.nlm.nih.gov/12345/",
        "year": 2024,
        "metadata": {"pmid": "12345", "doi": "10.1000/aox.1"},
    }
    values.update(overrides)
    return LiteratureHit(**values)  # type: ignore[arg-type]


def test_required_pubmed_complete_survives_enrichment_degradation() -> None:
    pubmed = completed_result(
        (_pubmed_hit(),),
        provenance=_provenance("pubmed"),
    )
    semantic_scholar = degraded_result(
        provenance=_provenance("semantic_scholar"),
        error_code="provider_rate_limited",
        message="semantic_scholar enrichment is rate limited",
        retryable=True,
        status_code=429,
    )

    result = evaluate_literature_quorum(
        pubmed=pubmed,
        semantic_scholar=semantic_scholar,
        tavily=None,
    )

    assert result.status is EvidenceQuorumStatus.DEGRADED
    assert result.cutover_eligible is True
    assert result.members[0].record_count == 1
    assert result.members[0].accepted is True
    assert result.members[1].error_code == "provider_rate_limited"
    assert result.members[2].error_code == "provider_absent"


def test_required_pubmed_empty_or_failed_fails_closed() -> None:
    pubmed_empty = completed_result((), provenance=_provenance("pubmed"))
    pubmed_failed = failed_result(
        provenance=_provenance("pubmed"),
        error_code="provider_schema_drift",
        message="pubmed schema drift",
        retryable=False,
    )
    enrichment = completed_result(
        ({"paper_id": "s2"},),
        provenance=_provenance("semantic_scholar"),
    )

    for required in (pubmed_empty, pubmed_failed, None):
        result = evaluate_literature_quorum(
            pubmed=required,
            semantic_scholar=enrichment,
            tavily=None,
        )
        assert result.status is EvidenceQuorumStatus.FAILED
        assert result.cutover_eligible is False


def test_required_pubmed_rejects_missing_ncbi_identity_digest() -> None:
    pubmed = completed_result(
        (_pubmed_hit(),),
        provenance=_provenance("pubmed", with_identity=False),
    )

    result = evaluate_literature_quorum(pubmed=pubmed)

    required = result.members[0]
    assert result.status is EvidenceQuorumStatus.FAILED
    assert result.cutover_eligible is False
    assert required.accepted is False
    assert required.error_code == "provider_identity_missing"


def test_required_pubmed_rejects_deterministic_fixture_evidence() -> None:
    fixture = DeterministicBioResearchService().search_pubmed_result(
        query="alternative oxidase",
        limit=1,
    )

    result = evaluate_literature_quorum(pubmed=fixture)

    required = result.members[0]
    assert result.status is EvidenceQuorumStatus.FAILED
    assert result.cutover_eligible is False
    assert required.accepted is False
    assert required.error_code == "fixture_non_cutover"


def test_required_pubmed_rejects_fixture_marker_in_record_metadata() -> None:
    fixture_hit = _pubmed_hit(
        metadata={
            "pmid": "12345",
            "scientific_status": "fixture_non_cutover",
        }
    )

    result = evaluate_literature_quorum(
        pubmed=completed_result(
            (fixture_hit,),
            provenance=_provenance("pubmed"),
        )
    )

    required = result.members[0]
    assert result.cutover_eligible is False
    assert required.accepted is False
    assert required.error_code == "fixture_non_cutover"


@pytest.mark.parametrize(
    "record",
    (
        {
            "provider": "semantic_scholar",
            "external_id": "PMID:12345",
            "title": "AOX evidence",
            "locator": "https://pubmed.ncbi.nlm.nih.gov/12345/",
            "metadata": {"pmid": "12345"},
        },
        {
            "provider": "pubmed",
            "external_id": "12345",
            "title": "AOX evidence",
            "locator": "https://pubmed.ncbi.nlm.nih.gov/12345/",
            "metadata": {"pmid": "12345"},
        },
        {
            "provider": "pubmed",
            "external_id": "PMID:12345",
            "title": "",
            "locator": "https://pubmed.ncbi.nlm.nih.gov/12345/",
            "metadata": {"pmid": "12345"},
        },
        {
            "provider": "pubmed",
            "external_id": "PMID:not-a-pmid",
            "title": "AOX evidence",
            "locator": "https://pubmed.ncbi.nlm.nih.gov/not-a-pmid/",
            "metadata": {"pmid": "not-a-pmid"},
        },
        {
            "provider": "pubmed",
            "external_id": "PMID:12345",
            "title": "AOX evidence",
            "locator": "http://169.254.169.254/latest/meta-data/",
            "metadata": {"pmid": "12345"},
        },
    ),
)
def test_required_pubmed_rejects_malformed_citation_record(
    record: dict[str, object],
) -> None:
    result = evaluate_literature_quorum(
        pubmed=completed_result(
            (record,),
            provenance=_provenance("pubmed"),
        )
    )

    required = result.members[0]
    assert result.status is EvidenceQuorumStatus.FAILED
    assert result.cutover_eligible is False
    assert required.accepted is False
    assert required.error_code == "provider_schema_drift"
