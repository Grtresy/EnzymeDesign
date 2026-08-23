import subprocess

from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_workspace_git_lfs import LocalGitLfsQualificationOperation
from openzyme_workspace_git_lfs import LocalGitLfsQualificationState
from openzyme_workspace_git_lfs import SubprocessLocalGitLfsQualificationCommandPort


DIGEST = "sha256:" + "1" * 64


def _request(operation: str) -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.git-lfs.{operation}",
        plan_digest=DIGEST,
        unit_digest=DIGEST,
        operation=operation,
        timeout_seconds=120,
        input_digest=DIGEST,
        expected_result_schema_digest=DIGEST,
        credential_locator_id=None,
    )


def test_local_git_lfs_qualification_runs_real_isolated_repository_and_restores_reconcile(
    tmp_path,
) -> None:
    repository = tmp_path / "qualification.git"
    subprocess.run(
        ("git", "init", "--bare", str(repository)),
        check=True,
        capture_output=True,
        text=True,
    )
    subprocess.run(
        ("git", "--git-dir", str(repository), "lfs", "install", "--local"),
        check=True,
        capture_output=True,
        text=True,
    )
    workspace = tmp_path / "workspace"
    state = LocalGitLfsQualificationState(
        repository=repository,
        workspace=workspace,
        command_port=SubprocessLocalGitLfsQualificationCommandPort(),
    )

    for operation in ("clone", "checkpoint", "publish", "lfs-fetch"):
        outcome = LocalGitLfsQualificationOperation(
            component_id="openzyme.workspace.git.lfs",
            route_id=f"openzyme.workspace.git.lfs.{operation}@1",
            subject_digest=DIGEST,
            state=state,
        ).dispatch(_request(operation))
        assert outcome.succeeded is True

    request = _request("response-loss-reconcile")
    first = LocalGitLfsQualificationOperation(
        component_id="openzyme.workspace.git.lfs",
        route_id="openzyme.workspace.git.lfs.response-loss-reconcile@1",
        subject_digest=DIGEST,
        state=state,
    ).dispatch(request)
    assert first.terminal is False

    restored_state = LocalGitLfsQualificationState(
        repository=repository,
        workspace=workspace,
        command_port=SubprocessLocalGitLfsQualificationCommandPort(),
    )
    restored = LocalGitLfsQualificationOperation(
        component_id="openzyme.workspace.git.lfs",
        route_id="openzyme.workspace.git.lfs.response-loss-reconcile@1",
        subject_digest=DIGEST,
        state=restored_state,
    )
    restored.restore_dispatched_attempt(request)

    terminal = restored.reconcile(request)

    assert terminal.succeeded is True
    assert restored_state.cleanup() == {
        "workspace_removed": True,
        "repository_preserved": True,
    }
    assert repository.is_dir()
