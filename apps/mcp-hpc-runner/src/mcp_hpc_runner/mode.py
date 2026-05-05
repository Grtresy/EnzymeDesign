from __future__ import annotations

from .config import RunnerConfig
from .models import RunSpec


def select_execution_mode(
    spec: RunSpec, config: RunnerConfig, override: str | None = None
) -> str:
    requested = (
        override or spec.execution_mode or config.execution.default_mode
    ).lower()
    if requested in {"ssh", "sbatch"}:
        return requested
    if requested != "auto":
        raise ValueError(f"Unsupported execution mode: {requested}")

    resources = spec.resources
    if resources.gpus > 0:
        return "sbatch"
    if resources.time_minutes >= config.slurm.time_threshold_minutes:
        return "sbatch"
    if resources.mem_mb >= config.slurm.mem_threshold_mb:
        return "sbatch"
    return "ssh"
