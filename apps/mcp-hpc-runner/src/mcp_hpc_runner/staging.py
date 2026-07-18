from __future__ import annotations

from pathlib import Path, PurePosixPath
import hashlib
from typing import Any, Never

from .config import RunnerConfig
from .errors import HpcStagingFailure, StagingFailurePhase
from .models import ExpectedOutput, StagedInput
from .remote import CommandResult, CommandRunner, wrap_ssh
from .store import ArtifactStore
from .validation import safe_relative_path, safe_remote_run_dir


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    if path.is_file():
        with path.open("rb") as handle:
            while True:
                chunk = handle.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
        return digest.hexdigest()

    for child in sorted(path.rglob("*")):
        digest.update(str(child.relative_to(path)).encode("utf-8"))
        if child.is_file():
            with child.open("rb") as handle:
                while True:
                    chunk = handle.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
    return digest.hexdigest()


class StagingManager:
    def __init__(
        self, config: RunnerConfig, store: ArtifactStore, command_runner: CommandRunner
    ) -> None:
        self.config = config
        self.store = store
        self.command_runner = command_runner

    @property
    def _ssh_target(self) -> str:
        return self.config.cluster.ssh_target

    def raise_staging_failure(
        self,
        *,
        phase: StagingFailurePhase,
        run_id: str,
        result: CommandResult,
        input_ordinal: int | None = None,
        content_digest: str | None = None,
    ) -> Never:
        failure = HpcStagingFailure(
            phase=phase,
            run_id=run_id,
            input_ordinal=input_ordinal,
            content_digest=content_digest,
            returncode=result.returncode,
            timed_out=result.timed_out,
            elapsed_seconds=result.elapsed_seconds,
        )
        self.store.write_runner_failure_manifest(
            run_id,
            failure.to_safe_diagnostic(),
        )
        raise failure from None

    def build_upload_command(
        self, local_path: Path, remote_path: str, use_rsync: bool
    ) -> list[str]:
        if use_rsync:
            return [
                "rsync",
                "-az",
                "--partial",
                "-e",
                "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=2",
                str(local_path),
                f"{self._ssh_target}:{remote_path}",
            ]
        cmd = [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=2",
        ]
        if local_path.is_dir():
            cmd.append("-r")
        cmd.extend([str(local_path), f"{self._ssh_target}:{remote_path}"])
        return cmd

    def build_download_command(
        self, remote_path: str, local_path: Path, use_rsync: bool
    ) -> list[str]:
        if use_rsync:
            return [
                "rsync",
                "-az",
                "--partial",
                "-e",
                "ssh -o BatchMode=yes -o ConnectTimeout=15 -o ServerAliveInterval=30 -o ServerAliveCountMax=2",
                f"{self._ssh_target}:{remote_path}",
                str(local_path),
            ]
        return [
            "scp",
            "-o",
            "BatchMode=yes",
            "-o",
            "ConnectTimeout=15",
            "-o",
            "ServerAliveInterval=30",
            "-o",
            "ServerAliveCountMax=2",
            "-r",
            f"{self._ssh_target}:{remote_path}",
            str(local_path),
        ]

    def upload_inputs(
        self, run_id: str, inputs: list[StagedInput], remote_run_dir: str
    ) -> list[dict[str, Any]]:
        run_dir = safe_remote_run_dir(remote_run_dir)
        if not inputs:
            self.store.write_inputs_manifest(run_id, {"run_id": run_id, "entries": []})
            return []

        cache = self.store.load_dedup_cache()
        entries: list[dict[str, Any]] = []
        for input_ordinal, item in enumerate(inputs, start=1):
            stage_to = str(item.stage_to)
            if stage_to not in {"work", "out"}:
                raise ValueError("inputs.stage_to must be one of ['out', 'work']")
            relative_path = safe_relative_path(
                item.remote_path,
                field="inputs.remote_path",
            )
            local_path = Path(item.local_path).expanduser().resolve()
            remote_path = str(
                run_dir / stage_to / relative_path
            )
            remote_parent = str(PurePosixPath(remote_path).parent)
            checksum = _sha256(local_path)
            content_digest = f"sha256:{checksum}"
            # Key is content + absolute remote destination (run-specific).
            # This avoids collisions across runs when remote_path is reused.
            cache_key = f"{checksum}:{remote_path}"
            skipped = cache.get(cache_key) == remote_path

            if not skipped:
                mkdir_cmd = wrap_ssh(self._ssh_target, ["mkdir", "-p", remote_parent])
                parent_result = self.command_runner.run(
                    mkdir_cmd,
                    check=False,
                    timeout=self.config.execution.staging_timeout_seconds,
                    stage="staging",
                )
                if parent_result.returncode != 0:
                    self.raise_staging_failure(
                        phase="input_parent",
                        run_id=run_id,
                        result=parent_result,
                        input_ordinal=input_ordinal,
                        content_digest=content_digest,
                    )
                transfer_cmd = self.build_upload_command(
                    local_path, remote_path, use_rsync=self.config.execution.use_rsync
                )
                transfer = self.command_runner.run(
                    transfer_cmd,
                    check=False,
                    timeout=self.config.execution.staging_timeout_seconds,
                    stage="staging",
                )
                if transfer.returncode != 0 and self.config.execution.use_rsync:
                    fallback = self.build_upload_command(
                        local_path, remote_path, use_rsync=False
                    )
                    fallback_result = self.command_runner.run(
                        fallback,
                        check=False,
                        timeout=self.config.execution.staging_timeout_seconds,
                        stage="staging",
                    )
                    if fallback_result.returncode != 0:
                        self.raise_staging_failure(
                            phase="input_transfer",
                            run_id=run_id,
                            result=fallback_result,
                            input_ordinal=input_ordinal,
                            content_digest=content_digest,
                        )
                elif transfer.returncode != 0:
                    self.raise_staging_failure(
                        phase="input_transfer",
                        run_id=run_id,
                        result=transfer,
                        input_ordinal=input_ordinal,
                        content_digest=content_digest,
                    )
                cache[cache_key] = remote_path

            entries.append(
                {
                    "local_path": str(local_path),
                    "remote_path": remote_path,
                    "checksum": checksum,
                    "skipped": skipped,
                }
            )

        self.store.save_dedup_cache(cache)
        self.store.write_inputs_manifest(run_id, {"run_id": run_id, "entries": entries})
        return entries

    def download_outputs(
        self,
        run_id: str,
        expected_outputs: list[ExpectedOutput],
        remote_run_dir: str,
    ) -> list[dict[str, Any]]:
        run_dir = safe_remote_run_dir(remote_run_dir)
        layout = self.store.ensure_run_layout(run_id)
        output_root = layout["outputs"]
        entries: list[dict[str, Any]] = []

        for expected in expected_outputs:
            relative_path = safe_relative_path(
                expected.path,
                field="expected_outputs.path",
            )
            remote_path = str(
                run_dir / "out" / relative_path
            )
            local_target = (output_root / Path(*relative_path.parts)).resolve()
            resolved_output_root = output_root.resolve()
            if (
                local_target != resolved_output_root
                and resolved_output_root not in local_target.parents
            ):
                raise ValueError("expected_outputs.path escapes the local output root")
            local_target.parent.mkdir(parents=True, exist_ok=True)

            transfer_cmd = self.build_download_command(
                remote_path,
                local_target,
                use_rsync=self.config.execution.use_rsync,
            )
            transfer = self.command_runner.run(
                transfer_cmd,
                check=False,
                timeout=self.config.execution.artifact_fetch_timeout_seconds,
                stage="artifact_fetch",
            )
            if transfer.returncode != 0 and self.config.execution.use_rsync:
                fallback = self.build_download_command(
                    remote_path, local_target, use_rsync=False
                )
                transfer = self.command_runner.run(
                    fallback,
                    check=False,
                    timeout=self.config.execution.artifact_fetch_timeout_seconds,
                    stage="artifact_fetch",
                )

            entries.append(
                {
                    "remote_path": remote_path,
                    "local_path": str(local_target),
                    "returncode": transfer.returncode,
                    "stderr": transfer.stderr.strip(),
                }
            )

        self.store.write_outputs_manifest(
            run_id, {"run_id": run_id, "entries": entries}
        )
        return entries
