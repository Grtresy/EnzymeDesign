from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import hashlib
import json
import re
from typing import Any


WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION = "workspace_publication_intent@1"
WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION = "workspace_publication_manifest@1"
WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION = (
    "workspace_publication_remote_receipt@1"
)
PUBLISHED_REVISION_SCHEMA_VERSION = "published_revision@1"
PUBLICATION_FETCH_IDENTITY_SCHEMA_VERSION = "publication_fetch_identity@1"


class WorkspacePublicationIntentState(StrEnum):
    FROZEN = "frozen"


class WorkspacePublicationResult(StrEnum):
    CONFIRMED = "confirmed"
    INTEGRITY_CONFLICT = "integrity_conflict"
    DISPATCH_IN_DOUBT = "dispatch_in_doubt"
    NO_EFFECT = "no_effect"


class PublicationManifestObjectKind(StrEnum):
    BLOB = "blob"
    COMMIT = "commit"


def canonical_publication_digest(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _require_identifier(value: str, field_name: str) -> None:
    if (
        not isinstance(value, str)
        or not value
        or value != value.strip()
        or any(character.isspace() for character in value)
    ):
        raise ValueError(f"{field_name} must be an exact non-empty identifier")


def _require_positive(value: int, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_object_id(value: str, field_name: str) -> None:
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
        raise ValueError(f"{field_name} must be a lowercase Git object id")


def _require_digest(value: str, field_name: str) -> None:
    if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
        raise ValueError(f"{field_name} must be a lowercase sha256 digest")


def _require_repository_path(path: str) -> None:
    if (
        not path
        or path.startswith("/")
        or path.endswith("/")
        or "\\" in path
        or "\x00" in path
        or any(part in {"", ".", "..", ".git"} for part in path.split("/"))
    ):
        raise ValueError("manifest path must be a canonical repository-relative path")


def _require_publication_ref(value: str, publication_id: str) -> None:
    if (
        not value.startswith("refs/")
        or not value.endswith(f"/{publication_id}")
        or ".." in value
        or "//" in value
        or re.search(r"[\x00-\x20~^:?*\\]", value) is not None
    ):
        raise ValueError("publication_ref must be the exact immutable publication ref")


@dataclass(frozen=True, slots=True)
class PublicationManifestEntry:
    path: str
    mode: str
    object_kind: PublicationManifestObjectKind
    object_id: str
    size_bytes: int | None = None
    lfs_oid: str | None = None
    lfs_size_bytes: int | None = None

    def __post_init__(self) -> None:
        _require_repository_path(self.path)
        if self.mode not in {"100644", "100755", "120000", "160000"}:
            raise ValueError("manifest mode is not a supported Git tree mode")
        if not isinstance(self.object_kind, PublicationManifestObjectKind):
            raise TypeError("object_kind must be a PublicationManifestObjectKind")
        if self.mode == "160000" and self.object_kind is not PublicationManifestObjectKind.COMMIT:
            raise ValueError("gitlink entries must name a commit object")
        if self.mode != "160000" and self.object_kind is not PublicationManifestObjectKind.BLOB:
            raise ValueError("non-gitlink entries must name a blob object")
        _require_object_id(self.object_id, "object_id")
        if self.size_bytes is not None and self.size_bytes < 0:
            raise ValueError("size_bytes must be non-negative")
        if (self.lfs_oid is None) != (self.lfs_size_bytes is None):
            raise ValueError("LFS oid and size must be present together")
        if self.lfs_oid is not None:
            _require_digest(self.lfs_oid, "lfs_oid")
            assert self.lfs_size_bytes is not None
            if self.lfs_size_bytes < 0:
                raise ValueError("lfs_size_bytes must be non-negative")

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "mode": self.mode,
            "object_kind": self.object_kind.value,
            "object_id": self.object_id,
            "size_bytes": self.size_bytes,
            "lfs_oid": self.lfs_oid,
            "lfs_size_bytes": self.lfs_size_bytes,
        }


@dataclass(frozen=True, slots=True)
class WorkspacePublicationManifest:
    entries: tuple[PublicationManifestEntry, ...]
    manifest_digest: str
    schema_version: str = WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION:
            raise ValueError("unsupported workspace publication manifest schema")
        if not self.entries:
            raise ValueError("publication manifest must contain the whole non-empty tree")
        paths = tuple(entry.path for entry in self.entries)
        if paths != tuple(sorted(set(paths))):
            raise ValueError("publication manifest paths must be unique and sorted")
        _require_digest(self.manifest_digest, "manifest_digest")
        if self.manifest_digest != canonical_publication_digest(self.payload):
            raise ValueError("manifest_digest does not match canonical whole tree")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "entries": [entry.to_dict() for entry in self.entries],
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "manifest_digest": self.manifest_digest}

    @classmethod
    def create(
        cls,
        entries: tuple[PublicationManifestEntry, ...],
    ) -> WorkspacePublicationManifest:
        ordered = tuple(sorted(entries, key=lambda entry: entry.path))
        payload = {
            "schema_version": WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in ordered],
        }
        return cls(
            entries=ordered,
            manifest_digest=canonical_publication_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class WorkspacePublicationIntent:
    intent_id: str
    publication_id: str
    idempotency_key: str
    project_id: str
    session_id: str
    agent_member_id: str
    agent_id: str
    workspace_id: str
    workspace_generation: int
    capability_lease_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    expected_head_commit: str
    expected_tree: str
    git_parent_commits: tuple[str, ...]
    declared_base_commit: str
    parent_publication_id: str | None
    supersedes_publication_id: str | None
    publication_ref: str
    manifest: WorkspacePublicationManifest
    repository_policy_version: str
    repository_policy_digest: str
    checkpoint_id: str
    state: WorkspacePublicationIntentState
    created_at: str
    canonical_digest: str
    schema_version: str = WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION:
            raise ValueError("unsupported workspace publication intent schema")
        for field_name in (
            "intent_id",
            "publication_id",
            "idempotency_key",
            "project_id",
            "session_id",
            "agent_member_id",
            "agent_id",
            "workspace_id",
            "capability_lease_id",
            "repository_binding_id",
            "repository_id",
            "repository_policy_version",
            "checkpoint_id",
            "created_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(self.workspace_generation, "workspace_generation")
        _require_positive(
            self.repository_binding_version,
            "repository_binding_version",
        )
        for value, field_name in (
            (self.expected_head_commit, "expected_head_commit"),
            (self.expected_tree, "expected_tree"),
            (self.declared_base_commit, "declared_base_commit"),
        ):
            _require_object_id(value, field_name)
        for parent in self.git_parent_commits:
            _require_object_id(parent, "git_parent_commit")
        if len(set(self.git_parent_commits)) != len(self.git_parent_commits):
            raise ValueError("git_parent_commits must not contain duplicates")
        if self.parent_publication_id is not None:
            _require_identifier(self.parent_publication_id, "parent_publication_id")
        if self.supersedes_publication_id is not None:
            _require_identifier(
                self.supersedes_publication_id,
                "supersedes_publication_id",
            )
        _require_publication_ref(self.publication_ref, self.publication_id)
        _require_digest(self.repository_policy_digest, "repository_policy_digest")
        if self.state is not WorkspacePublicationIntentState.FROZEN:
            raise ValueError("publication intent must be frozen at creation")
        _require_digest(self.canonical_digest, "canonical_digest")
        if self.canonical_digest != canonical_publication_digest(self.payload):
            raise ValueError("publication intent canonical digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "intent_id": self.intent_id,
            "publication_id": self.publication_id,
            "idempotency_key": self.idempotency_key,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "agent_id": self.agent_id,
            "workspace_id": self.workspace_id,
            "workspace_generation": self.workspace_generation,
            "capability_lease_id": self.capability_lease_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "expected_head_commit": self.expected_head_commit,
            "expected_tree": self.expected_tree,
            "git_parent_commits": list(self.git_parent_commits),
            "declared_base_commit": self.declared_base_commit,
            "parent_publication_id": self.parent_publication_id,
            "supersedes_publication_id": self.supersedes_publication_id,
            "publication_ref": self.publication_ref,
            "manifest": self.manifest.to_dict(),
            "repository_policy_version": self.repository_policy_version,
            "repository_policy_digest": self.repository_policy_digest,
            "checkpoint_id": self.checkpoint_id,
            "state": self.state.value,
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "canonical_digest": self.canonical_digest}

    @classmethod
    def create(cls, **values: Any) -> WorkspacePublicationIntent:
        payload = {
            "schema_version": WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION,
            **values,
            "git_parent_commits": list(values["git_parent_commits"]),
            "manifest": values["manifest"].to_dict(),
            "state": values["state"].value,
        }
        return cls(
            **values,
            canonical_digest=canonical_publication_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class WorkspacePublicationRemoteReceipt:
    receipt_id: str
    intent_id: str
    publication_id: str
    execution_id: str
    execution_dispatch_generation: int
    execution_fencing_token: int
    internal_git_service_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    publication_ref: str
    expected_previous_commit: None
    new_commit: str
    new_tree: str
    server_observed_commit: str
    observed_at: str
    receipt_digest: str
    schema_version: str = WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION:
            raise ValueError("unsupported publication remote receipt schema")
        for field_name in (
            "receipt_id",
            "intent_id",
            "publication_id",
            "execution_id",
            "internal_git_service_id",
            "repository_binding_id",
            "repository_id",
            "observed_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(
            self.execution_dispatch_generation,
            "execution_dispatch_generation",
        )
        _require_positive(self.execution_fencing_token, "execution_fencing_token")
        _require_positive(
            self.repository_binding_version,
            "repository_binding_version",
        )
        _require_publication_ref(self.publication_ref, self.publication_id)
        if self.expected_previous_commit is not None:
            raise ValueError("publication ref receipt must prove expected absence")
        for value, field_name in (
            (self.new_commit, "new_commit"),
            (self.new_tree, "new_tree"),
            (self.server_observed_commit, "server_observed_commit"),
        ):
            _require_object_id(value, field_name)
        if self.server_observed_commit != self.new_commit:
            raise ValueError("remote receipt does not confirm the intended commit")
        _require_digest(self.receipt_digest, "receipt_digest")
        if self.receipt_digest != canonical_publication_digest(self.payload):
            raise ValueError("publication remote receipt digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "receipt_id": self.receipt_id,
            "intent_id": self.intent_id,
            "publication_id": self.publication_id,
            "execution_id": self.execution_id,
            "execution_dispatch_generation": self.execution_dispatch_generation,
            "execution_fencing_token": self.execution_fencing_token,
            "internal_git_service_id": self.internal_git_service_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "publication_ref": self.publication_ref,
            "expected_previous_commit": self.expected_previous_commit,
            "new_commit": self.new_commit,
            "new_tree": self.new_tree,
            "server_observed_commit": self.server_observed_commit,
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: Any) -> WorkspacePublicationRemoteReceipt:
        payload = {
            "schema_version": WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION,
            **values,
        }
        return cls(
            **values,
            receipt_digest=canonical_publication_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class PublishedRevision:
    publication_id: str
    intent_id: str
    project_id: str
    session_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    commit: str
    tree: str
    git_parent_commits: tuple[str, ...]
    declared_base_commit: str
    parent_publication_id: str | None
    publisher_agent_member_id: str
    publisher_agent_id: str
    publisher_workspace_id: str
    publisher_workspace_generation: int
    publication_ref: str
    manifest: WorkspacePublicationManifest
    repository_policy_version: str
    repository_policy_digest: str
    controlled_execution_id: str
    remote_receipt_id: str
    supersedes_publication_id: str | None
    created_at: str
    revision_digest: str
    schema_version: str = PUBLISHED_REVISION_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != PUBLISHED_REVISION_SCHEMA_VERSION:
            raise ValueError("unsupported published revision schema")
        for field_name in (
            "publication_id",
            "intent_id",
            "project_id",
            "session_id",
            "repository_binding_id",
            "repository_id",
            "publisher_agent_member_id",
            "publisher_agent_id",
            "publisher_workspace_id",
            "repository_policy_version",
            "controlled_execution_id",
            "remote_receipt_id",
            "created_at",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(
            self.repository_binding_version,
            "repository_binding_version",
        )
        _require_positive(
            self.publisher_workspace_generation,
            "publisher_workspace_generation",
        )
        for value, field_name in (
            (self.commit, "commit"),
            (self.tree, "tree"),
            (self.declared_base_commit, "declared_base_commit"),
        ):
            _require_object_id(value, field_name)
        for parent in self.git_parent_commits:
            _require_object_id(parent, "git_parent_commit")
        if self.parent_publication_id is not None:
            _require_identifier(self.parent_publication_id, "parent_publication_id")
        if self.supersedes_publication_id is not None:
            _require_identifier(
                self.supersedes_publication_id,
                "supersedes_publication_id",
            )
        _require_publication_ref(self.publication_ref, self.publication_id)
        _require_digest(self.repository_policy_digest, "repository_policy_digest")
        _require_digest(self.revision_digest, "revision_digest")
        if self.revision_digest != canonical_publication_digest(self.payload):
            raise ValueError("published revision digest mismatch")

    @property
    def payload(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "publication_id": self.publication_id,
            "intent_id": self.intent_id,
            "project_id": self.project_id,
            "session_id": self.session_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "commit": self.commit,
            "tree": self.tree,
            "git_parent_commits": list(self.git_parent_commits),
            "declared_base_commit": self.declared_base_commit,
            "parent_publication_id": self.parent_publication_id,
            "publisher_agent_member_id": self.publisher_agent_member_id,
            "publisher_agent_id": self.publisher_agent_id,
            "publisher_workspace_id": self.publisher_workspace_id,
            "publisher_workspace_generation": self.publisher_workspace_generation,
            "publication_ref": self.publication_ref,
            "manifest": self.manifest.to_dict(),
            "repository_policy_version": self.repository_policy_version,
            "repository_policy_digest": self.repository_policy_digest,
            "controlled_execution_id": self.controlled_execution_id,
            "remote_receipt_id": self.remote_receipt_id,
            "supersedes_publication_id": self.supersedes_publication_id,
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.payload, "revision_digest": self.revision_digest}

    @classmethod
    def create(cls, **values: Any) -> PublishedRevision:
        payload = {
            "schema_version": PUBLISHED_REVISION_SCHEMA_VERSION,
            **values,
            "git_parent_commits": list(values["git_parent_commits"]),
            "manifest": values["manifest"].to_dict(),
        }
        return cls(
            **values,
            revision_digest=canonical_publication_digest(payload),
        )

    def contains_path(self, path: str) -> bool:
        _require_repository_path(path)
        return any(entry.path == path for entry in self.manifest.entries)


@dataclass(frozen=True, slots=True)
class PublicationFetchIdentity:
    publication_id: str
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    publication_ref: str
    commit: str
    tree: str
    manifest_digest: str
    schema_version: str = PUBLICATION_FETCH_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        for field_name in (
            "publication_id",
            "repository_binding_id",
            "repository_id",
        ):
            _require_identifier(getattr(self, field_name), field_name)
        _require_positive(
            self.repository_binding_version,
            "repository_binding_version",
        )
        _require_publication_ref(self.publication_ref, self.publication_id)
        _require_object_id(self.commit, "commit")
        _require_object_id(self.tree, "tree")
        _require_digest(self.manifest_digest, "manifest_digest")


__all__ = [
    "PUBLISHED_REVISION_SCHEMA_VERSION",
    "PUBLICATION_FETCH_IDENTITY_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_INTENT_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_MANIFEST_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_REMOTE_RECEIPT_SCHEMA_VERSION",
    "PublicationFetchIdentity",
    "PublicationManifestEntry",
    "PublicationManifestObjectKind",
    "PublishedRevision",
    "WorkspacePublicationIntent",
    "WorkspacePublicationIntentState",
    "WorkspacePublicationManifest",
    "WorkspacePublicationRemoteReceipt",
    "WorkspacePublicationResult",
    "canonical_publication_digest",
]
