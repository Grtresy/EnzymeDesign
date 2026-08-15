from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from openzyme_domain import ProjectRepositoryBinding

from .repository_credentials import GitRefAclValidator
from .repository_credentials import GitRefUpdate
from .repository_storage import DurableRepositoryRootManager


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
    "HOST_PUBLICATION_REF_OWNER",
    "MIGRATION_HISTORICAL_REF_OWNER",
    "RepositoryOwnerRefService",
    "RepositoryRefOwnerIdentity",
    "RepositoryRefOwnerKind",
    "RepositoryRefOwnerRejectedError",
]
