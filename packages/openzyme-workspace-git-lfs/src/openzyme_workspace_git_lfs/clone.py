from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Protocol

from openzyme_contracts import GitObjectFormat

from .agent_workspaces import AgentGitWorkspace
from .agent_workspaces import AgentGitWorkspaceStatus


_SAFE_NETWORK_NAME = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}")


class AgentGitWorkspaceProvisioningError(RuntimeError):
    error_code = "agent_git_workspace_provisioning_failed"


@dataclass(frozen=True, slots=True)
class AgentWorkspaceCloneResult:
    returncode: int
    stdout: str
    stderr: str
    head_commit: str | None = None
    head_tree: str | None = None
    object_format: GitObjectFormat | None = None
    remote_endpoint: str | None = None
    independent_git_directory: bool = False


class AgentWorkspaceCloneRunner(Protocol):
    def clone_exact_base(
        self,
        *,
        workspace: AgentGitWorkspace,
        credential_token: str,
    ) -> AgentWorkspaceCloneResult: ...


class CloneCommandResult(Protocol):
    returncode: int
    stdout: str
    stderr: str


class CloneCommandExecutor(Protocol):
    def run(
        self,
        argv: tuple[str, ...],
        *,
        environment: dict[str, str] | None = None,
    ) -> CloneCommandResult: ...


@dataclass(slots=True)
class PodmanAgentWorkspaceCloneRunner:
    """Git/LFS Adapter clone mechanism executed in an injected Podman command port."""

    executor: CloneCommandExecutor
    deployment_network: str
    podman_binary: str = "/usr/bin/podman"

    def __post_init__(self) -> None:
        if _SAFE_NETWORK_NAME.fullmatch(self.deployment_network) is None:
            raise ValueError("deployment_network is not a safe Podman network name")

    def clone_exact_base(
        self,
        *,
        workspace: AgentGitWorkspace,
        credential_token: str,
    ) -> AgentWorkspaceCloneResult:
        if workspace.status is not AgentGitWorkspaceStatus.PROVISIONING:
            raise AgentGitWorkspaceProvisioningError(
                "clone runner requires an exact provisioning workspace"
            )
        if not credential_token:
            raise AgentGitWorkspaceProvisioningError(
                "clone runner requires a process-scoped provision credential"
            )
        script = r"""
set -euo pipefail
remote_endpoint="$1"
base_commit="$2"
expected_object_format="$3"
clone_root="$4"
test "${clone_root}" = "/workspace/repository"
test ! -e "${clone_root}"
git clone --no-checkout -- "${remote_endpoint}" "${clone_root}"
test -d "${clone_root}/.git"
test ! -f "${clone_root}/.git"
test ! -e "${clone_root}/.git/objects/info/alternates"
git -C "${clone_root}" checkout --detach "${base_commit}"
observed_remote="$(git -C "${clone_root}" remote get-url origin)"
observed_format="$(git -C "${clone_root}" rev-parse --show-object-format)"
observed_head="$(git -C "${clone_root}" rev-parse --verify HEAD^{commit})"
observed_tree="$(git -C "${clone_root}" rev-parse --verify HEAD^{tree})"
test "${observed_remote}" = "${remote_endpoint}"
test "${observed_format}" = "${expected_object_format}"
test "${observed_head}" = "${base_commit}"
git -C "${clone_root}" fsck --no-dangling --no-reflogs
printf 'OPENZYME_REMOTE=%s\n' "${observed_remote}"
printf 'OPENZYME_OBJECT_FORMAT=%s\n' "${observed_format}"
printf 'OPENZYME_HEAD=%s\n' "${observed_head}"
printf 'OPENZYME_TREE=%s\n' "${observed_tree}"
printf 'OPENZYME_GIT_DIRECTORY=independent\n'
""".strip()
        environment = {
            "PATH": "/usr/bin:/bin",
            "GIT_CONFIG_COUNT": "1",
            "GIT_CONFIG_KEY_0": "http.extraHeader",
            "GIT_CONFIG_VALUE_0": f"Authorization: Bearer {credential_token}",
        }
        result = self.executor.run(
            (
                self.podman_binary,
                "run",
                "--rm",
                "--network",
                self.deployment_network,
                "--read-only",
                "--user",
                "10001:10001",
                "--cap-drop=all",
                "--security-opt=no-new-privileges",
                "--tmpfs",
                "/tmp:rw,nosuid,nodev,noexec,uid=10001,gid=10001,mode=0700",
                "--volume",
                f"{workspace.volume_id}:/workspace:rw,U",
                "--workdir",
                "/workspace",
                "--env",
                "GIT_CONFIG_COUNT",
                "--env",
                "GIT_CONFIG_KEY_0",
                "--env",
                "GIT_CONFIG_VALUE_0",
                workspace.image_ref,
                "/bin/bash",
                "-euo",
                "pipefail",
                "-c",
                script,
                "openzyme-clone",
                workspace.internal_git_endpoint,
                workspace.base_commit,
                workspace.object_format.value,
                workspace.clone_logical_root,
            ),
            environment=environment,
        )
        parsed = _parse_clone_output(result.stdout) if result.returncode == 0 else {}
        return AgentWorkspaceCloneResult(
            returncode=result.returncode,
            stdout=result.stdout,
            stderr=result.stderr,
            head_commit=parsed.get("OPENZYME_HEAD"),
            head_tree=parsed.get("OPENZYME_TREE"),
            object_format=(
                None
                if "OPENZYME_OBJECT_FORMAT" not in parsed
                else GitObjectFormat(parsed["OPENZYME_OBJECT_FORMAT"])
            ),
            remote_endpoint=parsed.get("OPENZYME_REMOTE"),
            independent_git_directory=(
                parsed.get("OPENZYME_GIT_DIRECTORY") == "independent"
            ),
        )


def _parse_clone_output(stdout: str) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for line in stdout.splitlines():
        if not line.startswith("OPENZYME_"):
            continue
        key, separator, value = line.partition("=")
        if separator != "=" or not value or key in parsed:
            raise AgentGitWorkspaceProvisioningError(
                "clone runner returned ambiguous identity output"
            )
        parsed[key] = value
    required = {
        "OPENZYME_REMOTE",
        "OPENZYME_OBJECT_FORMAT",
        "OPENZYME_HEAD",
        "OPENZYME_TREE",
        "OPENZYME_GIT_DIRECTORY",
    }
    if set(parsed) != required:
        raise AgentGitWorkspaceProvisioningError(
            "clone runner omitted or added identity output fields"
        )
    return parsed


__all__ = [
    "AgentGitWorkspaceProvisioningError",
    "AgentWorkspaceCloneResult",
    "AgentWorkspaceCloneRunner",
    "CloneCommandExecutor",
    "CloneCommandResult",
    "PodmanAgentWorkspaceCloneRunner",
]
