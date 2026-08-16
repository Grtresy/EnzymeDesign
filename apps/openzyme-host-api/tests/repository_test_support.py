from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import json
from pathlib import Path
import shutil
import subprocess
from urllib.parse import urlsplit

from openzyme_core import DurableRepositoryRootManager
from openzyme_core import IssuedRepositoryCredential
from openzyme_core import RepositoryCredentialBroker
from openzyme_core import RepositoryCredentialProtocol
from openzyme_core import RepositoryPrivateNamespaceHoldKind
from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_core import RepositoryRootBoundary
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core.agent_capability_service import AgentCapabilityLeaseService
from openzyme_core.agent_capability_service import AgentWorkspaceReadinessProof
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import GitObjectFormat
from openzyme_domain import GitLfsBindingPolicy
from openzyme_domain import GitLfsPathRepresentation
from openzyme_domain import GitLfsPathRule
from openzyme_domain import GitLfsRetentionClass
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryRefClass
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_domain import SessionRepositoryBindingPin
from openzyme_domain import canonical_capability_digest
from openzyme_host_api.repository_service_preflight import (
    build_repository_binding_inventory,
)
from openzyme_host_api.repository_transport import RepositoryTransportDependencies
from openzyme_runtime import RepositoryServiceSettings


@dataclass(frozen=True, slots=True)
class RepositoryTestFixture:
    settings: RepositoryServiceSettings
    roots: DurableRepositoryRootManager
    provider: SQLiteRepositoryProvider
    dependencies: RepositoryTransportDependencies
    binding: ProjectRepositoryBinding
    session: Session
    pin: SessionRepositoryBindingPin
    source_repository: Path
    credential: IssuedRepositoryCredential


@dataclass(frozen=True, slots=True)
class _RepositoryTestReadinessProvider:
    observed_at: str
    provider_id: str = "test.repository-workspace@1"

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
            observed_at=self.observed_at,
        )


def _required_executable(name: str) -> Path:
    executable = shutil.which(name)
    if executable is None:
        raise RuntimeError(f"repository tests require {name}")
    return Path(executable).resolve(strict=True)


def _settings(root: Path, *, https_origin: str) -> RepositoryServiceSettings:
    git_root = root / "git"
    lfs_root = root / "lfs"
    backup_root = root / "backup"
    for path in (git_root, lfs_root, backup_root):
        path.mkdir(parents=True)
        path.chmod(0o700)
    signing_key = root / "repository-token.key"
    signing_key.write_bytes(b"repository-native-test-key" * 4)
    signing_key.chmod(0o600)
    openssl = _required_executable("openssl")
    tls_key = root / "localhost.key"
    tls_certificate = root / "localhost.crt"
    subprocess.run(
        (
            str(openssl),
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tls_key),
            "-out",
            str(tls_certificate),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1,IP:::1",
        ),
        check=True,
        capture_output=True,
    )
    tls_key.chmod(0o600)
    git = _required_executable("git")
    git_exec_path = subprocess.run(
        (str(git), "--exec-path"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    parsed = urlsplit(https_origin)
    if parsed.hostname != "localhost":
        raise ValueError("repository test HTTPS origin must use localhost")
    return RepositoryServiceSettings(
        https_origin=https_origin,
        bare_repository_root=git_root,
        lfs_object_root=lfs_root,
        backup_root=backup_root,
        credential_signing_key_file=signing_key,
        tls_certificate_file=tls_certificate,
        tls_private_key_file=tls_key,
        binding_inventory_file=root / "bindings.json",
        git_executable=git,
        git_lfs_executable=_required_executable("git-lfs"),
        git_http_backend=(Path(git_exec_path) / "git-http-backend").resolve(
            strict=True
        ),
        credential_ttl_seconds=600,
    )


def _source(root: Path, *, git: Path) -> tuple[Path, str]:
    source = root / "source"
    source.mkdir()
    subprocess.run((str(git), "init", str(source)), check=True, capture_output=True)
    subprocess.run(
        (str(git), "-C", str(source), "config", "user.name", "C1 Test"),
        check=True,
    )
    subprocess.run(
        (str(git), "-C", str(source), "config", "user.email", "c1@test"),
        check=True,
    )
    (source / "README.md").write_text("repository native transport\n", encoding="utf-8")
    subprocess.run((str(git), "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        (str(git), "-C", str(source), "commit", "-m", "seed"),
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        (str(git), "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, commit


def _binding(commit: str, *, https_origin: str) -> ProjectRepositoryBinding:
    git_endpoint = f"{https_origin}/repositories/repo_openzyme.git"
    lfs_policy = build_git_lfs_test_policy(https_origin=https_origin)
    return ProjectRepositoryBinding.create(
        binding_id="binding_repository_test_v1",
        project_id="openzyme",
        binding_version=1,
        repository_id="repo_openzyme",
        internal_git_service_id="git_openzyme_local",
        internal_git_endpoint=git_endpoint,
        lfs_service_id="lfs_openzyme_local",
        lfs_endpoint=f"{git_endpoint}/info/lfs",
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
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=lfs_policy.policy_digest,
        created_at="2026-08-15T18:00:00+00:00",
        created_by="operator:c1",
    )


def build_git_lfs_test_policy(*, https_origin: str) -> GitLfsBindingPolicy:
    git_endpoint = f"{https_origin}/repositories/repo_openzyme.git"
    return GitLfsBindingPolicy.create(
        binding_id="binding_repository_test_v1",
        binding_version=1,
        repository_id="repo_openzyme",
        lfs_service_id="lfs_openzyme_local",
        lfs_endpoint=f"{git_endpoint}/info/lfs",
        object_format="sha256",
        path_rules=(
            GitLfsPathRule(
                rule_id="large_binary",
                pattern="*.bin",
                representation=GitLfsPathRepresentation.LFS_REQUIRED,
            ),
        ),
        ordinary_blob_threshold_bytes=1024 * 1024,
        max_object_bytes=64 * 1024 * 1024,
        max_workspace_bytes=256 * 1024 * 1024,
        max_repository_bytes=1024 * 1024 * 1024,
        published_retention_class=GitLfsRetentionClass.PUBLISHED,
        private_retention_class=GitLfsRetentionClass.PRIVATE,
        private_retention_seconds=86_400,
        policy_version="repository-policy-v1",
        created_at="2026-08-15T18:00:00+00:00",
        created_by="operator:c5",
    )


def issue_repository_credential(
    fixture: RepositoryTestFixture,
    *,
    agent_member_id: str,
    role: str,
    workspace_generation: int,
) -> IssuedRepositoryCredential:
    return _issue_repository_credential(
        provider=fixture.provider,
        settings=fixture.settings,
        roots=fixture.roots,
        binding=fixture.binding,
        pin=fixture.pin,
        session=fixture.session,
        agent_member_id=agent_member_id,
        role=role,
        workspace_generation=workspace_generation,
    )


def _issue_repository_credential(
    *,
    provider: SQLiteRepositoryProvider,
    settings: RepositoryServiceSettings,
    roots: DurableRepositoryRootManager,
    binding: ProjectRepositoryBinding,
    pin: SessionRepositoryBindingPin,
    session: Session,
    agent_member_id: str,
    role: str,
    workspace_generation: int,
) -> IssuedRepositoryCredential:
    now = datetime.now(tz=UTC)
    with provider.write() as scope:
        agent = AgentMember(
            member_id=agent_member_id,
            agent_id=agent_member_id,
            session_id=session.session_id,
            lane_id=None,
            task_id=None,
            name=agent_member_id,
            role=role,
            status=AgentMemberStatus.IDLE,
            parent_agent_id=None,
            created_at=now.isoformat(),
            updated_at=now.isoformat(),
            runtime_state="idle",
            idle_since=now.isoformat(),
        )
        existing_agent = scope.repositories.agents.get(
            session.session_id,
            agent.agent_id,
        )
        if existing_agent is None:
            scope.repositories.agents.save(agent)
        elif (
            existing_agent.member_id != agent_member_id
            or existing_agent.role != role
            or existing_agent.parent_agent_id is not None
        ):
            raise RuntimeError("repository test agent identity drifted")
        readiness_provider = _RepositoryTestReadinessProvider(now.isoformat())
        capability_service = AgentCapabilityLeaseService(
            scope.repositories,
            readiness_providers={
                readiness_provider.provider_id: readiness_provider,
            },
        )
        issuance = capability_service.reserve_and_issue(
            session_id=session.session_id,
            agent_id=agent.agent_id,
            idempotency_key=(
                f"repository-test:{agent_member_id}:g{workspace_generation}"
            ),
            actor_ref="test:repository-credential-issue",
            workspace_generation=workspace_generation,
        )
        lease = capability_service.activate_with_provider(
            lease_id=issuance.lease.lease_id,
            provider_id=readiness_provider.provider_id,
            actor_ref="test:repository-credential-activate",
        ).lease
        retention = RepositoryPrivateNamespaceRetentionService(
            scope.connection,
            roots,
        )
        namespace_row = scope.connection.execute(
            """
            SELECT namespace_id, status
            FROM repository_private_namespace_records
            WHERE session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (session.session_id, agent_member_id, workspace_generation),
        ).fetchone()
        if namespace_row is None:
            namespace = retention.open_namespace(
                binding=binding,
                pin=pin,
                agent_member_id=agent_member_id,
                workspace_generation=workspace_generation,
                retention_deadline=(now + timedelta(days=1)).isoformat(),
                opened_at=now.isoformat(),
                namespace_id=(
                    f"namespace_{session.session_id}_{agent_member_id}_"
                    f"{workspace_generation}"
                ),
            )
            namespace_id = namespace.namespace_id
        else:
            if namespace_row["status"] != "open":
                raise RuntimeError("repository test namespace is not open")
            namespace_id = str(namespace_row["namespace_id"])
        active_hold = scope.connection.execute(
            """
            SELECT hold_id
            FROM repository_private_namespace_holds
            WHERE namespace_id = ?
              AND hold_kind = 'active_capability_lease'
              AND owner_ref = ?
              AND released_at IS NULL
            """,
            (namespace_id, lease.lease_id),
        ).fetchone()
        if active_hold is None:
            retention.add_hold(
                namespace_id,
                hold_kind=(RepositoryPrivateNamespaceHoldKind.ACTIVE_CAPABILITY_LEASE),
                owner_ref=lease.lease_id,
                created_at=now.isoformat(),
                hold_id=f"hold_{namespace_id}_{lease.lease_id}",
            )
    with provider.connection_scope() as scope:
        return RepositoryCredentialBroker(
            connection=scope.connection,
            signing_key_path=settings.credential_signing_key_file,
            credential_ttl_seconds=settings.credential_ttl_seconds,
        ).issue(
            binding=binding,
            pin=pin,
            capability_lease_id=lease.lease_id,
            expected_agent_member_id=lease.agent_member_id,
            expected_agent_id=lease.agent_id,
            expected_workspace_generation=lease.workspace_generation,
            protocols=(
                RepositoryCredentialProtocol.GIT_READ,
                RepositoryCredentialProtocol.GIT_WRITE,
                RepositoryCredentialProtocol.LFS_READ,
                RepositoryCredentialProtocol.LFS_WRITE,
            ),
            ref_classes=(RepositoryRefClass.READ, RepositoryRefClass.PRIVATE),
            now=now,
        )


def build_repository_test_fixture(
    root: Path,
    *,
    https_origin: str,
) -> RepositoryTestFixture:
    service_root = root / "service"
    settings = _settings(service_root, https_origin=https_origin)
    checkout = root / "checkout"
    cwd = root / "cwd"
    checkout.mkdir()
    cwd.mkdir()
    boundary = RepositoryRootBoundary(
        host_checkout=checkout,
        process_cwd=cwd,
        temporary_roots=(),
    )
    roots = DurableRepositoryRootManager(settings, boundary)
    source, commit = _source(root, git=settings.git_executable)
    binding = _binding(commit, https_origin=https_origin)
    roots.create_bare_repository(binding)
    roots.import_exact_commit_from_repository(
        binding,
        source_repository=source,
        source_commit=commit,
    )
    provider = SQLiteRepositoryProvider(str(root / "control-plane.sqlite3"))
    now = datetime.now(tz=UTC)
    with provider.write() as scope:
        repositories = scope.repositories
        repositories.project_repository_bindings.add(binding)
        repositories.git_lfs.add_policy(
            build_git_lfs_test_policy(https_origin=https_origin)
        )
        repositories.project_repository_bindings.activate(
            binding.binding_id,
            actor_ref="operator:c1",
            activated_at=now.isoformat(),
        )
        session = Session.create(
            "sess_repository_test",
            "openzyme",
            "Repository test",
            "Exercise native Git and LFS protocols",
        )
        repositories.sessions.save(session)
        pin = SessionRepositoryBindingPin(
            session_id=session.session_id,
            project_id=binding.project_id,
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            resolved_base_commit=binding.default_base_commit,
            binding_canonical_digest=binding.canonical_digest,
            pinned_at=now.isoformat(),
        )
        repositories.session_repository_binding_pins.add(pin)
    settings.binding_inventory_file.write_text(
        json.dumps(
            build_repository_binding_inventory((binding,)),
            sort_keys=True,
            separators=(",", ":"),
        ),
        encoding="utf-8",
    )
    settings.binding_inventory_file.chmod(0o600)
    credential = _issue_repository_credential(
        provider=provider,
        settings=settings,
        roots=roots,
        binding=binding,
        pin=pin,
        session=session,
        agent_member_id="agent:executor",
        role="executor",
        workspace_generation=1,
    )
    return RepositoryTestFixture(
        settings=settings,
        roots=roots,
        provider=provider,
        dependencies=RepositoryTransportDependencies(
            repository_provider=provider,
            settings=settings,
            root_boundary=boundary,
        ),
        binding=binding,
        session=session,
        pin=pin,
        source_repository=source,
        credential=credential,
    )


__all__ = [
    "RepositoryTestFixture",
    "build_repository_test_fixture",
    "build_git_lfs_test_policy",
    "issue_repository_credential",
]
