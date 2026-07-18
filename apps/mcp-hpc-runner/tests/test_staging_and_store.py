from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from mcp_hpc_runner.config import (
    ClusterConfig,
    ExecutionConfig,
    LoggingConfig,
    RunnerConfig,
    SlurmConfig,
)
from mcp_hpc_runner.errors import FailureMapper, HpcStagingFailure
from mcp_hpc_runner.models import ExpectedOutput, ResourceSpec, RunSpec, StagedInput
from mcp_hpc_runner.remote import CommandResult, CommandRunner
from mcp_hpc_runner.slurm import SlurmRunner
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


class ScriptedRunner:
    def __init__(self, results: list[CommandResult]) -> None:
        self.results = list(results)
        self.commands: list[list[str]] = []
        self.timeouts: list[float | None] = []
        self.stages: list[str | None] = []

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:  # noqa: ARG002
        self.commands.append(args)
        self.timeouts.append(timeout)
        self.stages.append(stage)
        result = self.results.pop(0)
        result.args = args
        result.stage = stage
        return result


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


def test_input_parent_failure_persists_closed_sanitized_manifest(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=False)
    store = ArtifactStore(config.artifact_root)
    local_file = tmp_path / "private" / "input.fasta"
    local_file.parent.mkdir()
    local_file.write_text(">AOX\nMKTAYIAK\n", encoding="utf-8")
    expected_digest = "sha256:" + hashlib.sha256(local_file.read_bytes()).hexdigest()
    runner = ScriptedRunner(
        [
            CommandResult(
                args=["ssh", "alice@private-hpc"],
                returncode=255,
                stdout="",
                stderr=(
                    "ssh alice@private-hpc failed for /home/alice/private/input.fasta "
                    "token=must-not-cross"
                ),
                timed_out=False,
                elapsed_seconds=1.25,
            )
        ]
    )
    staging = StagingManager(config, store, runner)  # type: ignore[arg-type]

    with pytest.raises(HpcStagingFailure) as caught:
        staging.upload_inputs(
            run_id="opaque_run_123",
            inputs=[
                StagedInput(
                    local_path=str(local_file),
                    remote_path="private/input.fasta",
                )
            ],
            remote_run_dir="mcp_runs/opaque_run_123",
        )

    manifest = store.read_json("opaque_run_123", "runner_failure.json")
    assert manifest == {
        "schema_id": "runner_failure@1",
        "phase": "input_parent",
        "run_id": "opaque_run_123",
        "input_ordinal": 1,
        "content_digest": expected_digest,
        "returncode": 255,
        "timed_out": False,
        "elapsed_seconds": 1.25,
    }
    assert caught.value.to_safe_diagnostic() == manifest
    public_text = str(caught.value) + json.dumps(manifest, sort_keys=True)
    assert "alice@private-hpc" not in public_text
    assert str(local_file) not in public_text
    assert "mcp_runs/opaque_run_123" not in public_text
    assert "must-not-cross" not in public_text
    assert set(manifest) == {
        "schema_id",
        "phase",
        "run_id",
        "input_ordinal",
        "content_digest",
        "returncode",
        "timed_out",
        "elapsed_seconds",
    }


def test_input_transfer_timeout_persists_terminal_attempt_diagnostic(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=False)
    store = ArtifactStore(config.artifact_root)
    local_file = tmp_path / "input.fasta"
    local_file.write_text(">AOX\nMKTAYIAK\n", encoding="utf-8")
    expected_digest = "sha256:" + hashlib.sha256(local_file.read_bytes()).hexdigest()
    runner = ScriptedRunner(
        [
            CommandResult(args=[], returncode=0, stdout="", stderr=""),
            CommandResult(
                args=["scp", str(local_file), "alice@private-hpc:private/input"],
                returncode=124,
                stdout="",
                stderr="Command timed out while using a private locator",
                timed_out=True,
                elapsed_seconds=120.0012344,
            ),
        ]
    )
    staging = StagingManager(config, store, runner)  # type: ignore[arg-type]

    with pytest.raises(HpcStagingFailure, match="phase=input_transfer"):
        staging.upload_inputs(
            run_id="opaque_run_456",
            inputs=[
                StagedInput(
                    local_path=str(local_file),
                    remote_path="private/input.fasta",
                )
            ],
            remote_run_dir="mcp_runs/opaque_run_456",
        )

    manifest = store.read_json("opaque_run_456", "runner_failure.json")
    assert manifest == {
        "schema_id": "runner_failure@1",
        "phase": "input_transfer",
        "run_id": "opaque_run_456",
        "input_ordinal": 1,
        "content_digest": expected_digest,
        "returncode": 124,
        "timed_out": True,
        "elapsed_seconds": 120.001234,
    }


def test_rsync_failure_then_scp_success_has_no_failure_manifest(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=True)
    store = ArtifactStore(config.artifact_root)
    local_file = tmp_path / "input.fasta"
    local_file.write_text(">AOX\nMKTAYIAK\n", encoding="utf-8")
    runner = ScriptedRunner(
        [
            CommandResult(args=[], returncode=0, stdout="", stderr=""),
            CommandResult(args=[], returncode=23, stdout="", stderr="rsync failed"),
            CommandResult(args=[], returncode=0, stdout="", stderr=""),
        ]
    )
    staging = StagingManager(config, store, runner)  # type: ignore[arg-type]

    entries = staging.upload_inputs(
        run_id="opaque_rsync_success",
        inputs=[
            StagedInput(local_path=str(local_file), remote_path="input.fasta")
        ],
        remote_run_dir="mcp_runs/opaque_rsync_success",
    )

    assert len(entries) == 1
    assert [command[0] for command in runner.commands] == ["ssh", "rsync", "scp"]
    failure_path = (
        store.run_root("opaque_rsync_success")
        / "metadata"
        / "runner_failure.json"
    )
    assert not failure_path.exists()


def test_rsync_then_scp_terminal_failure_has_one_manifest_and_no_extra_retry(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=True)
    store = ArtifactStore(config.artifact_root)
    local_file = tmp_path / "input.fasta"
    local_file.write_text(">AOX\nMKTAYIAK\n", encoding="utf-8")
    expected_digest = "sha256:" + hashlib.sha256(local_file.read_bytes()).hexdigest()
    runner = ScriptedRunner(
        [
            CommandResult(args=[], returncode=0, stdout="", stderr=""),
            CommandResult(args=[], returncode=23, stdout="", stderr="rsync failed"),
            CommandResult(
                args=[],
                returncode=1,
                stdout="",
                stderr="scp failed with a private locator",
                elapsed_seconds=0.625,
            ),
        ]
    )
    staging = StagingManager(config, store, runner)  # type: ignore[arg-type]

    with pytest.raises(HpcStagingFailure, match="phase=input_transfer"):
        staging.upload_inputs(
            run_id="opaque_rsync_failure",
            inputs=[
                StagedInput(local_path=str(local_file), remote_path="input.fasta")
            ],
            remote_run_dir="mcp_runs/opaque_rsync_failure",
        )

    assert [command[0] for command in runner.commands] == ["ssh", "rsync", "scp"]
    assert store.read_json("opaque_rsync_failure", "runner_failure.json") == {
        "schema_id": "runner_failure@1",
        "phase": "input_transfer",
        "run_id": "opaque_rsync_failure",
        "input_ordinal": 1,
        "content_digest": expected_digest,
        "returncode": 1,
        "timed_out": False,
        "elapsed_seconds": 0.625,
    }


def test_remote_layout_failure_is_persisted_before_any_input_staging(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=False)
    store = ArtifactStore(config.artifact_root)
    runner = ScriptedRunner(
        [
            CommandResult(
                args=["ssh", "alice@private-hpc"],
                returncode=255,
                stdout="",
                stderr="private target rejected the connection",
                elapsed_seconds=0.75,
            )
        ]
    )
    staging = StagingManager(config, store, runner)  # type: ignore[arg-type]
    ssh_runner = SSHRunner(
        config,
        store,
        staging,
        runner,  # type: ignore[arg-type]
        FailureMapper(),
    )
    spec = RunSpec(
        name="remote-layout",
        stage="execution",
        command=["true"],
        run_id="opaque_run_789",
    )

    with pytest.raises(HpcStagingFailure, match="phase=remote_layout"):
        ssh_runner.exec_run(spec)

    assert store.read_json("opaque_run_789", "runspec.json")["run_id"] == (
        "opaque_run_789"
    )
    assert store.read_json("opaque_run_789", "runner_failure.json") == {
        "schema_id": "runner_failure@1",
        "phase": "remote_layout",
        "run_id": "opaque_run_789",
        "input_ordinal": None,
        "content_digest": None,
        "returncode": 255,
        "timed_out": False,
        "elapsed_seconds": 0.75,
    }
    assert not (store.run_root("opaque_run_789") / "metadata" / "inputs_manifest.json").exists()


def test_command_start_oserror_becomes_typed_remote_layout_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = _config(tmp_path, use_rsync=False)
    store = ArtifactStore(config.artifact_root)

    def raise_oserror(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("credential=must-not-cross private executable locator")

    monkeypatch.setattr("mcp_hpc_runner.remote.subprocess.run", raise_oserror)
    command_runner = CommandRunner()
    staging = StagingManager(config, store, command_runner)
    ssh_runner = SSHRunner(
        config,
        store,
        staging,
        command_runner,
        FailureMapper(),
    )

    with pytest.raises(HpcStagingFailure) as caught:
        ssh_runner.exec_run(
            RunSpec(
                name="oserror-layout",
                stage="execution",
                command=["true"],
                run_id="opaque_oserror",
            )
        )

    diagnostic = caught.value.to_safe_diagnostic()
    assert diagnostic["phase"] == "remote_layout"
    assert diagnostic["returncode"] == 127
    assert diagnostic["timed_out"] is False
    assert diagnostic["elapsed_seconds"] > 0
    assert "must-not-cross" not in str(caught.value)
    assert store.read_json("opaque_oserror", "runner_failure.json") == diagnostic


def test_slurm_remote_layout_failure_uses_typed_manifest(tmp_path: Path) -> None:
    config = _config(tmp_path, use_rsync=False)
    store = ArtifactStore(config.artifact_root)
    command_runner = ScriptedRunner(
        [
            CommandResult(
                args=[],
                returncode=255,
                stdout="",
                stderr="private Slurm SSH target failed",
                timed_out=True,
                elapsed_seconds=120.0,
            )
        ]
    )
    staging = StagingManager(config, store, command_runner)  # type: ignore[arg-type]
    slurm_runner = SlurmRunner(
        config,
        store,
        staging,
        command_runner,  # type: ignore[arg-type]
        FailureMapper(),
    )

    with pytest.raises(HpcStagingFailure, match="phase=remote_layout"):
        slurm_runner.submit(
            RunSpec(
                name="slurm-layout",
                stage="execution",
                command=["true"],
                execution_mode="sbatch",
                run_id="opaque_slurm_layout",
            )
        )

    assert command_runner.timeouts == [config.execution.staging_timeout_seconds]
    assert command_runner.stages == ["staging"]
    assert store.read_json("opaque_slurm_layout", "runner_failure.json") == {
        "schema_id": "runner_failure@1",
        "phase": "remote_layout",
        "run_id": "opaque_slurm_layout",
        "input_ordinal": None,
        "content_digest": None,
        "returncode": 255,
        "timed_out": True,
        "elapsed_seconds": 120.0,
    }


def test_slurm_control_transfer_terminal_failure_is_typed_and_bounded(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=True)
    store = ArtifactStore(config.artifact_root)
    local_script = tmp_path / "job.sbatch"
    local_script.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
    expected_digest = "sha256:" + hashlib.sha256(local_script.read_bytes()).hexdigest()
    command_runner = ScriptedRunner(
        [
            CommandResult(args=[], returncode=23, stdout="", stderr="rsync failed"),
            CommandResult(
                args=[],
                returncode=1,
                stdout="",
                stderr="scp exposed a private remote locator",
                elapsed_seconds=0.875,
            ),
        ]
    )
    staging = StagingManager(config, store, command_runner)  # type: ignore[arg-type]
    slurm_runner = SlurmRunner(
        config,
        store,
        staging,
        command_runner,  # type: ignore[arg-type]
        FailureMapper(),
    )

    with pytest.raises(HpcStagingFailure, match="phase=runner_control_transfer"):
        slurm_runner._transfer_runner_control_file(
            run_id="opaque_control_transfer",
            local_script=local_script,
            remote_script="mcp_runs/opaque_control_transfer/logs/job.sbatch",
        )

    assert [command[0] for command in command_runner.commands] == ["rsync", "scp"]
    assert command_runner.timeouts == [
        config.execution.staging_timeout_seconds,
        config.execution.staging_timeout_seconds,
    ]
    assert command_runner.stages == ["staging", "staging"]
    assert store.read_json("opaque_control_transfer", "runner_failure.json") == {
        "schema_id": "runner_failure@1",
        "phase": "runner_control_transfer",
        "run_id": "opaque_control_transfer",
        "input_ordinal": None,
        "content_digest": expected_digest,
        "returncode": 1,
        "timed_out": False,
        "elapsed_seconds": 0.875,
    }


def test_slurm_control_transfer_rsync_failure_then_scp_success_has_no_manifest(
    tmp_path: Path,
) -> None:
    config = _config(tmp_path, use_rsync=True)
    store = ArtifactStore(config.artifact_root)
    local_script = tmp_path / "job.sbatch"
    local_script.write_text("#!/bin/bash\ntrue\n", encoding="utf-8")
    command_runner = ScriptedRunner(
        [
            CommandResult(args=[], returncode=23, stdout="", stderr="rsync failed"),
            CommandResult(args=[], returncode=0, stdout="", stderr=""),
        ]
    )
    staging = StagingManager(config, store, command_runner)  # type: ignore[arg-type]
    slurm_runner = SlurmRunner(
        config,
        store,
        staging,
        command_runner,  # type: ignore[arg-type]
        FailureMapper(),
    )

    slurm_runner._transfer_runner_control_file(
        run_id="opaque_control_success",
        local_script=local_script,
        remote_script="mcp_runs/opaque_control_success/logs/job.sbatch",
    )

    assert [command[0] for command in command_runner.commands] == ["rsync", "scp"]
    assert command_runner.timeouts == [
        config.execution.staging_timeout_seconds,
        config.execution.staging_timeout_seconds,
    ]
    failure_path = (
        store.run_root("opaque_control_success")
        / "metadata"
        / "runner_failure.json"
    )
    assert not failure_path.exists()


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
