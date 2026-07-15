from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import re
from typing import Any
import tomllib


_SAFE_PARTITION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")


def _validated_partition(value: str | None, *, field_name: str) -> str | None:
    if value is None:
        return None
    normalized = str(value)
    if not _SAFE_PARTITION.fullmatch(normalized):
        raise ValueError(
            f"{field_name} must contain only letters, digits, '.', '_', or '-'"
        )
    return normalized


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
    allowed_partitions: tuple[str, ...] = ()
    gpu_flag_style: str = "gpus"
    time_threshold_minutes: int = 60
    mem_threshold_mb: int = 32768

    def __post_init__(self) -> None:
        self.default_partition = _validated_partition(
            self.default_partition,
            field_name="slurm.default_partition",
        )
        self.gpu_partition = _validated_partition(
            self.gpu_partition,
            field_name="slurm.gpu_partition",
        )
        self.allowed_partitions = tuple(
            dict.fromkeys(
                _validated_partition(value, field_name="slurm.allowed_partitions")
                for value in self.allowed_partitions
            )
        )


@dataclass(slots=True)
class ExecutionConfig:
    default_mode: str = "auto"
    create_remote_dir_for_ssh: bool = True
    artifact_root: str = ".mcp_hpc_runner/artifacts"
    use_rsync: bool = True
    staging_timeout_seconds: int = 120
    preflight_timeout_seconds: int = 60
    remote_execution_timeout_seconds: int = 7200
    artifact_fetch_timeout_seconds: int = 120


@dataclass(slots=True)
class LoggingConfig:
    inline_log_limit: int = 4096
    redact_patterns: list[str] = field(default_factory=list)


@dataclass(frozen=True, slots=True)
class ResourceLimitsConfig:
    max_cpus: int = 64
    max_mem_mb: int = 512 * 1024
    max_gpus: int = 8
    max_time_minutes: int = 7 * 24 * 60
    max_tail_lines: int = 5000

    def __post_init__(self) -> None:
        positive_fields = (
            "max_cpus",
            "max_mem_mb",
            "max_time_minutes",
            "max_tail_lines",
        )
        for name in positive_fields:
            if getattr(self, name) < 1:
                raise ValueError(f"limits.{name} must be >= 1")
        if self.max_gpus < 0:
            raise ValueError("limits.max_gpus must be >= 0")


@dataclass(slots=True)
class AdapterConfig:
    mode: str = "sif"
    partition: str | None = None
    gpus: int | None = None

    def __post_init__(self) -> None:
        self.partition = _validated_partition(
            self.partition,
            field_name="adapters.*.partition",
        )


@dataclass(slots=True)
class RunnerConfig:
    cluster: ClusterConfig = field(default_factory=ClusterConfig)
    slurm: SlurmConfig = field(default_factory=SlurmConfig)
    execution: ExecutionConfig = field(default_factory=ExecutionConfig)
    logging: LoggingConfig = field(default_factory=LoggingConfig)
    limits: ResourceLimitsConfig = field(default_factory=ResourceLimitsConfig)
    adapters: dict[str, AdapterConfig] = field(default_factory=dict)

    def __post_init__(self) -> None:
        operator_partitions = list(self.slurm.allowed_partitions)
        operator_partitions.extend(
            partition
            for partition in (
                self.slurm.default_partition,
                self.slurm.gpu_partition,
                *(adapter.partition for adapter in self.adapters.values()),
            )
            if partition is not None
        )
        self.slurm.allowed_partitions = tuple(dict.fromkeys(operator_partitions))

    @property
    def artifact_root(self) -> Path:
        return Path(self.execution.artifact_root).expanduser().resolve()


def _merge_defaults(data: dict[str, Any] | None) -> RunnerConfig:
    data = data or {}
    cluster_raw = data.get("cluster", {})
    slurm_raw = data.get("slurm", {})
    execution_raw = data.get("execution", {})
    logging_raw = data.get("logging", {})
    limits_raw = data.get("limits", {})

    adapters: dict[str, AdapterConfig] = {}
    for adapter_id, section in data.get("adapters", {}).items():
        gpus_raw = section.get("gpus")
        adapters[adapter_id] = AdapterConfig(
            mode=str(section.get("mode", "sif")),
            partition=str(section["partition"]) if section.get("partition") else None,
            gpus=int(gpus_raw) if gpus_raw is not None else None,
        )

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
            allowed_partitions=tuple(
                str(value) for value in slurm_raw.get("allowed_partitions", [])
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
            staging_timeout_seconds=int(execution_raw.get("staging_timeout_seconds", 120)),
            preflight_timeout_seconds=int(execution_raw.get("preflight_timeout_seconds", 60)),
            remote_execution_timeout_seconds=int(execution_raw.get("remote_execution_timeout_seconds", 7200)),
            artifact_fetch_timeout_seconds=int(execution_raw.get("artifact_fetch_timeout_seconds", 120)),
        ),
        logging=LoggingConfig(
            inline_log_limit=int(logging_raw.get("inline_log_limit", 4096)),
            redact_patterns=[
                str(pattern) for pattern in logging_raw.get("redact_patterns", [])
            ],
        ),
        limits=ResourceLimitsConfig(
            max_cpus=int(limits_raw.get("max_cpus", 64)),
            max_mem_mb=int(limits_raw.get("max_mem_mb", 512 * 1024)),
            max_gpus=int(limits_raw.get("max_gpus", 8)),
            max_time_minutes=int(limits_raw.get("max_time_minutes", 7 * 24 * 60)),
            max_tail_lines=int(limits_raw.get("max_tail_lines", 5000)),
        ),
        adapters=adapters,
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
    if remote_base_dir in {"~", "~/"}:
        remote_base_dir = ""
    if remote_base_dir.startswith("~/"):
        remote_base_dir = remote_base_dir[2:]
    config.cluster.remote_base_dir = remote_base_dir
    return config
