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
    command = f"cd {shlex.quote(cwd)} && {shlex.join(argv)}"
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
