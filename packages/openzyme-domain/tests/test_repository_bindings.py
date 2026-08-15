from dataclasses import FrozenInstanceError
from dataclasses import replace

import pytest

from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryBindingDriftKind
from openzyme_domain import RepositoryBindingLifecycleStatus
from openzyme_domain import RepositoryRefClass
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import SessionRepositoryBindingPin


def _binding(**overrides: object) -> ProjectRepositoryBinding:
    values: dict[str, object] = {
        "binding_id": "binding_openzyme_v1",
        "project_id": "openzyme",
        "binding_version": 1,
        "repository_id": "repo_openzyme",
        "internal_git_service_id": "git_openzyme_local",
        "internal_git_endpoint": "https://localhost:8443/repositories/repo_openzyme.git",
        "lfs_service_id": "lfs_openzyme_local",
        "lfs_endpoint": "https://localhost:8443/repositories/repo_openzyme.git/info/lfs",
        "upstream_identity": "github_grtresy_enzymedesign",
        "upstream_url": "git@github.com:Grtresy/EnzymeDesign.git",
        "object_format": GitObjectFormat.SHA1,
        "default_base_ref": "refs/heads/dev",
        "default_base_commit": "9b78ec6a883f90ec4239d113e9300098120f68bd",
        "ref_namespace_policy": RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        "repository_policy_version": "repository-policy-v1",
        "repository_policy_digest": f"sha256:{'1' * 64}",
        "created_at": "2026-08-15T13:48:15+00:00",
        "created_by": "operator:c1",
    }
    values.update(overrides)
    return ProjectRepositoryBinding.create(**values)  # type: ignore[arg-type]


def test_repository_binding_digest_is_canonical_and_binding_is_frozen() -> None:
    first = _binding()
    second = _binding()

    assert first.canonical_digest == second.canonical_digest
    assert first.to_dict()["object_format"] == "sha1"
    with pytest.raises(FrozenInstanceError):
        first.default_base_commit = "0" * 40  # type: ignore[misc]


def test_repository_binding_safe_projection_hides_endpoints_and_upstream() -> None:
    projected = _binding().safe_projection(
        lifecycle_status=RepositoryBindingLifecycleStatus.ACTIVE,
        allowed_ref_classes=(RepositoryRefClass.READ, RepositoryRefClass.PRIVATE),
    )

    assert projected["binding_id"] == "binding_openzyme_v1"
    assert projected["default_base_commit"] == (
        "9b78ec6a883f90ec4239d113e9300098120f68bd"
    )
    assert projected["allowed_ref_classes"] == ["read", "private"]
    assert "internal_git_endpoint" not in projected
    assert "lfs_endpoint" not in projected
    assert "upstream_url" not in projected


def test_repository_binding_drift_reports_each_authority_dimension() -> None:
    pinned = _binding()
    configured = _binding(
        internal_git_endpoint="https://localhost:9443/repositories/repo_openzyme.git",
        upstream_url="https://github.com/Grtresy/EnzymeDesign.git",
        object_format=GitObjectFormat.SHA256,
        default_base_commit="2" * 64,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private-v2",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        lfs_service_id="lfs_openzyme_v2",
        repository_policy_digest=f"sha256:{'3' * 64}",
    )

    assert pinned.drift_from(configured) == (
        RepositoryBindingDriftKind.INTERNAL_REMOTE,
        RepositoryBindingDriftKind.UPSTREAM_ORIGIN,
        RepositoryBindingDriftKind.OBJECT_FORMAT,
        RepositoryBindingDriftKind.DEFAULT_BASE,
        RepositoryBindingDriftKind.REF_NAMESPACE_POLICY,
        RepositoryBindingDriftKind.LFS_IDENTITY,
        RepositoryBindingDriftKind.REPOSITORY_POLICY,
        RepositoryBindingDriftKind.CANONICAL_DIGEST,
    )


def test_repository_binding_rejects_plaintext_or_host_path_endpoints() -> None:
    with pytest.raises(ValueError, match="must use https"):
        _binding(
            internal_git_endpoint=(
                "http://localhost:8443/repositories/repo_openzyme.git"
            )
        )
    with pytest.raises(ValueError, match="Host filesystem"):
        _binding(upstream_url="/home/grtresy/VSCodeRepo/EnzymeDesign")
    with pytest.raises(ValueError, match="Host filesystem"):
        _binding(upstream_url="../EnzymeDesign")
    with pytest.raises(ValueError, match="SSH remote"):
        _binding(upstream_url="relative-repository.git")


@pytest.mark.parametrize(
    "prefix",
    (
        "refs/openzyme/private:other",
        "refs/openzyme/private branch",
        "refs/openzyme/.private",
        "refs/openzyme/private.lock",
        "refs/openzyme/private?name",
        "refs/openzyme/private\\name",
        "refs/openzyme/private.",
        "refs/openzyme/" + "x" * 1024,
    ),
)
def test_repository_binding_rejects_git_invalid_or_unbounded_ref_prefixes(
    prefix: str,
) -> None:
    with pytest.raises(ValueError, match="Git ref|length limit|whitespace"):
        RepositoryRefNamespacePolicy(
            private_prefix=prefix,
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        )


def test_session_binding_pin_keeps_exact_version_base_and_digest() -> None:
    binding = _binding()
    pin = SessionRepositoryBindingPin(
        session_id="sess_001",
        project_id=binding.project_id,
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=binding.default_base_commit,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at="2026-08-15T14:00:00+00:00",
    )

    assert pin.to_dict()["binding_version"] == 1
    with pytest.raises(ValueError, match="exact Git commit"):
        replace(pin, resolved_base_commit="refs/heads/dev")
