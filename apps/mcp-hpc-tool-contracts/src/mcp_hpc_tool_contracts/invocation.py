from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import subprocess
from typing import Callable

from .models import FallbackReason, InvocationMode


@dataclass(frozen=True, slots=True)
class InvocationCandidate:
    mode: InvocationMode
    command: list[str]
    entrypoint: str | None = None
    smoke_check: list[str] | None = None


@dataclass(frozen=True, slots=True)
class InvocationSelection:
    selected: InvocationCandidate
    fallback: list[FallbackReason]


WrapperCheck = Callable[[InvocationCandidate], tuple[bool, str | None]]


def default_wrapper_check(candidate: InvocationCandidate) -> tuple[bool, str | None]:
    if not candidate.entrypoint:
        return False, "wrapper entrypoint is not configured"
    entrypoint = Path(candidate.entrypoint).expanduser()
    if not entrypoint.exists():
        return False, f"wrapper entrypoint not found: {candidate.entrypoint}"
    smoke = candidate.smoke_check or [candidate.entrypoint, "--help"]
    try:
        result = subprocess.run(
            smoke, capture_output=True, text=True, timeout=6, check=False
        )
    except OSError as exc:
        return False, f"wrapper smoke check failed to start: {exc}"
    except subprocess.TimeoutExpired:
        return False, "wrapper smoke check timed out"
    if result.returncode != 0:
        return False, "wrapper smoke check returned non-zero exit"
    return True, None


def build_sif_command(
    *,
    image: str,
    entrypoint: str,
    args: list[str],
    use_run: bool = False,
    extra_runtime_args: list[str] | None = None,
    extra_host_binds: list[str] | None = None,
) -> list[str]:
    """Build an apptainer exec/run command.

    Args:
        extra_host_binds: Host paths to bind into the container at the same
            path (e.g. ``["/db", "/models"]``).  Each entry may be a bare
            path (``"/db"`` → ``/db:/db``) or an explicit ``src:dst`` pair.
            The standard work/out/tmp bind mounts are always included.
    """
    subcommand = "run" if use_run else "exec"
    command = [
        "apptainer",
        subcommand,
        "--cleanenv",
        "--bind",
        ".:/work",
        "--bind",
        "../out:/out",
        "--bind",
        "../tmp:/tmp",
    ]
    for bind_path in extra_host_binds or []:
        bind_spec = bind_path if ":" in bind_path else f"{bind_path}:{bind_path}"
        command.extend(["--bind", bind_spec])
    if extra_runtime_args:
        command.extend(extra_runtime_args)
    # Expand leading ~/ so shlex.join in the sbatch generator does not
    # single-quote the tilde, which would prevent shell expansion on the remote.
    command.append(os.path.expanduser(image))
    if not use_run:
        command.append(entrypoint)
    command.extend(args)
    return command


def select_invocation(
    *,
    wrapper: InvocationCandidate | None,
    sif: InvocationCandidate | None,
    fallback: InvocationCandidate | None,
    wrapper_check: WrapperCheck = default_wrapper_check,
) -> InvocationSelection:
    fallback_reasons: list[FallbackReason] = []

    ordered = [wrapper, sif, fallback]
    for candidate in ordered:
        if candidate is None:
            continue
        if candidate.mode == "wrapper":
            viable, reason = wrapper_check(candidate)
            if viable:
                return InvocationSelection(
                    selected=candidate, fallback=fallback_reasons
                )
            fallback_reasons.append(
                FallbackReason(mode="wrapper", reason=reason or "wrapper is not viable")
            )
            continue
        return InvocationSelection(selected=candidate, fallback=fallback_reasons)

    raise ValueError("No viable invocation mode was configured")
