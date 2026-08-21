from __future__ import annotations

from dataclasses import dataclass
import hashlib
import re
from typing import Protocol

from .identity import canonical_sha256_digest
from .identity import require_digest
from .identity import require_identifier
from .repository_bindings import ProjectRepositoryBinding
from .revision_paths import RevisionPathRef
from .workspace_checkpoints import RemotePrivateRefObservation
from .workspace_checkpoints import WorkspaceCheckpointProofInput
from .workspace_publications import PublishedRevision
from .workspace_publications import WorkspacePublicationIntent
from .workspace_publications import WorkspacePublicationManifest
from .workspace_publications import WorkspacePublicationRemoteReceipt
from .workspace_runtime import require_workspace_relative_path


REVISION_COMMIT_OBSERVATION_SCHEMA_VERSION = "revision_commit_observation@1"
REVISION_MANIFEST_OBSERVATION_SCHEMA_VERSION = "revision_manifest_observation@1"
PUBLICATION_NAMESPACE_OBSERVATION_SCHEMA_VERSION = (
    "publication_namespace_observation@1"
)
REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION = (
    "revision_path_verification_receipt@1"
)
REVISION_PATH_READ_REQUEST_SCHEMA_VERSION = "revision_path_read_request@1"
REVISION_PATH_READ_RECEIPT_SCHEMA_VERSION = "revision_path_read_receipt@1"
WORKSPACE_PUBLICATION_DISPATCH_IDENTITY_SCHEMA_VERSION = (
    "workspace_publication_dispatch_identity@1"
)


def _require_positive(value: int, *, field_name: str) -> None:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")


def _require_object_id(value: str, *, field_name: str) -> None:
    if re.fullmatch(r"(?:[0-9a-f]{40}|[0-9a-f]{64})", value) is None:
        raise ValueError(f"{field_name} must be a lowercase Git object id")


@dataclass(frozen=True, slots=True)
class WorkspacePublicationDispatchIdentity:
    """ControlledOperation identity supplied to one create-only Git dispatch."""

    receipt_id: str
    execution_id: str
    dispatch_generation: int
    fencing_token: int
    schema_version: str = WORKSPACE_PUBLICATION_DISPATCH_IDENTITY_SCHEMA_VERSION

    def __post_init__(self) -> None:
        if self.schema_version != WORKSPACE_PUBLICATION_DISPATCH_IDENTITY_SCHEMA_VERSION:
            raise ValueError("unsupported workspace publication dispatch identity schema")
        require_identifier(self.receipt_id, field_name="receipt_id")
        require_identifier(self.execution_id, field_name="execution_id")
        _require_positive(self.dispatch_generation, field_name="dispatch_generation")
        _require_positive(self.fencing_token, field_name="fencing_token")


@dataclass(frozen=True, slots=True)
class RevisionCommitObservation:
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    commit: str
    tree: str
    parent_commits: tuple[str, ...]
    observed_at: str
    observation_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "repository_binding_id",
            "repository_id",
            "observed_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _require_positive(
            self.repository_binding_version,
            field_name="repository_binding_version",
        )
        _require_object_id(self.commit, field_name="commit")
        _require_object_id(self.tree, field_name="tree")
        if len(set(self.parent_commits)) != len(self.parent_commits):
            raise ValueError("parent_commits must be unique and ordered")
        for parent in self.parent_commits:
            _require_object_id(parent, field_name="parent_commit")
        require_digest(self.observation_digest, field_name="observation_digest")
        if self.observation_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("revision commit observation digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": REVISION_COMMIT_OBSERVATION_SCHEMA_VERSION,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "commit": self.commit,
            "tree": self.tree,
            "parent_commits": list(self.parent_commits),
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: object) -> RevisionCommitObservation:
        payload = {
            "schema_version": REVISION_COMMIT_OBSERVATION_SCHEMA_VERSION,
            **values,
            "parent_commits": list(values["parent_commits"]),
        }
        return cls(
            **values,  # type: ignore[arg-type]
            observation_digest=canonical_sha256_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class RevisionManifestObservation:
    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    commit: str
    tree: str
    manifest: WorkspacePublicationManifest
    observed_at: str
    observation_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "repository_binding_id",
            "repository_id",
            "observed_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _require_positive(
            self.repository_binding_version,
            field_name="repository_binding_version",
        )
        _require_object_id(self.commit, field_name="commit")
        _require_object_id(self.tree, field_name="tree")
        require_digest(self.observation_digest, field_name="observation_digest")
        if self.observation_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("revision manifest observation digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": REVISION_MANIFEST_OBSERVATION_SCHEMA_VERSION,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "commit": self.commit,
            "tree": self.tree,
            "manifest_digest": self.manifest.manifest_digest,
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: object) -> RevisionManifestObservation:
        manifest = values["manifest"]
        if not isinstance(manifest, WorkspacePublicationManifest):
            raise TypeError("manifest must be a WorkspacePublicationManifest")
        payload = {
            "schema_version": REVISION_MANIFEST_OBSERVATION_SCHEMA_VERSION,
            **values,
            "manifest_digest": manifest.manifest_digest,
        }
        payload.pop("manifest")
        return cls(
            **values,  # type: ignore[arg-type]
            observation_digest=canonical_sha256_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class PublicationNamespaceObservation:
    """Exact Adapter observation of the configured publication ref namespace."""

    repository_binding_id: str
    repository_binding_version: int
    repository_id: str
    publication_ref_prefix: str
    refs: tuple[tuple[str, str], ...]
    observed_at: str
    observation_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "repository_binding_id",
            "repository_id",
            "observed_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _require_positive(
            self.repository_binding_version,
            field_name="repository_binding_version",
        )
        if not self.publication_ref_prefix.startswith("refs/"):
            raise ValueError("publication_ref_prefix must be an exact Git ref prefix")
        if self.refs != tuple(sorted(self.refs)):
            raise ValueError("publication namespace refs must be sorted")
        if len({ref_name for ref_name, _ in self.refs}) != len(self.refs):
            raise ValueError("publication namespace refs must be unique")
        for ref_name, commit in self.refs:
            if not ref_name.startswith(f"{self.publication_ref_prefix}/"):
                raise ValueError("publication ref is outside the observed namespace")
            _require_object_id(commit, field_name="publication_commit")
        require_digest(self.observation_digest, field_name="observation_digest")
        if self.observation_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("publication namespace observation digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": PUBLICATION_NAMESPACE_OBSERVATION_SCHEMA_VERSION,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "repository_id": self.repository_id,
            "publication_ref_prefix": self.publication_ref_prefix,
            "refs": [list(item) for item in self.refs],
            "observed_at": self.observed_at,
        }

    @classmethod
    def create(cls, **values: object) -> PublicationNamespaceObservation:
        payload = {
            "schema_version": PUBLICATION_NAMESPACE_OBSERVATION_SCHEMA_VERSION,
            **values,
            "refs": [list(item) for item in values["refs"]],
        }
        return cls(
            **values,  # type: ignore[arg-type]
            observation_digest=canonical_sha256_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class RevisionPathVerificationReceipt:
    ref_id: str
    publication_id: str
    repository_binding_id: str
    repository_binding_version: int
    commit: str
    tree: str
    path: str
    object_id: str
    actual_size_bytes: int | None
    actual_content_digest: str | None
    lfs_oid: str | None
    lfs_size_bytes: int | None
    verified_at: str
    verification_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "ref_id",
            "publication_id",
            "repository_binding_id",
            "verified_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _require_positive(
            self.repository_binding_version,
            field_name="repository_binding_version",
        )
        _require_object_id(self.commit, field_name="commit")
        _require_object_id(self.tree, field_name="tree")
        require_workspace_relative_path(self.path, field_name="path")
        _require_object_id(self.object_id, field_name="object_id")
        if self.actual_size_bytes is not None and self.actual_size_bytes < 0:
            raise ValueError("actual_size_bytes must be non-negative")
        if self.actual_content_digest is not None:
            require_digest(
                self.actual_content_digest,
                field_name="actual_content_digest",
            )
        if (self.lfs_oid is None) != (self.lfs_size_bytes is None):
            raise ValueError("LFS identity must be complete")
        if self.lfs_oid is not None:
            require_digest(self.lfs_oid, field_name="lfs_oid")
            assert self.lfs_size_bytes is not None
            if self.lfs_size_bytes < 0:
                raise ValueError("lfs_size_bytes must be non-negative")
        require_digest(self.verification_digest, field_name="verification_digest")
        if self.verification_digest != canonical_sha256_digest(self.identity_payload):
            raise ValueError("revision path verification digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION,
            "ref_id": self.ref_id,
            "publication_id": self.publication_id,
            "repository_binding_id": self.repository_binding_id,
            "repository_binding_version": self.repository_binding_version,
            "commit": self.commit,
            "tree": self.tree,
            "path": self.path,
            "object_id": self.object_id,
            "actual_size_bytes": self.actual_size_bytes,
            "actual_content_digest": self.actual_content_digest,
            "lfs_oid": self.lfs_oid,
            "lfs_size_bytes": self.lfs_size_bytes,
            "verified_at": self.verified_at,
        }

    @classmethod
    def create(cls, **values: object) -> RevisionPathVerificationReceipt:
        payload = {
            "schema_version": REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION,
            **values,
        }
        return cls(
            **values,  # type: ignore[arg-type]
            verification_digest=canonical_sha256_digest(payload),
        )


@dataclass(frozen=True, slots=True)
class RevisionPathReadRequest:
    ref: RevisionPathRef
    max_bytes: int

    def __post_init__(self) -> None:
        if not 1 <= self.max_bytes <= 1_048_576:
            raise ValueError("max_bytes must be between 1 and 1048576")


@dataclass(frozen=True, slots=True)
class RevisionPathReadReceipt:
    ref_id: str
    publication_id: str
    returned_bytes: bytes
    returned_bytes_digest: str
    actual_size_bytes: int
    actual_content_digest: str
    truncated: bool
    verified_at: str

    def __post_init__(self) -> None:
        for field_name in ("ref_id", "publication_id", "verified_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.actual_size_bytes < 0:
            raise ValueError("actual_size_bytes must be non-negative")
        require_digest(
            self.returned_bytes_digest,
            field_name="returned_bytes_digest",
        )
        require_digest(
            self.actual_content_digest,
            field_name="actual_content_digest",
        )
        observed = "sha256:" + hashlib.sha256(self.returned_bytes).hexdigest()
        if self.returned_bytes_digest != observed:
            raise ValueError("returned byte digest mismatch")
        if self.truncated:
            if len(self.returned_bytes) >= self.actual_size_bytes:
                raise ValueError("truncated read must omit at least one byte")
        elif (
            len(self.returned_bytes) != self.actual_size_bytes
            or self.returned_bytes_digest != self.actual_content_digest
        ):
            raise ValueError("complete read must match actual size and digest")


class WorkspaceRevisionBackendPort(Protocol):
    """Git-shaped semantic Port; implementations own all Git/LFS I/O."""

    def observe_private_ref(
        self,
        binding: ProjectRepositoryBinding,
        proof: WorkspaceCheckpointProofInput,
    ) -> RemotePrivateRefObservation: ...

    def observe_commit(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> RevisionCommitObservation: ...

    def observe_manifest(
        self,
        binding: ProjectRepositoryBinding,
        *,
        commit: str,
    ) -> RevisionManifestObservation: ...

    def dispatch_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
    ) -> WorkspacePublicationRemoteReceipt: ...

    def observe_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        receipt: WorkspacePublicationRemoteReceipt,
    ) -> WorkspacePublicationRemoteReceipt: ...

    def reconcile_publication(
        self,
        binding: ProjectRepositoryBinding,
        intent: WorkspacePublicationIntent,
        dispatch: WorkspacePublicationDispatchIdentity,
    ) -> WorkspacePublicationRemoteReceipt | None: ...

    def observe_publication_namespace(
        self,
        binding: ProjectRepositoryBinding,
    ) -> PublicationNamespaceObservation: ...

    def verify_revision_path(
        self,
        binding: ProjectRepositoryBinding,
        revision: PublishedRevision,
        ref: RevisionPathRef,
    ) -> RevisionPathVerificationReceipt: ...

    def read_revision_path(
        self,
        binding: ProjectRepositoryBinding,
        request: RevisionPathReadRequest,
    ) -> RevisionPathReadReceipt: ...


__all__ = [
    "PUBLICATION_NAMESPACE_OBSERVATION_SCHEMA_VERSION",
    "REVISION_COMMIT_OBSERVATION_SCHEMA_VERSION",
    "REVISION_MANIFEST_OBSERVATION_SCHEMA_VERSION",
    "REVISION_PATH_READ_RECEIPT_SCHEMA_VERSION",
    "REVISION_PATH_READ_REQUEST_SCHEMA_VERSION",
    "REVISION_PATH_VERIFICATION_RECEIPT_SCHEMA_VERSION",
    "WORKSPACE_PUBLICATION_DISPATCH_IDENTITY_SCHEMA_VERSION",
    "PublicationNamespaceObservation",
    "RevisionCommitObservation",
    "RevisionManifestObservation",
    "RevisionPathReadReceipt",
    "RevisionPathReadRequest",
    "RevisionPathVerificationReceipt",
    "WorkspaceRevisionBackendPort",
    "WorkspacePublicationDispatchIdentity",
]
