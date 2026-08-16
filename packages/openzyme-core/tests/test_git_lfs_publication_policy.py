from __future__ import annotations

from dataclasses import dataclass
import hashlib
from typing import Any
from typing import cast

import pytest

from openzyme_core import GitLfsClosureError
from openzyme_core import GitLfsOversizedBlobError
from openzyme_core import GitLfsPointerError
from openzyme_core import GitLfsPublicationManifestPolicyValidator
from openzyme_domain import GitLfsBindingPolicy
from openzyme_domain import GitLfsClosureManifest
from openzyme_domain import GitLfsClosureVerification
from openzyme_domain import GitLfsObjectReadReceipt
from openzyme_domain import GitLfsPathRepresentation
from openzyme_domain import GitLfsPathRule
from openzyme_domain import GitLfsPointer
from openzyme_domain import GitLfsRetentionClass
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import WorkspacePublicationManifest


def _policy() -> GitLfsBindingPolicy:
    return GitLfsBindingPolicy.create(
        binding_id="binding_c5_policy",
        binding_version=1,
        repository_id="repository_c5_policy",
        lfs_service_id="lfs_c5_policy",
        lfs_endpoint=(
            "https://git.internal/repositories/repository_c5_policy.git/info/lfs"
        ),
        object_format="sha256",
        path_rules=(
            GitLfsPathRule(
                rule_id="model_files",
                pattern="models/**",
                representation=GitLfsPathRepresentation.LFS_REQUIRED,
            ),
        ),
        ordinary_blob_threshold_bytes=128,
        max_object_bytes=1024,
        max_workspace_bytes=4096,
        max_repository_bytes=8192,
        published_retention_class=GitLfsRetentionClass.PUBLISHED,
        private_retention_class=GitLfsRetentionClass.PRIVATE,
        private_retention_seconds=3600,
        policy_version="repository-policy-c5",
        created_at="2026-08-16T00:00:00+00:00",
        created_by="operator:c5",
    )


def _binding(policy: GitLfsBindingPolicy) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id=policy.binding_id,
        project_id="project_c5",
        binding_version=policy.binding_version,
        repository_id=policy.repository_id,
        internal_git_service_id="git_c5_policy",
        internal_git_endpoint=(
            "https://git.internal/repositories/repository_c5_policy.git"
        ),
        lfs_service_id=policy.lfs_service_id,
        lfs_endpoint=policy.lfs_endpoint,
        upstream_identity="upstream_c5",
        upstream_url="ssh://git.internal/project_c5.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/dev",
        default_base_commit="1" * 40,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version=policy.policy_version,
        repository_policy_digest=policy.policy_digest,
        created_at="2026-08-16T00:00:00+00:00",
        created_by="operator:c5",
    )


@dataclass(slots=True)
class _GitReader:
    blobs: dict[str, bytes]

    def read_blob(
        self,
        binding: ProjectRepositoryBinding,
        *,
        object_id: str,
        max_bytes: int,
    ) -> bytes:
        del binding
        value = self.blobs[object_id]
        if len(value) > max_bytes:
            raise ValueError("test blob exceeds requested bound")
        return value


@dataclass(slots=True)
class _ObjectStore:
    values: dict[str, bytes]

    def verify(self, repository_id: str, oid: str, *, size: int) -> object:
        del repository_id
        value = self.values.get(oid)
        if value is None:
            raise FileNotFoundError(oid)
        if len(value) != size or hashlib.sha256(value).hexdigest() != oid:
            raise ValueError("test object mismatch")
        return object()


@dataclass(slots=True)
class _LfsRepository:
    policy: GitLfsBindingPolicy
    object_sizes: dict[str, int]
    receipts: list[GitLfsObjectReadReceipt]
    closure: GitLfsClosureManifest | None = None
    verifications: list[GitLfsClosureVerification] | None = None

    def __post_init__(self) -> None:
        if self.verifications is None:
            self.verifications = []

    def get_policy(self, *, binding_id: str, binding_version: int):
        if (
            binding_id == self.policy.binding_id
            and binding_version == self.policy.binding_version
        ):
            return self.policy
        return None

    def has_object_metadata(
        self,
        *,
        policy: GitLfsBindingPolicy,
        oid: str,
        size_bytes: int | None = None,
    ) -> bool:
        assert policy == self.policy
        observed = self.object_sizes.get(oid)
        return observed is not None and (
            size_bytes is None or observed == size_bytes
        )

    def add_object_read_receipt(
        self,
        receipt: GitLfsObjectReadReceipt,
    ) -> GitLfsObjectReadReceipt:
        self.receipts.append(receipt)
        return receipt

    def get_cached_closure(self, **identity: object) -> GitLfsClosureManifest | None:
        del identity
        return self.closure

    def add_closure_manifest(
        self,
        manifest: GitLfsClosureManifest,
    ) -> GitLfsClosureManifest:
        self.closure = manifest
        return manifest

    def add_closure_verification(
        self,
        verification: GitLfsClosureVerification,
        *,
        observed_closure: GitLfsClosureManifest,
    ) -> GitLfsClosureVerification:
        assert verification.manifest_digest == observed_closure.manifest_digest
        assert self.verifications is not None
        self.verifications.append(verification)
        return verification


def _validator_fixture():
    policy = _policy()
    binding = _binding(policy)
    content = b"model bytes"
    oid = hashlib.sha256(content).hexdigest()
    pointer = GitLfsPointer(oid=oid, size=len(content)).to_bytes()
    attributes_oid = "2" * 40
    pointer_oid = "3" * 40
    reader = _GitReader(
        {
            attributes_oid: b"models/** filter=lfs diff=lfs merge=lfs -text\n",
            pointer_oid: pointer,
        }
    )
    repository = _LfsRepository(policy, {oid: len(content)}, [])
    store = _ObjectStore({oid: content})
    manifest = WorkspacePublicationManifest.create(
        (
            PublicationManifestEntry(
                path=".gitattributes",
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id=attributes_oid,
                size_bytes=len(reader.blobs[attributes_oid]),
            ),
            PublicationManifestEntry(
                path="models/model.bin",
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id=pointer_oid,
                size_bytes=len(pointer),
            ),
        )
    )
    validator = GitLfsPublicationManifestPolicyValidator(
        repositories=cast(Any, repository),
        git_reader=reader,
        object_store=cast(Any, store),
    )
    return validator, repository, store, binding, manifest, oid


def test_publication_validator_freezes_stable_closure_and_fresh_read_proof() -> None:
    validator, repository, _, binding, manifest, oid = _validator_fixture()

    first = validator.validate(
        binding=binding,
        commit="4" * 40,
        tree="5" * 40,
        manifest=manifest,
        authorization_scope_digest=f"sha256:{'6' * 64}",
    )
    second = validator.validate(
        binding=binding,
        commit="4" * 40,
        tree="5" * 40,
        manifest=manifest,
        authorization_scope_digest=f"sha256:{'6' * 64}",
    )

    assert first.lfs_closure is not None
    assert second.lfs_closure is not None
    assert first.lfs_verification is not None
    assert second.lfs_verification is not None
    assert first.lfs_closure.manifest_digest == second.lfs_closure.manifest_digest
    assert first.manifest.entries[1].lfs_oid == f"sha256:{oid}"
    assert len(repository.receipts) == 2
    assert len(repository.verifications or []) == 2


def test_publication_validator_rejects_missing_and_malformed_lfs_objects() -> None:
    validator, _, store, binding, manifest, oid = _validator_fixture()
    del store.values[oid]

    with pytest.raises(GitLfsClosureError, match="unreadable or corrupt"):
        validator.validate(
            binding=binding,
            commit="4" * 40,
            tree="5" * 40,
            manifest=manifest,
            authorization_scope_digest=f"sha256:{'6' * 64}",
        )

    validator, _, _, binding, manifest, _ = _validator_fixture()
    cast(_GitReader, validator.git_reader).blobs["3" * 40] = b"not a pointer\n"
    with pytest.raises(GitLfsPointerError, match="invalid Git LFS pointer"):
        validator.validate(
            binding=binding,
            commit="4" * 40,
            tree="5" * 40,
            manifest=manifest,
            authorization_scope_digest=f"sha256:{'6' * 64}",
        )


def test_publication_validator_reports_every_oversized_ordinary_blob() -> None:
    policy = _policy()
    binding = _binding(policy)
    manifest = WorkspacePublicationManifest.create(
        tuple(
            PublicationManifestEntry(
                path=path,
                mode="100644",
                object_kind=PublicationManifestObjectKind.BLOB,
                object_id=str(index) * 40,
                size_bytes=129 + index,
            )
            for index, path in ((7, "data/a.txt"), (8, "data/b.txt"))
        )
    )
    repository = _LfsRepository(policy, {}, [])
    validator = GitLfsPublicationManifestPolicyValidator(
        repositories=cast(Any, repository),
        git_reader=_GitReader({}),
        object_store=cast(Any, _ObjectStore({})),
    )

    with pytest.raises(GitLfsOversizedBlobError) as captured:
        validator.validate(
            binding=binding,
            commit="4" * 40,
            tree="5" * 40,
            manifest=manifest,
            authorization_scope_digest=f"sha256:{'6' * 64}",
        )

    assert [item["path"] for item in captured.value.violations] == [
        "data/a.txt",
        "data/b.txt",
    ]
    assert all(item["threshold"] == 128 for item in captured.value.violations)
