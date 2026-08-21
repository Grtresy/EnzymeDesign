from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from .identity import JsonValue
from .identity import canonical_sha256_digest
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_digest
from .identity import require_identifier


EVIDENCE_REF_SCHEMA_VERSION = "openzyme_evidence_ref@1"


class EvidenceKind(StrEnum):
    REVISION_PATH = "revision_path"
    CONTROLLED_OPERATION_RESULT = "controlled_operation_result"
    EXTENSION = "extension"


@dataclass(frozen=True, slots=True)
class EvidenceRef:
    """Domain-neutral reference to immutable evidence owned elsewhere."""

    evidence_id: str
    evidence_kind: EvidenceKind
    contract_id: str
    owner_component_id: str
    project_id: str
    session_id: str
    task_id: str
    subject_ref: str
    subject_digest: str
    attributes: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        for field_name in (
            "evidence_id",
            "contract_id",
            "owner_component_id",
            "project_id",
            "session_id",
            "task_id",
            "subject_ref",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.subject_digest, field_name="subject_digest")
        attributes = freeze_json(self.attributes, field_name="attributes")
        if not isinstance(attributes, Mapping):
            raise ValueError("attributes must be a JSON object")
        object.__setattr__(self, "attributes", attributes)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EVIDENCE_REF_SCHEMA_VERSION,
            "evidence_id": self.evidence_id,
            "evidence_kind": self.evidence_kind.value,
            "contract_id": self.contract_id,
            "owner_component_id": self.owner_component_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "task_id": self.task_id,
            "subject_ref": self.subject_ref,
            "subject_digest": self.subject_digest,
            "attributes": json_compatible(self.attributes),
        }

    @property
    def evidence_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


__all__ = [
    "EVIDENCE_REF_SCHEMA_VERSION",
    "EvidenceKind",
    "EvidenceRef",
]
