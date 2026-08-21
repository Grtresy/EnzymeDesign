from __future__ import annotations

from dataclasses import dataclass
from dataclasses import fields
from datetime import datetime
from enum import StrEnum
import hashlib
import json
from pathlib import PurePosixPath
import re
import unicodedata
from typing import Any


_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_OID = re.compile(r"(?:[0-9a-f]{40}|[0-9a-f]{64})")
SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION = "scientific_deliverable_ref@1"


def canonical_scientific_deliverable_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _record(instance: object, schema_version: str) -> dict[str, object]:
    result: dict[str, object] = {"schema_version": schema_version}
    for item in fields(instance):
        if item.name == "schema_version":
            continue
        value = getattr(instance, item.name)
        if isinstance(value, StrEnum):
            value = value.value
        elif isinstance(value, tuple):
            value = [
                entry.to_dict() if hasattr(entry, "to_dict") else entry
                for entry in value
            ]
        result[item.name] = value
    return result


def _require_identifier(name: str, value: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{name} must be a non-empty identifier")


def _require_digest(name: str, value: str) -> None:
    if not isinstance(value, str) or _DIGEST.fullmatch(value) is None:
        raise ValueError(f"{name} must be a canonical SHA-256 digest")


def _require_oid(name: str, value: str) -> None:
    if not isinstance(value, str) or _OID.fullmatch(value) is None:
        raise ValueError(f"{name} must be a Git object id")


def _require_timestamp(name: str, value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be an ISO timestamp") from exc
    if parsed.tzinfo is None:
        raise ValueError(f"{name} must include timezone")


def normalize_scientific_path(value: str) -> str:
    if not isinstance(value, str) or value != unicodedata.normalize("NFC", value):
        raise ValueError("scientific path must use Unicode NFC")
    path = PurePosixPath(value)
    if (
        not value
        or path.is_absolute()
        or path.as_posix() != value
        or value.endswith("/")
        or any(part in {"", ".", ".."} for part in path.parts)
        or value == ".git"
        or value.startswith(".git/")
        or "\\" in value
    ):
        raise ValueError("scientific path must be normalized and repository-relative")
    return value


class ScientificFileStorage(StrEnum):
    GIT_BLOB = "git_blob"
    GIT_LFS = "git_lfs"


@dataclass(frozen=True, slots=True)
class ScientificFileEffectAdoption:
    adoption_id: str
    selection_id: str
    selection_revision: int
    attempt_id: str
    workflow_role: str
    operation_id: str
    execution_id: str
    result_id: str
    result_digest: str
    effect_certainty: str
    actor_ref: str
    execution_fencing_token: int
    idempotency_key: str
    request_digest: str
    created_at: str
    adoption_digest: str
    schema_version: str = "scientific_file_effect_adoption@1"

    def __post_init__(self) -> None:
        for name in (
            "adoption_id",
            "selection_id",
            "attempt_id",
            "workflow_role",
            "operation_id",
            "execution_id",
            "result_id",
            "actor_ref",
            "idempotency_key",
        ):
            _require_identifier(name, getattr(self, name))
        for name in ("result_digest", "request_digest", "adoption_digest"):
            _require_digest(name, getattr(self, name))
        if self.effect_certainty not in {"effect_known", "terminal_known"}:
            raise ValueError("scientific file adoption requires a known effect")
        if (
            not isinstance(self.selection_revision, int)
            or isinstance(self.selection_revision, bool)
            or self.selection_revision < 1
            or not isinstance(self.execution_fencing_token, int)
            or isinstance(self.execution_fencing_token, bool)
            or self.execution_fencing_token < 1
        ):
            raise ValueError("scientific file adoption revision or fence is invalid")
        _require_timestamp("created_at", self.created_at)
        if self.adoption_digest != canonical_scientific_deliverable_digest(
            self.payload
        ):
            raise ValueError("scientific file adoption digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "adoption_digest"
        }

    def to_dict(self) -> dict[str, object]:
        return _record(self, self.schema_version)

    @classmethod
    def create(cls, **values: Any) -> "ScientificFileEffectAdoption":
        payload = {"schema_version": "scientific_file_effect_adoption@1", **values}
        return cls(
            **values,
            adoption_digest=canonical_scientific_deliverable_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class ScientificDeliverableRef:
    ref_id: str
    project_id: str
    session_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_policy_digest: str
    publication_id: str
    publication_digest: str
    publication_ref: str
    published_commit: str
    published_tree: str
    path: str
    storage: ScientificFileStorage
    git_blob_oid: str | None
    lfs_oid: str | None
    lfs_declared_size: int | None
    actual_size: int
    content_digest: str
    scientific_role: str
    format_contract_id: str
    format_contract_digest: str
    deliverable_contract_id: str
    deliverable_contract_digest: str
    producer_operation_id: str
    producer_execution_id: str
    producer_result_id: str
    producer_result_digest: str
    attempt_id: str
    attempt_state_version: int
    selection_id: str
    selection_revision: int
    producer_adoption_id: str
    selection_adoption_digest: str
    publisher_workspace_id: str
    publisher_workspace_generation: int
    publisher_agent_member_id: str
    created_at: str
    supersedes_ref_id: str | None
    ref_digest: str
    schema_version: str = SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION:
            raise ValueError("unsupported scientific deliverable ref schema")
        for name in (
            "ref_id",
            "project_id",
            "session_id",
            "repository_binding_id",
            "publication_id",
            "scientific_role",
            "format_contract_id",
            "deliverable_contract_id",
            "producer_operation_id",
            "producer_execution_id",
            "producer_result_id",
            "attempt_id",
            "selection_id",
            "producer_adoption_id",
            "publisher_workspace_id",
            "publisher_agent_member_id",
        ):
            _require_identifier(name, getattr(self, name))
        for name in (
            "repository_policy_digest",
            "publication_digest",
            "content_digest",
            "format_contract_digest",
            "deliverable_contract_digest",
            "producer_result_digest",
            "selection_adoption_digest",
            "ref_digest",
        ):
            _require_digest(name, getattr(self, name))
        for name in (
            "repository_binding_version",
            "attempt_state_version",
            "selection_revision",
            "publisher_workspace_generation",
        ):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        if (
            not isinstance(self.actual_size, int)
            or isinstance(self.actual_size, bool)
            or self.actual_size < 0
        ):
            raise ValueError("actual_size must be non-negative")
        _require_oid("published_commit", self.published_commit)
        _require_oid("published_tree", self.published_tree)
        normalize_scientific_path(self.path)
        if not self.publication_ref.startswith("refs/openzyme/publications/"):
            raise ValueError(
                "scientific deliverable requires an immutable publication ref"
            )
        if self.storage is ScientificFileStorage.GIT_BLOB:
            if (
                self.git_blob_oid is None
                or self.lfs_oid is not None
                or self.lfs_declared_size is not None
            ):
                raise ValueError(
                    "ordinary Git deliverable has inconsistent byte identity"
                )
            _require_oid("git_blob_oid", self.git_blob_oid)
        else:
            if self.git_blob_oid is not None or self.lfs_oid is None:
                raise ValueError(
                    "Git LFS deliverable has inconsistent pointer identity"
                )
            _require_digest("lfs_oid", self.lfs_oid)
            if (
                not isinstance(self.lfs_declared_size, int)
                or isinstance(self.lfs_declared_size, bool)
                or self.lfs_declared_size < 0
                or self.lfs_declared_size != self.actual_size
            ):
                raise ValueError("Git LFS declared and actual sizes must match")
        if self.supersedes_ref_id is not None:
            _require_identifier("supersedes_ref_id", self.supersedes_ref_id)
            if self.supersedes_ref_id == self.ref_id:
                raise ValueError("scientific deliverable cannot supersede itself")
        _require_timestamp("created_at", self.created_at)
        if self.ref_digest != canonical_scientific_deliverable_digest(self.payload):
            raise ValueError("scientific deliverable ref digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "ref_digest"
        }

    def to_dict(self) -> dict[str, object]:
        return _record(self, self.schema_version)

    @classmethod
    def create(cls, **values: Any) -> "ScientificDeliverableRef":
        payload = {"schema_version": "scientific_deliverable_ref@1", **values}
        payload["storage"] = values["storage"].value
        return cls(
            **values,
            ref_digest=canonical_scientific_deliverable_digest(payload),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScientificDeliverableRef":
        expected = {item.name for item in fields(cls)}
        if set(value) != expected:
            raise ValueError("scientific deliverable ref has unknown or missing fields")
        normalized = dict(value)
        normalized["storage"] = ScientificFileStorage(value["storage"])
        return cls(**normalized)


@dataclass(frozen=True, slots=True)
class ScientificDeliverableBundle:
    bundle_id: str
    project_id: str
    session_id: str
    attempt_id: str
    selection_id: str
    publication_id: str
    publication_digest: str
    contract_id: str
    contract_digest: str
    ref_ids: tuple[str, ...]
    role_manifest_digest: str
    validation_preimage_digest: str
    created_at: str
    bundle_digest: str
    schema_version: str = "scientific_deliverable_bundle@1"

    def __post_init__(self) -> None:
        for name in (
            "bundle_id",
            "project_id",
            "session_id",
            "attempt_id",
            "selection_id",
            "publication_id",
            "contract_id",
        ):
            _require_identifier(name, getattr(self, name))
        for name in (
            "publication_digest",
            "contract_digest",
            "role_manifest_digest",
            "validation_preimage_digest",
            "bundle_digest",
        ):
            _require_digest(name, getattr(self, name))
        if not self.ref_ids or self.ref_ids != tuple(sorted(set(self.ref_ids))):
            raise ValueError("bundle ref ids must be non-empty, unique, and sorted")
        _require_timestamp("created_at", self.created_at)
        if self.bundle_digest != canonical_scientific_deliverable_digest(self.payload):
            raise ValueError("scientific deliverable bundle digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "bundle_digest"
        }

    def to_dict(self) -> dict[str, object]:
        return _record(self, self.schema_version)

    @classmethod
    def create(cls, **values: Any) -> "ScientificDeliverableBundle":
        normalized = {**values, "ref_ids": tuple(sorted(values["ref_ids"]))}
        payload = {"schema_version": "scientific_deliverable_bundle@1", **normalized}
        payload["ref_ids"] = list(normalized["ref_ids"])
        return cls(
            **normalized,
            bundle_digest=canonical_scientific_deliverable_digest(payload),
        )

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "ScientificDeliverableBundle":
        expected = {item.name for item in fields(cls)}
        if set(value) != expected:
            raise ValueError(
                "scientific deliverable bundle has unknown or missing fields"
            )
        normalized = dict(value)
        raw_ref_ids = value["ref_ids"]
        if not isinstance(raw_ref_ids, list):
            raise ValueError("scientific deliverable bundle ref_ids must be an array")
        normalized["ref_ids"] = tuple(raw_ref_ids)
        return cls(**normalized)


@dataclass(frozen=True, slots=True)
class ScientificDeliverableValidationReceipt:
    receipt_id: str
    bundle_id: str
    bundle_digest: str
    publication_id: str
    publication_digest: str
    attempt_id: str
    attempt_state_version: int
    selection_id: str
    selection_revision: int
    actor_ref: str
    execution_fencing_token: int
    validation_preimage_digest: str
    verified_ref_digests: tuple[str, ...]
    created_at: str
    receipt_digest: str
    schema_version: str = "scientific_deliverable_validation_receipt@1"

    def __post_init__(self) -> None:
        for name in (
            "receipt_id",
            "bundle_id",
            "publication_id",
            "attempt_id",
            "selection_id",
            "actor_ref",
        ):
            _require_identifier(name, getattr(self, name))
        for name in (
            "bundle_digest",
            "publication_digest",
            "validation_preimage_digest",
            "receipt_digest",
        ):
            _require_digest(name, getattr(self, name))
        for name in ("attempt_state_version", "selection_revision"):
            value = getattr(self, name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{name} must be positive")
        if (
            not isinstance(self.execution_fencing_token, int)
            or isinstance(self.execution_fencing_token, bool)
            or self.execution_fencing_token < 1
        ):
            raise ValueError("execution_fencing_token must be positive")
        if self.verified_ref_digests != tuple(sorted(set(self.verified_ref_digests))):
            raise ValueError("verified ref digests must be unique and sorted")
        for digest in self.verified_ref_digests:
            _require_digest("verified_ref_digest", digest)
        _require_timestamp("created_at", self.created_at)
        if self.receipt_digest != canonical_scientific_deliverable_digest(self.payload):
            raise ValueError("scientific validation receipt digest mismatch")

    @property
    def payload(self) -> dict[str, object]:
        return {
            key: value
            for key, value in _record(self, self.schema_version).items()
            if key != "receipt_digest"
        }

    def to_dict(self) -> dict[str, object]:
        return _record(self, self.schema_version)

    @classmethod
    def create(cls, **values: Any) -> "ScientificDeliverableValidationReceipt":
        normalized = {
            **values,
            "verified_ref_digests": tuple(sorted(values["verified_ref_digests"])),
        }
        payload = {
            "schema_version": "scientific_deliverable_validation_receipt@1",
            **normalized,
        }
        payload["verified_ref_digests"] = list(normalized["verified_ref_digests"])
        return cls(
            **normalized,
            receipt_digest=canonical_scientific_deliverable_digest(payload),
        )

    @classmethod
    def from_dict(
        cls,
        value: dict[str, Any],
    ) -> "ScientificDeliverableValidationReceipt":
        expected = {item.name for item in fields(cls)}
        if set(value) != expected:
            raise ValueError(
                "scientific validation receipt has unknown or missing fields"
            )
        normalized = dict(value)
        raw_digests = value["verified_ref_digests"]
        if not isinstance(raw_digests, list):
            raise ValueError("verified_ref_digests must be an array")
        normalized["verified_ref_digests"] = tuple(raw_digests)
        return cls(**normalized)


__all__ = [
    "SCIENTIFIC_DELIVERABLE_REF_SCHEMA_VERSION",
    "ScientificDeliverableBundle",
    "ScientificDeliverableRef",
    "ScientificDeliverableValidationReceipt",
    "ScientificFileStorage",
    "ScientificFileEffectAdoption",
    "canonical_scientific_deliverable_digest",
    "normalize_scientific_path",
]
