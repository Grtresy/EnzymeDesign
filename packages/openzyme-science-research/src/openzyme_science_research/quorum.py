from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from openzyme_research import ProviderCallResult
from openzyme_research import ProviderOutcome
from openzyme_research import safe_public_locator

from .contracts import EvidenceQuorumMember
from .contracts import EvidenceQuorumResult
from .contracts import EvidenceQuorumStatus
from .contracts import EvidenceRequirement


def evaluate_literature_quorum(
    *,
    pubmed: ProviderCallResult[Any] | None,
    semantic_scholar: ProviderCallResult[Any] | None = None,
    tavily: ProviderCallResult[Any] | None = None,
) -> EvidenceQuorumResult:
    required = _member("pubmed", EvidenceRequirement.REQUIRED, pubmed)
    enrichments = (
        _member(
            "semantic_scholar",
            EvidenceRequirement.OPTIONAL_ENRICHMENT,
            semantic_scholar,
        ),
        _member("tavily", EvidenceRequirement.OPTIONAL_ENRICHMENT, tavily),
    )
    required_accepted, error_code, message = _validate_pubmed(pubmed)
    if not required_accepted:
        required = EvidenceQuorumMember(
            provider=required.provider,
            requirement=required.requirement,
            outcome=required.outcome,
            record_count=required.record_count,
            accepted=False,
            error_code=error_code or required.error_code,
            message=message or required.message,
            provenance=required.provenance,
        )
        return EvidenceQuorumResult(
            status=EvidenceQuorumStatus.FAILED,
            cutover_eligible=False,
            members=(required, *enrichments),
        )
    degraded = any(not member.accepted for member in enrichments)
    return EvidenceQuorumResult(
        status=(
            EvidenceQuorumStatus.DEGRADED
            if degraded
            else EvidenceQuorumStatus.COMPLETED
        ),
        cutover_eligible=True,
        members=(required, *enrichments),
    )


def _member(
    provider: str,
    requirement: EvidenceRequirement,
    result: ProviderCallResult[Any] | None,
) -> EvidenceQuorumMember:
    if result is None:
        return EvidenceQuorumMember(
            provider=provider,
            requirement=requirement,
            outcome="absent",
            record_count=0,
            accepted=False,
            error_code="provider_absent",
            message=f"{provider} is not selected in this composition",
        )
    failure = result.failure
    accepted = result.outcome is ProviderOutcome.COMPLETED and bool(result.items)
    return EvidenceQuorumMember(
        provider=provider,
        requirement=requirement,
        outcome=result.outcome.value,
        record_count=len(result.items),
        accepted=accepted,
        error_code=None if failure is None else failure.error_code,
        message=None if failure is None else failure.message,
        provenance=result.provenance.to_dict(),
    )


def _validate_pubmed(
    result: ProviderCallResult[Any] | None,
) -> tuple[bool, str | None, str | None]:
    if (
        result is None
        or result.outcome is not ProviderOutcome.COMPLETED
        or not result.items
    ):
        return False, "required_provider_unsatisfied", "PubMed evidence is required"
    if result.provenance.cache_status == "fixture_non_cutover":
        return False, "fixture_non_cutover", "fixture evidence cannot satisfy quorum"
    identity = dict(result.provenance.provider_identity)
    digest = str(identity.get("identity_digest") or "")
    if not _sha256(digest):
        return False, "provider_identity_missing", "PubMed provider identity is missing"
    for item in result.items:
        provider = str(_field(item, "provider") or "")
        external_id = str(_field(item, "external_id") or "")
        title = str(_field(item, "title") or "")
        locator = str(_field(item, "locator") or "")
        metadata = _metadata(item)
        pmid = str(metadata.get("pmid") or "")
        if (
            provider != "pubmed"
            or not pmid.isdigit()
            or external_id != f"PMID:{pmid}"
            or not title
            or safe_public_locator(locator) is None
        ):
            return False, "provider_schema_drift", "malformed PubMed citation"
        if (
            metadata.get("fixture") is True
            or metadata.get("synthetic_source") is True
            or metadata.get("cutover_eligible") is False
            or str(metadata.get("scientific_status") or "").casefold()
            == "fixture_non_cutover"
        ):
            return (
                False,
                "fixture_non_cutover",
                "fixture evidence cannot satisfy quorum",
            )
    return True, None, None


def _field(item: Any, name: str) -> Any:
    return item.get(name) if isinstance(item, Mapping) else getattr(item, name, None)


def _metadata(item: Any) -> Mapping[str, Any]:
    value = _field(item, "metadata")
    return value if isinstance(value, Mapping) else {}


def _sha256(value: str) -> bool:
    if not value.startswith("sha256:") or len(value) != 71:
        return False
    try:
        int(value[7:], 16)
    except ValueError:
        return False
    return True


__all__ = ["evaluate_literature_quorum"]
