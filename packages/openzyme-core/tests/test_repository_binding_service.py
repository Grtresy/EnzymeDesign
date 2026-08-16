from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import sqlite3
import subprocess

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import AgentCapabilityLeaseService
from openzyme_core import AgentWorkspaceReadinessProof
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import ProjectRepositoryBindingService
from openzyme_core import RepositoryBindingConflictError
from openzyme_core import RepositoryBindingDriftError
from openzyme_core import RepositoryBindingRequiredError
from openzyme_core import RepositoryRootBoundary
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core.agent_identity import create_agent_member
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryBindingDriftKind
from openzyme_domain import RepositoryBindingLifecycleStatus
from openzyme_domain import RepositoryRefClass
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_domain import canonical_capability_digest
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import RepositoryServiceSettings


@dataclass(frozen=True, slots=True)
class _WorkspaceReadinessProvider:
    provider_id: str = "test.repository-binding-workspace-readiness@1"

    def verify_readiness(
        self,
        reservation: AgentWorkspaceGenerationReservation,
    ) -> AgentWorkspaceReadinessProof:
        return AgentWorkspaceReadinessProof(
            provider_id=self.provider_id,
            reservation_id=reservation.reservation_id,
            reservation_fingerprint=reservation.immutable_fingerprint,
            session_id=reservation.session_id,
            agent_member_id=reservation.agent_member_id,
            agent_id=reservation.agent_id,
            workspace_generation=reservation.workspace_generation,
            readiness_ref=f"test-ready:{reservation.reservation_id}",
            readiness_digest=canonical_capability_digest(
                {
                    "provider_id": self.provider_id,
                    "reservation_id": reservation.reservation_id,
                }
            ),
            observed_at=utc_now_iso(),
        )


def _settings(root: Path) -> RepositoryServiceSettings:
    git_root = root / "git"
    lfs_root = root / "lfs"
    backup_root = root / "backup"
    for path in (git_root, lfs_root, backup_root):
        path.mkdir(parents=True)
        path.chmod(0o700)
    return RepositoryServiceSettings(
        https_origin="https://localhost:8443",
        bare_repository_root=git_root,
        lfs_object_root=lfs_root,
        backup_root=backup_root,
        credential_signing_key_file=root / "token.key",
        tls_certificate_file=root / "tls.crt",
        tls_private_key_file=root / "tls.key",
        binding_inventory_file=root / "bindings.json",
        git_executable=Path("/usr/bin/git"),
        git_lfs_executable=Path("/usr/bin/false"),
        git_http_backend=Path("/usr/lib/git-core/git-http-backend"),
    )


def _source(root: Path) -> tuple[Path, str]:
    root.mkdir()
    source = root / "source"
    source.mkdir()
    subprocess.run(
        ("/usr/bin/git", "init", str(source)), check=True, capture_output=True
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "config", "user.name", "C1 Test"),
        check=True,
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "config", "user.email", "c1@test"),
        check=True,
    )
    (source / "README.md").write_text("binding service\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "commit", "-m", "seed"),
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ("/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, commit


def _binding(
    commit: str,
    *,
    version: int = 1,
    https_origin: str = "https://localhost:8443",
) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id=f"binding_openzyme_v{version}",
        project_id="openzyme",
        binding_version=version,
        repository_id="repo_openzyme",
        internal_git_service_id="git_openzyme_local",
        internal_git_endpoint=(f"{https_origin}/repositories/repo_openzyme.git"),
        lfs_service_id="lfs_openzyme_local",
        lfs_endpoint=(f"{https_origin}/repositories/repo_openzyme.git/info/lfs"),
        upstream_identity="github_grtresy_enzymedesign",
        upstream_url="git@github.com:Grtresy/EnzymeDesign.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/dev",
        default_base_commit=commit,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version=f"repository-policy-v{version}",
        repository_policy_digest=f"sha256:{str(version) * 64}",
        created_at=f"2026-08-15T17:0{version}:00+00:00",
        created_by="operator:c1",
    )


def _service(tmp_path: Path):
    settings = _settings(tmp_path / "service")
    checkout = tmp_path / "checkout"
    cwd = tmp_path / "cwd"
    checkout.mkdir()
    cwd.mkdir()
    roots = DurableRepositoryRootManager(
        settings,
        RepositoryRootBoundary(
            host_checkout=checkout,
            process_cwd=cwd,
            temporary_roots=(),
        ),
    )
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    return connection, roots, ProjectRepositoryBindingService(repositories, roots)


def _prepare_binding(
    tmp_path: Path,
    roots: DurableRepositoryRootManager,
    service: ProjectRepositoryBindingService,
    *,
    version: int = 1,
) -> ProjectRepositoryBinding:
    source, commit = _source(tmp_path / f"source_{version}")
    binding = _binding(commit, version=version)
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=commit,
    )
    service.register(binding)
    service.activate(
        binding.binding_id,
        actor_ref="operator:c1",
        activated_at=f"2026-08-15T17:1{version}:00+00:00",
    )
    return binding


def test_session_creation_atomically_pins_active_binding_and_safe_projection(
    tmp_path: Path,
) -> None:
    _, roots, service = _service(tmp_path)
    binding = _prepare_binding(tmp_path, roots, service)
    session = Session.create(
        "sess_pinned_service",
        "openzyme",
        "Pinned service",
        "Pin before workspace provisioning",
    )

    resolved = service.create_pinned_session(session)
    projected = resolved.safe_projection(
        allowed_ref_classes=(RepositoryRefClass.READ, RepositoryRefClass.PRIVATE)
    )

    assert resolved.pin.binding_id == binding.binding_id
    assert projected["lifecycle_status"] == "active"
    assert projected["allowed_ref_classes"] == ["read", "private"]
    serialized = repr(projected)
    assert str(roots.settings.bare_repository_root) not in serialized
    assert binding.internal_git_endpoint not in serialized
    assert binding.upstream_url not in serialized


def test_session_creation_rejects_active_binding_change_before_atomic_pin(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, roots, service = _service(tmp_path)
    first = _prepare_binding(tmp_path, roots, service)
    second = _binding(first.default_base_commit, version=2)
    service.register(second)
    repository = service.repositories.project_repository_bindings
    repository_type = type(repository)
    original_get_active = repository_type.get_active
    calls = 0

    def changing_get_active(self, project_id: str):
        nonlocal calls
        calls += 1
        if calls == 1:
            return first
        if calls == 2:
            return second
        return original_get_active(self, project_id)

    monkeypatch.setattr(repository_type, "get_active", changing_get_active)
    session = Session.create(
        "sess_active_binding_changed",
        "openzyme",
        "Changed binding",
        "Reject a stale session pin",
    )

    with pytest.raises(RepositoryBindingConflictError, match="changed during"):
        service.create_pinned_session(session)

    assert service.repositories.sessions.get(session.session_id) is None


def test_session_creation_rejects_raw_noncanonical_active_endpoint(
    tmp_path: Path,
) -> None:
    _, roots, service = _service(tmp_path)
    first = _prepare_binding(tmp_path, roots, service)
    hostile = _binding(
        first.default_base_commit,
        version=2,
        https_origin="https://unconfigured.example",
    )
    service.repositories.project_repository_bindings.add(hostile)
    service.repositories.project_repository_bindings.activate(
        hostile.binding_id,
        actor_ref="raw:test",
        activated_at="2026-08-15T17:20:00+00:00",
    )
    session = Session.create(
        "sess_noncanonical_endpoint",
        "openzyme",
        "Noncanonical endpoint",
        "Reject a binding outside the configured service",
    )

    with pytest.raises(RepositoryBindingConflictError, match="configured repository"):
        service.create_pinned_session(session)

    assert service.repositories.sessions.get(session.session_id) is None


def test_new_active_version_does_not_move_existing_session_pin(tmp_path: Path) -> None:
    _, roots, service = _service(tmp_path)
    first = _prepare_binding(tmp_path, roots, service, version=1)
    first_session = Session.create(
        "sess_first_binding",
        "openzyme",
        "First",
        "Remain on version one",
    )
    service.create_pinned_session(first_session)
    rollover_source = tmp_path / "rollover_source"
    subprocess.run(
        (
            "/usr/bin/git",
            "clone",
            str(roots.repository_path(first.repository_id)),
            str(rollover_source),
        ),
        check=True,
        capture_output=True,
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(rollover_source), "config", "user.name", "C1 Test"),
        check=True,
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(rollover_source), "config", "user.email", "c1@test"),
        check=True,
    )
    (rollover_source / "README.md").write_text(
        "binding service\nrollover\n",
        encoding="utf-8",
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(rollover_source), "commit", "-am", "rollover"),
        check=True,
        capture_output=True,
    )
    second_commit = subprocess.run(
        ("/usr/bin/git", "-C", str(rollover_source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    second = _binding(second_commit, version=2)
    roots.import_exact_commit_from_repository(
        second,
        source_repository=rollover_source,
        source_commit=second_commit,
    )
    service.register(second)
    service.activate(
        second.binding_id,
        actor_ref="operator:c1",
        activated_at="2026-08-15T17:22:00+00:00",
    )
    second_session = Session.create(
        "sess_second_binding",
        "openzyme",
        "Second",
        "Use version two",
    )
    service.create_pinned_session(second_session)

    restored_first = service.require_session_binding(
        first_session.session_id,
        prerequisite="session_restore",
    )
    restored_second = service.require_session_binding(
        second_session.session_id,
        prerequisite="agent_workspace",
    )
    assert restored_first.binding.binding_id == first.binding_id
    assert (
        restored_first.lifecycle_status is RepositoryBindingLifecycleStatus.REGISTERED
    )
    assert restored_second.binding.binding_id == second.binding_id


def test_all_downstream_prerequisites_resolve_only_the_session_pin(
    tmp_path: Path,
) -> None:
    _, roots, service = _service(tmp_path)
    first = _prepare_binding(tmp_path, roots, service, version=1)
    session = Session.create(
        "sess_all_repository_prerequisites",
        "openzyme",
        "All prerequisites",
        "Keep every downstream consumer on the exact session pin",
    )
    service.create_pinned_session(session)
    second = _binding(first.default_base_commit, version=2)
    service.register(second)
    service.activate(
        second.binding_id,
        actor_ref="operator:c1",
        activated_at="2026-08-15T17:25:00+00:00",
    )

    for prerequisite in (
        "session_restore",
        "agent_workspace",
        "publication",
        "hpc_workspace",
        "historical_migration",
    ):
        resolved = service.require_session_binding(
            session.session_id,
            prerequisite=prerequisite,
        )
        assert resolved.binding.binding_id == first.binding_id
        assert resolved.pin.resolved_base_commit == first.default_base_commit
        assert resolved.lifecycle_status is RepositoryBindingLifecycleStatus.REGISTERED


def test_missing_binding_and_restore_drift_fail_without_ambient_fallback(
    tmp_path: Path,
) -> None:
    _, roots, service = _service(tmp_path)
    missing = Session.create(
        "sess_missing_binding",
        "missing_project",
        "Missing",
        "Must fail",
    )
    with pytest.raises(RepositoryBindingRequiredError, match="no active"):
        service.create_pinned_session(missing)
    assert service.repositories.sessions.get(missing.session_id) is None

    binding = _prepare_binding(tmp_path, roots, service)
    session = Session.create(
        "sess_drift",
        "openzyme",
        "Drift",
        "Reject configured policy drift",
    )
    service.create_pinned_session(session)
    drifted = _binding(binding.default_base_commit, version=2)
    with pytest.raises(RepositoryBindingDriftError) as captured:
        service.assert_restore_configuration(
            session.session_id,
            configured_binding=drifted,
        )
    assert RepositoryBindingDriftKind.BINDING_IDENTITY in captured.value.drift
    assert RepositoryBindingDriftKind.REPOSITORY_POLICY in captured.value.drift
    assert RepositoryBindingDriftKind.CANONICAL_DIGEST in captured.value.drift


def test_legacy_mapping_requires_exact_version_and_base(tmp_path: Path) -> None:
    _, roots, service = _service(tmp_path)
    binding = _prepare_binding(tmp_path, roots, service)
    legacy = Session.create(
        "sess_legacy_service",
        "openzyme",
        "Legacy",
        "Require operator mapping",
    )
    service.repositories.sessions.save(legacy)

    with pytest.raises(RepositoryBindingRequiredError, match="exact existing"):
        service.map_legacy_session(
            session_id=legacy.session_id,
            binding_id=binding.binding_id,
            binding_version=2,
            exact_base_commit=binding.default_base_commit,
            operator_ref="operator:c1",
            mapping_reason="wrong version",
            mapped_at="2026-08-15T17:30:00+00:00",
            receipt_id="mapping_wrong",
        )
    with pytest.raises(RepositoryBindingConflictError, match="base commit"):
        service.map_legacy_session(
            session_id=legacy.session_id,
            binding_id=binding.binding_id,
            binding_version=1,
            exact_base_commit="2" * 40,
            operator_ref="operator:c1",
            mapping_reason="wrong base",
            mapped_at="2026-08-15T17:31:00+00:00",
            receipt_id="mapping_wrong_base",
        )
    resolved, receipt = service.map_legacy_session(
        session_id=legacy.session_id,
        binding_id=binding.binding_id,
        binding_version=1,
        exact_base_commit=binding.default_base_commit,
        operator_ref="operator:c1",
        mapping_reason="Verified exact repository and base.",
        mapped_at="2026-08-15T17:32:00+00:00",
        receipt_id="mapping_exact",
    )
    assert resolved.pin.mapping_receipt_id == "mapping_exact"
    assert receipt["receipt_digest"].startswith("sha256:")


def test_direct_mapping_receipt_mismatch_and_active_retirement_are_rejected(
    tmp_path: Path,
) -> None:
    connection, roots, service = _service(tmp_path)
    binding = _prepare_binding(tmp_path, roots, service)
    legacy = Session.create(
        "sess_trigger_legacy",
        "openzyme",
        "Legacy",
        "Trigger integrity",
    )
    service.repositories.sessions.save(legacy)

    with pytest.raises(sqlite3.IntegrityError, match="owner mismatch"):
        connection.execute(
            """
            INSERT INTO repository_binding_mapping_receipts (
                receipt_id, session_id, project_id, binding_id, binding_version,
                resolved_base_commit, binding_canonical_digest, operator_ref,
                mapping_reason, receipt_digest, receipt_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "bad_mapping",
                legacy.session_id,
                binding.project_id,
                binding.binding_id,
                binding.binding_version,
                "2" * 40,
                binding.canonical_digest,
                "operator:c1",
                "bad",
                f"sha256:{'3' * 64}",
                "{}",
                "2026-08-15T17:40:00+00:00",
            ),
        )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be retired"):
        connection.execute(
            """
            INSERT INTO project_repository_binding_retirement_receipts (
                receipt_id, binding_id, binding_version, project_id,
                reference_audit_digest, receipt_digest, receipt_json,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "retire_active",
                binding.binding_id,
                binding.binding_version,
                binding.project_id,
                f"sha256:{'4' * 64}",
                f"sha256:{'5' * 64}",
                "{}",
                "2026-08-15T17:41:00+00:00",
                "operator:c1",
            ),
        )


def test_unreferenced_superseded_binding_retires_with_immutable_receipt(
    tmp_path: Path,
) -> None:
    connection, roots, service = _service(tmp_path)
    first = _prepare_binding(tmp_path, roots, service, version=1)
    second = _binding(first.default_base_commit, version=2)
    service.register(second)
    service.activate(
        second.binding_id,
        actor_ref="operator:c1",
        activated_at="2026-08-15T17:50:00+00:00",
    )

    with pytest.raises(sqlite3.IntegrityError, match="requires receipt"):
        connection.execute(
            """
            INSERT INTO project_repository_binding_lifecycle_events (
                event_id, project_id, binding_id, binding_version,
                status, actor_ref, reason, created_at
            ) VALUES (?, ?, ?, ?, 'retired', ?, ?, ?)
            """,
            (
                "retired_without_receipt",
                first.project_id,
                first.binding_id,
                first.binding_version,
                "operator:c1",
                "invalid direct event",
                "2026-08-15T17:51:00+00:00",
            ),
        )
    connection.rollback()

    receipt = service.retire_binding(
        first.binding_id,
        retired_at="2026-08-15T17:52:00+00:00",
        retired_by="operator:c1",
        receipt_id="retire_binding_v1",
    )
    repeated = service.retire_binding(
        first.binding_id,
        retired_at="2026-08-15T17:53:00+00:00",
        retired_by="operator:other",
    )

    assert receipt == repeated
    assert receipt["receipt_id"] == "retire_binding_v1"
    assert (
        service.repositories.project_repository_bindings.lifecycle_status(
            first.binding_id
        )
        is RepositoryBindingLifecycleStatus.RETIRED
    )
    with pytest.raises(sqlite3.IntegrityError, match="cannot be activated"):
        connection.execute(
            """
            UPDATE project_repository_active_bindings
            SET binding_id = ?, binding_version = ?,
                activation_generation = activation_generation + 1
            WHERE project_id = ?
            """,
            (
                first.binding_id,
                first.binding_version,
                first.project_id,
            ),
        )


def test_raw_retirement_rejects_repository_credential_reference(
    tmp_path: Path,
) -> None:
    connection, roots, service = _service(tmp_path)
    first = _prepare_binding(tmp_path, roots, service, version=1)
    legacy = Session.create(
        "sess_credential_reference",
        first.project_id,
        "Credential reference",
        "Retain the immutable repository universe referenced by a credential record",
    )
    service.create_pinned_session(legacy)
    agent = create_agent_member(
        service.repositories,
        session_id=legacy.session_id,
        role="executor",
    )
    assert agent.member_id is not None
    readiness_provider = _WorkspaceReadinessProvider()
    capability_service = AgentCapabilityLeaseService(
        service.repositories,
        readiness_providers={readiness_provider.provider_id: readiness_provider},
    )
    issuance = capability_service.reserve_and_issue(
        session_id=legacy.session_id,
        agent_id=agent.agent_id,
        idempotency_key="repository-binding-reference-generation-1",
        actor_ref="test:repository-binding-capability-issue",
    )
    active_lease = capability_service.activate_with_provider(
        lease_id=issuance.lease.lease_id,
        provider_id=readiness_provider.provider_id,
        actor_ref="test:repository-binding-capability-activate",
    ).lease
    second = _binding(first.default_base_commit, version=2)
    service.register(second)
    service.activate(
        second.binding_id,
        actor_ref="operator:c1",
        activated_at="2026-08-15T17:55:00+00:00",
    )
    connection.execute(
        """
        INSERT INTO repository_credential_issuance_records (
            credential_id, token_digest, binding_id, binding_version,
            repository_id, session_id, agent_member_id, workspace_generation,
            capability_lease_id, protocols_json, ref_classes_json,
            claims_digest, issued_at, expires_at, revoked_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            "credential_binding_reference",
            f"sha256:{'1' * 64}",
            first.binding_id,
            first.binding_version,
            first.repository_id,
            legacy.session_id,
            agent.member_id,
            1,
            active_lease.lease_id,
            '["git_write"]',
            '["private"]',
            f"sha256:{'2' * 64}",
            "2026-08-15T17:56:00+00:00",
            "2026-08-15T18:01:00+00:00",
            "2026-08-15T17:57:00+00:00",
        ),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="cannot be retired"):
        connection.execute(
            """
            INSERT INTO project_repository_binding_retirement_receipts (
                receipt_id, binding_id, binding_version, project_id,
                reference_audit_digest, receipt_digest, receipt_json,
                created_at, created_by
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "retire_credential_referenced",
                first.binding_id,
                first.binding_version,
                first.project_id,
                f"sha256:{'3' * 64}",
                f"sha256:{'4' * 64}",
                "{}",
                "2026-08-15T18:02:00+00:00",
                "operator:c1",
            ),
        )
