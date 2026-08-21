from __future__ import annotations

import pytest

from openzyme_workspace_git_lfs import AgentGitDirectoryKind
from openzyme_workspace_git_lfs import AgentGitWorkspace
from openzyme_workspace_git_lfs import AgentGitWorkspaceBlockerCode
from openzyme_workspace_git_lfs import AgentGitWorkspaceIdentityDriftKind
from openzyme_workspace_git_lfs import AgentGitWorkspaceObservation
from openzyme_workspace_git_lfs import AgentGitWorkspaceStatus
from openzyme_workspace_git_lfs import AgentGitWorkspaceProvisioningMechanism
from openzyme_workspace_git_lfs import AgentGitWorkspaceRecoveryMechanism
from openzyme_workspace_git_lfs import AgentWorkspaceCloneResult
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import AgentWorkspaceVolumeFact
from openzyme_workspace_git_lfs import compare_agent_git_workspace_identity


BASE_COMMIT = "8ae3d73b3054f2058ff33ea183f62c811b9272a3"


def _workspace() -> AgentGitWorkspace:
    return AgentGitWorkspace.create(
        workspace_id="workspace_1",
        session_id="session_1",
        agent_member_id="member_1",
        agent_id="agent:master",
        workspace_generation=1,
        reservation_id="reservation_1",
        reservation_fingerprint=f"sha256:{'1' * 64}",
        capability_lease_id="lease_1",
        capability_lease_intent_digest=f"sha256:{'2' * 64}",
        repository_binding_id="binding_1",
        repository_binding_version=1,
        repository_binding_digest=f"sha256:{'3' * 64}",
        repository_id="repository_1",
        internal_git_service_id="git_service_1",
        internal_git_endpoint="https://git.internal/repositories/repository_1.git",
        object_format=GitObjectFormat.SHA1,
        base_commit=BASE_COMMIT,
        volume_id="volume_session_1_member_1_g1",
        clone_logical_root="/workspace/repository",
        image_ref="localhost/openzyme-agent-capsule@sha256:" + "a" * 64,
        image_manifest_digest=f"sha256:{'6' * 64}",
        image_qualification_digest=f"sha256:{'7' * 64}",
        private_ref_namespace="refs/openzyme/private/session_1/member_1/g1",
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=f"sha256:{'4' * 64}",
        capability_policy_version="agent-capability-policy-v1",
        capability_policy_digest=f"sha256:{'5' * 64}",
        status=AgentGitWorkspaceStatus.PROVISIONING,
        state_version=1,
        created_at="2026-08-16T01:00:00+00:00",
        updated_at="2026-08-16T01:00:00+00:00",
    )


def _observation(
    workspace: AgentGitWorkspace,
    **overrides: object,
) -> AgentGitWorkspaceObservation:
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
        "observed_at": "2026-08-16T01:01:00+00:00",
    }
    values.update(overrides)
    return AgentGitWorkspaceObservation(**values)  # type: ignore[arg-type]


def test_workspace_identity_digest_binds_generation_volume_and_pending_intent() -> None:
    workspace = _workspace()

    assert workspace.to_dict()["workspace_identity_digest"] == (
        workspace.workspace_identity_digest
    )
    assert workspace.to_dict()["capability_lease_intent_digest"] == (
        f"sha256:{'2' * 64}"
    )
    assert workspace.to_dict()["volume_id"] == "volume_session_1_member_1_g1"


def test_restore_comparison_checks_head_readability_generation_and_policy() -> None:
    workspace = _workspace()
    comparison = compare_agent_git_workspace_identity(
        workspace,
        _observation(
            workspace,
            workspace_generation=2,
            head_commit=None,
            head_tree=None,
            head_readable=False,
            repository_policy_digest=f"sha256:{'9' * 64}",
        ),
    )

    assert comparison.drift == (
        AgentGitWorkspaceIdentityDriftKind.GENERATION,
        AgentGitWorkspaceIdentityDriftKind.HEAD_UNREADABLE,
        AgentGitWorkspaceIdentityDriftKind.POLICY,
    )


def test_observation_rejects_host_path_escape_and_credentialled_remote() -> None:
    workspace = _workspace()

    with pytest.raises(ValueError, match="escape"):
        _observation(workspace, clone_logical_root="/workspace/../host")
    with pytest.raises(ValueError, match="credential-free"):
        _observation(
            workspace,
            internal_git_endpoint=(
                "https://secret@git.internal/repositories/repository_1.git"
            ),
        )


def test_ready_workspace_requires_complete_observed_identity() -> None:
    workspace = _workspace()
    values = {
        field_name: getattr(workspace, field_name)
        for field_name in workspace.__dataclass_fields__
        if field_name not in {"workspace_identity_digest", "canonical_digest"}
    }
    values.update(
        status=AgentGitWorkspaceStatus.READY,
        state_version=2,
        updated_at="2026-08-16T01:01:00+00:00",
    )

    with pytest.raises(ValueError, match="head_commit is required"):
        AgentGitWorkspace.create(**values)


class _VolumeAllocator:
    def allocate(self, **kwargs: object) -> AgentWorkspaceVolumeFact:
        return AgentWorkspaceVolumeFact(
            volume_id="volume_session_1_member_1_g1",
            labels=tuple(
                sorted(
                    {
                        "io.openzyme.workspace_id": str(kwargs["workspace_id"]),
                        "io.openzyme.session_id": str(kwargs["session_id"]),
                        "io.openzyme.agent_member_id": str(
                            kwargs["agent_member_id"]
                        ),
                        "io.openzyme.workspace_generation": str(
                            kwargs["workspace_generation"]
                        ),
                        "io.openzyme.volume_schema": "agent_workspace_volume@1",
                    }.items()
                )
            ),
        )


class _CloneRunner:
    def clone_exact_base(
        self,
        *,
        workspace: AgentGitWorkspace,
        credential_token: str,
    ) -> AgentWorkspaceCloneResult:
        assert credential_token == "secret-process-token"
        return AgentWorkspaceCloneResult(
            returncode=0,
            stdout="",
            stderr="",
            head_commit=workspace.base_commit,
            head_tree="1" * 40,
            object_format=workspace.object_format,
            remote_endpoint=workspace.internal_git_endpoint,
            independent_git_directory=True,
        )


class _VolumeBackend:
    def __init__(self, fact: AgentWorkspaceVolumeFact | None) -> None:
        self.fact = fact

    def inspect(self, volume_id: str) -> AgentWorkspaceVolumeFact | None:
        if self.fact is not None:
            assert self.fact.volume_id == volume_id
        return self.fact

    def create(
        self,
        volume_id: str,
        *,
        labels: tuple[tuple[str, str], ...],
    ) -> AgentWorkspaceVolumeFact:
        raise AssertionError((volume_id, labels))


class _ObservationProvider:
    def __init__(self, observation: AgentGitWorkspaceObservation) -> None:
        self.observation = observation

    def observe(self, workspace: AgentGitWorkspace) -> AgentGitWorkspaceObservation:
        assert workspace.workspace_id == self.observation.workspace_id
        return self.observation


def test_provisioning_mechanism_returns_exact_volume_and_clone_observation() -> None:
    workspace = _workspace()
    mechanism = AgentGitWorkspaceProvisioningMechanism(
        volume_allocator=_VolumeAllocator(),
        clone_runner=_CloneRunner(),
    )

    volume_id = mechanism.allocate_volume(
        workspace_id=workspace.workspace_id,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        workspace_generation=workspace.workspace_generation,
    )
    observation = mechanism.clone_and_observe(
        workspace=workspace,
        credential_token="secret-process-token",
    )

    assert volume_id == workspace.volume_id
    assert observation.workspace_id == workspace.workspace_id
    assert observation.head_commit == workspace.base_commit
    assert observation.git_directory_kind is AgentGitDirectoryKind.INDEPENDENT


def test_recovery_mechanism_classifies_missing_volume_without_observing_git() -> None:
    workspace = _workspace()
    mechanism = AgentGitWorkspaceRecoveryMechanism(
        volume_backend=_VolumeBackend(None),
        observation_provider=_ObservationProvider(_observation(workspace)),
    )

    probe = mechanism.probe(workspace)

    assert probe.observation is None
    assert probe.blocker_code is AgentGitWorkspaceBlockerCode.MISSING_VOLUME
    assert probe.private_error is None


def test_recovery_mechanism_returns_observation_without_canonical_mutation() -> None:
    workspace = _workspace()
    volume = _VolumeAllocator().allocate(
        workspace_id=workspace.workspace_id,
        session_id=workspace.session_id,
        agent_member_id=workspace.agent_member_id,
        workspace_generation=workspace.workspace_generation,
    )
    expected = _observation(workspace)
    mechanism = AgentGitWorkspaceRecoveryMechanism(
        volume_backend=_VolumeBackend(volume),
        observation_provider=_ObservationProvider(expected),
    )

    probe = mechanism.probe(workspace)

    assert probe.observation == expected
    assert probe.blocker_code is None
    assert workspace.status is AgentGitWorkspaceStatus.PROVISIONING
