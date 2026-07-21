from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import tempfile
from typing import Iterator

import pytest

from mcp_hpc_runner.config import ClusterConfig
from mcp_hpc_runner.config import ExecutionConfig
from mcp_hpc_runner.config import RunnerConfig
from mcp_hpc_runner.config import SshTransportMode
from mcp_hpc_runner.config import SshTransportPolicy
from mcp_hpc_runner.errors import HpcStagingFailure
from mcp_hpc_runner.models import StagedInput
from mcp_hpc_runner.remote import CommandResult
from mcp_hpc_runner.staging import StagingManager
from mcp_hpc_runner.store import ArtifactStore
from mcp_hpc_runner.transport import SshTransportManager
from mcp_hpc_runner.verification import AuthorizedInput
from mcp_hpc_runner.verification import RemoteVerificationStatus
from mcp_hpc_runner.verification import build_canonical_tree_manifest
from mcp_hpc_runner.verification import remote_verification_stdout


@contextmanager
def _short_root() -> Iterator[Path]:
    with tempfile.TemporaryDirectory(prefix="ozv-", dir="/tmp") as raw:
        yield Path(raw)


class VerificationRunner:
    def __init__(self, verification_results: list[CommandResult]) -> None:
        self.verification_results = list(verification_results)
        self.commands: list[list[str]] = []
        self.stages: list[str | None] = []

    def run(
        self,
        args: list[str],
        check: bool = False,
        *,
        timeout: float | None = None,
        stage: str | None = None,
    ) -> CommandResult:
        del check, timeout
        self.commands.append(list(args))
        self.stages.append(stage)
        if stage == "input_verification":
            result = self.verification_results.pop(0)
            result.args = list(args)
            result.stage = stage
            return result
        return CommandResult(
            args=list(args),
            returncode=0,
            stdout="",
            stderr="",
            stage=stage,
        )


def _result(stdout: str, *, returncode: int = 0) -> CommandResult:
    return CommandResult(args=[], returncode=returncode, stdout=stdout, stderr="")


def _staging(
    root: Path,
    runner: VerificationRunner,
) -> tuple[StagingManager, ArtifactStore, SshTransportManager]:
    config = RunnerConfig(
        cluster=ClusterConfig(ssh_host="hpc-login", ssh_user="alice"),
        execution=ExecutionConfig(
            artifact_root=str(root / "artifacts"),
            use_rsync=False,
        ),
        ssh_transport=SshTransportPolicy(
            mode=SshTransportMode.CONTROLMASTER_V1,
            channel_acquire_timeout_seconds=0.1,
        ),
        transport_control_root=str(root / "control"),
    )
    store = ArtifactStore(config.artifact_root)
    manager = SshTransportManager(
        config,
        runner,  # type: ignore[arg-type]
        runner_nonce="test-runner",
    )
    return (
        StagingManager(
            config,
            store,
            runner,  # type: ignore[arg-type]
            transport_manager=manager,
        ),
        store,
        manager,
    )


def test_file_upload_is_remotely_verified_before_cache_publication() -> None:
    with _short_root() as root:
        local = root / "input.txt"
        local.write_text("exact bytes", encoding="utf-8")
        authorized = AuthorizedInput.from_path(local)
        runner = VerificationRunner(
            [
                _result(remote_verification_stdout(authorized)),
                _result(remote_verification_stdout(authorized)),
            ]
        )
        staging, store, manager = _staging(root, runner)
        try:
            entries = staging.upload_inputs(
                "run-1",
                [StagedInput(local_path=str(local), remote_path="input.txt")],
                "mcp_runs/run-1",
            )
        finally:
            manager.shutdown()

        assert entries[0]["verification_status"] == "verified"
        assert entries[0]["content_digest"] == authorized.content_digest
        assert entries[0]["verification_receipt_digest"].startswith("sha256:")
        assert list(store.load_dedup_cache().values()) == [
            "mcp_runs/run-1/work/input.txt"
        ]
        assert runner.stages.count("input_verification") == 2


def test_cache_digest_drift_invalidates_then_replaces_and_reverifies() -> None:
    with _short_root() as root:
        local = root / "input.txt"
        local.write_text("authorized", encoding="utf-8")
        authorized = AuthorizedInput.from_path(local)
        runner = VerificationRunner(
            [
                _result(remote_verification_stdout(authorized)),
                _result(remote_verification_stdout(authorized)),
                _result(
                    remote_verification_stdout(
                        authorized,
                        observed_content_digest="sha256:" + "0" * 64,
                    )
                ),
                _result(remote_verification_stdout(authorized)),
                _result(remote_verification_stdout(authorized)),
            ]
        )
        staging, _, manager = _staging(root, runner)
        try:
            first = staging.upload_inputs(
                "run-2",
                [StagedInput(local_path=str(local), remote_path="input.txt")],
                "mcp_runs/run-2",
            )
            second = staging.upload_inputs(
                "run-2",
                [StagedInput(local_path=str(local), remote_path="input.txt")],
                "mcp_runs/run-2",
            )
        finally:
            manager.shutdown()

        assert first[0]["skipped"] is False
        assert second[0]["skipped"] is False
        assert second[0]["verification_status"] == "verified"
        assert runner.stages.count("staging") == 6
        assert runner.stages.count("input_verification") == 5


def test_cache_verification_transport_failure_invalidates_without_upload() -> None:
    with _short_root() as root:
        local = root / "input.txt"
        local.write_text("authorized", encoding="utf-8")
        authorized = AuthorizedInput.from_path(local)
        runner = VerificationRunner(
            [
                _result(remote_verification_stdout(authorized)),
                _result(remote_verification_stdout(authorized)),
                _result("", returncode=255),
            ]
        )
        staging, store, manager = _staging(root, runner)
        try:
            staging.upload_inputs(
                "run-3",
                [StagedInput(local_path=str(local), remote_path="input.txt")],
                "mcp_runs/run-3",
            )
            staging_commands_before = runner.stages.count("staging")
            with pytest.raises(HpcStagingFailure, match="phase=input_verification"):
                staging.upload_inputs(
                    "run-3",
                    [StagedInput(local_path=str(local), remote_path="input.txt")],
                    "mcp_runs/run-3",
                )
            assert runner.stages.count("staging") == staging_commands_before
        finally:
            manager.shutdown()

        assert store.load_dedup_cache() == {}
        diagnostic = store.read_json("run-3", "runner_failure.json")
        assert diagnostic["phase"] == "input_verification"
        assert diagnostic["returncode"] == 255


def test_directory_manifest_is_deterministic_and_content_sensitive(
    tmp_path: Path,
) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    for root in (first, second):
        (root / "nested").mkdir(parents=True)
    (first / "z.txt").write_text("z", encoding="utf-8")
    (first / "nested" / "a.txt").write_text("a", encoding="utf-8")
    (second / "nested" / "a.txt").write_text("a", encoding="utf-8")
    (second / "z.txt").write_text("z", encoding="utf-8")

    first_manifest = build_canonical_tree_manifest(first)
    second_manifest = build_canonical_tree_manifest(second)

    assert first_manifest == second_manifest
    (second / "z.txt").write_text("changed", encoding="utf-8")
    assert (
        build_canonical_tree_manifest(second).manifest_digest
        != first_manifest.manifest_digest
    )


def test_directory_manifest_rejects_symlinks_and_persists_private_manifest(
    tmp_path: Path,
) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    target = tmp_path / "outside.txt"
    target.write_text("outside", encoding="utf-8")
    (root / "link").symlink_to(target)

    with pytest.raises(ValueError, match="symbolic links"):
        build_canonical_tree_manifest(root)


def test_directory_upload_persists_and_verifies_canonical_tree_manifest() -> None:
    with _short_root() as root:
        local = root / "tree"
        (local / "nested").mkdir(parents=True)
        (local / "nested" / "input.txt").write_text("bytes", encoding="utf-8")
        authorized = AuthorizedInput.from_path(local)
        runner = VerificationRunner(
            [
                _result(remote_verification_stdout(authorized)),
                _result(remote_verification_stdout(authorized)),
            ]
        )
        staging, store, manager = _staging(root, runner)
        try:
            entries = staging.upload_inputs(
                "run-tree",
                [StagedInput(local_path=str(local), remote_path="tree")],
                "mcp_runs/run-tree",
            )
        finally:
            manager.shutdown()

        persisted = store.read_json(
            "run-tree",
            "input_tree_manifest_000001.json",
        )
        assert persisted["schema_version"] == "canonical_tree_manifest@1"
        assert persisted["manifest_digest"] == authorized.content_digest
        assert entries[0]["kind"] == "directory"
        assert entries[0]["tree_manifest_digest"] == authorized.content_digest
        assert entries[0]["verification_status"] == "verified"
        transfer = next(
            command
            for command, stage in zip(runner.commands, runner.stages, strict=True)
            if stage == "staging" and command[0] == "scp"
        )
        assert "-r" in transfer


def test_hash_mkdir_and_transfer_use_one_control_path() -> None:
    with _short_root() as root:
        local = root / "input.txt"
        local.write_text("exact bytes", encoding="utf-8")
        authorized = AuthorizedInput.from_path(local)
        runner = VerificationRunner(
            [
                _result(remote_verification_stdout(authorized)),
                _result(remote_verification_stdout(authorized)),
            ]
        )
        staging, _, manager = _staging(root, runner)
        try:
            staging.upload_inputs(
                "run-4",
                [StagedInput(local_path=str(local), remote_path="input.txt")],
                "mcp_runs/run-4",
            )
        finally:
            manager.shutdown()

        relevant = [
            command
            for command, stage in zip(runner.commands, runner.stages, strict=True)
            if stage in {"staging", "input_verification"}
        ]
        control_paths = {
            item
            for command in relevant
            for item in command
            if item.startswith("ControlPath=")
        }
        assert len(relevant) == 5
        assert len(control_paths) == 1


def test_digest_mismatch_after_upload_never_populates_cache() -> None:
    with _short_root() as root:
        local = root / "input.txt"
        local.write_text("authorized", encoding="utf-8")
        authorized = AuthorizedInput.from_path(local)
        runner = VerificationRunner(
            [
                _result(
                    remote_verification_stdout(
                        authorized,
                        observed_content_digest="sha256:" + "f" * 64,
                    )
                )
            ]
        )
        staging, store, manager = _staging(root, runner)
        try:
            with pytest.raises(HpcStagingFailure, match="phase=input_verification"):
                staging.upload_inputs(
                    "run-5",
                    [StagedInput(local_path=str(local), remote_path="input.txt")],
                    "mcp_runs/run-5",
                )
        finally:
            manager.shutdown()

        assert store.load_dedup_cache() == {}
        manifest_path = (
            store.run_root("run-5") / "metadata" / "inputs_manifest.json"
        )
        assert not manifest_path.exists()
        assert runner.stages.count("input_verification") == 1


def test_remote_receipt_status_is_closed() -> None:
    with _short_root() as root:
        local = root / "input.txt"
        local.write_text("authorized", encoding="utf-8")
        runner = VerificationRunner([_result("not-a-closed-receipt")])
        staging, _, manager = _staging(root, runner)
        try:
            with pytest.raises(HpcStagingFailure) as caught:
                staging.upload_inputs(
                    "run-6",
                    [StagedInput(local_path=str(local), remote_path="input.txt")],
                    "mcp_runs/run-6",
                )
        finally:
            manager.shutdown()

        assert caught.value.returncode == 69
        assert RemoteVerificationStatus.INVALID_RECEIPT.value == "invalid_receipt"
