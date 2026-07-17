from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Mapping

from .provider_runtime import ProviderCallResult
from .provider_runtime import ProviderOutcome
from .provider_runtime import safe_public_locator


class EvidenceRequirement(StrEnum):
    REQUIRED = "required"
    ENRICHMENT = "enrichment"


class EvidenceQuorumStatus(StrEnum):
    COMPLETE = "complete"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvidenceQuorumMember:
    provider: str
    requirement: EvidenceRequirement
    outcome: ProviderOutcome
    record_count: int
    accepted: bool
    error_code: str | None = None
    warning: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "provider": self.provider,
            "requirement": self.requirement.value,
            "outcome": self.outcome.value,
            "record_count": self.record_count,
            "accepted": self.accepted,
            "error_code": self.error_code,
            "warning": self.warning,
        }


@dataclass(frozen=True, slots=True)
class EvidenceQuorumResult:
    status: EvidenceQuorumStatus
    cutover_eligible: bool
    members: tuple[EvidenceQuorumMember, ...]
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "cutover_eligible": self.cutover_eligible,
            "members": [member.to_dict() for member in self.members],
            "warnings": list(self.warnings),
        }


def evaluate_literature_quorum(
    *,
    pubmed: ProviderCallResult[Any] | None,
    semantic_scholar: ProviderCallResult[Any] | None = None,
    tavily: ProviderCallResult[Any] | None = None,
) -> EvidenceQuorumResult:
    """Evaluate PubMed-required and enrichment-only literature evidence.

    A required provider must return at least one schema-valid record. Missing or
    empty enrichment never fabricates replacement evidence; it remains an
    explicit degradation while valid PubMed evidence stays usable.
    """

    members = [
        _member(
            provider="pubmed",
            requirement=EvidenceRequirement.REQUIRED,
            result=pubmed,
        ),
        _member(
            provider="semantic_scholar",
            requirement=EvidenceRequirement.ENRICHMENT,
            result=semantic_scholar,
        ),
        _member(
            provider="tavily",
            requirement=EvidenceRequirement.ENRICHMENT,
            result=tavily,
        ),
    ]
    required_complete = all(
        member.accepted
        for member in members
        if member.requirement is EvidenceRequirement.REQUIRED
    )
    degraded_enrichment = [
        member
        for member in members
        if member.requirement is EvidenceRequirement.ENRICHMENT
        and member.outcome is not ProviderOutcome.COMPLETED
    ]
    if not required_complete:
        status = EvidenceQuorumStatus.FAILED
    elif degraded_enrichment:
        status = EvidenceQuorumStatus.DEGRADED
    else:
        status = EvidenceQuorumStatus.COMPLETE
    warnings = tuple(
        member.warning
        for member in degraded_enrichment
        if member.warning is not None
    )
    return EvidenceQuorumResult(
        status=status,
        cutover_eligible=required_complete,
        members=tuple(members),
        warnings=warnings,
    )


def _member(
    *,
    provider: str,
    requirement: EvidenceRequirement,
    result: ProviderCallResult[Any] | None,
) -> EvidenceQuorumMember:
    if result is None:
        outcome = (
            ProviderOutcome.FAILED
            if requirement is EvidenceRequirement.REQUIRED
            else ProviderOutcome.DEGRADED
        )
        return EvidenceQuorumMember(
            provider=provider,
            requirement=requirement,
            outcome=outcome,
            record_count=0,
            accepted=False,
            error_code="provider_absent",
            warning=f"{provider} {requirement.value} provider is not configured",
        )
    if requirement is EvidenceRequirement.REQUIRED and provider == "pubmed":
        accepted, validation_error, validation_warning = (
            _validate_required_pubmed_result(result)
        )
    else:
        accepted = (
            result.outcome is ProviderOutcome.COMPLETED and bool(result.items)
        )
        validation_error = None
        validation_warning = None
    failure = result.failure
    warning = None
    if result.outcome is not ProviderOutcome.COMPLETED:
        warning = (
            f"{provider} returned {result.outcome.value}"
            if failure is None
            else failure.message
        )
    if validation_warning is not None:
        warning = validation_warning
    return EvidenceQuorumMember(
        provider=provider,
        requirement=requirement,
        outcome=result.outcome,
        record_count=len(result.items),
        accepted=accepted,
        error_code=(
            validation_error
            if validation_error is not None
            else (
                failure.error_code
                if failure is not None
                else (
                    "provider_empty"
                    if result.outcome is ProviderOutcome.EMPTY
                    else None
                )
            )
        ),
        warning=warning,
    )


def _validate_required_pubmed_result(
    result: ProviderCallResult[Any],
) -> tuple[bool, str | None, str | None]:
    if result.outcome is not ProviderOutcome.COMPLETED or not result.items:
        return False, None, None
    provenance = result.provenance
    if provenance.provider != "pubmed":
        return (
            False,
            "provider_identity_mismatch",
            "required PubMed evidence came from a different provider",
        )
    fixture_markers = {
        str(provenance.cache_status).casefold(),
        *(str(warning).casefold() for warning in result.warnings),
    }
    if any(
        "fixture" in marker or "non_cutover" in marker
        for marker in fixture_markers
    ):
        return (
            False,
            "fixture_non_cutover",
            "fixture PubMed evidence cannot satisfy required quorum",
        )
    identity = dict(provenance.provider_identity)
    identity_digest = str(identity.get("identity_digest") or "")
    if not identity.get("tool") or not _is_sha256_digest(identity_digest):
        return (
            False,
            "provider_identity_missing",
            "required PubMed evidence is missing its bound NCBI identity",
        )
    if not provenance.response_digest or not provenance.retrieved_at:
        return (
            False,
            "provider_provenance_incomplete",
            "required PubMed evidence is missing response provenance",
        )
    for item in result.items:
        item_provider = str(_item_field(item, "provider") or "")
        external_id = str(_item_field(item, "external_id") or "")
        title = str(_item_field(item, "title") or "").strip()
        locator = str(_item_field(item, "locator") or "")
        metadata = _item_metadata(item)
        pmid = str(metadata.get("pmid") or "")
        if (
            item_provider != "pubmed"
            or not pmid.isdigit()
            or external_id != f"PMID:{pmid}"
            or not title
            or safe_public_locator(locator) is None
        ):
            return (
                False,
                "provider_schema_drift",
                "required PubMed evidence contains a malformed citation record",
            )
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
                "fixture PubMed evidence cannot satisfy required quorum",
            )
    return True, None, None


def _item_field(item: Any, field: str) -> Any:
    if isinstance(item, Mapping):
        return item.get(field)
    return getattr(item, field, None)


def _item_metadata(item: Any) -> Mapping[str, Any]:
    value = _item_field(item, "metadata")
    return value if isinstance(value, Mapping) else {}


def _is_sha256_digest(value: str) -> bool:
    if not value.startswith("sha256:") or len(value) != 71:
        return False
    try:
        int(value.removeprefix("sha256:"), 16)
    except ValueError:
        return False
    return True


__all__ = [
    "EvidenceQuorumMember",
    "EvidenceQuorumResult",
    "EvidenceQuorumStatus",
    "EvidenceRequirement",
    "evaluate_literature_quorum",
]
