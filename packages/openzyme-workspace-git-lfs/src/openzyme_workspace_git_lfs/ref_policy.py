"""Git ref namespace and ACL mechanisms owned by the Git/LFS Adapter.

The Kernel owns publication and handoff authority.  This module only translates
an already-authorized repository operation into exact Git ref constraints; it
does not grant authority or infer publication state.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
from enum import StrEnum

from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefClass

from .repository_storage import DurableRepositoryRootManager


class RepositoryCredentialProtocol(StrEnum):
    GIT_READ = "git_read"
    GIT_WRITE = "git_write"
    LFS_READ = "lfs_read"
    LFS_WRITE = "lfs_write"


class RepositoryRefAclError(RuntimeError):
    error_code = "repository_ref_acl_rejected"


def private_ref_prefix(
    binding: ProjectRepositoryBinding,
    *,
    session_id: str,
    agent_member_id: str,
    workspace_generation: int,
) -> str:
    """Derive the exact private namespace without exposing a storage locator."""

    if workspace_generation <= 0:
        raise ValueError("workspace_generation must be positive")
    if not session_id or not agent_member_id:
        raise ValueError("session_id and agent_member_id must not be empty")

    def encode_component(value: str) -> str:
        encoded = base64.b32encode(value.encode("utf-8")).rstrip(b"=")
        return encoded.decode("ascii").lower()

    return (
        f"{binding.ref_namespace_policy.private_prefix}/"
        f"s-{encode_component(session_id)}/"
        f"a-{encode_component(agent_member_id)}/g{workspace_generation}"
    )


@dataclass(frozen=True, slots=True)
class GitRefUpdate:
    old_oid: str
    new_oid: str
    ref_name: str

    def is_create(self, *, object_hex_length: int) -> bool:
        return self.old_oid == "0" * object_hex_length

    def is_delete(self, *, object_hex_length: int) -> bool:
        return self.new_oid == "0" * object_hex_length


@dataclass(frozen=True, slots=True)
class RepositoryCredentialClaimsView:
    """Minimum verified claims required by the ref ACL mechanism."""

    binding_id: str
    binding_version: int
    repository_id: str
    session_id: str
    agent_member_id: str
    workspace_generation: int
    protocols: tuple[RepositoryCredentialProtocol, ...]
    ref_classes: tuple[RepositoryRefClass, ...]


@dataclass(slots=True)
class GitRefAclValidator:
    roots: DurableRepositoryRootManager

    def validate_agent_updates(
        self,
        *,
        binding: ProjectRepositoryBinding,
        claims: RepositoryCredentialClaimsView,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        if (
            claims.binding_id != binding.binding_id
            or claims.binding_version != binding.binding_version
            or claims.repository_id != binding.repository_id
        ):
            raise RepositoryRefAclError(
                "credential binding identity does not match repository binding"
            )
        if RepositoryCredentialProtocol.GIT_WRITE not in claims.protocols:
            raise RepositoryRefAclError("credential does not authorize Git writes")
        if RepositoryRefClass.PRIVATE not in claims.ref_classes:
            raise RepositoryRefAclError("credential does not authorize private refs")
        expected_prefix = private_ref_prefix(
            binding,
            session_id=claims.session_id,
            agent_member_id=claims.agent_member_id,
            workspace_generation=claims.workspace_generation,
        )
        for update in updates:
            self._validate_oid_lengths(binding, update)
            if not update.ref_name.startswith(f"{expected_prefix}/"):
                raise RepositoryRefAclError(
                    "agent ref update is outside its exact private namespace"
                )
            if update.is_delete(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("agent ref deletion is forbidden")
            if update.is_create(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                continue
            if not self.roots.is_ancestor(
                binding,
                ancestor=update.old_oid,
                descendant=update.new_oid,
            ):
                raise RepositoryRefAclError(
                    "agent private ref updates must be fast-forward"
                )

    def validate_publication_create(
        self,
        *,
        binding: ProjectRepositoryBinding,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        prefix = binding.ref_namespace_policy.publication_prefix
        for update in updates:
            self._validate_oid_lengths(binding, update)
            if not update.ref_name.startswith(f"{prefix}/"):
                raise RepositoryRefAclError(
                    "publication update is outside the publication namespace"
                )
            if update.is_delete(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("publication ref deletion is forbidden")
            if not update.is_create(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("publication refs are create-only")

    def validate_historical_update(
        self,
        *,
        binding: ProjectRepositoryBinding,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        prefix = binding.ref_namespace_policy.historical_prefix
        for update in updates:
            self._validate_oid_lengths(binding, update)
            if not update.ref_name.startswith(f"{prefix}/"):
                raise RepositoryRefAclError(
                    "historical update is outside the historical namespace"
                )
            if update.is_delete(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                raise RepositoryRefAclError("historical ref deletion is forbidden")
            if update.is_create(
                object_hex_length=binding.object_format.commit_hex_length
            ):
                continue
            if not self.roots.is_ancestor(
                binding,
                ancestor=update.old_oid,
                descendant=update.new_oid,
            ):
                raise RepositoryRefAclError(
                    "historical ref updates must be fast-forward"
                )

    @staticmethod
    def _validate_oid_lengths(
        binding: ProjectRepositoryBinding,
        update: GitRefUpdate,
    ) -> None:
        expected = binding.object_format.commit_hex_length
        if len(update.old_oid) != expected or len(update.new_oid) != expected:
            raise RepositoryRefAclError("Git ref update object id length is invalid")
        for oid in (update.old_oid, update.new_oid):
            try:
                int(oid, 16)
            except ValueError as exc:
                raise RepositoryRefAclError(
                    "Git ref update object id is not hexadecimal"
                ) from exc


class RepositoryRefOwnerKind(StrEnum):
    HOST_PUBLICATION = "host_publication"
    MIGRATION_HISTORICAL = "migration_historical"


@dataclass(frozen=True, slots=True)
class RepositoryRefOwnerIdentity:
    owner_id: str
    owner_kind: RepositoryRefOwnerKind

    def __post_init__(self) -> None:
        if not self.owner_id or any(character.isspace() for character in self.owner_id):
            raise ValueError("repository ref owner_id must be a non-empty identifier")
        if not isinstance(self.owner_kind, RepositoryRefOwnerKind):
            raise TypeError("owner_kind must be a RepositoryRefOwnerKind")


HOST_PUBLICATION_REF_OWNER = RepositoryRefOwnerIdentity(
    owner_id="openzyme.repository-owner.host-publication@1",
    owner_kind=RepositoryRefOwnerKind.HOST_PUBLICATION,
)
MIGRATION_HISTORICAL_REF_OWNER = RepositoryRefOwnerIdentity(
    owner_id="openzyme.repository-owner.migration-historical@1",
    owner_kind=RepositoryRefOwnerKind.MIGRATION_HISTORICAL,
)


class RepositoryRefOwnerRejectedError(RuntimeError):
    error_code = "repository_ref_owner_rejected"


@dataclass(slots=True)
class RepositoryOwnerRefService:
    roots: DurableRepositoryRootManager

    def create_publication_refs(
        self,
        *,
        binding: ProjectRepositoryBinding,
        owner: RepositoryRefOwnerIdentity,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        self._require_owner(
            owner,
            expected=HOST_PUBLICATION_REF_OWNER,
            operation="publication ref creation",
        )
        GitRefAclValidator(self.roots).validate_publication_create(
            binding=binding,
            updates=updates,
        )
        self.roots.apply_exact_ref_updates(binding, updates)

    def update_historical_refs(
        self,
        *,
        binding: ProjectRepositoryBinding,
        owner: RepositoryRefOwnerIdentity,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        self._require_owner(
            owner,
            expected=MIGRATION_HISTORICAL_REF_OWNER,
            operation="historical ref update",
        )
        GitRefAclValidator(self.roots).validate_historical_update(
            binding=binding,
            updates=updates,
        )
        self.roots.apply_exact_ref_updates(binding, updates)

    @staticmethod
    def _require_owner(
        owner: RepositoryRefOwnerIdentity,
        *,
        expected: RepositoryRefOwnerIdentity,
        operation: str,
    ) -> None:
        if owner != expected:
            raise RepositoryRefOwnerRejectedError(
                f"{operation} requires owner {expected.owner_id!r}"
            )


__all__ = [
    "GitRefAclValidator",
    "GitRefUpdate",
    "HOST_PUBLICATION_REF_OWNER",
    "MIGRATION_HISTORICAL_REF_OWNER",
    "RepositoryCredentialClaimsView",
    "RepositoryCredentialProtocol",
    "RepositoryOwnerRefService",
    "RepositoryRefAclError",
    "RepositoryRefOwnerIdentity",
    "RepositoryRefOwnerKind",
    "RepositoryRefOwnerRejectedError",
    "private_ref_prefix",
]
