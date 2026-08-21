from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from .deliverables import ScientificDeliverableBundle
from .deliverables import ScientificDeliverableRef
from .deliverables import ScientificDeliverableValidationReceipt
from .deliverables import normalize_scientific_path


@dataclass(frozen=True, slots=True)
class ScientificRoleFinalizationRequirement:
    scientific_role: str
    path: str
    format_contract_id: str
    format_contract_digest: str
    producer_adoption_id: str

    def __post_init__(self) -> None:
        for field, value in (
            ("scientific_role", self.scientific_role),
            ("format_contract_id", self.format_contract_id),
            ("producer_adoption_id", self.producer_adoption_id),
        ):
            if (
                not value
                or value != value.strip()
                or any(character.isspace() for character in value)
            ):
                raise ValueError(f"{field} must be a non-empty identifier")
        normalize_scientific_path(self.path)
        if (
            not self.format_contract_digest.startswith("sha256:")
            or len(self.format_contract_digest) != 71
        ):
            raise ValueError("format_contract_digest must be a SHA-256 digest")


@dataclass(frozen=True, slots=True)
class ScientificDeliverableFinalizationCommand:
    publication_id: str
    attempt_id: str
    selection_id: str
    actor_ref: str
    execution_fencing_token: int
    contract_id: str
    contract_digest: str
    requirements: tuple[ScientificRoleFinalizationRequirement, ...]

    def __post_init__(self) -> None:
        if self.execution_fencing_token < 1:
            raise ValueError("execution_fencing_token must be positive")
        if not self.requirements:
            raise ValueError("scientific finalization requirements cannot be empty")


@dataclass(frozen=True, slots=True)
class ScientificDeliverableFinalizationOutcome:
    refs: tuple[ScientificDeliverableRef, ...]
    bundle: ScientificDeliverableBundle
    receipt: ScientificDeliverableValidationReceipt


class ScientificPublishedFileReadPort(Protocol):
    """Read exact immutable publication bytes without exposing a storage locator."""

    def read_bytes(self, *, publication_id: str, path: str) -> bytes: ...


class ScientificDeliverableFinalizationPort(Protocol):
    """Commit generic Science-owned deliverable facts through one application port."""

    def finalize(
        self,
        command: ScientificDeliverableFinalizationCommand,
    ) -> ScientificDeliverableFinalizationOutcome: ...


class ScientificDeliverableRequestHandler(Protocol):
    """Extension-owned parser/finalizer for one closed scientific product request."""

    def finalize_request(
        self,
        *,
        request: Mapping[str, object],
        actor_ref: str,
        published_files: ScientificPublishedFileReadPort,
        scientific_finalization: ScientificDeliverableFinalizationPort,
    ) -> Mapping[str, object]: ...


__all__ = [
    "ScientificDeliverableFinalizationCommand",
    "ScientificDeliverableFinalizationOutcome",
    "ScientificDeliverableFinalizationPort",
    "ScientificDeliverableRequestHandler",
    "ScientificPublishedFileReadPort",
    "ScientificRoleFinalizationRequirement",
]
