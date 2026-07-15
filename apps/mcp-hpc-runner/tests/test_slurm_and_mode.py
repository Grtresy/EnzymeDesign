from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hpc_runner.config import (
    AdapterConfig,
    ClusterConfig,
    ExecutionConfig,
    LoggingConfig,
    RunnerConfig,
    SlurmConfig,
)
from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.mode import select_execution_mode
from mcp_hpc_runner.models import JobHandle, ResourceSpec, RunSpec
from mcp_hpc_runner.remote import CommandResult, CommandRunner
from mcp_hpc_runner.slurm import SlurmRunner
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:  # noqa: ARG002
        self.commands.append(args)
        return CommandResult(args=args, returncode=0, stdout="", stderr="", stage=stage)


def _config(tmp_path: Path, gpu_flag_style: str = "gpus") -> RunnerConfig:
    return RunnerConfig(
        cluster=ClusterConfig(ssh_host="hpc"),
        slurm=SlurmConfig(
            default_partition="cpu",
            gpu_partition="gpu",
            gpu_flag_style=gpu_flag_style,
            time_threshold_minutes=30,
            mem_threshold_mb=16000,
        ),
        execution=ExecutionConfig(artifact_root=str(tmp_path / "artifacts")),
        logging=LoggingConfig(),
    )


def _slurm_runner(tmp_path: Path, gpu_flag_style: str = "gpus") -> SlurmRunner:
    config = _config(tmp_path, gpu_flag_style=gpu_flag_style)
    store = ArtifactStore(config.artifact_root)
    command_runner = CommandRunner()
    staging = StagingManager(config, store, command_runner)
    return SlurmRunner(config, store, staging, command_runner, FailureMapper())


def test_sbatch_script_generation_uses_gpus_flag(tmp_path: Path) -> None:
    runner = _slurm_runner(tmp_path, gpu_flag_style="gpus")
    spec = RunSpec(
        name="gpu-job",
        stage="generator",
        command=["python3", "-V"],
        execution_mode="sbatch",
        resources=ResourceSpec(cpus=8, mem_mb=32000, gpus=1, time_minutes=120),
    )
    script = runner.build_sbatch_script(spec, "~/mcp_runs/abc123")
    assert "#SBATCH --gpus=1" in script
    assert "#SBATCH --partition=gpu" in script


def test_sbatch_script_generation_uses_gres_flag(tmp_path: Path) -> None:
    runner = _slurm_runner(tmp_path, gpu_flag_style="gres")
    spec = RunSpec(
        name="gpu-job",
        stage="generator",
        command=["python3", "-V"],
        execution_mode="sbatch",
        resources=ResourceSpec(cpus=8, mem_mb=32000, gpus=2, time_minutes=120),
    )
    script = runner.build_sbatch_script(spec, "~/mcp_runs/abc123")
    assert "#SBATCH --gres=gpu:2" in script


def test_auto_mode_selection_policy(tmp_path: Path) -> None:
    config = _config(tmp_path)
    light = RunSpec(
        name="light",
        stage="evidence",
        command=["python3", "--version"],
        execution_mode="auto",
        resources=ResourceSpec(cpus=1, mem_mb=512, gpus=0, time_minutes=5),
    )
    heavy = RunSpec(
        name="heavy",
        stage="generator",
        command=["python3", "task.py"],
        execution_mode="auto",
        resources=ResourceSpec(cpus=8, mem_mb=64000, gpus=0, time_minutes=120),
    )
    gpu = RunSpec(
        name="gpu",
        stage="generator",
        command=["python3", "task.py"],
        execution_mode="auto",
        resources=ResourceSpec(cpus=8, mem_mb=8000, gpus=1, time_minutes=10),
    )

    assert select_execution_mode(light, config) == "ssh"
    assert select_execution_mode(heavy, config) == "sbatch"
    assert select_execution_mode(gpu, config) == "sbatch"


def test_runner_config_collects_operator_selected_partitions(tmp_path: Path) -> None:
    config = RunnerConfig(
        cluster=ClusterConfig(ssh_host="hpc"),
        slurm=SlurmConfig(
            default_partition="cpu",
            gpu_partition="gpu",
            allowed_partitions=("long",),
        ),
        execution=ExecutionConfig(artifact_root=str(tmp_path / "artifacts")),
        adapters={"tool": AdapterConfig(partition="adapter")},
    )

    assert config.slurm.allowed_partitions == ("long", "cpu", "gpu", "adapter")


@pytest.mark.parametrize(
    "partition",
    ["cpu\n#SBATCH --exclusive", "cpu;touch-pwned", "cpu partition"],
)
def test_runner_config_rejects_unsafe_operator_partition(partition: str) -> None:
    with pytest.raises(ValueError, match="partition"):
        SlurmConfig(default_partition=partition)


def test_sbatch_script_rejects_directive_injection(tmp_path: Path) -> None:
    runner = _slurm_runner(tmp_path)
    spec = RunSpec(
        name="safe\n#SBATCH --exclusive",
        stage="execution",
        command=["true"],
        resources=ResourceSpec(partition="cpu\n#SBATCH --exclusive"),
    )

    with pytest.raises(ValueError, match="RunSpec validation failed"):
        runner.build_sbatch_script(spec, "mcp_runs/run123")


def test_sbatch_script_rejects_injected_configured_partition(tmp_path: Path) -> None:
    runner = _slurm_runner(tmp_path)
    runner.config.slurm.default_partition = "cpu\n#SBATCH --exclusive"
    spec = RunSpec(
        name="safe-name",
        stage="execution",
        command=["true"],
    )

    with pytest.raises(ValueError, match="slurm.default_partition"):
        runner.build_sbatch_script(spec, "mcp_runs/run123")


@pytest.mark.parametrize("tail_lines", [0, -1, 5001])
def test_slurm_logs_rejects_unbounded_tail_before_remote_call(
    tmp_path: Path,
    tail_lines: int,
) -> None:
    runner = _slurm_runner(tmp_path)
    fake_runner = FakeRunner()
    runner.command_runner = fake_runner  # type: ignore[assignment]

    with pytest.raises(ValueError, match="tail_lines"):
        runner.logs(
            JobHandle(
                run_id="run123",
                job_id="12345",
                remote_run_dir="mcp_runs/run123",
            ),
            tail_lines=tail_lines,
        )

    assert fake_runner.commands == []


@pytest.mark.parametrize(
    ("job_id", "remote_run_dir"),
    [
        ("12345;touch-pwned", "mcp_runs/run123"),
        ("12345", "mcp_runs/run123/../other"),
    ],
)
def test_slurm_status_rejects_unsafe_handle_before_remote_call(
    tmp_path: Path,
    job_id: str,
    remote_run_dir: str,
) -> None:
    runner = _slurm_runner(tmp_path)
    fake_runner = FakeRunner()
    runner.command_runner = fake_runner  # type: ignore[assignment]

    with pytest.raises(ValueError):
        runner.status(
            JobHandle(
                run_id="run123",
                job_id=job_id,
                remote_run_dir=remote_run_dir,
            )
        )

    assert fake_runner.commands == []


@pytest.mark.parametrize(
    "remote_run_dir",
    ["/etc/run123", "other_runs/run123", "~/mcp_runs/other-run"],
)
def test_slurm_status_rejects_safe_but_out_of_scope_remote_dir(
    tmp_path: Path,
    remote_run_dir: str,
) -> None:
    runner = _slurm_runner(tmp_path)
    fake_runner = FakeRunner()
    runner.command_runner = fake_runner  # type: ignore[assignment]

    with pytest.raises(ValueError, match="configured run directory"):
        runner.status(
            JobHandle(
                run_id="run123",
                job_id="12345",
                remote_run_dir=remote_run_dir,
            )
        )

    assert fake_runner.commands == []
