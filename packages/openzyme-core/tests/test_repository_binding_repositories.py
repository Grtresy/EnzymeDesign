from dataclasses import replace
import sqlite3

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import RepositoryBindingConflictError
from openzyme_core import RepositoryBindingRequiredError
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryBindingLifecycleStatus
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_domain import SessionRepositoryBindingPin
from openzyme_domain import SessionRepositoryBindingStatus


def _binding(version: int = 1, **overrides: object) -> ProjectRepositoryBinding:
    values: dict[str, object] = {
        "binding_id": f"binding_openzyme_v{version}",
        "project_id": "openzyme",
        "binding_version": version,
        "repository_id": "repo_openzyme",
        "internal_git_service_id": "git_openzyme_local",
        "internal_git_endpoint": "https://localhost:8443/repositories/repo_openzyme.git",
        "lfs_service_id": "lfs_openzyme_local",
        "lfs_endpoint": "https://localhost:8443/repositories/repo_openzyme.git/info/lfs",
        "upstream_identity": "github_grtresy_enzymedesign",
        "upstream_url": "git@github.com:Grtresy/EnzymeDesign.git",
        "object_format": GitObjectFormat.SHA1,
        "default_base_ref": "refs/heads/dev",
        "default_base_commit": (
            "9b78ec6a883f90ec4239d113e9300098120f68bd" if version == 1 else "1" * 40
        ),
        "ref_namespace_policy": RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        "repository_policy_version": f"repository-policy-v{version}",
        "repository_policy_digest": f"sha256:{str(version) * 64}",
        "created_at": f"2026-08-15T14:0{version}:00+00:00",
        "created_by": "operator:c1",
    }
    values.update(overrides)
    return ProjectRepositoryBinding.create(**values)  # type: ignore[arg-type]


def _pin(
    session_id: str, binding: ProjectRepositoryBinding
) -> SessionRepositoryBindingPin:
    return SessionRepositoryBindingPin(
        session_id=session_id,
        project_id=binding.project_id,
        binding_id=binding.binding_id,
        binding_version=binding.binding_version,
        repository_id=binding.repository_id,
        resolved_base_commit=binding.default_base_commit,
        binding_canonical_digest=binding.canonical_digest,
        pinned_at="2026-08-15T14:10:00+00:00",
    )


def test_binding_versions_are_immutable_and_active_pointer_rolls_forward() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    first = _binding(1)
    second = _binding(2)

    repositories.project_repository_bindings.add(first)
    repositories.project_repository_bindings.activate(
        first.binding_id,
        actor_ref="operator:c1",
        activated_at="2026-08-15T14:02:00+00:00",
    )
    repositories.project_repository_bindings.add(second)
    repositories.project_repository_bindings.activate(
        second.binding_id,
        actor_ref="operator:c1",
        activated_at="2026-08-15T14:03:00+00:00",
    )

    assert repositories.project_repository_bindings.get_active("openzyme") == second
    assert (
        repositories.project_repository_bindings.lifecycle_status(first.binding_id)
        is RepositoryBindingLifecycleStatus.REGISTERED
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE project_repository_binding_versions SET upstream_url = ? WHERE binding_id = ?",
            ("https://example.invalid/other.git", first.binding_id),
        )


def test_binding_version_identity_rejects_conflicting_reuse() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    first = _binding(1)
    repositories.project_repository_bindings.add(first)

    with pytest.raises(RepositoryBindingConflictError):
        repositories.project_repository_bindings.add(
            _binding(1, binding_id="binding_other")
        )
    with pytest.raises(RepositoryBindingConflictError):
        repositories.project_repository_bindings.add(
            _binding(1, upstream_url="https://github.com/other/repository.git")
        )


def test_new_session_and_exact_pin_commit_in_one_uow(tmp_path) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "binding.sqlite3"))
    binding = _binding(1)
    with provider.write() as owner:
        owner.repositories.project_repository_bindings.add(binding)
        owner.repositories.project_repository_bindings.activate(
            binding.binding_id,
            actor_ref="operator:c1",
            activated_at="2026-08-15T14:02:00+00:00",
        )
        session = Session.create(
            "sess_pinned",
            "openzyme",
            "Pinned",
            "Pin an exact repository universe",
        )
        owner.repositories.sessions.save(session)
        owner.repositories.session_repository_binding_pins.add(
            _pin(session.session_id, binding)
        )

    with provider.read() as owner:
        session = owner.repositories.sessions.get("sess_pinned")
        assert session is not None
        assert (
            session.repository_binding_status is SessionRepositoryBindingStatus.PINNED
        )
        assert (
            owner.repositories.session_repository_binding_pins.require(
                session.session_id
            ).binding_canonical_digest
            == binding.canonical_digest
        )


def test_failed_pin_rolls_back_new_session(tmp_path) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "rollback.sqlite3"))
    binding = _binding(1)
    with provider.write() as owner:
        owner.repositories.project_repository_bindings.add(binding)

    with pytest.raises(sqlite3.IntegrityError, match="owner mismatch"):
        with provider.write() as owner:
            session = Session.create(
                "sess_rollback",
                "openzyme",
                "Rollback",
                "Reject a mismatched base",
            )
            owner.repositories.sessions.save(session)
            owner.repositories.session_repository_binding_pins.add(
                replace(
                    _pin(session.session_id, binding),
                    resolved_base_commit="2" * 40,
                )
            )

    with provider.read() as owner:
        assert owner.repositories.sessions.get("sess_rollback") is None


def test_session_cannot_claim_pinned_status_without_pin() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    session = replace(
        Session.create(
            "sess_false_pin",
            "openzyme",
            "False pin",
            "Reject status without immutable pin",
        ),
        repository_binding_status=SessionRepositoryBindingStatus.PINNED,
    )

    with pytest.raises(sqlite3.IntegrityError, match="must be inserted explicitly"):
        repositories.sessions.save(session)


def test_legacy_session_requires_explicit_mapping_receipt() -> None:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    binding = _binding(1)
    session = Session.create(
        "sess_legacy",
        "openzyme",
        "Legacy",
        "Require explicit mapping",
    )
    repositories.project_repository_bindings.add(binding)
    repositories.sessions.save(session)

    with pytest.raises(RepositoryBindingRequiredError):
        repositories.session_repository_binding_pins.require(session.session_id)

    pin, receipt = repositories.session_repository_binding_pins.map_legacy_session(
        session_id=session.session_id,
        binding=binding,
        operator_ref="operator:c1",
        mapping_reason="Exact remote, policy, and base were independently verified.",
        mapped_at="2026-08-15T14:20:00+00:00",
        receipt_id="mapping_receipt_001",
    )

    assert pin.mapping_receipt_id == "mapping_receipt_001"
    assert receipt["schema_version"] == "repository_binding_mapping_receipt@1"
    assert repositories.sessions.get(session.session_id).repository_binding_status is (
        SessionRepositoryBindingStatus.PINNED
    )
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        connection.execute(
            "UPDATE session_repository_binding_pins SET resolved_base_commit = ? WHERE session_id = ?",
            ("3" * 40, session.session_id),
        )
