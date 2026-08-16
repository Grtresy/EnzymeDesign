from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")


def canonical_historical_artifact_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


class HistoricalArtifactEligibility(StrEnum):
    NON_ADOPTABLE = "historical_import_non_adoptable"


class HistoricalArtifactStorage(StrEnum):
    GIT_BLOB = "git_blob"
    GIT_LFS = "git_lfs"


@dataclass(frozen=True, slots=True)
class HistoricalArtifactRef:
    historical_ref_id: str
    original_artifact_id: str
    original_kind: str
    original_digest: str
    original_size: int
    project_id: str
    session_id: str
    owner_identity_digest: str
    lineage_digest: str
    source_snapshot_digest: str
    migration_unit_id: str
    repository_binding_id: str
    repository_binding_version: int
    historical_ref: str
    historical_commit: str
    historical_tree: str
    path: str
    storage: HistoricalArtifactStorage
    git_blob_oid: str | None
    lfs_oid: str | None
    lfs_size: int | None
    verification_digest: str
    eligibility: HistoricalArtifactEligibility
    supersession_decision_digest: str | None
    created_at: str
    ref_digest: str
    schema_version: str = "historical_artifact_ref@1"

    def __post_init__(self) -> None:
        if self.eligibility is not HistoricalArtifactEligibility.NON_ADOPTABLE:
            raise ValueError("historical artifact imports are permanently non-adoptable")
        if self.original_size < 0 or self.repository_binding_version < 1:
            raise ValueError("historical artifact size or binding version is invalid")
        if not self.historical_ref.startswith("refs/openzyme/history/"):
            raise ValueError("historical artifact ref is outside the append-only namespace")
        if _OID.fullmatch(self.historical_commit) is None or _OID.fullmatch(
            self.historical_tree
        ) is None:
            raise ValueError("historical commit/tree identity is invalid")
        if not self.path or self.path.startswith("/") or ".." in self.path.split("/"):
            raise ValueError("historical artifact path is not normalized")
        for value in (
            self.original_digest,
            self.owner_identity_digest,
            self.lineage_digest,
            self.source_snapshot_digest,
            self.verification_digest,
            self.ref_digest,
        ):
            if _DIGEST.fullmatch(value) is None:
                raise ValueError("historical artifact digest is invalid")
        if self.supersession_decision_digest is not None and _DIGEST.fullmatch(
            self.supersession_decision_digest
        ) is None:
            raise ValueError("historical supersession digest is invalid")
        if self.storage is HistoricalArtifactStorage.GIT_BLOB:
            if self.git_blob_oid is None or self.lfs_oid is not None or self.lfs_size is not None:
                raise ValueError("historical Git blob identity is inconsistent")
            if _OID.fullmatch(self.git_blob_oid) is None:
                raise ValueError("historical Git blob oid is invalid")
        elif (
            self.git_blob_oid is not None
            or self.lfs_oid is None
            or self.lfs_size != self.original_size
            or _DIGEST.fullmatch(self.lfs_oid) is None
        ):
            raise ValueError("historical Git LFS identity is inconsistent")
        if self.ref_digest != canonical_historical_artifact_digest(self.payload):
            raise ValueError("historical artifact ref digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            "schema_version": self.schema_version,
            "historical_ref_id": self.historical_ref_id,
            "original_artifact_id": self.original_artifact_id,
            "original_kind": self.original_kind,
            "original_digest": self.original_digest,
            "original_size": self.original_size,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "owner_identity_digest": self.owner_identity_digest,
            "lineage_digest": self.lineage_digest,
            "source_snapshot_digest": self.source_snapshot_digest,
            "migration_unit_id": self.migration_unit_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "historical_ref": self.historical_ref,
            "historical_commit": self.historical_commit,
            "historical_tree": self.historical_tree,
            "path": self.path,
            "storage": self.storage.value,
            "git_blob_oid": self.git_blob_oid,
            "lfs_oid": self.lfs_oid,
            "lfs_size": self.lfs_size,
            "verification_digest": self.verification_digest,
            "eligibility": self.eligibility.value,
            "supersession_decision_digest": self.supersession_decision_digest,
            "created_at": self.created_at,
        }

    @classmethod
    def create(cls, **values: Any) -> "HistoricalArtifactRef":
        payload = {
            "schema_version": "historical_artifact_ref@1",
            **values,
            "storage": values["storage"].value,
            "eligibility": values["eligibility"].value,
        }
        return cls(
            **values,
            ref_digest=canonical_historical_artifact_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class HistoricalArtifactMigrationUnitReceipt:
    receipt_id: str
    migration_unit_id: str
    inventory_digest: str
    expected_identity_set_digest: str
    migrated_identity_set_digest: str
    target_ref: str
    target_commit: str
    target_tree: str
    lfs_closure_digest: str
    mapping_digest: str
    reference_rewrite_digest: str
    actual_byte_total: int
    zero_post_freeze_write: bool
    non_adoption_digest: str
    created_at: str
    receipt_digest: str
    schema_version: str = "historical_artifact_migration_unit_receipt@1"

    def __post_init__(self) -> None:
        if self.expected_identity_set_digest != self.migrated_identity_set_digest:
            raise ValueError("historical migration unit identity sets differ")
        if self.actual_byte_total < 0 or not self.zero_post_freeze_write:
            raise ValueError("historical migration unit is not deletion-ready")
        if not self.target_ref.startswith("refs/openzyme/history/"):
            raise ValueError("historical migration target ref is invalid")


@dataclass(frozen=True, slots=True)
class HistoricalArtifactMigrationReceipt:
    receipt_id: str
    inventory_digest: str
    expected_global_identity_set_digest: str
    migrated_global_identity_set_digest: str
    unit_receipt_set_digest: str
    mapping_set_digest: str
    reference_rewrite_set_digest: str
    git_lfs_closure_set_digest: str
    non_adoption_set_digest: str
    negative_item_count: int
    source_preserved: bool
    created_at: str
    receipt_digest: str
    schema_version: str = "historical_artifact_migration_receipt@1"

    def __post_init__(self) -> None:
        if (
            self.expected_global_identity_set_digest
            != self.migrated_global_identity_set_digest
            or self.negative_item_count != 0
            or not self.source_preserved
        ):
            raise ValueError("historical migration global exact-set proof is incomplete")


__all__ = [
    "HistoricalArtifactEligibility",
    "HistoricalArtifactMigrationReceipt",
    "HistoricalArtifactMigrationUnitReceipt",
    "HistoricalArtifactRef",
    "HistoricalArtifactStorage",
    "canonical_historical_artifact_digest",
]
