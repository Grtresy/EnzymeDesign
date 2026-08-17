from __future__ import annotations

import json
import sqlite3
from dataclasses import replace
from typing import Any
from typing import cast

import pytest

from openzyme_core import AgentCapabilityLeaseService
from openzyme_core import AgentCapabilityError
from openzyme_core import AgentCapsuleAdmissionError
from openzyme_core import AgentCapsuleImageQualification
from openzyme_core import AgentCapsuleProcessResult
from openzyme_core import AgentCapsuleRuntimeService
from openzyme_core import AgentCapsuleRuntimeError
from openzyme_core import AgentProcessCredentialRequest
from openzyme_core import AgentProcessCredentialRouter
from openzyme_core import IssuedAgentProcessCredential
from openzyme_core import PodmanAgentCapsuleProcessRunner
from openzyme_core import CapsuleCommandResult
from openzyme_core import AgentGitWorkspaceProvisioner
from openzyme_core import AgentGitWorkspaceProvisioningError
from openzyme_core import AgentGitWorkspaceGenerationService
from openzyme_core import AgentGitWorkspaceRecoveryError
from openzyme_core import AgentGitWorkspaceRecoveryService
from openzyme_core import AgentWorkspaceCloneResult
from openzyme_core import AgentWorkspaceVolumeAllocator
from openzyme_core import AgentWorkspaceVolumeFact
from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_core import RevisionPathReferenceService
from openzyme_core import RepositoryProvisionCredentialBroker
from openzyme_core import FileWorkspaceProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import TaskBoardService
from openzyme_core import TaskFinishCommand
from openzyme_core import WorkspaceCheckpointError
from openzyme_core import WorkspaceCheckpointService
from openzyme_core import WorkspacePublicationError
from openzyme_core import WorkspacePublicationService
from openzyme_core import WorkspacePublishCommand
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import MemoryEventBus
from openzyme_core import NativeRevisionPathFetchError
from openzyme_core import NativeRevisionPathFetchService
from openzyme_core import RestoreFocus
from openzyme_core import register_report_draft_tools
from openzyme_core import OptimisticStateConflictError
from openzyme_core import load_agent_capsule_image_manifest
from openzyme_core import AgentGitWorkspaceConflictError
from openzyme_core import AgentGitWorkspaceLifecycleService
from openzyme_core import AgentGitWorkspaceTransitionError
from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import private_ref_prefix
from openzyme_core import agent_capsule_tools_available
from openzyme_domain import AgentGitDirectoryKind
from openzyme_domain import AgentGitWorkspaceBlockerCode
from openzyme_domain import AgentGitWorkspaceIdentityDriftKind
from openzyme_domain import AgentGitWorkspaceObservation
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import ProtocolFileHandoff
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_domain import SessionRepositoryBindingPin
from openzyme_domain import AgentWorkspaceStateObservation
from openzyme_domain import PrivateRefAdvanceKind
from openzyme_domain import RemotePrivateRefObservation
from openzyme_domain import WorkspaceCheckpointProofInput
from openzyme_domain import WorkspaceDirtyState
from openzyme_domain import WorkspaceFormalBoundary
from openzyme_domain import PublicationManifestEntry
from openzyme_domain import PublicationManifestObjectKind
from openzyme_domain import WorkspacePublicationManifest
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import TaskStatus
from openzyme_domain import TaskEvidenceKind
from openzyme_domain import TaskEvidenceRef
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxImageRecord
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus


BASE_COMMIT = "8ae3d73b3054f2058ff33ea183f62c811b9272a3"
REPOSITORY_POLICY_DIGEST = f"sha256:{'1' * 64}"
IMAGE_REF = "localhost/openzyme-agent-capsule@sha256:" + "a" * 64


def _binding() -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="binding_openzyme_v1",
        project_id="openzyme",
        binding_version=1,
        repository_id="repo_openzyme",
        internal_git_service_id="git_openzyme_local",
        internal_git_endpoint=(
            "https://localhost:8443/repositories/repo_openzyme.git"
        ),
        lfs_service_id="lfs_openzyme_local",
        lfs_endpoint=(
            "https://localhost:8443/repositories/repo_openzyme.git/info/lfs"
        ),
        upstream_identity="github_grtresy_enzymedesign",
        upstream_url="git@github.com:Grtresy/EnzymeDesign.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/dev",
        default_base_commit=BASE_COMMIT,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=REPOSITORY_POLICY_DIGEST,
        created_at="2026-08-16T01:00:00+00:00",
        created_by="operator:c3-test",
    )


def _member(
    member_id: str,
    agent_id: str,
    *,
    name: str,
    role: str = "master",
    parent_agent_id: str | None = None,
) -> AgentMember:
    return AgentMember(
        member_id=member_id,
        agent_id=agent_id,
        session_id="session_1",
        lane_id=None,
        task_id=None,
        name=name,
        role=role,
        status=AgentMemberStatus.ACTIVE,
        parent_agent_id=parent_agent_id,
        created_at="2026-08-16T01:00:00+00:00",
        updated_at="2026-08-16T01:00:00+00:00",
    )


def _environment() -> tuple[
    sqlite3.Connection,
    CoreRepositories,
    ProjectRepositoryBinding,
    AgentCapabilityLeaseService,
    AgentGitWorkspaceLifecycleService,
]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    binding = _binding()
    repositories.project_repository_bindings.add(binding)
    repositories.project_repository_bindings.activate(
        binding.binding_id,
        actor_ref="operator:c3-test",
        activated_at="2026-08-16T01:01:00+00:00",
    )
    repositories.sessions.save(
        Session.create(
            session_id="session_1",
            project_id="openzyme",
            title="Independent Git workspace",
            objective="Bind an exact clone to one agent generation",
        )
    )
    repositories.session_repository_binding_pins.add(
        SessionRepositoryBindingPin(
            session_id="session_1",
            project_id="openzyme",
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            repository_id=binding.repository_id,
            resolved_base_commit=BASE_COMMIT,
            binding_canonical_digest=binding.canonical_digest,
            pinned_at="2026-08-16T01:02:00+00:00",
        )
    )
    repositories.agents.save(_member("member_1", "agent:master", name="master"))
    capability_service = AgentCapabilityLeaseService(repositories)
    capability_service.reserve_and_issue(
        session_id="session_1",
        agent_id="agent:master",
        idempotency_key="issue-master-g1",
        actor_ref="host:c3-test",
    )
    return (
        connection,
        repositories,
        binding,
        capability_service,
        AgentGitWorkspaceLifecycleService(repositories),
    )


def _create_workspace(
    service: AgentGitWorkspaceLifecycleService,
    *,
    member_id: str = "member_1",
    generation: int = 1,
    volume_id: str = "volume_session_1_member_1_g1",
):
    return service.create_provisioning(
        session_id="session_1",
        agent_member_id=member_id,
        workspace_generation=generation,
        workspace_id=f"workspace_{member_id}_g{generation}",
        volume_id=volume_id,
        clone_logical_root="/workspace/repository",
        image_qualification=AgentCapsuleImageQualification(
            image_ref=IMAGE_REF,
            image_manifest_digest=f"sha256:{'b' * 64}",
            qualification_output_digest=f"sha256:{'c' * 64}",
            qualified_at="2026-08-16T01:02:30+00:00",
        ),
        created_at="2026-08-16T01:03:00+00:00",
    )


def _observation(workspace, **overrides: object) -> AgentGitWorkspaceObservation:
    values: dict[str, object] = {
        "workspace_id": workspace.workspace_id,
        "session_id": workspace.session_id,
        "agent_member_id": workspace.agent_member_id,
        "agent_id": workspace.agent_id,
        "workspace_generation": workspace.workspace_generation,
        "volume_id": workspace.volume_id,
        "clone_logical_root": workspace.clone_logical_root,
        "git_directory_kind": AgentGitDirectoryKind.INDEPENDENT,
        "internal_git_service_id": workspace.internal_git_service_id,
        "internal_git_endpoint": workspace.internal_git_endpoint,
        "repository_id": workspace.repository_id,
        "object_format": workspace.object_format,
        "base_commit": workspace.base_commit,
        "head_commit": workspace.base_commit,
        "head_tree": "1" * 40,
        "head_readable": True,
        "private_ref_namespace": workspace.private_ref_namespace,
        "repository_policy_digest": workspace.repository_policy_digest,
        "capability_policy_digest": workspace.capability_policy_digest,
        "observed_at": "2026-08-16T01:04:00+00:00",
    }
    values.update(overrides)
    return AgentGitWorkspaceObservation(**values)  # type: ignore[arg-type]


def _open_namespace(
    connection: sqlite3.Connection,
    binding: ProjectRepositoryBinding,
) -> None:
    connection.execute(
        """
        INSERT INTO repository_private_namespace_records (
            namespace_id,
            binding_id,
            binding_version,
            session_id,
            agent_member_id,
            workspace_generation,
            namespace_prefix,
            status,
            retention_deadline,
            opened_at,
            closed_at,
            retired_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 'open', ?, ?, NULL, NULL)
        """,
        (
            "namespace_member_1_g1",
            binding.binding_id,
            binding.binding_version,
            "session_1",
            "member_1",
            1,
            private_ref_prefix(
                binding,
                session_id="session_1",
                agent_member_id="member_1",
                workspace_generation=1,
            ),
            "2027-08-16T01:04:00+00:00",
            "2026-08-16T01:04:00+00:00",
        ),
    )
    connection.commit()


def test_workspace_generation_is_unique_and_replay_is_identity_exact() -> None:
    _, _, _, _, service = _environment()
    workspace = _create_workspace(service)

    assert _create_workspace(service) == workspace
    with pytest.raises(AgentGitWorkspaceConflictError):
        _create_workspace(service, volume_id="another_volume")


def test_volume_cannot_be_relabelled_across_agents() -> None:
    _, repositories, _, capability_service, service = _environment()
    first = _create_workspace(service)
    repositories.agents.save(_member("member_2", "agent:second", name="second"))
    capability_service.reserve_and_issue(
        session_id="session_1",
        agent_id="agent:second",
        idempotency_key="issue-second-g1",
        actor_ref="host:c3-test",
    )

    with pytest.raises(sqlite3.IntegrityError, match="UNIQUE"):
        _create_workspace(
            service,
            member_id="member_2",
            volume_id=first.volume_id,
        )


def test_invalid_lifecycle_transition_is_rejected() -> None:
    _, _, _, _, service = _environment()
    workspace = _create_workspace(service)
    blocked = service.block(
        workspace_id=workspace.workspace_id,
        blocker_code=AgentGitWorkspaceBlockerCode.CLONE_FAILED,
        blocker_detail={"native_exit": 128},
        blocked_at="2026-08-16T01:04:00+00:00",
    )
    assert blocked.status is AgentGitWorkspaceStatus.BLOCKED

    with pytest.raises(AgentGitWorkspaceTransitionError):
        service.block(
            workspace_id=workspace.workspace_id,
            blocker_code=AgentGitWorkspaceBlockerCode.CLONE_FAILED,
            blocker_detail={"native_exit": 128},
        )


def test_restore_comparator_reports_exact_identity_drift_without_mutation() -> None:
    _, repositories, _, _, service = _environment()
    workspace = _create_workspace(service)
    comparison = service.compare_restore(
        workspace_id=workspace.workspace_id,
        observation=_observation(
            workspace,
            volume_id="volume_owned_by_another_agent",
            internal_git_endpoint="https://localhost:9443/repositories/other.git",
        ),
    )

    assert comparison.matches is False
    assert comparison.drift == (
        AgentGitWorkspaceIdentityDriftKind.VOLUME,
        AgentGitWorkspaceIdentityDriftKind.REMOTE_IDENTITY,
    )
    assert repositories.agent_git_workspaces.get(workspace.workspace_id) == workspace


def test_readiness_requires_c2_atomic_transaction_and_rolls_back_as_one_unit() -> None:
    connection, repositories, binding, _, service = _environment()
    workspace = _create_workspace(service)
    observation = _observation(workspace)
    _open_namespace(connection, binding)

    with pytest.raises(AgentGitWorkspaceTransitionError, match="atomic"):
        service.stage_ready_in_current_transaction(
            workspace_id=workspace.workspace_id,
            observation=observation,
        )

    class RollbackProbe(RuntimeError):
        pass

    with pytest.raises(RollbackProbe):
        with repositories.atomic(prefix="c3_readiness_probe"):
            ready = service.stage_ready_in_current_transaction(
                workspace_id=workspace.workspace_id,
                observation=observation,
            )
            assert ready.status is AgentGitWorkspaceStatus.READY
            raise RollbackProbe

    assert repositories.agent_git_workspaces.get(workspace.workspace_id) == workspace


def test_explicit_replacement_preserves_old_workspace_identity() -> None:
    _, repositories, _, capability_service, service = _environment()
    workspace = _create_workspace(service)
    frozen = service.freeze(
        workspace_id=workspace.workspace_id,
        reason="explicit_generation_replacement",
        frozen_at="2026-08-16T01:05:00+00:00",
    )

    with pytest.raises(AgentGitWorkspaceTransitionError, match="revoked"):
        service.mark_replaced(
            workspace_id=workspace.workspace_id,
            replaced_by_generation=2,
        )

    capability_service.replace_workspace_generation(
        workspace.capability_lease_id,
        idempotency_key="issue-master-g2",
        actor_ref="operator:c3-test",
    )
    replaced = service.mark_replaced(
        workspace_id=workspace.workspace_id,
        replaced_by_generation=2,
        replaced_at="2026-08-16T01:06:00+00:00",
    )

    assert replaced.status is AgentGitWorkspaceStatus.REPLACED
    assert replaced.workspace_identity_digest == frozen.workspace_identity_digest
    assert replaced.volume_id == workspace.volume_id
    assert repositories.agent_git_workspaces.list_by_agent(
        session_id="session_1",
        agent_member_id="member_1",
    ) == [replaced]


class _MemoryVolumeBackend:
    def __init__(self) -> None:
        self.volumes: dict[str, AgentWorkspaceVolumeFact] = {}
        self.create_count = 0

    def inspect(self, volume_id: str) -> AgentWorkspaceVolumeFact | None:
        return self.volumes.get(volume_id)

    def create(
        self,
        volume_id: str,
        *,
        labels: tuple[tuple[str, str], ...],
    ) -> AgentWorkspaceVolumeFact:
        self.create_count += 1
        fact = AgentWorkspaceVolumeFact(volume_id=volume_id, labels=labels)
        self.volumes[volume_id] = fact
        return fact


class _CloneRunner:
    def __init__(self, *, returncode: int = 0, remote_override: str | None = None):
        self.returncode = returncode
        self.remote_override = remote_override
        self.calls: list[tuple[str, str]] = []

    def clone_exact_base(self, *, workspace, credential_token: str):
        self.calls.append((workspace.workspace_id, credential_token))
        if self.returncode != 0:
            return AgentWorkspaceCloneResult(
                returncode=self.returncode,
                stdout="",
                stderr="fatal: native clone failed",
            )
        return AgentWorkspaceCloneResult(
            returncode=0,
            stdout="identity observed",
            stderr="",
            head_commit=workspace.base_commit,
            head_tree="1" * workspace.object_format.commit_hex_length,
            object_format=workspace.object_format,
            remote_endpoint=(
                self.remote_override or workspace.internal_git_endpoint
            ),
            independent_git_directory=True,
        )


def _provisioner(
    tmp_path,
    repositories: CoreRepositories,
    clone_runner: _CloneRunner,
    volume_backend: _MemoryVolumeBackend,
) -> AgentGitWorkspaceProvisioner:
    signing_key = tmp_path / "repository-signing.key"
    signing_key.write_bytes(b"c3-test-signing-key-material-32-bytes-minimum")
    signing_key.chmod(0o600)
    return AgentGitWorkspaceProvisioner(
        repositories=repositories,
        volume_allocator=AgentWorkspaceVolumeAllocator(volume_backend),
        clone_runner=clone_runner,
        provision_credentials=RepositoryProvisionCredentialBroker(
            connection=repositories.tasks.connection,
            signing_key_path=signing_key,
            credential_ttl_seconds=60,
        ),
        namespace_retention=RepositoryPrivateNamespaceRetentionService(
            connection=repositories.tasks.connection,
            roots=cast(Any, object()),
        ),
    )


def _qualified_image() -> AgentCapsuleImageQualification:
    manifest = load_agent_capsule_image_manifest()
    return AgentCapsuleImageQualification(
        image_ref=IMAGE_REF,
        image_manifest_digest=manifest.manifest_digest,
        qualification_output_digest=f"sha256:{'c' * 64}",
        qualified_at="2026-08-16T01:02:30+00:00",
    )


def test_provisioner_activates_two_agent_clones_with_distinct_full_git_volumes(
    tmp_path,
) -> None:
    _, repositories, _, capability_service, _ = _environment()
    volumes = _MemoryVolumeBackend()
    clones = _CloneRunner()
    provisioner = _provisioner(tmp_path, repositories, clones, volumes)
    first = provisioner.provision_and_activate(
        session_id="session_1",
        agent_member_id="member_1",
        workspace_generation=1,
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        actor_ref="host:c3-test",
        workspace_id="workspace_member_1_g1",
    )
    repositories.agents.save(
        _member(
            "member_2",
            "agent:researcher",
            name="researcher",
            role="researcher",
            parent_agent_id="agent:master",
        )
    )
    capability_service.reserve_and_issue(
        session_id="session_1",
        agent_id="agent:researcher",
        idempotency_key="issue-researcher-g1",
        actor_ref="host:c3-test",
        parent_lease_id=first.lease.lease_id,
    )
    second = provisioner.provision_and_activate(
        session_id="session_1",
        agent_member_id="member_2",
        workspace_generation=1,
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        actor_ref="host:c3-test",
        workspace_id="workspace_member_2_g1",
    )

    first_workspace = repositories.agent_git_workspaces.get(
        "workspace_member_1_g1"
    )
    second_workspace = repositories.agent_git_workspaces.get(
        "workspace_member_2_g1"
    )
    assert first_workspace is not None and second_workspace is not None
    assert first_workspace.status is AgentGitWorkspaceStatus.READY
    assert second_workspace.status is AgentGitWorkspaceStatus.READY
    assert first_workspace.base_commit == second_workspace.base_commit
    assert first_workspace.volume_id != second_workspace.volume_id
    assert first_workspace.workspace_identity_digest != (
        second_workspace.workspace_identity_digest
    )
    assert first.lease.status.value == "active"
    assert second.lease.status.value == "active"
    assert volumes.create_count == 2
    assert len(clones.calls) == 2
    assert all(token.startswith("ozprovision1.") for _, token in clones.calls)


def test_provisioner_remote_drift_blocks_without_lease_activation_or_fallback(
    tmp_path,
) -> None:
    _, repositories, _, _, _ = _environment()
    volumes = _MemoryVolumeBackend()
    clones = _CloneRunner(
        remote_override="https://localhost:9443/repositories/other.git"
    )
    provisioner = _provisioner(tmp_path, repositories, clones, volumes)

    with pytest.raises(AgentGitWorkspaceProvisioningError, match="drifted"):
        provisioner.provision_and_activate(
            session_id="session_1",
            agent_member_id="member_1",
            workspace_generation=1,
            image_qualification=_qualified_image(),
            namespace_retention_deadline="2027-08-16T01:00:00+00:00",
            actor_ref="host:c3-test",
            workspace_id="workspace_member_1_g1",
        )

    workspace = repositories.agent_git_workspaces.get("workspace_member_1_g1")
    lease = repositories.agent_capability_leases.get_by_generation(
        session_id="session_1",
        agent_member_id="member_1",
        workspace_generation=1,
    )
    assert workspace is not None
    assert workspace.status is AgentGitWorkspaceStatus.BLOCKED
    assert workspace.blocker_code is (
        AgentGitWorkspaceBlockerCode.REMOTE_IDENTITY_DRIFT
    )
    assert lease is not None and lease.status.value == "pending_workspace"
    assert volumes.create_count == 1
    assert len(clones.calls) == 1


def test_atomic_activation_failure_rolls_back_ready_lease_and_blocker_clear(
    tmp_path,
    monkeypatch,
) -> None:
    _, repositories, _, _, _ = _environment()
    volumes = _MemoryVolumeBackend()
    clones = _CloneRunner()
    provisioner = _provisioner(tmp_path, repositories, clones, volumes)

    def fail_lease_update(*args, **kwargs):
        del args, kwargs
        raise RuntimeError("injected atomic lease persistence failure")

    monkeypatch.setattr(
        type(repositories.agent_capability_leases),
        "update",
        fail_lease_update,
    )
    with pytest.raises(RuntimeError, match="injected atomic"):
        provisioner.provision_and_activate(
            session_id="session_1",
            agent_member_id="member_1",
            workspace_generation=1,
            image_qualification=_qualified_image(),
            namespace_retention_deadline="2027-08-16T01:00:00+00:00",
            actor_ref="host:c3-test",
            workspace_id="workspace_member_1_g1",
        )

    workspace = repositories.agent_git_workspaces.get("workspace_member_1_g1")
    reservation = (
        repositories.agent_workspace_generation_reservations.get_by_generation(
            session_id="session_1",
            agent_member_id="member_1",
            workspace_generation=1,
        )
    )
    lease = repositories.agent_capability_leases.get_by_generation(
        session_id="session_1",
        agent_member_id="member_1",
        workspace_generation=1,
    )
    agent = repositories.agents.get_by_member_id("member_1")
    assert workspace is not None and workspace.status is AgentGitWorkspaceStatus.BLOCKED
    assert reservation is not None and reservation.status.value == "reserved"
    assert lease is not None and lease.status.value == "pending_workspace"
    assert agent is not None
    assert (agent.status.value, agent.runtime_state) == (
        "blocked",
        "provisioning_required",
    )


def test_native_clone_failure_is_single_attempt_and_keeps_partial_volume(
    tmp_path,
) -> None:
    _, repositories, _, _, _ = _environment()
    volumes = _MemoryVolumeBackend()
    clones = _CloneRunner(returncode=128)
    provisioner = _provisioner(tmp_path, repositories, clones, volumes)

    with pytest.raises(AgentGitWorkspaceProvisioningError, match="native exit 128"):
        provisioner.provision_and_activate(
            session_id="session_1",
            agent_member_id="member_1",
            workspace_generation=1,
            image_qualification=_qualified_image(),
            namespace_retention_deadline="2027-08-16T01:00:00+00:00",
            actor_ref="host:c3-test",
            workspace_id="workspace_member_1_g1",
        )

    workspace = repositories.agent_git_workspaces.get("workspace_member_1_g1")
    assert workspace is not None
    assert workspace.status is AgentGitWorkspaceStatus.BLOCKED
    assert workspace.blocker_code is AgentGitWorkspaceBlockerCode.CLONE_FAILED
    assert workspace.volume_id in volumes.volumes
    assert len(clones.calls) == 1


def test_pending_generation_mismatch_never_starts_clone_or_creates_fallback(
    tmp_path,
) -> None:
    _, repositories, _, _, _ = _environment()
    volumes = _MemoryVolumeBackend()
    clones = _CloneRunner()
    provisioner = _provisioner(tmp_path, repositories, clones, volumes)

    with pytest.raises(AgentGitWorkspaceConflictError, match="reserved generation"):
        provisioner.provision_and_activate(
            session_id="session_1",
            agent_member_id="member_1",
            workspace_generation=2,
            image_qualification=_qualified_image(),
            namespace_retention_deadline="2027-08-16T01:00:00+00:00",
            actor_ref="host:c3-test",
            workspace_id="workspace_member_1_g2",
        )

    assert clones.calls == []
    assert repositories.agent_git_workspaces.get("workspace_member_1_g2") is None
    assert len(volumes.volumes) == 1


class _ProcessRunner:
    def __init__(
        self,
        result: AgentCapsuleProcessResult | None = None,
    ) -> None:
        self.result = result or AgentCapsuleProcessResult(0, "ok", "")
        self.calls: list[dict[str, object]] = []

    def run(
        self,
        *,
        workspace,
        argv,
        credential_environment,
        timeout_seconds,
    ):
        self.calls.append(
            {
                "workspace": workspace,
                "argv": argv,
                "credential_environment": credential_environment,
                "timeout_seconds": timeout_seconds,
            }
        )
        return self.result


class _RecordingNativeFetchRuntime:
    def __init__(self, *, returncode: int = 0) -> None:
        self.returncode = returncode
        self.requests: list[AgentProcessCredentialRequest] = []

    def execute(self, *, credential_request, argv, **kwargs):
        del kwargs
        self.requests.append(credential_request)
        ref_id = argv[-5]
        return {
            "returncode": self.returncode,
            "stdout": (
                f"OPENZYME_GIT_REF={ref_id}\n" if self.returncode == 0 else ""
            ),
            "result_digest": f"sha256:{'d' * 64}",
        }


def _active_runtime_environment(tmp_path):
    _, repositories, _, _, _ = _environment()
    volumes = _MemoryVolumeBackend()
    provisioner = _provisioner(
        tmp_path,
        repositories,
        _CloneRunner(),
        volumes,
    )
    provisioner.provision_and_activate(
        session_id="session_1",
        agent_member_id="member_1",
        workspace_generation=1,
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        actor_ref="host:c3-runtime-test",
        workspace_id="workspace_member_1_g1",
    )
    workspace = repositories.agent_git_workspaces.get("workspace_member_1_g1")
    assert workspace is not None
    return repositories, workspace


def test_native_runtime_requires_ready_workspace_and_matching_active_lease(
    tmp_path,
) -> None:
    _, pending_repositories, _, _, _ = _environment()
    pending_runner = _ProcessRunner()

    with pytest.raises(AgentCapsuleAdmissionError, match="exact ready"):
        AgentCapsuleRuntimeService(
            repositories=pending_repositories,
            process_runner=pending_runner,
        ).execute(
            session_id="session_1",
            agent_id="agent:master",
            argv=("git", "status"),
        )

    assert pending_runner.calls == []
    repositories, workspace = _active_runtime_environment(tmp_path)
    active_runner = _ProcessRunner()
    result = AgentCapsuleRuntimeService(
        repositories=repositories,
        process_runner=active_runner,
    ).execute(
        session_id="session_1",
        agent_id="agent:master",
        argv=("git", "status", "--short"),
    )

    assert result["returncode"] == 0
    assert result["workspace_id"] == workspace.workspace_id
    assert result["cwd"] == workspace.clone_logical_root
    assert len(active_runner.calls) == 1
    assert agent_capsule_tools_available(
        repositories,
        session_id="session_1",
        agent_id="agent:master",
    )

    AgentCapabilityLeaseService(repositories).revoke_exact(
        workspace.capability_lease_id,
        actor_ref="operator:c3-runtime-test",
    )
    revoked_runner = _ProcessRunner()
    with pytest.raises(AgentCapabilityError):
        AgentCapsuleRuntimeService(
            repositories=repositories,
            process_runner=revoked_runner,
        ).execute(
            session_id="session_1",
            agent_id="agent:master",
            argv=("git", "status"),
        )
    assert revoked_runner.calls == []
    assert not agent_capsule_tools_available(
        repositories,
        session_id="session_1",
        agent_id="agent:master",
    )


class _StatefulWorkspaceRunner:
    def __init__(self) -> None:
        self.state_by_volume: dict[str, dict[str, str]] = {}

    def run(
        self,
        *,
        workspace,
        argv,
        credential_environment,
        timeout_seconds,
    ):
        del credential_environment, timeout_seconds
        if argv == ("c3-test-seed-workspace-state",):
            self.state_by_volume[workspace.volume_id] = {
                "tracked": "tracked-content",
                "untracked": "untracked-content",
                "index": "staged-content",
                "ref": "refs/openzyme/private/checkpoint-1",
                "object": "a" * 40,
                "download": "private-downloaded-bytes",
            }
            return AgentCapsuleProcessResult(0, "seeded", "")
        return AgentCapsuleProcessResult(
            0,
            json.dumps(self.state_by_volume[workspace.volume_id], sort_keys=True),
            "",
        )


def test_ephemeral_process_and_host_service_restart_reuse_full_workspace_state(
    tmp_path,
) -> None:
    repositories, workspace = _active_runtime_environment(tmp_path)
    runner = _StatefulWorkspaceRunner()
    AgentCapsuleRuntimeService(repositories, runner).execute(
        session_id="session_1",
        agent_id="agent:master",
        argv=("c3-test-seed-workspace-state",),
    )

    restarted_service = AgentCapsuleRuntimeService(repositories, runner)
    observed = restarted_service.execute(
        session_id="session_1",
        agent_id="agent:master",
        argv=("c3-test-observe-workspace-state",),
    )

    assert observed["workspace_id"] == workspace.workspace_id
    assert json.loads(observed["stdout"]) == {
        "download": "private-downloaded-bytes",
        "index": "staged-content",
        "object": "a" * 40,
        "ref": "refs/openzyme/private/checkpoint-1",
        "tracked": "tracked-content",
        "untracked": "untracked-content",
    }


class _ProcessCredentialProvider:
    service_id = "service_exact"

    def __init__(self) -> None:
        self.issue_count = 0
        self.revoked: list[str] = []

    def issue(self, *, request, claims, now):
        del claims, now
        self.issue_count += 1
        secret = "exact-process-secret"
        return IssuedAgentProcessCredential(
            credential_id=f"credential_{self.issue_count}",
            service_id=request.service_id,
            target_id=request.target_id,
            protocol=request.protocol,
            audience=request.audience,
            environment=(("OPENZYME_EXACT_TOKEN", secret),),
            exact_secret_material=(secret,),
            expires_at="2026-08-16T04:00:00+00:00",
        )

    def revoke(self, credential, *, revoked_at):
        assert revoked_at
        self.revoked.append(credential.credential_id)


def test_process_credential_is_ephemeral_redacted_and_not_used_for_ordinary_network(
    tmp_path,
) -> None:
    repositories, _ = _active_runtime_environment(tmp_path)
    provider = _ProcessCredentialProvider()
    runner = _ProcessRunner(
        AgentCapsuleProcessResult(
            0,
            "downloaded private bytes",
            "",
        )
    )
    service = AgentCapsuleRuntimeService(
        repositories=repositories,
        process_runner=runner,
        credential_router=AgentProcessCredentialRouter(
            providers={provider.service_id: provider}
        ),
    )
    baseline = {
        "approvals": repositories.approvals.list_by_session("session_1"),
        "controlled_operations": (
            repositories.controlled_operations.list_by_session("session_1")
        ),
        "engines": repositories.invocations.list_by_session("session_1"),
        "inbox": repositories.inbox.list_by_session("session_1"),
        "published_revisions": (
            repositories.published_revisions.list_by_session("session_1")
        ),
        "tasks": repositories.tasks.list_by_session("session_1"),
    }

    for argv in (
        ("curl", "https://reachable.example/private-input"),
        ("scp", "private-input", "peer:private-input"),
        ("rsync", "private-input", "peer:private-input"),
    ):
        ordinary = service.execute(
            session_id="session_1",
            agent_id="agent:master",
            argv=argv,
        )
        assert ordinary["credential_issued"] is False
        assert ordinary["returncode"] == 0
    assert provider.issue_count == 0

    runner.result = AgentCapsuleProcessResult(
        22,
        "client output exact-process-secret",
        "endpoint rejected exact-process-secret",
    )
    failed = service.execute(
        session_id="session_1",
        agent_id="agent:master",
        argv=("curl", "https://service.example/upload"),
        credential_request=AgentProcessCredentialRequest(
            service_id=provider.service_id,
            target_id="target_exact",
            protocol="upload",
            audience="https://service.example/upload",
        ),
    )

    assert failed["returncode"] == 22
    assert failed["retry_performed"] is False
    assert failed["fallback_performed"] is False
    assert "exact-process-secret" not in failed["stdout"]
    assert "exact-process-secret" not in failed["stderr"]
    assert provider.issue_count == 1
    assert provider.revoked == ["credential_1"]
    assert runner.calls[-1]["credential_environment"] == (
        ("OPENZYME_EXACT_TOKEN", "exact-process-secret"),
    )
    assert baseline == {
        "approvals": repositories.approvals.list_by_session("session_1"),
        "controlled_operations": (
            repositories.controlled_operations.list_by_session("session_1")
        ),
        "engines": repositories.invocations.list_by_session("session_1"),
        "inbox": repositories.inbox.list_by_session("session_1"),
        "published_revisions": (
            repositories.published_revisions.list_by_session("session_1")
        ),
        "tasks": repositories.tasks.list_by_session("session_1"),
    }


def test_process_launch_exception_is_secret_redacted_and_credential_revoked(
    tmp_path,
) -> None:
    repositories, _ = _active_runtime_environment(tmp_path)
    provider = _ProcessCredentialProvider()

    class FailingRunner:
        def run(self, **kwargs):
            assert kwargs["credential_environment"]
            raise RuntimeError("launch exposed exact-process-secret")

    service = AgentCapsuleRuntimeService(
        repositories=repositories,
        process_runner=FailingRunner(),
        credential_router=AgentProcessCredentialRouter(
            providers={provider.service_id: provider}
        ),
    )
    with pytest.raises(AgentCapsuleRuntimeError) as error:
        service.execute(
            session_id="session_1",
            agent_id="agent:master",
            argv=("curl", "https://service.example/upload"),
            credential_request=AgentProcessCredentialRequest(
                service_id=provider.service_id,
                target_id="target_exact",
                protocol="upload",
                audience="https://service.example/upload",
            ),
        )

    assert "exact-process-secret" not in str(error.value)
    assert "[REDACTED_PROCESS_CREDENTIAL]" in str(error.value)
    assert provider.revoked == ["credential_1"]


class _CapsuleExecutor:
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def run(self, argv, *, environment=None):
        self.calls.append((argv, environment))
        return CapsuleCommandResult(7, "", "connection refused")


def test_podman_native_process_reuses_one_volume_and_preserves_native_failure(
    tmp_path,
) -> None:
    repositories, workspace = _active_runtime_environment(tmp_path)
    executor = _CapsuleExecutor()
    podman_runner = PodmanAgentCapsuleProcessRunner(
        executor=executor,
        deployment_network="openzyme-agent-network",
        podman_binary="/usr/bin/podman",
    )
    first_service = AgentCapsuleRuntimeService(repositories, podman_runner)
    first = first_service.execute(
        session_id="session_1",
        agent_id="agent:master",
        argv=("curl", "https://unreachable.example"),
    )
    restarted_service = AgentCapsuleRuntimeService(repositories, podman_runner)
    second = restarted_service.execute(
        session_id="session_1",
        agent_id="agent:master",
        argv=("git", "status", "--short"),
    )

    assert (first["returncode"], first["stderr"]) == (7, "connection refused")
    assert second["returncode"] == 7
    assert len(executor.calls) == 2
    for argv, environment in executor.calls:
        joined = " ".join(argv)
        assert argv[:3] == ("/usr/bin/podman", "run", "--rm")
        assert ("--network", "openzyme-agent-network") == (
            argv[3],
            argv[4],
        )
        assert (
            f"type=volume,src={workspace.volume_id},dst=/workspace,rw" in argv
        )
        assert workspace.clone_logical_root in argv
        assert "allowlist" not in joined
        assert "/home/" not in joined
        assert "/.ssh" not in joined
        assert environment == {"PATH": "/usr/bin:/bin"}


class _CheckpointGitReader:
    def __init__(self, *, binding, workspace) -> None:
        self.binding = binding
        self.refs = {
            f"{workspace.private_ref_namespace}/step-1": BASE_COMMIT,
        }
        self.trees = {BASE_COMMIT: "1" * 40}
        self.ancestry: set[tuple[str, str]] = set()
        self.read_count = 0
        self.dispatch_count = 0
        self.dispatch_error: Exception | None = None
        self.create_before_error = False

    def read_exact_ref(self, binding, *, ref_name):
        assert binding == self.binding
        self.read_count += 1
        return self.refs.get(ref_name)

    def list_refs(self, binding, *, prefix):
        assert binding == self.binding
        self.read_count += 1
        return tuple(
            sorted(
                (ref_name, commit)
                for ref_name, commit in self.refs.items()
                if ref_name.startswith(prefix)
            )
        )

    def read_commit_tree(self, binding, *, commit):
        assert binding == self.binding
        self.read_count += 1
        return self.trees[commit]

    def is_ancestor(self, binding, *, ancestor, descendant, extra_env=None):
        assert binding == self.binding
        assert extra_env is None
        self.read_count += 1
        return (ancestor, descendant) in self.ancestry

    def read_commit_parents(self, binding, *, commit):
        assert binding == self.binding
        self.read_count += 1
        return () if commit == BASE_COMMIT else (BASE_COMMIT,)

    def read_whole_tree_manifest(self, binding, *, commit):
        assert binding == self.binding
        self.read_count += 1
        return WorkspacePublicationManifest.create(
            (
                PublicationManifestEntry(
                    path="src/result.txt",
                    mode="100644",
                    object_kind=PublicationManifestObjectKind.BLOB,
                    object_id="9" * 40,
                    size_bytes=12,
                ),
            )
        )

    def create_publication_ref_if_absent(
        self,
        binding,
        *,
        publication_id,
        ref_name,
        commit,
    ):
        assert binding == self.binding
        assert ref_name == (
            f"{binding.ref_namespace_policy.publication_prefix}/{publication_id}"
        )
        self.dispatch_count += 1
        if self.create_before_error:
            self.refs[ref_name] = commit
        if self.dispatch_error is not None:
            raise self.dispatch_error
        if ref_name in self.refs:
            raise RuntimeError("create-only publication ref already exists")
        self.refs[ref_name] = commit
        return commit


def _checkpoint_input(
    *,
    workspace,
    private_ref: str,
    commit: str,
    tree: str,
    advance_kind: PrivateRefAdvanceKind,
    prior_commit: str | None,
    boundary: WorkspaceFormalBoundary = WorkspaceFormalBoundary.DURABLE_CHECKPOINT,
) -> WorkspaceCheckpointProofInput:
    return WorkspaceCheckpointProofInput(
        boundary=boundary,
        workspace_id=workspace.workspace_id,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        agent_id=workspace.agent_id,
        workspace_generation=workspace.workspace_generation,
        repository_binding_id=workspace.repository_binding_id,
        repository_binding_version=workspace.repository_binding_version,
        commit=commit,
        tree=tree,
        private_ref=private_ref,
        remote_observation=RemotePrivateRefObservation(
            service_id=workspace.internal_git_service_id,
            repository_id=workspace.repository_id,
            private_ref=private_ref,
            prior_commit=prior_commit,
            observed_commit=commit,
            advance_kind=advance_kind,
            observed_at="2026-08-16T05:00:00+00:00",
        ),
    )


def test_two_private_checkpoints_are_create_then_fast_forward_without_git_mutation(
    tmp_path,
) -> None:
    repositories, workspace = _active_runtime_environment(tmp_path)
    binding = repositories.project_repository_bindings.get(
        workspace.repository_binding_id
    )
    assert binding is not None
    reader = _CheckpointGitReader(binding=binding, workspace=workspace)
    service = WorkspaceCheckpointService(repositories, reader)
    private_ref = f"{workspace.private_ref_namespace}/step-1"
    first = service.verify_checkpoint(
        _checkpoint_input(
            workspace=workspace,
            private_ref=private_ref,
            commit=BASE_COMMIT,
            tree="1" * 40,
            advance_kind=PrivateRefAdvanceKind.CREATE,
            prior_commit=None,
        ),
        checkpoint_id="checkpoint_step_1",
        verified_at="2026-08-16T05:01:00+00:00",
    )
    second_commit = "2" * 40
    second_tree = "3" * 40
    reader.refs[private_ref] = second_commit
    reader.trees[second_commit] = second_tree
    reader.ancestry.add((BASE_COMMIT, second_commit))
    second = service.verify_checkpoint(
        _checkpoint_input(
            workspace=workspace,
            private_ref=private_ref,
            commit=second_commit,
            tree=second_tree,
            advance_kind=PrivateRefAdvanceKind.FAST_FORWARD,
            prior_commit=BASE_COMMIT,
        ),
        checkpoint_id="checkpoint_step_2",
        verified_at="2026-08-16T05:02:00+00:00",
    )

    assert (first.advance_kind, second.advance_kind) == (
        PrivateRefAdvanceKind.CREATE,
        PrivateRefAdvanceKind.FAST_FORWARD,
    )
    assert repositories.verified_workspace_checkpoints.list_by_workspace(
        workspace.workspace_id
    ) == [first, second]
    assert reader.refs == {private_ref: second_commit}


def test_dirty_projection_clean_boundary_and_immutable_handoff_are_separate(
    tmp_path,
) -> None:
    repositories, workspace = _active_runtime_environment(tmp_path)
    binding = repositories.project_repository_bindings.get(
        workspace.repository_binding_id
    )
    assert binding is not None
    reader = _CheckpointGitReader(binding=binding, workspace=workspace)
    service = WorkspaceCheckpointService(repositories, reader)
    private_ref = f"{workspace.private_ref_namespace}/step-1"
    checkpoint = service.verify_checkpoint(
        _checkpoint_input(
            workspace=workspace,
            private_ref=private_ref,
            commit=BASE_COMMIT,
            tree="1" * 40,
            advance_kind=PrivateRefAdvanceKind.CREATE,
            prior_commit=None,
        ),
        checkpoint_id="checkpoint_clean_boundary",
        verified_at="2026-08-16T05:01:00+00:00",
    )
    dirty = AgentWorkspaceStateObservation(
        observation_id="observation_dirty",
        workspace_id=workspace.workspace_id,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        agent_id=workspace.agent_id,
        workspace_generation=workspace.workspace_generation,
        head_commit=BASE_COMMIT,
        head_tree="1" * 40,
        dirty_state=WorkspaceDirtyState.DIRTY,
        staged=False,
        unstaged=True,
        untracked=True,
        changed_paths=("notes/dirty.txt",),
        changed_paths_truncated=False,
        observed_at="2026-08-16T05:02:00+00:00",
    )
    service.record_state_observation(dirty)
    with pytest.raises(WorkspaceCheckpointError, match="clean state"):
        service.validate_clean_committed_revision(
            workspace_id=workspace.workspace_id,
            expected_commit=BASE_COMMIT,
            expected_tree="1" * 40,
        )
    assert service.validate_immutable_revision_handoff(
        checkpoint_id=checkpoint.checkpoint_id,
        expected_commit=BASE_COMMIT,
        expected_tree="1" * 40,
    ) == checkpoint

    clean = AgentWorkspaceStateObservation(
        observation_id="observation_clean",
        workspace_id=workspace.workspace_id,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        agent_id=workspace.agent_id,
        workspace_generation=workspace.workspace_generation,
        head_commit=BASE_COMMIT,
        head_tree="1" * 40,
        dirty_state=WorkspaceDirtyState.CLEAN,
        staged=False,
        unstaged=False,
        untracked=False,
        changed_paths=(),
        changed_paths_truncated=False,
        observed_at="2026-08-16T05:03:00+00:00",
    )
    service.record_state_observation(clean)
    proof = service.validate_clean_committed_revision(
        workspace_id=workspace.workspace_id,
        expected_commit=BASE_COMMIT,
        expected_tree="1" * 40,
        verified_at="2026-08-16T05:04:00+00:00",
    )

    assert proof.verified_checkpoint_id == checkpoint.checkpoint_id
    projected = FileWorkspaceProjectionBuilder(
        repositories,
        tool_catalog_digest="sha256:" + "0" * 64,
    ).build(
        session_id="session_1",
        subject_agent_member_id=None,
    ).to_dict()["workspace_status"][0]
    assert projected["dirty_state"] == "clean"
    assert projected["head_commit"] == BASE_COMMIT
    assert "private_ref" not in json.dumps(projected)
    assert workspace.internal_git_endpoint not in json.dumps(projected)
    assert workspace.volume_id not in json.dumps(projected)


def test_file_producing_task_terminal_requires_exact_checkpoint_evidence(
    tmp_path,
) -> None:
    repositories, workspace = _active_runtime_environment(tmp_path)
    binding = repositories.project_repository_bindings.get(
        workspace.repository_binding_id
    )
    assert binding is not None
    reader = _CheckpointGitReader(binding=binding, workspace=workspace)
    private_ref = f"{workspace.private_ref_namespace}/task-terminal"
    reader.refs[private_ref] = BASE_COMMIT
    checkpoint = WorkspaceCheckpointService(
        repositories,
        reader,
    ).verify_checkpoint(
        _checkpoint_input(
            workspace=workspace,
            private_ref=private_ref,
            commit=BASE_COMMIT,
            tree="1" * 40,
            advance_kind=PrivateRefAdvanceKind.CREATE,
            prior_commit=None,
            boundary=WorkspaceFormalBoundary.TASK_TERMINAL,
        ),
        checkpoint_id="checkpoint_task_terminal",
        verified_at="2026-08-16T05:05:00+00:00",
    )
    board = TaskBoardService(repositories)
    task = board.create_task(
        session_id="session_1",
        task_id="task_file_output",
        subject="Produce coherent files",
        description="Must checkpoint before terminal completion",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=workspace.agent_id,
    )

    with pytest.raises(TypeError, match="produced_durable_files"):
        board.finish_task(
            task.task_id,
            TaskFinishCommand(
                status=TaskStatus.COMPLETED,
                summary="Files complete",
                finished_by=workspace.agent_id,
                produced_durable_files=True,
            ),
        )
    with pytest.raises(TypeError, match="workspace_checkpoint_id"):
        TaskFinishCommand(
            status=TaskStatus.COMPLETED,
            summary="Files complete",
            finished_by=workspace.agent_id,
            workspace_checkpoint_id=checkpoint.checkpoint_id,
        )
    assert repositories.tasks.get(task.task_id).status is TaskStatus.IN_PROGRESS


def _publication_environment(tmp_path):
    repositories, workspace = _active_runtime_environment(tmp_path)
    binding = repositories.project_repository_bindings.get(
        workspace.repository_binding_id
    )
    assert binding is not None
    route = _CheckpointGitReader(binding=binding, workspace=workspace)
    checkpoint_service = WorkspaceCheckpointService(repositories, route)
    private_ref = f"{workspace.private_ref_namespace}/publication-1"
    route.refs[private_ref] = BASE_COMMIT
    checkpoint = checkpoint_service.verify_checkpoint(
        _checkpoint_input(
            workspace=workspace,
            private_ref=private_ref,
            commit=BASE_COMMIT,
            tree="1" * 40,
            advance_kind=PrivateRefAdvanceKind.CREATE,
            prior_commit=None,
            boundary=WorkspaceFormalBoundary.PUBLICATION,
        ),
        checkpoint_id="checkpoint_publication_1",
        verified_at="2026-08-16T05:10:00+00:00",
    )
    checkpoint_service.record_state_observation(
        AgentWorkspaceStateObservation(
            observation_id="observation_publication_clean",
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            head_commit=BASE_COMMIT,
            head_tree="1" * 40,
            dirty_state=WorkspaceDirtyState.CLEAN,
            staged=False,
            unstaged=False,
            untracked=False,
            changed_paths=(),
            changed_paths_truncated=False,
            observed_at="2026-08-16T05:11:00+00:00",
        )
    )
    command = WorkspacePublishCommand(
        idempotency_key="publish-clean-head-1",
        workspace_id=workspace.workspace_id,
        workspace_generation=workspace.workspace_generation,
        expected_head_commit=BASE_COMMIT,
        expected_tree="1" * 40,
        declared_base_commit=workspace.base_commit,
        checkpoint_id=checkpoint.checkpoint_id,
        whole_repository=True,
        repository_binding_version=workspace.repository_binding_version,
    )
    return repositories, workspace, route, command


def test_workspace_publication_materializes_once_without_human_approval_or_retry(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    service = WorkspacePublicationService(repositories, route, route)

    first = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )
    replay = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )

    assert first.revision is not None
    assert replay.revision == first.revision
    assert route.dispatch_count == 1
    assert repositories.approvals.list_pending_by_session(workspace.session_id) == []
    assert repositories.durable_events.get(
        f"publication_outbox_{first.revision.publication_id}"
    ) is not None
    projected = FileWorkspaceProjectionBuilder(
        repositories,
        tool_catalog_digest="sha256:" + "0" * 64,
    ).build(
        session_id=workspace.session_id,
        subject_agent_member_id=workspace.agent_member_id,
    ).to_dict()
    assert projected["published_revisions"][0]["publication_id"] == (
        first.revision.publication_id
    )
    assert projected["agent_workspaces"][0]["workspace_id"] == workspace.workspace_id
    assert service.audit_session_namespace(workspace.session_id)["ok"] is True
    with pytest.raises(sqlite3.IntegrityError, match="immutable"):
        repositories.sessions.connection.execute(
            "UPDATE published_revisions SET tree_id = ? WHERE publication_id = ?",
            ("0" * 40, first.revision.publication_id),
        )
    repositories.sessions.connection.rollback()
    with pytest.raises(sqlite3.IntegrityError, match="append-only"):
        repositories.sessions.connection.execute(
            "DELETE FROM workspace_publication_intents WHERE intent_id = ?",
            (first.intent.intent_id,),
        )
    repositories.sessions.connection.rollback()
    with pytest.raises(WorkspacePublicationError, match="idempotency replay"):
        service.publish(
            session_id=workspace.session_id,
            agent_id=workspace.agent_id,
            command=replace(command, expected_tree="7" * 40),
        )
    assert route.dispatch_count == 1


def test_publication_response_loss_reconciles_same_ref_without_redispatch(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    route.create_before_error = True
    route.dispatch_error = RuntimeError("response lost")
    service = WorkspacePublicationService(repositories, route, route)

    uncertain = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )
    recovered = WorkspacePublicationService(repositories, route, route).publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )

    assert uncertain.execution.lifecycle_state is (
        ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED
    )
    assert uncertain.execution.effect_certainty is (
        ExternalEffectCertainty.DISPATCH_IN_DOUBT
    )
    assert recovered.revision is not None
    assert recovered.revision.publication_id == uncertain.intent.publication_id
    assert route.dispatch_count == 1


def test_unproven_publication_effect_stays_in_doubt_and_never_retries(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    route.dispatch_error = RuntimeError("connection outcome unknown")
    service = WorkspacePublicationService(repositories, route, route)

    first = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )
    second = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )

    assert first.revision is None and second.revision is None
    assert second.execution.effect_certainty is (
        ExternalEffectCertainty.DISPATCH_IN_DOUBT
    )
    assert route.dispatch_count == 1


def test_publication_different_ref_target_is_terminal_integrity_conflict(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    route.dispatch_error = RuntimeError("response lost")
    service = WorkspacePublicationService(repositories, route, route)
    uncertain = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )
    route.refs[uncertain.intent.publication_ref] = "0" * 40

    conflicted = service.reconcile(intent_id=uncertain.intent.intent_id)

    assert conflicted.execution.lifecycle_state is (
        ControlledOperationExecutionLifecycle.TERMINAL
    )
    assert conflicted.execution.error_code == "publication_ref_integrity_conflict"
    assert conflicted.revision is None
    assert route.dispatch_count == 1


def test_publication_execution_repository_rejects_stale_state_and_fence(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    admitted = WorkspacePublicationService(repositories, route, route).admit(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )

    with pytest.raises(OptimisticStateConflictError, match="stale"):
        repositories.workspace_publication_executions.replace_if_version(
            replace(admitted.execution, state_version=2),
            expected_state_version=99,
        )
    assert route.dispatch_count == 0


def test_new_publication_can_supersede_without_mutating_old_revision(tmp_path) -> None:
    repositories, workspace, route, first_command = _publication_environment(tmp_path)
    service = WorkspacePublicationService(repositories, route, route)
    first = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=first_command,
    )
    assert first.revision is not None
    second_commit = "2" * 40
    second_tree = "3" * 40
    second_private_ref = f"{workspace.private_ref_namespace}/publication-2"
    route.refs[second_private_ref] = second_commit
    route.trees[second_commit] = second_tree
    checkpoint_service = WorkspaceCheckpointService(repositories, route)
    second_checkpoint = checkpoint_service.verify_checkpoint(
        _checkpoint_input(
            workspace=workspace,
            private_ref=second_private_ref,
            commit=second_commit,
            tree=second_tree,
            advance_kind=PrivateRefAdvanceKind.CREATE,
            prior_commit=None,
            boundary=WorkspaceFormalBoundary.PUBLICATION,
        ),
        checkpoint_id="checkpoint_publication_2",
        verified_at="2026-08-16T05:20:00+00:00",
    )
    checkpoint_service.record_state_observation(
        AgentWorkspaceStateObservation(
            observation_id="observation_publication_clean_2",
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            head_commit=second_commit,
            head_tree=second_tree,
                dirty_state=WorkspaceDirtyState.CLEAN,
                staged=False,
                unstaged=False,
                untracked=False,
                changed_paths=(),
                changed_paths_truncated=False,
                observed_at="2026-08-16T05:21:00+00:00",
        )
    )

    second = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=replace(
            first_command,
            idempotency_key="publish-clean-head-2",
            expected_head_commit=second_commit,
            expected_tree=second_tree,
            checkpoint_id=second_checkpoint.checkpoint_id,
            supersedes_publication_id=first.revision.publication_id,
        ),
    )

    assert second.revision is not None
    assert second.revision.supersedes_publication_id == first.revision.publication_id
    assert repositories.published_revisions.get(first.revision.publication_id) == (
        first.revision
    )
    assert route.dispatch_count == 2


def test_publication_path_evidence_requires_exact_revision_and_does_not_finish_task(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    board = TaskBoardService(repositories)
    task = board.create_task(
        session_id=workspace.session_id,
        task_id="task_publication_handoff",
        subject="Publish exact files",
        description="Publication and task terminal remain orthogonal",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=workspace.agent_id,
    )
    state = WorkspacePublicationService(repositories, route, route).publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=replace(command, task_id=task.task_id),
    )
    assert state.revision is not None
    assert repositories.tasks.get(task.task_id).status is TaskStatus.IN_PROGRESS
    path_ref = RevisionPathReferenceService(repositories).create_file_ref(
        publication_id=state.revision.publication_id,
        path="src/result.txt",
        ref_id="revision_path_publication_handoff",
        created_at="2026-08-16T05:30:00+00:00",
    )
    evidence_ref = TaskEvidenceRef(
        kind=TaskEvidenceKind.REVISION_PATH,
        project_id=path_ref.project_id,
        session_id=path_ref.session_id,
        task_id=task.task_id,
        owner_id=path_ref.ref_id,
        owner_digest=path_ref.ref_digest,
        revision_path_ref=path_ref,
    )

    outcome = board.finish_task(
        task.task_id,
        TaskFinishCommand(
            status=TaskStatus.COMPLETED,
            summary="Exact published path handed off",
            finished_by=workspace.agent_id,
            evidence_refs=(evidence_ref,),
        ),
    )

    assert outcome.task.status is TaskStatus.COMPLETED
    assert evidence_ref.to_dict() in outcome.payload["evidence_refs"]


def test_report_publish_binds_exact_file_without_publishing_or_finishing_task(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    task = TaskBoardService(repositories).create_task(
        session_id=workspace.session_id,
        task_id="task_report_file",
        subject="Publish report",
        description="Keep workspace and report publication distinct",
        status=TaskStatus.IN_PROGRESS,
        assigned_ref=workspace.agent_id,
    )
    publication = WorkspacePublicationService(repositories, route, route).publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=replace(command, task_id=task.task_id),
    )
    assert publication.revision is not None
    content_ref = RevisionPathReferenceService(repositories).create_file_ref(
        publication_id=publication.revision.publication_id,
        path="src/result.txt",
        ref_id="report_body_ref_1",
        created_at="2026-08-16T05:31:00+00:00",
    )
    registry = ToolRegistry()
    register_report_draft_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, workspace.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id=task.task_id),
        agent_id=workspace.agent_id,
    )
    updated = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_report_draft",
            tool_name="report_draft.update",
            arguments={
                "task_id": task.task_id,
                "title": "Exact report",
                "content_ref": content_ref.to_dict(),
            },
            task_id=task.task_id,
        ),
    )
    published = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_report_publish",
            tool_name="report.publish",
            arguments={
                "task_id": task.task_id,
                "report_id": "report_file_1",
                "content_ref": content_ref.to_dict(),
            },
            task_id=task.task_id,
        ),
    )

    payload = json.loads(published.content)
    assert updated.ok is True
    assert published.ok is True
    assert payload["report"]["content_ref_id"] == content_ref.ref_id
    assert payload["report"]["workspace_publication_performed"] is False
    assert payload["task_evidence_ref"]["kind"] == "report"
    assert route.dispatch_count == 1
    assert repositories.tasks.get(task.task_id).status is TaskStatus.IN_PROGRESS
    assert repositories.published_revisions.list_by_session(workspace.session_id) == [
        publication.revision
    ]


def test_two_agent_publication_exposes_only_explicit_fetch_identity(tmp_path) -> None:
    repositories, publisher, route, command = _publication_environment(tmp_path)
    repositories.agents.save(
        _member(
            "member_2",
            "agent:researcher",
            name="researcher",
            role="researcher",
            parent_agent_id=publisher.agent_id,
        )
    )
    AgentCapabilityLeaseService(repositories).reserve_and_issue(
        session_id=publisher.session_id,
        agent_id="agent:researcher",
        idempotency_key="issue-researcher-publication-g1",
        actor_ref="host:c4-test",
        parent_lease_id=publisher.capability_lease_id,
    )
    recipient_volumes = _MemoryVolumeBackend()
    recipient_provisioner = _provisioner(
        tmp_path,
        repositories,
        _CloneRunner(),
        recipient_volumes,
    )
    recipient_provisioner.provision_and_activate(
        session_id=publisher.session_id,
        agent_member_id="member_2",
        workspace_generation=1,
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        actor_ref="host:c4-test",
        workspace_id="workspace_member_2_g1",
    )
    recipient_before = repositories.agent_git_workspaces.get(
        "workspace_member_2_g1"
    )
    assert recipient_before is not None
    service = WorkspacePublicationService(repositories, route, route)

    published = service.publish(
        session_id=publisher.session_id,
        agent_id=publisher.agent_id,
        command=command,
    )

    assert published.revision is not None
    assert repositories.agent_git_workspaces.get(recipient_before.workspace_id) == (
        recipient_before
    )
    assert (
        repositories.agent_workspace_state_observations.latest_for_workspace(
            recipient_before.workspace_id
        )
        is None
    )
    fetch = service.fetch_identity(published.revision.publication_id)
    assert fetch.commit == published.revision.commit
    assert fetch.tree == published.revision.tree
    assert route.dispatch_count == 1


def test_native_handoff_fetch_uses_scoped_git_read_without_checkout_or_task_change(
    tmp_path,
) -> None:
    repositories, publisher, route, command = _publication_environment(tmp_path)
    repositories.agents.save(
        _member(
            "member_2",
            "agent:researcher",
            name="researcher",
            role="researcher",
            parent_agent_id=publisher.agent_id,
        )
    )
    publication = WorkspacePublicationService(repositories, route, route).publish(
        session_id=publisher.session_id,
        agent_id=publisher.agent_id,
        command=command,
    )
    assert publication.revision is not None
    path_ref = RevisionPathReferenceService(repositories).create_file_ref(
        publication_id=publication.revision.publication_id,
        path="src/result.txt",
        ref_id="native_fetch_ref_1",
        created_at="2026-08-16T05:40:00+00:00",
    )
    handoff = ProtocolFileHandoff.create(
        handoff_id="handoff_native_fetch_1",
        project_id=path_ref.project_id,
        session_id=path_ref.session_id,
        producer_agent_id=publisher.agent_id,
        recipient_agent_id="agent:researcher",
        purpose="review exact research file",
        entries=(path_ref,),
        created_at="2026-08-16T05:41:00+00:00",
    )
    repositories.revision_path_handoffs.add_handoff(handoff)
    runtime = _RecordingNativeFetchRuntime()

    result = NativeRevisionPathFetchService(
        repositories,
        runtime,  # type: ignore[arg-type]
    ).fetch_handoff_publication(
        session_id=publisher.session_id,
        agent_id="agent:researcher",
        handoff_id=handoff.handoff_id,
        publication_id=publication.revision.publication_id,
    )

    assert [request.protocol for request in runtime.requests] == ["git_read"]
    assert result.checkout_performed is False
    assert result.merge_performed is False
    assert result.task_transition_performed is False
    assert result.verified_ref_ids == (path_ref.ref_id,)


def test_published_path_handoff_ignores_later_dirty_producer_workspace(
    tmp_path,
) -> None:
    repositories, publisher, route, command = _publication_environment(tmp_path)
    publication = WorkspacePublicationService(repositories, route, route).publish(
        session_id=publisher.session_id,
        agent_id=publisher.agent_id,
        command=command,
    )
    assert publication.revision is not None
    dirty = AgentWorkspaceStateObservation(
        observation_id="observation_after_publication_dirty",
        workspace_id=publisher.workspace_id,
        session_id=publisher.session_id,
        agent_member_id=publisher.agent_member_id,
        agent_id=publisher.agent_id,
        workspace_generation=publisher.workspace_generation,
        head_commit="9" * 40,
        head_tree="8" * 40,
        dirty_state=WorkspaceDirtyState.DIRTY,
        staged=True,
        unstaged=True,
        untracked=True,
        changed_paths=("src/result.txt",),
        changed_paths_truncated=False,
        observed_at="2026-08-16T05:41:00+00:00",
    )
    repositories.agent_workspace_state_observations.add(dirty)

    service = RevisionPathReferenceService(repositories)
    path_ref = service.create_file_ref(
        publication_id=publication.revision.publication_id,
        path="src/result.txt",
        ref_id="immutable_published_path_after_dirty_workspace",
        created_at="2026-08-16T05:42:00+00:00",
    )

    assert service.require_exact(path_ref) == path_ref
    assert (
        repositories.agent_workspace_state_observations.latest_for_workspace(
            publisher.workspace_id
        )
        == dirty
    )
    assert route.dispatch_count == 1


def test_native_handoff_fetch_fails_closed_on_git_identity_conflict(tmp_path) -> None:
    repositories, publisher, route, command = _publication_environment(tmp_path)
    repositories.agents.save(
        _member(
            "member_2",
            "agent:researcher",
            name="researcher",
            role="researcher",
            parent_agent_id=publisher.agent_id,
        )
    )
    publication = WorkspacePublicationService(repositories, route, route).publish(
        session_id=publisher.session_id,
        agent_id=publisher.agent_id,
        command=command,
    )
    assert publication.revision is not None
    path_ref = RevisionPathReferenceService(repositories).create_file_ref(
        publication_id=publication.revision.publication_id,
        path="src/result.txt",
        ref_id="native_fetch_conflict_ref",
    )
    handoff = ProtocolFileHandoff.create(
        handoff_id="handoff_native_fetch_conflict",
        project_id=path_ref.project_id,
        session_id=path_ref.session_id,
        producer_agent_id=publisher.agent_id,
        recipient_agent_id="agent:researcher",
        purpose="reject conflicting fetched ref",
        entries=(path_ref,),
        created_at="2026-08-16T05:42:00+00:00",
    )
    repositories.revision_path_handoffs.add_handoff(handoff)

    with pytest.raises(NativeRevisionPathFetchError, match="did not verify"):
        NativeRevisionPathFetchService(
            repositories,
            _RecordingNativeFetchRuntime(returncode=1),  # type: ignore[arg-type]
        ).fetch_handoff_publication(
            session_id=publisher.session_id,
            agent_id="agent:researcher",
            handoff_id=handoff.handoff_id,
            publication_id=publication.revision.publication_id,
        )


def test_lease_revoke_before_dispatch_closes_no_effect_without_git_io(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    service = WorkspacePublicationService(repositories, route, route)
    admitted = service.admit(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )
    AgentCapabilityLeaseService(repositories).revoke_exact(
        workspace.capability_lease_id,
        actor_ref="operator:c4-test",
    )

    closed = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )

    assert admitted.execution.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert closed.execution.lifecycle_state is (
        ControlledOperationExecutionLifecycle.TERMINAL
    )
    assert closed.execution.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert route.dispatch_count == 0


def test_lease_revoke_after_possible_effect_still_reconciles_original_ref(
    tmp_path,
) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    route.create_before_error = True
    route.dispatch_error = RuntimeError("response lost")
    service = WorkspacePublicationService(repositories, route, route)
    uncertain = service.publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )
    AgentCapabilityLeaseService(repositories).revoke_exact(
        workspace.capability_lease_id,
        actor_ref="operator:c4-test",
    )

    recovered = WorkspacePublicationService(repositories, route, route).publish(
        session_id=workspace.session_id,
        agent_id=workspace.agent_id,
        command=command,
    )

    assert recovered.revision is not None
    assert recovered.revision.publication_id == uncertain.intent.publication_id
    assert route.dispatch_count == 1


def test_dirty_or_partial_publication_is_rejected_before_remote_io(tmp_path) -> None:
    repositories, workspace, route, command = _publication_environment(tmp_path)
    service = WorkspacePublicationService(repositories, route, route)

    with pytest.raises(WorkspacePublicationError, match="complete repository"):
        service.publish(
            session_id=workspace.session_id,
            agent_id=workspace.agent_id,
            command=replace(command, whole_repository=False),
        )
    WorkspaceCheckpointService(repositories, route).record_state_observation(
        AgentWorkspaceStateObservation(
            observation_id="observation_publication_dirty",
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            head_commit=BASE_COMMIT,
            head_tree="1" * 40,
            dirty_state=WorkspaceDirtyState.DIRTY,
            staged=True,
            unstaged=False,
            untracked=False,
            changed_paths=("src/result.txt",),
            changed_paths_truncated=False,
            observed_at="2026-08-16T05:12:00+00:00",
        )
    )
    with pytest.raises(WorkspacePublicationError, match="clean state"):
        service.publish(
            session_id=workspace.session_id,
            agent_id=workspace.agent_id,
            command=replace(command, idempotency_key="publish-dirty-head-2"),
        )
    assert route.dispatch_count == 0


class _RecoveryObservationProvider:
    def __init__(self, observation=None, *, error: Exception | None = None) -> None:
        self.observation = observation
        self.error = error
        self.calls = 0

    def observe(self, workspace):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.observation or _observation(workspace)


def _recovery_environment(tmp_path):
    _, repositories, _, _, _ = _environment()
    volumes = _MemoryVolumeBackend()
    provisioner = _provisioner(
        tmp_path,
        repositories,
        _CloneRunner(),
        volumes,
    )
    provisioner.provision_and_activate(
        session_id="session_1",
        agent_member_id="member_1",
        workspace_generation=1,
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        actor_ref="host:c3-recovery-test",
        workspace_id="workspace_member_1_g1",
    )
    workspace = repositories.agent_git_workspaces.get("workspace_member_1_g1")
    assert workspace is not None
    return repositories, workspace, volumes, provisioner


def test_restore_reuses_intact_volume_and_accepts_new_readable_local_head(
    tmp_path,
) -> None:
    repositories, workspace, volumes, _ = _recovery_environment(tmp_path)
    local_commit = "4" * 40
    local_tree = "5" * 40
    observer = _RecoveryObservationProvider(
        _observation(
            workspace,
            head_commit=local_commit,
            head_tree=local_tree,
        )
    )

    restored = AgentGitWorkspaceRecoveryService(
        repositories,
        volumes,
        observer,
    ).restore(workspace.workspace_id)

    assert restored == workspace
    assert observer.calls == 1
    assert volumes.create_count == 1
    assert repositories.agent_git_workspaces.get(workspace.workspace_id) == workspace


@pytest.mark.parametrize(
    ("mode", "expected_blocker"),
    [
        ("missing_volume", AgentGitWorkspaceBlockerCode.MISSING_VOLUME),
        ("corrupt_git", AgentGitWorkspaceBlockerCode.CORRUPT_GIT_DIRECTORY),
        ("unreadable_head", AgentGitWorkspaceBlockerCode.UNREADABLE_HEAD),
        ("remote_drift", AgentGitWorkspaceBlockerCode.REMOTE_IDENTITY_DRIFT),
        ("generation_drift", AgentGitWorkspaceBlockerCode.GENERATION_DRIFT),
    ],
)
def test_restore_blocks_missing_corrupt_or_drifted_workspace_without_reclone(
    tmp_path,
    mode,
    expected_blocker,
) -> None:
    repositories, workspace, volumes, _ = _recovery_environment(tmp_path)
    if mode == "missing_volume":
        volumes.volumes.pop(workspace.volume_id)
        observer = _RecoveryObservationProvider()
    elif mode == "corrupt_git":
        observer = _RecoveryObservationProvider(
            error=AgentGitWorkspaceRecoveryError("corrupt .git")
        )
    elif mode == "unreadable_head":
        observer = _RecoveryObservationProvider(
            _observation(
                workspace,
                head_commit=None,
                head_tree=None,
                head_readable=False,
            )
        )
    elif mode == "remote_drift":
        observer = _RecoveryObservationProvider(
            _observation(
                workspace,
                internal_git_endpoint=(
                    "https://localhost:9443/repositories/drifted.git"
                ),
            )
        )
    else:
        observer = _RecoveryObservationProvider(
            _observation(workspace, workspace_generation=2)
        )
    service = AgentGitWorkspaceRecoveryService(
        repositories,
        volumes,
        observer,
    )

    blocked = service.restore(workspace.workspace_id)

    assert blocked.status is AgentGitWorkspaceStatus.BLOCKED
    assert blocked.blocker_code is expected_blocker
    assert volumes.create_count == 1
    assert repositories.agents.get_by_member_id("member_1").status is (
        AgentMemberStatus.BLOCKED
    )
    if mode == "missing_volume":
        assert observer.calls == 0


def test_restore_blocks_when_active_lease_no_longer_matches_workspace(
    tmp_path,
) -> None:
    repositories, workspace, volumes, _ = _recovery_environment(tmp_path)
    AgentCapabilityLeaseService(repositories).revoke_exact(
        workspace.capability_lease_id,
        actor_ref="operator:c3-recovery-test",
    )

    blocked = AgentGitWorkspaceRecoveryService(
        repositories,
        volumes,
        _RecoveryObservationProvider(),
    ).restore(workspace.workspace_id)

    assert blocked.status is AgentGitWorkspaceStatus.BLOCKED
    assert blocked.blocker_code is (
        AgentGitWorkspaceBlockerCode.LEASE_INTENT_MISMATCH
    )


def test_explicit_replacement_preserves_old_volume_and_revokes_old_lease(
    tmp_path,
) -> None:
    repositories, workspace, volumes, provisioner = _recovery_environment(tmp_path)
    replacement = AgentGitWorkspaceGenerationService(
        repositories,
        provisioner,
    ).replace_and_provision(
        workspace_id=workspace.workspace_id,
        idempotency_key="replace-master-g2",
        actor_ref="operator:c3-recovery-test",
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        replacement_workspace_id="workspace_member_1_g2",
    )

    old = repositories.agent_git_workspaces.get(workspace.workspace_id)
    old_lease = repositories.agent_capability_leases.get(
        workspace.capability_lease_id
    )
    assert old is not None and old.status is AgentGitWorkspaceStatus.REPLACED
    assert old.volume_id == workspace.volume_id
    assert old.volume_id in volumes.volumes
    assert old_lease is not None and old_lease.status.value == "revoked"
    assert replacement.status is AgentGitWorkspaceStatus.READY
    assert replacement.workspace_generation == 2
    assert replacement.volume_id != old.volume_id


def test_legacy_migration_freezes_sandbox_without_copying_legacy_files(
    tmp_path,
) -> None:
    _, repositories, _, _, _ = _environment()
    repositories.sandbox_images.save(
        SandboxImageRecord(
            image_ref="legacy-image:1",
            image_digest=None,
            image_family="legacy",
            image_version="1",
            sandbox_protocol_version="legacy",
            manifest_schema_version="legacy-v1",
            capabilities_declared=(),
            compatibility=SandboxImageCompatibility.COMPATIBLE,
            is_default=False,
            created_at="2026-08-16T00:00:00+00:00",
            updated_at="2026-08-16T00:00:00+00:00",
        )
    )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="legacy_sandbox_member_1",
            session_id="session_1",
            agent_member_id="member_1",
            agent_id="agent:master",
            status=SandboxWorkspaceStatus.READY,
            image_ref="legacy-image:1",
            image_digest=None,
            image_version="1",
            sandbox_protocol_version="legacy",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="legacy-v1",
            created_at="2026-08-16T00:00:00+00:00",
            last_attached_at="2026-08-16T00:01:00+00:00",
            directory_summary={"private_file": "legacy-only.txt"},
        )
    )
    volumes = _MemoryVolumeBackend()
    provisioner = _provisioner(
        tmp_path,
        repositories,
        _CloneRunner(),
        volumes,
    )

    migrated = AgentGitWorkspaceGenerationService(
        repositories,
        provisioner,
    ).migrate_pending_legacy_agent(
        session_id="session_1",
        agent_member_id="member_1",
        workspace_generation=1,
        actor_ref="operator:c3-legacy-migration",
        image_qualification=_qualified_image(),
        namespace_retention_deadline="2027-08-16T01:00:00+00:00",
        workspace_id="workspace_member_1_g1",
    )

    legacy = repositories.sandbox_workspaces.get("legacy_sandbox_member_1")
    assert legacy is not None
    assert legacy.status is SandboxWorkspaceStatus.FROZEN_LEGACY
    assert legacy.directory_summary == {"private_file": "legacy-only.txt"}
    assert migrated.status is AgentGitWorkspaceStatus.READY
    assert list(volumes.volumes) == [migrated.volume_id]
