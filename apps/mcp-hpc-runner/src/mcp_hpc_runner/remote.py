from __future__ import annotations

from dataclasses import dataclass
import shlex
import subprocess
import time

from .transport import compile_legacy_ssh


@dataclass(slots=True)
class CommandResult:
    args: list[str]
    returncode: int
    stdout: str
    stderr: str
    stage: str | None = None
    timed_out: bool = False
    elapsed_seconds: float = 0.0
    process_started: bool = True


class CommandRunner:
    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
        input_text: str | None = None,
    ) -> CommandResult:
        started_at = time.monotonic()
        try:
            proc = subprocess.run(
                args,
                capture_output=True,
                text=True,
                input=input_text,
                check=False,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_seconds = time.monotonic() - started_at
            stdout = "" if exc.stdout is None else str(exc.stdout)
            stderr = "" if exc.stderr is None else str(exc.stderr)
            if stderr:
                stderr = stderr.rstrip() + "\n"
            stderr += f"Command timed out after {timeout} seconds"
            result = CommandResult(
                args=args,
                returncode=124,
                stdout=stdout,
                stderr=stderr,
                stage=stage,
                timed_out=True,
                elapsed_seconds=elapsed_seconds,
            )
            if check:
                raise RuntimeError(
                    f"Command timed out ({stage or 'unknown'}): {shlex.join(args)}\n{stderr}"
                )
            return result
        except OSError as exc:
            elapsed_seconds = time.monotonic() - started_at
            result = CommandResult(
                args=args,
                returncode=127,
                stdout="",
                stderr=str(exc),
                stage=stage,
                elapsed_seconds=elapsed_seconds,
                process_started=False,
            )
            if check:
                raise RuntimeError(
                    f"Command could not start ({stage or 'unknown'}): "
                    f"{shlex.join(args)}\n{exc}"
                ) from exc
            return result
        elapsed_seconds = time.monotonic() - started_at
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({proc.returncode}): {shlex.join(args)}\n{proc.stderr}"
            )
        return CommandResult(
            args=args,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            stage=stage,
            elapsed_seconds=elapsed_seconds,
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
    layout_vars = (
        "WORKDIR",
        "OUTDIR",
        "MCP_RUN_DIR",
        "MCP_WORKDIR",
        "MCP_OUTDIR",
        "MCP_TMPDIR",
        "MCP_LOGDIR",
    )
    normalize = (
        'anchor="${PWD}"; '
        "_oz_abspath() { "
        'case "$1" in '
        "/*) printf '%s' \"$1\" ;; "
        "~) printf '%s' \"$HOME\" ;; "
        "~/*) printf '%s/%s' \"$HOME\" \"${1#~/}\" ;; "
        "*) printf '%s/%s' \"$anchor\" \"$1\" ;; "
        "esac; "
        "}; "
    )
    if env:
        normalize += " ".join(
            (
                f'if [[ -n "${{{key}:-}}" ]]; then '
                f'{key}="$(_oz_abspath "${{{key}}}")"; export {key}; '
                "fi;"
            )
            for key in layout_vars
        )
        normalize += " "
    command = (
        f"{exports}{normalize}"
        f"cd $(_oz_abspath {shlex.quote(cwd)}) && {shlex.join(argv)}"
    )
    return ["bash", "-lc", command]


def wrap_ssh(target: str, remote_argv: list[str]) -> list[str]:
    return compile_legacy_ssh(target, remote_argv)
