from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hpc_runner.config import (
    ClusterConfig,
    ExecutionConfig,
    LoggingConfig,
    RunnerConfig,
    SlurmConfig,
)
from mcp_hpc_runner.errors import FailureMapper
from mcp_hpc_runner.models import ExpectedOutput, ResourceSpec, RunSpec, StagedInput
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore
from mcp_hpc_runner.ssh_runner import SSHRunner


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


@pytest.mark.parametrize(
    "run_id",
    ["../escape", "nested/run", ".", "run\nother"],
)
def test_artifact_store_rejects_unsafe_run_ids(tmp_path: Path, run_id: str) -> None:
    store = ArtifactStore(tmp_path / "artifacts")

    with pytest.raises(ValueError, match="run_id"):
        store.ensure_run_layout(run_id)


@pytest.mark.parametrize(
    ("managed_directory", "write_kind"),
    [("metadata", "json"), ("logs", "log")],
)
def test_artifact_store_rejects_managed_directory_symlink_escape(
    tmp_path: Path,
    managed_directory: str,
    write_kind: str,
) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    layout = store.ensure_run_layout("run123")
    escaped = tmp_path / "escaped"
    escaped.mkdir()
    layout[managed_directory].rmdir()
    layout[managed_directory].symlink_to(escaped, target_is_directory=True)

    with pytest.raises(ValueError, match="symbolic link"):
        if write_kind == "json":
            store.write_json("run123", "record.json", {"ok": True})
        else:
            store.write_log("run123", "stdout.log", "escaped")

    assert list(escaped.iterdir()) == []


def test_artifact_store_rejects_dedup_cache_symlink_escape(tmp_path: Path) -> None:
    store = ArtifactStore(tmp_path / "artifacts")
    escaped = tmp_path / "escaped-cache.json"
    escaped.write_text("{}", encoding="utf-8")
    cache_path = store.cache_dir / "input_dedup.json"
    cache_path.symlink_to(escaped)

    with pytest.raises(ValueError, match="symbolic link"):
        store.save_dedup_cache({"digest": "remote"})

    assert escaped.read_text(encoding="utf-8") == "{}"


def test_staging_rejects_input_path_escape_before_remote_command(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    fake_runner = FakeRunner()
    staging = StagingManager(config, store, fake_runner)  # type: ignore[arg-type]
    local_file = tmp_path / "input.txt"
    local_file.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="remote_path"):
        staging.upload_inputs(
            run_id="run123",
            inputs=[StagedInput(local_path=str(local_file), remote_path="../../escape")],
            remote_run_dir="mcp_runs/run123",
        )

    assert fake_runner.commands == []


def test_staging_rejects_output_path_escape_before_local_write(tmp_path: Path) -> None:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    fake_runner = FakeRunner()
    staging = StagingManager(config, store, fake_runner)  # type: ignore[arg-type]

    with pytest.raises(ValueError, match="expected_outputs.path"):
        staging.download_outputs(
            run_id="run123",
            expected_outputs=[ExpectedOutput(path="../../escape")],
            remote_run_dir="mcp_runs/run123",
        )

    assert fake_runner.commands == []


@pytest.mark.parametrize(
    "remote_run_dir",
    [
        "mcp_runs/run123;touch-pwned",
        "mcp_runs/run 123",
        "mcp_runs/../other",
        "mcp_runs/run123\nother",
    ],
)
def test_staging_rejects_unsafe_remote_run_dir_before_transfer(
    tmp_path: Path,
    remote_run_dir: str,
) -> None:
    config = _config(tmp_path)
    store = ArtifactStore(config.artifact_root)
    fake_runner = FakeRunner()
    staging = StagingManager(config, store, fake_runner)  # type: ignore[arg-type]
    local_file = tmp_path / "input.txt"
    local_file.write_text("hello", encoding="utf-8")

    with pytest.raises(ValueError, match="remote_run_dir"):
        staging.upload_inputs(
            run_id="run123",
            inputs=[StagedInput(local_path=str(local_file), remote_path="input.txt")],
            remote_run_dir=remote_run_dir,
        )

    assert fake_runner.commands == []


def test_ssh_runner_enforces_configured_limits_before_remote_call(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path)
    config.limits = config.limits.__class__(
        max_cpus=2,
        max_mem_mb=2048,
        max_gpus=0,
        max_time_minutes=30,
        max_tail_lines=100,
    )
    store = ArtifactStore(config.artifact_root)
    fake_runner = FakeRunner()
    staging = StagingManager(config, store, fake_runner)  # type: ignore[arg-type]
    runner = SSHRunner(
        config,
        store,
        staging,
        fake_runner,  # type: ignore[arg-type]
        FailureMapper(),
    )

    with pytest.raises(ValueError, match="resources.cpus"):
        runner.exec_run(
            RunSpec(
                name="bounded",
                stage="execution",
                command=["true"],
                resources=ResourceSpec(cpus=3),
            )
        )

    assert fake_runner.commands == []
