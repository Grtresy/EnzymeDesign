from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib


@dataclass(slots=True)
class ClusterConfig:
    ssh_host: str = "localhost"
    ssh_user: str | None = None
    remote_base_dir: str = "~/mcp_runs"

    @property
    def ssh_target(self) -> str:
        if self.ssh_user:
            return f"{self.ssh_user}@{self.ssh_host}"
        return self.ssh_host


@dataclass(slots=True)
class SlurmConfig:
    default_partition: str | None = None
    gpu_partition: str | None = None
    gpu_flag_style: str = "gpus"
    time_threshold_minutes: int = 60
    mem_threshold_mb: int = 32768


@dataclass(slots=True)
class ExecutionConfig:
    default_mode: str = "auto"
    create_remote_dir_for_ssh: bool = True
    artifact_root: str = ".mcp_hpc_runner/artifacts"
    use_rsync: bool = True


@dataclass(slots=True)
class LoggingConfig:
    inline_log_limit: int = 4096
    redact_patterns: list[str] = field(default_factory=list)


@dataclass(slots=True)
class RunnerConfig:
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    slurm: SlurmConfig = field(default_factory=SlurmConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)

    @property
    def artifact_root(self) -> Path:
        return Path(self.execution.artifact_root).expanduser().resolve()


def _merge_defaults(data: dict[str, Any] | None) -> RunnerConfig:
    data = data or {}
    cluster_raw = data.get("cluster", {})
    slurm_raw = data.get("slurm", {})
    execution_raw = data.get("execution", {})
    logging_raw = data.get("logging", {})

    return RunnerConfig(
        cluster=ClusterConfig(
            ssh_host=str(cluster_raw.get("ssh_host", "localhost")),
            ssh_user=(
                str(cluster_raw["ssh_user"])
                if cluster_raw.get("ssh_user") not in (None, "")
                else None
            ),
            remote_base_dir=str(cluster_raw.get("remote_base_dir", "~/mcp_runs")),
        ),
        slurm=SlurmConfig(
            default_partition=(
                str(slurm_raw["default_partition"])
                if slurm_raw.get("default_partition")
                else None
            ),
            gpu_partition=(
                str(slurm_raw["gpu_partition"])
                if slurm_raw.get("gpu_partition")
                else None
            ),
            gpu_flag_style=str(slurm_raw.get("gpu_flag_style", "gpus")),
            time_threshold_minutes=int(slurm_raw.get("time_threshold_minutes", 60)),
            mem_threshold_mb=int(slurm_raw.get("mem_threshold_mb", 32768)),
        ),
        execution=ExecutionConfig(
            default_mode=str(execution_raw.get("default_mode", "auto")),
            create_remote_dir_for_ssh=bool(
                execution_raw.get("create_remote_dir_for_ssh", True)
            ),
            artifact_root=str(
                execution_raw.get("artifact_root", ".mcp_hpc_runner/artifacts")
            ),
            use_rsync=bool(execution_raw.get("use_rsync", True)),
        ),
        logging=LoggingConfig(
            inline_log_limit=int(logging_raw.get("inline_log_limit", 4096)),
            redact_patterns=[
                str(pattern) for pattern in logging_raw.get("redact_patterns", [])
            ],
        ),
    )


def load_config(path: str | Path | None) -> RunnerConfig:
    if path is None:
        return _merge_defaults(None)

    config_path = Path(path).expanduser().resolve()
    raw = tomllib.loads(config_path.read_text(encoding="utf-8"))
    config = _merge_defaults(raw)

    artifact_root = Path(config.execution.artifact_root).expanduser()
    if not artifact_root.is_absolute():
        artifact_root = (config_path.parent / artifact_root).resolve()
    config.execution.artifact_root = str(artifact_root)

    # Remote paths are passed as argv; avoid relying on shell-only expansions.
    remote_base_dir = config.cluster.remote_base_dir.strip()
    if remote_base_dir.startswith("~/"):
        remote_base_dir = remote_base_dir[2:]
    config.cluster.remote_base_dir = remote_base_dir
    return config
