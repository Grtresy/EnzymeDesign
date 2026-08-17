from __future__ import annotations

from dataclasses import dataclass
import subprocess
import time


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
                raise RuntimeError(f"Command timed out ({stage or 'unknown'})")
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
                    f"Command could not start ({stage or 'unknown'})"
                ) from exc
            return result
        elapsed_seconds = time.monotonic() - started_at
        if check and proc.returncode != 0:
            raise RuntimeError(
                f"Command failed ({proc.returncode}) at {stage or 'unknown'}"
            )
        return CommandResult(
            args=args,
            returncode=proc.returncode,
            stdout=proc.stdout,
            stderr=proc.stderr,
            stage=stage,
            elapsed_seconds=elapsed_seconds,
        )
