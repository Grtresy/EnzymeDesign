from __future__ import annotations

from pathlib import Path

from mcp_hpc_runner.config import (
    ClusterConfig,
    ExecutionConfig,
    LoggingConfig,
    RunnerConfig,
    SlurmConfig,
)
from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.mode import select_execution_mode
from mcp_hpc_runner.models import ResourceSpec, RunSpec
from mcp_hpc_runner.remote import CommandRunner
from mcp_hpc_runner.slurm import SlurmRunner
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore


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
