from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Protocol

from openzyme_contracts import GitObjectFormat

from .agent_workspaces import AgentGitDirectoryKind
from .agent_workspaces import AgentGitWorkspace
from .agent_workspaces import AgentGitWorkspaceObservation


_RESTORE_OBSERVATION_SCRIPT = r"""
set -eu
remote=$(git remote get-url origin) || exit 41
object_format=$(git rev-parse --show-object-format) || exit 42
head_commit=$(git rev-parse --verify HEAD) || exit 43
head_tree=$(git rev-parse --verify 'HEAD^{tree}') || exit 44
git cat-file -e "${1}^{commit}" || exit 45
git_dir=$(git rev-parse --git-dir) || exit 46
git_kind=corrupt
if [ "$git_dir" = ".git" ] && [ -d .git ]; then
  git_kind=independent
fi
if [ -f .git ]; then
  git_kind=linked_worktree
fi
if [ -e .git/commondir ] || [ -s .git/objects/info/alternates ]; then
  git_kind=shared
fi
printf 'OPENZYME_REMOTE=%s\n' "$remote"
printf 'OPENZYME_OBJECT_FORMAT=%s\n' "$object_format"
printf 'OPENZYME_HEAD=%s\n' "$head_commit"
printf 'OPENZYME_TREE=%s\n' "$head_tree"
printf 'OPENZYME_GIT_DIRECTORY=%s\n' "$git_kind"
""".strip()


class AgentGitWorkspaceRecoveryError(RuntimeError):
    error_code = "agent_git_workspace_recovery_rejected"


class AgentGitWorkspaceCorruptionError(AgentGitWorkspaceRecoveryError):
    error_code = "agent_git_workspace_corruption_proven"


class AgentGitWorkspaceBaseCommitDriftError(AgentGitWorkspaceRecoveryError):
    error_code = "agent_git_workspace_identity_drift"


class AgentGitWorkspaceInfrastructureError(AgentGitWorkspaceRecoveryError):
    error_code = "agent_git_workspace_infrastructure_unavailable"


class AgentGitWorkspacePermissionError(AgentGitWorkspaceRecoveryError):
    error_code = "agent_git_workspace_permission_or_configuration_failure"


class AgentGitWorkspaceInvariantError(AgentGitWorkspaceRecoveryError):
    error_code = "agent_git_workspace_internal_invariant_failure"


class AgentGitWorkspaceObservationProvider(Protocol):
    def observe(
        self,
        workspace: AgentGitWorkspace,
    ) -> AgentGitWorkspaceObservation: ...


class WorkspaceObservationProcessResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class WorkspaceObservationProcessRunner(Protocol):
    def run(
        self,
        *,
        workspace: AgentGitWorkspace,
        argv: tuple[str, ...],
        credential_environment: tuple[tuple[str, str], ...],
        timeout_seconds: int,
    ) -> WorkspaceObservationProcessResult: ...


@dataclass(slots=True)
class PodmanAgentGitWorkspaceObservationProvider:
    """Read-only Git identity probe over an injected workspace process port."""

    process_runner: WorkspaceObservationProcessRunner

    def observe(self, workspace: AgentGitWorkspace) -> AgentGitWorkspaceObservation:
        try:
            result = self.process_runner.run(
                workspace=workspace,
                argv=(
                    "/bin/sh",
                    "-c",
                    _RESTORE_OBSERVATION_SCRIPT,
                    "openzyme-workspace-restore",
                    workspace.base_commit,
                ),
                credential_environment=(),
                timeout_seconds=120,
            )
        except PermissionError as exc:
            raise AgentGitWorkspacePermissionError(
                "workspace observation process was denied"
            ) from exc
        except OSError as exc:
            raise AgentGitWorkspaceInfrastructureError(
                "workspace observation process was unavailable"
            ) from exc
        if result.returncode != 0:
            error_type: type[AgentGitWorkspaceRecoveryError]
            if result.returncode == 41:
                error_type = AgentGitWorkspacePermissionError
            elif result.returncode in {42, 43, 44, 46}:
                error_type = AgentGitWorkspaceCorruptionError
            elif result.returncode == 45:
                error_type = AgentGitWorkspaceBaseCommitDriftError
            else:
                error_type = AgentGitWorkspaceInvariantError
            error = error_type(
                f"workspace restore probe exited at typed stage {result.returncode}"
            )
            error.returncode = result.returncode  # type: ignore[attr-defined]
            error.stderr = result.stderr  # type: ignore[attr-defined]
            raise error
        facts = _parse_restore_facts(result.stdout)
        return AgentGitWorkspaceObservation(
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            volume_id=workspace.volume_id,
            clone_logical_root=workspace.clone_logical_root,
            git_directory_kind=AgentGitDirectoryKind(
                facts["OPENZYME_GIT_DIRECTORY"]
            ),
            internal_git_service_id=workspace.internal_git_service_id,
            internal_git_endpoint=facts["OPENZYME_REMOTE"],
            repository_id=workspace.repository_id,
            object_format=GitObjectFormat(facts["OPENZYME_OBJECT_FORMAT"]),
            base_commit=workspace.base_commit,
            head_commit=facts["OPENZYME_HEAD"],
            head_tree=facts["OPENZYME_TREE"],
            head_readable=True,
            private_ref_namespace=workspace.private_ref_namespace,
            repository_policy_digest=workspace.repository_policy_digest,
            capability_policy_digest=workspace.capability_policy_digest,
            observed_at=datetime.now(tz=UTC).isoformat(),
        )


def _parse_restore_facts(value: str) -> dict[str, str]:
    facts: dict[str, str] = {}
    for line in value.splitlines():
        key, separator, item = line.partition("=")
        if separator and key.startswith("OPENZYME_"):
            if key in facts:
                raise AgentGitWorkspaceRecoveryError(
                    "workspace restore probe output is ambiguous"
                )
            facts[key] = item
    required = {
        "OPENZYME_REMOTE",
        "OPENZYME_OBJECT_FORMAT",
        "OPENZYME_HEAD",
        "OPENZYME_TREE",
        "OPENZYME_GIT_DIRECTORY",
    }
    if set(facts) != required or any(not item for item in facts.values()):
        raise AgentGitWorkspaceRecoveryError(
            "workspace restore probe output is incomplete"
        )
    return facts


__all__ = [
    "AgentGitWorkspaceBaseCommitDriftError",
    "AgentGitWorkspaceCorruptionError",
    "AgentGitWorkspaceInfrastructureError",
    "AgentGitWorkspaceInvariantError",
    "AgentGitWorkspaceObservationProvider",
    "AgentGitWorkspacePermissionError",
    "AgentGitWorkspaceRecoveryError",
    "PodmanAgentGitWorkspaceObservationProvider",
    "WorkspaceObservationProcessResult",
    "WorkspaceObservationProcessRunner",
]
