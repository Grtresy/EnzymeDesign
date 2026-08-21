from dataclasses import dataclass, field

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefClass
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_workspace_git_lfs import GitRefAclValidator
from openzyme_workspace_git_lfs import GitRefUpdate
from openzyme_workspace_git_lfs import HOST_PUBLICATION_REF_OWNER
from openzyme_workspace_git_lfs import MIGRATION_HISTORICAL_REF_OWNER
from openzyme_workspace_git_lfs import RepositoryCredentialClaimsView
from openzyme_workspace_git_lfs import RepositoryCredentialProtocol
from openzyme_workspace_git_lfs import RepositoryOwnerRefService
from openzyme_workspace_git_lfs import RepositoryRefAclError
from openzyme_workspace_git_lfs import RepositoryRefOwnerRejectedError
from openzyme_workspace_git_lfs import private_ref_prefix


def _binding() -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="binding-ref-policy",
        project_id="openzyme",
        binding_version=1,
        repository_id="repository-ref-policy",
        internal_git_service_id="git-local",
        internal_git_endpoint="https://localhost/repository.git",
        lfs_service_id="lfs-local",
        lfs_endpoint="https://localhost/repository.git/info/lfs",
        upstream_identity="upstream-ref-policy",
        upstream_url="git@example.test:openzyme/repository.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/dev",
        default_base_commit="1" * 40,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=f"sha256:{'2' * 64}",
        created_at="2026-08-20T00:00:00+00:00",
        created_by="operator:test",
    )


@dataclass
class _FakeRoots:
    applied: list[tuple[GitRefUpdate, ...]] = field(default_factory=list)

    def is_ancestor(
        self,
        binding: ProjectRepositoryBinding,
        *,
        ancestor: str,
        descendant: str,
    ) -> bool:
        del binding
        return ancestor == "1" * 40 and descendant == "2" * 40

    def apply_exact_ref_updates(
        self,
        binding: ProjectRepositoryBinding,
        updates: tuple[GitRefUpdate, ...],
    ) -> None:
        del binding
        self.applied.append(updates)


def test_private_ref_prefix_is_exact_and_hides_raw_owner_ids() -> None:
    prefix = private_ref_prefix(
        _binding(),
        session_id="session-sensitive",
        agent_member_id="member-sensitive",
        workspace_generation=3,
    )

    assert prefix.startswith("refs/openzyme/private/s-")
    assert prefix.endswith("/g3")
    assert "session-sensitive" not in prefix
    assert "member-sensitive" not in prefix


def test_agent_ref_acl_rejects_host_publication_namespace() -> None:
    binding = _binding()
    claims = RepositoryCredentialClaimsView(
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        session_id="session-1",
        agent_member_id="member-1",
        workspace_generation=1,
        protocols=(RepositoryCredentialProtocol.GIT_WRITE,),
        ref_classes=(RepositoryRefClass.PRIVATE,),
    )

    with pytest.raises(RepositoryRefAclError, match="outside"):
        GitRefAclValidator(_FakeRoots()).validate_agent_updates(
            binding=binding,
            claims=claims,
            updates=(
                GitRefUpdate(
                    old_oid="0" * 40,
                    new_oid="1" * 40,
                    ref_name="refs/openzyme/publications/forbidden",
                ),
            ),
        )


def test_publication_ref_service_requires_exact_host_owner() -> None:
    binding = _binding()
    roots = _FakeRoots()
    service = RepositoryOwnerRefService(roots)  # type: ignore[arg-type]
    updates = (
        GitRefUpdate(
            old_oid="0" * 40,
            new_oid="1" * 40,
            ref_name="refs/openzyme/publications/publication-1",
        ),
    )

    with pytest.raises(RepositoryRefOwnerRejectedError, match="host-publication"):
        service.create_publication_refs(
            binding=binding,
            owner=MIGRATION_HISTORICAL_REF_OWNER,
            updates=updates,
        )

    service.create_publication_refs(
        binding=binding,
        owner=HOST_PUBLICATION_REF_OWNER,
        updates=updates,
    )
    assert roots.applied == [updates]
