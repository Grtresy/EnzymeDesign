from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import GitObjectFormat
from openzyme_workspace_git_lfs import AgentGitDirectoryKind
from openzyme_workspace_git_lfs import AgentGitWorkspace
from openzyme_workspace_git_lfs import AgentGitWorkspaceBaseCommitDriftError
from openzyme_workspace_git_lfs import AgentGitWorkspaceCorruptionError
from openzyme_workspace_git_lfs import AgentGitWorkspacePermissionError
from openzyme_workspace_git_lfs import AgentGitWorkspaceRecoveryError
from openzyme_workspace_git_lfs import AgentGitWorkspaceStatus
from openzyme_workspace_git_lfs import PodmanAgentGitWorkspaceObservationProvider


@dataclass(frozen=True, slots=True)
class _Result:
    returncode: int
    stdout: str = ""
    stderr: str = ""


class _Runner:
    def __init__(self, result: _Result | BaseException) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    def run(self, **kwargs):  # type: ignore[no-untyped-def]
        self.calls.append(dict(kwargs))
        if isinstance(self.result, BaseException):
            raise self.result
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


def test_observation_reconstructs_exact_git_identity_without_credentials() -> None:
    workspace = _workspace()
    runner = _Runner(
        _Result(
            0,
            "\n".join(
                (
                    f"OPENZYME_REMOTE={workspace.internal_git_endpoint}",
                    "OPENZYME_OBJECT_FORMAT=sha1",
                    f"OPENZYME_HEAD={workspace.base_commit}",
                    f"OPENZYME_TREE={'9' * 40}",
                    "OPENZYME_GIT_DIRECTORY=independent",
                )
            ),
        )
    )

    observed = PodmanAgentGitWorkspaceObservationProvider(runner).observe(workspace)

    assert observed.head_commit == workspace.base_commit
    assert observed.head_tree == "9" * 40
    assert observed.git_directory_kind is AgentGitDirectoryKind.INDEPENDENT
    assert runner.calls[0]["credential_environment"] == ()
    assert runner.calls[0]["timeout_seconds"] == 120


@pytest.mark.parametrize(
    ("returncode", "error_type"),
    [
        (41, AgentGitWorkspacePermissionError),
        (42, AgentGitWorkspaceCorruptionError),
        (45, AgentGitWorkspaceBaseCommitDriftError),
    ],
)
def test_observation_classifies_typed_probe_stage(
    returncode: int,
    error_type: type[AgentGitWorkspaceRecoveryError],
) -> None:
    provider = PodmanAgentGitWorkspaceObservationProvider(
        _Runner(_Result(returncode, stderr="private native detail"))
    )

    with pytest.raises(error_type) as caught:
        provider.observe(_workspace())

    assert getattr(caught.value, "returncode") == returncode
    assert getattr(caught.value, "stderr") == "private native detail"


def test_observation_rejects_duplicate_or_incomplete_fact_output() -> None:
    provider = PodmanAgentGitWorkspaceObservationProvider(
        _Runner(_Result(0, "OPENZYME_HEAD=a\nOPENZYME_HEAD=b\n"))
    )

    with pytest.raises(AgentGitWorkspaceRecoveryError, match="ambiguous"):
        provider.observe(_workspace())
