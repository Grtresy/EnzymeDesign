from __future__ import annotations

from pathlib import Path, PurePosixPath
import hashlib
from typing import Any

from .config import RunnerConfig
from .models import ExpectedOutput, StagedInput
from .remote import CommandRunner, wrap_ssh
from .store import ArtifactStore


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

    def build_upload_command(
        self, local_path: Path, remote_path: str, use_rsync: bool
    ) -> list[str]:
        if use_rsync:
            return [
                "rsync",
                "-az",
                "--partial",
                "-e",
                "ssh -o BatchMode=yes",
                str(local_path),
                f"{self._ssh_target}:{remote_path}",
            ]
        cmd = ["scp", "-o", "BatchMode=yes"]
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
                "ssh -o BatchMode=yes",
                f"{self._ssh_target}:{remote_path}",
                str(local_path),
            ]
        return [
            "scp",
            "-o",
            "BatchMode=yes",
            "-r",
            f"{self._ssh_target}:{remote_path}",
            str(local_path),
        ]

    def upload_inputs(
        self, run_id: str, inputs: list[StagedInput], remote_run_dir: str
    ) -> list[dict[str, Any]]:
        if not inputs:
            self.store.write_inputs_manifest(run_id, {"run_id": run_id, "entries": []})
            return []

        cache = self.store.load_dedup_cache()
        entries: list[dict[str, Any]] = []
        for item in inputs:
            local_path = Path(item.local_path).expanduser().resolve()
            remote_path = str(PurePosixPath(remote_run_dir) / item.stage_to / item.remote_path)
            remote_parent = str(PurePosixPath(remote_path).parent)
            checksum = _sha256(local_path)
            # Key is content + absolute remote destination (run-specific).
            # This avoids collisions across runs when remote_path is reused.
            cache_key = f"{checksum}:{remote_path}"
            skipped = cache.get(cache_key) == remote_path

            if not skipped:
                mkdir_cmd = wrap_ssh(self._ssh_target, ["mkdir", "-p", remote_parent])
                self.command_runner.run(mkdir_cmd, check=True)
                transfer_cmd = self.build_upload_command(
                    local_path, remote_path, use_rsync=self.config.execution.use_rsync
                )
                transfer = self.command_runner.run(transfer_cmd, check=False)
                if transfer.returncode != 0 and self.config.execution.use_rsync:
                    fallback = self.build_upload_command(
                        local_path, remote_path, use_rsync=False
                    )
                    self.command_runner.run(fallback, check=True)
                elif transfer.returncode != 0:
                    raise RuntimeError(transfer.stderr.strip())
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
        layout = self.store.ensure_run_layout(run_id)
        output_root = layout["outputs"]
        entries: list[dict[str, Any]] = []

        for expected in expected_outputs:
            remote_path = str(PurePosixPath(remote_run_dir) / "out" / expected.path)
            local_target = output_root / expected.path
            local_target.parent.mkdir(parents=True, exist_ok=True)

            transfer_cmd = self.build_download_command(
                remote_path,
                local_target,
                use_rsync=self.config.execution.use_rsync,
            )
            transfer = self.command_runner.run(transfer_cmd, check=False)
            if transfer.returncode != 0 and self.config.execution.use_rsync:
                fallback = self.build_download_command(
                    remote_path, local_target, use_rsync=False
                )
                transfer = self.command_runner.run(fallback, check=False)

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
