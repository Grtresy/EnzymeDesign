from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Any
from typing import ClassVar
import tomllib


_SAFE_PARTITION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_SAFE_CONFIG_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")
_SAFE_SSH_HOST = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,254}$")
_SAFE_SSH_USER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")
SSH_TRANSPORT_POLICY_SCHEMA_VERSION = "ssh_transport_policy@1"
RUNNER_EFFECTIVE_CONFIG_SCHEMA_VERSION = "runner_effective_config@1"


class SshTransportMode(StrEnum):
    DISABLED = "disabled"
    CONTROLMASTER_V1 = "controlmaster_v1"


@dataclass(frozen=True, slots=True)
class SshTransportPolicy:
    SCHEMA_VERSION: ClassVar[str] = SSH_TRANSPORT_POLICY_SCHEMA_VERSION

    mode: SshTransportMode = SshTransportMode.DISABLED
    control_persist_seconds: int = 300
    max_channels_per_target: int = 4
    connect_attempts: int = 1
    pre_effect_recovery_attempts: int = 1
    backoff_initial_seconds: float = 0.25
    backoff_multiplier: float = 2.0
    backoff_max_seconds: float = 2.0
    health_check_interval_seconds: float = 30.0
    health_check_timeout_seconds: float = 5.0
    channel_acquire_timeout_seconds: float = 30.0
    shutdown_timeout_seconds: float = 10.0

    def __post_init__(self) -> None:
        if not isinstance(self.mode, SshTransportMode):
            object.__setattr__(self, "mode", SshTransportMode(str(self.mode)))
        _bounded_int(
            self.control_persist_seconds,
            field_name="ssh_transport.control_persist_seconds",
            minimum=1,
            maximum=3_600,
        )
        _bounded_int(
            self.max_channels_per_target,
            field_name="ssh_transport.max_channels_per_target",
            minimum=1,
            maximum=64,
        )
        _bounded_int(
            self.connect_attempts,
            field_name="ssh_transport.connect_attempts",
            minimum=1,
            maximum=3,
        )
        _bounded_int(
            self.pre_effect_recovery_attempts,
            field_name="ssh_transport.pre_effect_recovery_attempts",
            minimum=0,
            maximum=1,
        )
        _bounded_float(
            self.backoff_initial_seconds,
            field_name="ssh_transport.backoff_initial_seconds",
            minimum=0.0,
            maximum=30.0,
        )
        _bounded_float(
            self.backoff_multiplier,
            field_name="ssh_transport.backoff_multiplier",
            minimum=1.0,
            maximum=4.0,
        )
        _bounded_float(
            self.backoff_max_seconds,
            field_name="ssh_transport.backoff_max_seconds",
            minimum=self.backoff_initial_seconds,
            maximum=30.0,
        )
        _bounded_float(
            self.health_check_interval_seconds,
            field_name="ssh_transport.health_check_interval_seconds",
            minimum=0.1,
            maximum=300.0,
        )
        _bounded_float(
            self.health_check_timeout_seconds,
            field_name="ssh_transport.health_check_timeout_seconds",
            minimum=0.1,
            maximum=30.0,
        )
        _bounded_float(
            self.channel_acquire_timeout_seconds,
            field_name="ssh_transport.channel_acquire_timeout_seconds",
            minimum=0.1,
            maximum=300.0,
        )
        _bounded_float(
            self.shutdown_timeout_seconds,
            field_name="ssh_transport.shutdown_timeout_seconds",
            minimum=0.1,
            maximum=60.0,
        )

    def to_authority_dict(self) -> dict[str, object]:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "mode": self.mode.value,
            "control_persist_seconds": self.control_persist_seconds,
            "max_channels_per_target": self.max_channels_per_target,
            "connect_attempts": self.connect_attempts,
            "pre_effect_recovery_attempts": self.pre_effect_recovery_attempts,
            "backoff_initial_seconds": self.backoff_initial_seconds,
            "backoff_multiplier": self.backoff_multiplier,
            "backoff_max_seconds": self.backoff_max_seconds,
            "health_check_interval_seconds": self.health_check_interval_seconds,
            "health_check_timeout_seconds": self.health_check_timeout_seconds,
            "channel_acquire_timeout_seconds": self.channel_acquire_timeout_seconds,
            "shutdown_timeout_seconds": self.shutdown_timeout_seconds,
        }

    @property
    def policy_digest(self) -> str:
        return _json_digest(self.to_authority_dict())


def _bounded_int(
    value: int,
    *,
    field_name: str,
    minimum: int,
    maximum: int,
) -> None:
    if isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")


def _bounded_float(
    value: float,
    *,
    field_name: str,
    minimum: float,
    maximum: float,
) -> None:
    if isinstance(value, bool) or not minimum <= value <= maximum:
        raise ValueError(f"{field_name} must be between {minimum} and {maximum}")


def _json_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


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
    credential_policy_id: str = "ssh-agent-default-v1"
    host_key_policy_id: str = "system-known-hosts-v1"

    def __post_init__(self) -> None:
        self.ssh_host = self.ssh_host.strip()
        if _SAFE_SSH_HOST.fullmatch(self.ssh_host) is None:
            raise ValueError("cluster.ssh_host is not a safe SSH host or alias")
        if self.ssh_user is not None:
            self.ssh_user = self.ssh_user.strip()
            if _SAFE_SSH_USER.fullmatch(self.ssh_user) is None:
                raise ValueError("cluster.ssh_user is not a safe SSH user")
        for field_name in ("credential_policy_id", "host_key_policy_id"):
            if _SAFE_CONFIG_ID.fullmatch(getattr(self, field_name)) is None:
                raise ValueError(f"cluster.{field_name} is not a safe policy id")

    @property
    def ssh_target(self) -> str:
        if self.ssh_user:
            return f"{self.ssh_user}@{self.ssh_host}"
        return self.ssh_host

    @property
    def normalized_ssh_target(self) -> str:
        host = self.ssh_host.casefold()
        return f"{self.ssh_user}@{host}" if self.ssh_user else host


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
    apptainer_executable: str = "/usr/bin/apptainer"

    def __post_init__(self) -> None:
        path = PurePosixPath(self.apptainer_executable)
        if (
            not path.is_absolute()
            or path.name != "apptainer"
            or any(part in {"", ".", ".."} for part in path.parts[1:])
            or re.fullmatch(
                r"/(?:[A-Za-z0-9._-]+/)*apptainer",
                self.apptainer_executable,
            )
            is None
        ):
            raise ValueError(
                "execution.apptainer_executable must be an absolute path ending in /apptainer"
            )
        self.apptainer_executable = path.as_posix()


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
    ssh_transport: SshTransportPolicy = field(default_factory=SshTransportPolicy)
    deployment_id: str = "local-runner"
    transport_control_root: str = ".mcp_hpc_runner/control"

    def __post_init__(self) -> None:
        if _SAFE_CONFIG_ID.fullmatch(self.deployment_id) is None:
            raise ValueError("runner.deployment_id is not a safe identifier")
        if not str(self.transport_control_root).strip():
            raise ValueError("runner.transport_control_root must not be empty")
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

    @property
    def control_root(self) -> Path:
        return Path(self.transport_control_root).expanduser().resolve()

    @property
    def effective_config_digest(self) -> str:
        adapters = {
            key: {
                "mode": value.mode,
                "partition": value.partition,
                "gpus": value.gpus,
            }
            for key, value in sorted(self.adapters.items())
        }
        return _json_digest(
            {
                "schema_version": RUNNER_EFFECTIVE_CONFIG_SCHEMA_VERSION,
                "deployment_id": self.deployment_id,
                "transport_control_root": str(self.control_root),
                "cluster": {
                    "normalized_ssh_target": self.cluster.normalized_ssh_target,
                    "remote_base_dir": self.cluster.remote_base_dir,
                    "credential_policy_id": self.cluster.credential_policy_id,
                    "host_key_policy_id": self.cluster.host_key_policy_id,
                },
                "slurm": {
                    "default_partition": self.slurm.default_partition,
                    "gpu_partition": self.slurm.gpu_partition,
                    "allowed_partitions": list(self.slurm.allowed_partitions),
                    "gpu_flag_style": self.slurm.gpu_flag_style,
                    "time_threshold_minutes": self.slurm.time_threshold_minutes,
                    "mem_threshold_mb": self.slurm.mem_threshold_mb,
                },
                "execution": {
                    "artifact_root": str(self.artifact_root),
                    "default_mode": self.execution.default_mode,
                    "create_remote_dir_for_ssh": (
                        self.execution.create_remote_dir_for_ssh
                    ),
                    "use_rsync": self.execution.use_rsync,
                    "staging_timeout_seconds": (
                        self.execution.staging_timeout_seconds
                    ),
                    "preflight_timeout_seconds": (
                        self.execution.preflight_timeout_seconds
                    ),
                    "remote_execution_timeout_seconds": (
                        self.execution.remote_execution_timeout_seconds
                    ),
                    "artifact_fetch_timeout_seconds": (
                        self.execution.artifact_fetch_timeout_seconds
                    ),
                    "apptainer_executable": self.execution.apptainer_executable,
                },
                "limits": {
                    "max_cpus": self.limits.max_cpus,
                    "max_mem_mb": self.limits.max_mem_mb,
                    "max_gpus": self.limits.max_gpus,
                    "max_time_minutes": self.limits.max_time_minutes,
                    "max_tail_lines": self.limits.max_tail_lines,
                },
                "ssh_transport": self.ssh_transport.to_authority_dict(),
                "logging": {
                    "inline_log_limit": self.logging.inline_log_limit,
                    "redact_patterns": list(self.logging.redact_patterns),
                },
                "adapters": adapters,
            }
        )


def _merge_defaults(data: dict[str, Any] | None) -> RunnerConfig:
    data = data or {}
    cluster_raw = data.get("cluster", {})
    slurm_raw = data.get("slurm", {})
    execution_raw = data.get("execution", {})
    logging_raw = data.get("logging", {})
    limits_raw = data.get("limits", {})
    runner_raw = data.get("runner", {})
    transport_raw = data.get("ssh_transport", {})

    unexpected_runner = sorted(
        set(runner_raw) - {"deployment_id", "transport_control_root"}
    )
    if unexpected_runner:
        raise ValueError(
            "runner contains unsupported fields: " + ", ".join(unexpected_runner)
        )

    allowed_transport_fields = {
        "mode",
        "control_persist_seconds",
        "max_channels_per_target",
        "connect_attempts",
        "pre_effect_recovery_attempts",
        "backoff_initial_seconds",
        "backoff_multiplier",
        "backoff_max_seconds",
        "health_check_interval_seconds",
        "health_check_timeout_seconds",
        "channel_acquire_timeout_seconds",
        "shutdown_timeout_seconds",
    }
    unexpected_transport = sorted(set(transport_raw) - allowed_transport_fields)
    if unexpected_transport:
        raise ValueError(
            "ssh_transport contains unsupported fields: "
            + ", ".join(unexpected_transport)
        )

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
            credential_policy_id=str(
                cluster_raw.get("credential_policy_id", "ssh-agent-default-v1")
            ),
            host_key_policy_id=str(
                cluster_raw.get("host_key_policy_id", "system-known-hosts-v1")
            ),
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
            apptainer_executable=str(
                execution_raw.get("apptainer_executable", "/usr/bin/apptainer")
            ),
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
        ssh_transport=SshTransportPolicy(
            mode=SshTransportMode(
                str(transport_raw.get("mode", SshTransportMode.DISABLED.value))
            ),
            control_persist_seconds=int(
                transport_raw.get("control_persist_seconds", 300)
            ),
            max_channels_per_target=int(
                transport_raw.get("max_channels_per_target", 4)
            ),
            connect_attempts=int(transport_raw.get("connect_attempts", 1)),
            pre_effect_recovery_attempts=int(
                transport_raw.get("pre_effect_recovery_attempts", 1)
            ),
            backoff_initial_seconds=float(
                transport_raw.get("backoff_initial_seconds", 0.25)
            ),
            backoff_multiplier=float(transport_raw.get("backoff_multiplier", 2.0)),
            backoff_max_seconds=float(
                transport_raw.get("backoff_max_seconds", 2.0)
            ),
            health_check_interval_seconds=float(
                transport_raw.get("health_check_interval_seconds", 30.0)
            ),
            health_check_timeout_seconds=float(
                transport_raw.get("health_check_timeout_seconds", 5.0)
            ),
            channel_acquire_timeout_seconds=float(
                transport_raw.get("channel_acquire_timeout_seconds", 30.0)
            ),
            shutdown_timeout_seconds=float(
                transport_raw.get("shutdown_timeout_seconds", 10.0)
            ),
        ),
        deployment_id=str(runner_raw.get("deployment_id", "local-runner")),
        transport_control_root=str(
            runner_raw.get(
                "transport_control_root",
                ".mcp_hpc_runner/control",
            )
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

    control_root = Path(config.transport_control_root).expanduser()
    if not control_root.is_absolute():
        control_root = (config_path.parent / control_root).resolve()
    config.transport_control_root = str(control_root)

    # Remote paths are passed as argv; avoid relying on shell-only expansions.
    remote_base_dir = config.cluster.remote_base_dir.strip()
    if remote_base_dir in {"~", "~/"}:
        remote_base_dir = ""
    if remote_base_dir.startswith("~/"):
        remote_base_dir = remote_base_dir[2:]
    config.cluster.remote_base_dir = remote_base_dir
    return config
