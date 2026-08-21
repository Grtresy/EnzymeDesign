"""Git/LFS implementation of repository-binding mechanism verification."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryBindingEndpointMismatchError

from .repository_storage import DurableRepositoryRootManager


class RepositoryEndpointSettings(Protocol):
    https_origin: str


@dataclass(frozen=True, slots=True)
class GitLfsRepositoryBindingMechanism:
    """Verify Git-shaped binding facts without owning canonical binding state."""

    settings: RepositoryEndpointSettings
    roots: DurableRepositoryRootManager

    def verify_endpoint(self, binding: ProjectRepositoryBinding) -> None:
        origin = self.settings.https_origin.rstrip("/")
        expected_git = f"{origin}/repositories/{binding.repository_id}.git"
        expected_lfs = f"{expected_git}/info/lfs"
        if binding.internal_git_endpoint != expected_git:
            raise RepositoryBindingEndpointMismatchError(
                "binding Git endpoint does not match configured repository service"
            )
        if binding.lfs_endpoint != expected_lfs:
            raise RepositoryBindingEndpointMismatchError(
                "binding LFS endpoint does not match configured repository service"
            )

    def verify_registration(self, binding: ProjectRepositoryBinding) -> None:
        self.verify_endpoint(binding)
        self.roots.preflight_roots()
        self.roots.verify_exact_base(binding)

    def activate(self, binding: ProjectRepositoryBinding) -> None:
        self.verify_registration(binding)
        self.roots.set_default_head(binding)
        self.roots.verify_default_head(binding)

    def verify_pinned(self, binding: ProjectRepositoryBinding) -> None:
        self.verify_endpoint(binding)
        self.roots.verify_pinned_commit(binding)


__all__ = ["GitLfsRepositoryBindingMechanism", "RepositoryEndpointSettings"]
