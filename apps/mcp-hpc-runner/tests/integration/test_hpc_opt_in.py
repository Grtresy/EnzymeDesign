from __future__ import annotations

import os
from pathlib import Path
import time

import pytest

from mcp_hpc_runner.config import load_config
from mcp_hpc_runner.config import RunnerConfig
from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.models import ExpectedOutput, ResourceSpec, RunResult, RunSpec
from mcp_hpc_runner.remote import CommandRunner
from mcp_hpc_runner.slurm import SlurmRunner
from mcp_hpc_runner.ssh_runner import SSHRunner
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore


pytestmark = [pytest.mark.integration, pytest.mark.live_hpc]


def _project_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _default_config_path() -> Path:
    return _project_root() / "config" / "hpc_runner.toml"


def _config(tmp_path: Path) -> RunnerConfig:
    configured_path = (
        os.getenv("OPENZYME_HPC_RUNNER_CONFIG")
        or os.getenv("HPC_RUNNER_CONFIG")
        or str(_default_config_path())
    )
    config_path = Path(configured_path).expanduser()
    if not config_path.exists():
        pytest.skip(f"Integration config not found: {config_path}")

    config = load_config(config_path)

    # Optional overrides.
    if os.getenv("HPC_SSH_HOST"):
        config.cluster.ssh_host = os.environ["HPC_SSH_HOST"]
    if os.getenv("HPC_SSH_USER") is not None:
        config.cluster.ssh_user = os.getenv("HPC_SSH_USER") or None
    if os.getenv("HPC_REMOTE_BASE_DIR"):
        config.cluster.remote_base_dir = os.environ["HPC_REMOTE_BASE_DIR"]
    if os.getenv("HPC_SLURM_PARTITION"):
        config.slurm.default_partition = os.environ["HPC_SLURM_PARTITION"]
    if os.getenv("HPC_SLURM_GPU_PARTITION"):
        config.slurm.gpu_partition = os.environ["HPC_SLURM_GPU_PARTITION"]
    if os.getenv("HPC_GPU_FLAG_STYLE"):
        config.slurm.gpu_flag_style = os.environ["HPC_GPU_FLAG_STYLE"]

    # Keep integration test artifacts isolated.
    config.execution.artifact_root = str((tmp_path / "artifacts").resolve())
    config.execution.use_rsync = True
    return config


def _runners(tmp_path: Path) -> tuple[SSHRunner, SlurmRunner]:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    command_runner = CommandRunner()
    staging = StagingManager(config, store, command_runner)
    mapper = FailureMapper()
    ssh = SSHRunner(config, store, staging, command_runner, mapper)
    slurm = SlurmRunner(config, store, staging, command_runner, mapper)
    return ssh, slurm


def _ssh_attempts() -> int:
    configured = os.getenv("HPC_LIVE_SSH_ATTEMPTS")
    if configured is None:
        return 3
    return max(1, int(configured))


def _is_transient_ssh_failure(result: RunResult) -> bool:
    stderr = (result.stderr or "").lower()
    return result.status != "completed" and (
        "connection timed out" in stderr
        or "operation timed out" in stderr
        or "connection reset" in stderr
    )


def _exec_ssh_with_transient_retry(ssh: SSHRunner, spec: RunSpec) -> RunResult:
    attempts = _ssh_attempts()
    result = None
    for attempt in range(1, attempts + 1):
        result = ssh.exec_run(spec)
        if not _is_transient_ssh_failure(result) or attempt == attempts:
            return result
        time.sleep(min(5 * attempt, 15))
    assert result is not None
    return result


def test_ssh_smoke_python_version(tmp_path: Path) -> None:
    ssh, _ = _runners(tmp_path)
    spec = RunSpec(
        name="ssh-smoke",
        stage="evidence",
        command=["python3", "--version"],
        execution_mode="ssh",
        resources=ResourceSpec(cpus=1, mem_mb=256, gpus=0, time_minutes=5),
    )
    result = _exec_ssh_with_transient_retry(ssh, spec)
    assert result.status == "completed", result.to_dict()
    assert result.exit_code == 0, result.to_dict()
    assert "Python" in (result.stdout or ""), result.to_dict()


def test_sbatch_sentinel_and_fetch(tmp_path: Path) -> None:
    _, slurm = _runners(tmp_path)
    spec = RunSpec(
        name="sbatch-sentinel",
        stage="evaluator",
        command=[
            "python3",
            "-c",
            (
                "import os; "
                "from pathlib import Path; "
                "out = Path(os.environ.get('OUTDIR', '../out')); "
                "out.mkdir(parents=True, exist_ok=True); "
                "(out / 'success.txt').write_text('ok\\n', encoding='utf-8')"
            ),
        ],
        execution_mode="sbatch",
        resources=ResourceSpec(cpus=1, mem_mb=512, gpus=0, time_minutes=10),
        expected_outputs=[
            ExpectedOutput(
                path="success.txt", kind="file", required=True, non_empty=True
            )
        ],
    )
    submitted = slurm.submit(spec)
    assert submitted.status == "submitted"
    assert submitted.job_id

    handle = slurm.load_handle(submitted.run_id)
    status = None
    for _ in range(60):
        status = slurm.status(handle)
        if status.state in {"completed", "failed", "cancelled"}:
            break
        time.sleep(5)
    else:
        pytest.fail("Timed out waiting for Slurm job completion")

    assert status is not None
    assert status.state == "completed"
    fetched = slurm.fetch_artifacts(spec, handle)
    assert fetched.status == "completed"
    local_out = Path(fetched.artifacts[next(iter(fetched.artifacts))])
    assert local_out.exists()
