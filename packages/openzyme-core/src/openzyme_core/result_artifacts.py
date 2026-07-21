from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json

from openzyme_domain import ArtifactKind


@dataclass(frozen=True, slots=True)
class ControlledOperationResultArtifactRef:
    artifact_id: str
    kind: ArtifactKind
    relative_path: str
    artifact_digest: str

    def identity(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "kind": self.kind.value,
            "relative_path": self.relative_path,
            "content_digest": self.artifact_digest,
        }


def normalize_controlled_operation_result_artifacts(
    refs: tuple[ControlledOperationResultArtifactRef, ...],
) -> tuple[ControlledOperationResultArtifactRef, ...]:
    ordered = tuple(sorted(refs, key=lambda ref: ref.artifact_id))
    if len({ref.artifact_id for ref in ordered}) != len(ordered):
        raise ValueError("durable result artifact ids must be unique")
    return ordered


def controlled_operation_artifact_set_digest(
    refs: tuple[ControlledOperationResultArtifactRef, ...],
) -> str:
    ordered = normalize_controlled_operation_result_artifacts(refs)
    encoded = json.dumps(
        [ref.identity() for ref in ordered],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


__all__ = [
    "ControlledOperationResultArtifactRef",
    "controlled_operation_artifact_set_digest",
    "normalize_controlled_operation_result_artifacts",
]
