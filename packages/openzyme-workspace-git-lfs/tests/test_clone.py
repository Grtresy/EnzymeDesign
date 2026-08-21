from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_workspace_git_lfs import AgentGitWorkspace
from openzyme_workspace_git_lfs import AgentGitWorkspaceProvisioningError
from openzyme_workspace_git_lfs import AgentGitWorkspaceStatus
from openzyme_workspace_git_lfs import PodmanAgentWorkspaceCloneRunner


@dataclass(frozen=True, slots=True)
class _Result:
    returncode: int
    stdout: str
    stderr: str


class _Executor:
    def __init__(self, result: _Result) -> None:
        self.result = result
        self.calls: list[tuple[tuple[str, ...], dict[str, str] | None]] = []

    def run(self, argv, *, environment=None):  # type: ignore[no-untyped-def]
        self.calls.append((tuple(argv), environment))
        return self.result


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
        base_commit="8ae3d73b3054f2058ff33ea183f62c811b9272a3",
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


def test_clone_uses_exact_volume_and_keeps_credential_out_of_argv() -> None:
    workspace = _workspace()
    output = "\n".join(
        (
            f"OPENZYME_REMOTE={workspace.internal_git_endpoint}",
            "OPENZYME_OBJECT_FORMAT=sha1",
            f"OPENZYME_HEAD={workspace.base_commit}",
            f"OPENZYME_TREE={'2' * 40}",
            "OPENZYME_GIT_DIRECTORY=independent",
        )
    )
    executor = _Executor(_Result(0, output, ""))
    runner = PodmanAgentWorkspaceCloneRunner(
        executor=executor,
        deployment_network="openzyme-agent-network",
    )
    token = "ozprovision1.secret.payload"

    result = runner.clone_exact_base(
        workspace=workspace,
        credential_token=token,
    )

    argv, environment = executor.calls[0]
    assert result.head_commit == workspace.base_commit
    assert result.head_tree == "2" * 40
    assert f"{workspace.volume_id}:/workspace:rw,U" in argv
    assert token not in " ".join(argv)
    assert environment == {
        "PATH": "/usr/bin:/bin",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "http.extraHeader",
        "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {token}",
    }
    assert "--reference" not in argv
    assert "worktree" not in argv


def test_clone_rejects_missing_or_ambiguous_identity_receipt() -> None:
    executor = _Executor(_Result(0, "OPENZYME_HEAD=abc\n", ""))
    runner = PodmanAgentWorkspaceCloneRunner(
        executor=executor,
        deployment_network="openzyme-agent-network",
    )

    with pytest.raises(
        AgentGitWorkspaceProvisioningError,
        match="omitted or added identity",
    ):
        runner.clone_exact_base(
            workspace=_workspace(),
            credential_token="scoped-token",
        )


def test_clone_rejects_unsafe_network_and_absent_credential() -> None:
    with pytest.raises(ValueError, match="safe Podman network"):
        PodmanAgentWorkspaceCloneRunner(
            executor=_Executor(_Result(0, "", "")),
            deployment_network="network with spaces",
        )
    runner = PodmanAgentWorkspaceCloneRunner(
        executor=_Executor(_Result(0, "", "")),
        deployment_network="openzyme-agent-network",
    )
    with pytest.raises(AgentGitWorkspaceProvisioningError, match="credential"):
        runner.clone_exact_base(workspace=_workspace(), credential_token="")
