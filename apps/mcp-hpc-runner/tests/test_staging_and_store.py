from __future__ import annotations

from pathlib import Path

from mcp_hpc_runner.config import (
    ClusterConfig,
    ExecutionConfig,
    LoggingConfig,
    RunnerConfig,
    SlurmConfig,
)
from mcp_hpc_runner.models import StagedInput
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore


class FakeRunner:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []

    def run(self, args: list[str], check: bool = False) -> CommandResult:  # noqa: ARG002
        self.commands.append(args)
        return CommandResult(args=args, returncode=0, stdout="", stderr="")


def _config(tmp_path: Path, use_rsync: bool = True) -> RunnerConfig:
    return RunnerConfig(
        cluster=ClusterConfig(ssh_host="hpc-login", ssh_user="alice"),
        slurm=SlurmConfig(),
        execution=ExecutionConfig(
            artifact_root=str(tmp_path / "artifacts"),
            use_rsync=use_rsync,
        ),
        logging=LoggingConfig(),
    )


def test_rsync_and_scp_command_construction(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    fake_runner = FakeRunner()
    staging = StagingManager(config, store, fake_runner)  # type: ignore[arg-type]

    local_file = tmp_path / "input.txt"
    local_file.write_text("x", encoding="utf-8")

    rsync_upload = staging.build_upload_command(
        local_file, "~/mcp_runs/r1/work/input.txt", True
    )
    scp_upload = staging.build_upload_command(
        local_file, "~/mcp_runs/r1/work/input.txt", False
    )
    rsync_download = staging.build_download_command(
        "~/mcp_runs/r1/out/result.txt", tmp_path / "result.txt", True
    )

    assert rsync_upload[0] == "rsync"
    assert scp_upload[0] == "scp"
    assert rsync_download[0] == "rsync"


def test_artifact_store_manifest_creation(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    fake_runner = FakeRunner()
    staging = StagingManager(config, store, fake_runner)  # type: ignore[arg-type]

    local_file = tmp_path / "input.txt"
    local_file.write_text("hello", encoding="utf-8")

    entries = staging.upload_inputs(
        run_id="run123",
        inputs=[StagedInput(local_path=str(local_file), remote_path="data/input.txt")],
        remote_run_dir="~/mcp_runs/run123",
    )
    assert len(entries) == 1

    manifest = store.read_json("run123", "inputs_manifest.json")
    assert manifest["run_id"] == "run123"
    assert manifest["entries"][0]["remote_path"].endswith("/work/data/input.txt")
