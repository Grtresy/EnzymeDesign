"""Git clean/dirty observation mechanism for an Agent-owned workspace."""

from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import AgentWorkspaceStateObservation
from openzyme_contracts import WorkspaceDirtyState

from .agent_workspaces import AgentGitWorkspace


WORKSPACE_STATUS_SCRIPT = r"""
set -eu
head_commit=$(git rev-parse --verify HEAD)
head_tree=$(git rev-parse --verify 'HEAD^{tree}')
printf 'OPENZYME_HEAD=%s\nOPENZYME_TREE=%s\n' "$head_commit" "$head_tree"
git status --porcelain=v1 --untracked-files=normal | awk '
BEGIN { staged=0; unstaged=0; untracked=0; count=0 }
substr($0,1,2)=="??" { untracked=1 }
substr($0,1,1)!=" " { staged=1 }
substr($0,2,1)!=" " { unstaged=1 }
{ if (count < 2000) printf "OPENZYME_CHANGE=%s\n", substr($0,4); count++ }
END {
  printf "OPENZYME_STAGED=%d\n", staged
  printf "OPENZYME_UNSTAGED=%d\n", unstaged
  printf "OPENZYME_UNTRACKED=%d\n", untracked
  printf "OPENZYME_CHANGE_TRUNCATED=%d\n", count > 2000
}
'
""".strip()


class AgentGitWorkspaceStatusError(RuntimeError):
    error_code = "agent_git_workspace_status_invalid"


@dataclass(frozen=True, slots=True)
class AgentGitWorkspaceStatusMechanism:
    """Return exact argv and parse bounded native Git status facts."""

    def command_argv(self) -> tuple[str, ...]:
        return ("/bin/sh", "-c", WORKSPACE_STATUS_SCRIPT)

    def observe(
        self,
        *,
        workspace: AgentGitWorkspace,
        stdout: str,
        observation_id: str,
        observed_at: str,
    ) -> AgentWorkspaceStateObservation:
        facts = parse_workspace_status_output(stdout)
        changed_paths = facts["OPENZYME_CHANGE"]
        if not isinstance(changed_paths, list) or not all(
            isinstance(path, str) for path in changed_paths
        ):
            raise AgentGitWorkspaceStatusError(
                "native Git changed path list is invalid"
            )
        staged = facts["OPENZYME_STAGED"] == "1"
        unstaged = facts["OPENZYME_UNSTAGED"] == "1"
        untracked = facts["OPENZYME_UNTRACKED"] == "1"
        return AgentWorkspaceStateObservation(
            observation_id=observation_id,
            workspace_id=workspace.workspace_id,
            session_id=workspace.session_id,
            agent_member_id=workspace.agent_member_id,
            agent_id=workspace.agent_id,
            workspace_generation=workspace.workspace_generation,
            head_commit=str(facts["OPENZYME_HEAD"]),
            head_tree=str(facts["OPENZYME_TREE"]),
            dirty_state=(
                WorkspaceDirtyState.DIRTY
                if staged or unstaged or untracked
                else WorkspaceDirtyState.CLEAN
            ),
            staged=staged,
            unstaged=unstaged,
            untracked=untracked,
            changed_paths=tuple(changed_paths),
            changed_paths_truncated=(
                facts["OPENZYME_CHANGE_TRUNCATED"] == "1"
            ),
            observed_at=observed_at,
        )


def parse_workspace_status_output(value: str) -> dict[str, object]:
    facts: dict[str, object] = {"OPENZYME_CHANGE": []}
    for line in value.splitlines():
        key, separator, item = line.partition("=")
        if separator and key.startswith("OPENZYME_"):
            if key == "OPENZYME_CHANGE":
                changes = facts[key]
                if not isinstance(changes, list):
                    raise AgentGitWorkspaceStatusError(
                        "native Git changed path list is invalid"
                    )
                changes.append(item)
            else:
                facts[key] = item
    required = {
        "OPENZYME_HEAD",
        "OPENZYME_TREE",
        "OPENZYME_STAGED",
        "OPENZYME_UNSTAGED",
        "OPENZYME_UNTRACKED",
        "OPENZYME_CHANGE",
        "OPENZYME_CHANGE_TRUNCATED",
    }
    if set(facts) != required:
        raise AgentGitWorkspaceStatusError("native Git status output is incomplete")
    dirty_flag_keys = {
        "OPENZYME_STAGED",
        "OPENZYME_UNSTAGED",
        "OPENZYME_UNTRACKED",
    }
    if any(facts[key] not in {"0", "1"} for key in dirty_flag_keys) or facts[
        "OPENZYME_CHANGE_TRUNCATED"
    ] not in {"0", "1"}:
        raise AgentGitWorkspaceStatusError("native Git dirty flags are invalid")
    return facts


__all__ = [
    "AgentGitWorkspaceStatusError",
    "AgentGitWorkspaceStatusMechanism",
    "WORKSPACE_STATUS_SCRIPT",
    "parse_workspace_status_output",
]
