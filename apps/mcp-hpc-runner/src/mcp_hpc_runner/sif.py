from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(slots=True)
class BindPolicy:
    work_dir: Path
    out_dir: Path
    db_dir: Path
    model_dir: Path
    tmp_dir: Path


def map_input_path(relative_path: str, source: str = "work") -> str:
    clean = relative_path.lstrip("/")
    if source == "work":
        return f"/work/{clean}"
    if source == "db":
        return f"/db/{clean}"
    raise ValueError("source must be work or db")


def map_output_path(relative_path: str) -> str:
    clean = relative_path.lstrip("/")
    return f"/out/{clean}"


def build_apptainer_command(
    image: str,
    entrypoint: str,
    args: list[str],
    bind_policy: BindPolicy,
    *,
    use_run: bool = False,
) -> list[str]:
    subcommand = "run" if use_run else "exec"
    command = [
        "apptainer",
        subcommand,
        "--cleanenv",
        "--bind",
        f"{bind_policy.work_dir}:/work",
        "--bind",
        f"{bind_policy.out_dir}:/out",
        "--bind",
        f"{bind_policy.db_dir}:/db",
        "--bind",
        f"{bind_policy.model_dir}:/models",
        "--bind",
        f"{bind_policy.tmp_dir}:/tmp",
        image,
    ]
    if not use_run:
        command.append(entrypoint)
    command.extend(args)
    return command
