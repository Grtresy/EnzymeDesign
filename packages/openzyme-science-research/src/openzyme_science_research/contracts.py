from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol

from openzyme_research import ProviderCallResult


@dataclass(frozen=True, slots=True)
class LiteratureHit:
    provider: str
    external_id: str
    title: str
    summary: str
    locator: str
    year: int | None = None
    citation_count: int | None = None
    metadata: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class LiteratureProviderPort(Protocol):
    @property
    def provider_id(self) -> str: ...

    def search(
        self,
        *,
        query: str,
        limit: int,
        operation_id: str,
    ) -> ProviderCallResult[LiteratureHit]: ...


class EvidenceRequirement(StrEnum):
    REQUIRED = "required"
    OPTIONAL_ENRICHMENT = "optional_enrichment"


class EvidenceQuorumStatus(StrEnum):
    COMPLETED = "completed"
    DEGRADED = "degraded"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class EvidenceQuorumMember:
    provider: str
    requirement: EvidenceRequirement
    outcome: str
    record_count: int
    accepted: bool
    error_code: str | None = None
    message: str | None = None
    provenance: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["requirement"] = self.requirement.value
        return data


@dataclass(frozen=True, slots=True)
class EvidenceQuorumResult:
    status: EvidenceQuorumStatus
    cutover_eligible: bool
    members: tuple[EvidenceQuorumMember, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "status": self.status.value,
            "cutover_eligible": self.cutover_eligible,
            "members": [member.to_dict() for member in self.members],
        }


__all__ = [
    "EvidenceQuorumMember",
    "EvidenceQuorumResult",
    "EvidenceQuorumStatus",
    "EvidenceRequirement",
    "LiteratureHit",
    "LiteratureProviderPort",
]
