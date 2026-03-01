from __future__ import annotations

from dataclasses import dataclass
import shlex
import subprocess


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str


class CommandRunner:
    def run(self, args: list[str], check: bool = False) -> CommandResult:
        proc = subprocess.run(args, capture_output=True, text=True, check=False)
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({proc.returncode}): {shlex.join(args)}\n{proc.stderr}"
            )
        return CommandResult(
            args=args,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
        )


def make_remote_shell_command(cwd: str, argv: list[str]) -> list[str]:
    return make_remote_shell_command_with_env(cwd, argv, env=None)


def make_remote_shell_command_with_env(
    cwd: str, argv: list[str], env: dict[str, str] | None
) -> list[str]:
    exports = ""
    if env:
        # Use explicit exports so both ssh and sbatch can share layout hints.
        # Note: RunSpec.command is argv (not a shell snippet), so callers that
        # want to use these variables should read them from the process env.
        exports = "; ".join(
            f"export {key}={shlex.quote(value)}" for key, value in env.items()
        )
        exports = exports + "; "
    command = f"{exports}cd {shlex.quote(cwd)} && {shlex.join(argv)}"
    return ["bash", "-lc", command]


def wrap_ssh(target: str, remote_argv: list[str]) -> list[str]:
    return [
        "ssh",
        "-o",
        "BatchMode=yes",
        target,
        "--",
        shlex.join(remote_argv),
    ]
