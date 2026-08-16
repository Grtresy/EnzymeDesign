from __future__ import annotations

import pytest

from openzyme_domain import AgentGitDirectoryKind
from openzyme_domain import AgentGitWorkspace
from openzyme_domain import AgentGitWorkspaceIdentityDriftKind
from openzyme_domain import AgentGitWorkspaceObservation
from openzyme_domain import AgentGitWorkspaceStatus
from openzyme_domain import GitObjectFormat
from openzyme_domain import compare_agent_git_workspace_identity


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
