from __future__ import annotations

from pathlib import Path, PurePosixPath
import shutil
from typing import Any, Never

from .config import RunnerConfig
from .errors import HpcOutputFailure
from .errors import HpcStagingFailure, StagingFailurePhase
from .models import ExpectedOutput, StagedInput
from .remote import CommandResult, CommandRunner
from .store import ArtifactStore
from .transport import SshCommandCompiler
from .transport import SshTransportManager
from .validation import safe_relative_path, safe_remote_run_dir
from .verification import AuthorizedInput
from .verification import InputKind
from .verification import RemoteInputVerifier
from .verification import RemoteVerification
from .verification import RemoteVerificationStatus


_REMOTE_REPLACE_AUTHORIZED_INPUT = r'''
import os
import shutil
import stat
import sys

source = sys.argv[1]
destination = sys.argv[2]
source_parent = os.path.normpath(os.path.dirname(source))
destination_parent = os.path.normpath(os.path.dirname(destination))
if source_parent != destination_parent or source == destination:
    raise SystemExit(64)
source_metadata = os.lstat(source)
if stat.S_ISLNK(source_metadata.st_mode):
    raise SystemExit(65)
try:
    destination_metadata = os.lstat(destination)
except FileNotFoundError:
    destination_metadata = None
if destination_metadata is not None:
    if stat.S_ISLNK(destination_metadata.st_mode):
        raise SystemExit(66)
    if stat.S_ISDIR(destination_metadata.st_mode):
        shutil.rmtree(destination)
    elif stat.S_ISREG(destination_metadata.st_mode):
        os.unlink(destination)
    else:
        raise SystemExit(67)
os.replace(source, destination)
'''.strip()

_REMOTE_RESET_TRANSFER_CANDIDATE = r'''
import os
import shutil
import stat
import sys

candidate = sys.argv[1]
try:
    metadata = os.lstat(candidate)
except FileNotFoundError:
    raise SystemExit(0)
if stat.S_ISLNK(metadata.st_mode):
    raise SystemExit(65)
if stat.S_ISDIR(metadata.st_mode):
    shutil.rmtree(candidate)
elif stat.S_ISREG(metadata.st_mode):
    os.unlink(candidate)
else:
    raise SystemExit(66)
'''.strip()


class StagingManager:
    def __init__(
        self,
        config: RunnerConfig,
        store: ArtifactStore,
        command_runner: CommandRunner,
        ssh_compiler: SshCommandCompiler | None = None,
        transport_manager: SshTransportManager | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.command_runner = command_runner
        self.ssh_compiler = ssh_compiler or SshCommandCompiler.legacy(
            config.cluster.ssh_target
        )
        self.transport_manager = transport_manager or SshTransportManager(
            config,
            command_runner,
        )
        self.remote_verifier = RemoteInputVerifier(self.transport_manager)

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
            process_started=result.process_started,
            executable=(result.args[0] if result.args else "ssh"),
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
            return self.ssh_compiler.rsync_upload(local_path, remote_path)
        return self.ssh_compiler.scp_upload(
            local_path,
            remote_path,
            recursive=local_path.is_dir(),
        )

    def build_download_command(
        self, remote_path: str, local_path: Path, use_rsync: bool
    ) -> list[str]:
        if use_rsync:
            return self.ssh_compiler.rsync_download(remote_path, local_path)
        return self.ssh_compiler.scp_download(
            remote_path,
            local_path,
            recursive=True,
        )

    def _raise_verification_failure(
        self,
        *,
        run_id: str,
        input_ordinal: int,
        content_digest: str,
        verification: RemoteVerification,
    ) -> Never:
        synthetic_returncode = verification.returncode
        if synthetic_returncode == 0:
            synthetic_returncode = {
                RemoteVerificationStatus.MISSING: 64,
                RemoteVerificationStatus.KIND_MISMATCH: 65,
                RemoteVerificationStatus.DIGEST_MISMATCH: 66,
                RemoteVerificationStatus.UNSAFE_TREE: 67,
                RemoteVerificationStatus.METADATA_BOUND_EXCEEDED: 68,
                RemoteVerificationStatus.INVALID_RECEIPT: 69,
            }.get(verification.status, 70)
        self.raise_staging_failure(
            phase="input_verification",
            run_id=run_id,
            result=CommandResult(
                args=[],
                returncode=synthetic_returncode,
                stdout="",
                stderr="",
                timed_out=verification.timed_out,
                elapsed_seconds=verification.elapsed_seconds,
                process_started=verification.process_started,
                stage="input_verification",
            ),
            input_ordinal=input_ordinal,
            content_digest=content_digest,
        )

    def _raise_output_failure(
        self,
        *,
        phase: str,
        run_id: str,
        output_ordinal: int,
        content_digest: str | None,
        result: CommandResult,
    ) -> Never:
        failure = HpcOutputFailure(
            phase=phase,  # type: ignore[arg-type]
            run_id=run_id,
            output_ordinal=output_ordinal,
            content_digest=content_digest,
            returncode=result.returncode,
            timed_out=result.timed_out,
            elapsed_seconds=result.elapsed_seconds,
            process_started=result.process_started,
            executable=(result.args[0] if result.args else "ssh"),
        )
        self.store.write_runner_failure_manifest(
            run_id,
            failure.to_safe_diagnostic(),
        )
        raise failure from None

    @staticmethod
    def _remote_transfer_candidate(
        remote_path: str,
        *,
        input_ordinal: int,
        content_digest: str,
    ) -> str:
        destination = PurePosixPath(remote_path)
        suffix = content_digest.removeprefix("sha256:")[:24]
        return str(
            destination.parent
            / f".openzyme-stage-{input_ordinal:06d}-{suffix}"
        )

    def _run_candidate_command(
        self,
        *,
        run_id: str,
        input_ordinal: int,
        content_digest: str,
        remote_argv: list[str],
    ) -> None:
        result = self.transport_manager.run_ssh(
            remote_argv,
            check=False,
            timeout=self.config.execution.staging_timeout_seconds,
            stage="staging",
        )
        if result.returncode != 0:
            self.raise_staging_failure(
                phase="input_transfer",
                run_id=run_id,
                result=result,
                input_ordinal=input_ordinal,
                content_digest=content_digest,
            )

    def upload_inputs(
        self,
        run_id: str,
        inputs: list[StagedInput],
        remote_run_dir: str,
        *,
        verify_before_transfer: bool = False,
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
            authorized = AuthorizedInput.from_path(local_path)
            content_digest = authorized.content_digest
            transfer_remote_path = (
                self._remote_transfer_candidate(
                    remote_path,
                    input_ordinal=input_ordinal,
                    content_digest=content_digest,
                )
                if self.transport_manager.enabled
                else remote_path
            )
            checksum = content_digest.removeprefix("sha256:")
            if authorized.tree_manifest is not None:
                self.store.write_json(
                    run_id,
                    f"input_tree_manifest_{input_ordinal:06d}.json",
                    authorized.tree_manifest.to_dict(),
                )
            # Key is content + absolute remote destination (run-specific).
            # This avoids collisions across runs when remote_path is reused.
            cache_key = f"{checksum}:{remote_path}"
            cache_hit = cache.get(cache_key) == remote_path
            skipped = False
            verification: RemoteVerification | None = None

            if self.transport_manager.enabled and cache_hit:
                verification = self.remote_verifier.verify(
                    remote_path,
                    authorized,
                    timeout=self.config.execution.staging_timeout_seconds,
                )
                if verification.verified:
                    skipped = True
                else:
                    cache.pop(cache_key, None)
                    self.store.save_dedup_cache(cache)
                    if verification.status not in {
                        RemoteVerificationStatus.MISSING,
                        RemoteVerificationStatus.DIGEST_MISMATCH,
                    }:
                        self._raise_verification_failure(
                            run_id=run_id,
                            input_ordinal=input_ordinal,
                            content_digest=content_digest,
                            verification=verification,
                        )
            elif not self.transport_manager.enabled:
                skipped = cache_hit

            if (
                self.transport_manager.enabled
                and verify_before_transfer
                and not skipped
                and not cache_hit
            ):
                verification = self.remote_verifier.verify(
                    remote_path,
                    authorized,
                    timeout=self.config.execution.staging_timeout_seconds,
                )
                if verification.verified:
                    skipped = True
                    cache[cache_key] = remote_path
                    self.store.save_dedup_cache(cache)
                elif verification.status not in {
                    RemoteVerificationStatus.MISSING,
                    RemoteVerificationStatus.DIGEST_MISMATCH,
                }:
                    self._raise_verification_failure(
                        run_id=run_id,
                        input_ordinal=input_ordinal,
                        content_digest=content_digest,
                        verification=verification,
                    )

            if not skipped:
                parent_result = self.transport_manager.run_ssh(
                    ["mkdir", "-p", remote_parent],
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
                candidate_ready = False
                if self.transport_manager.enabled and verify_before_transfer:
                    candidate_verification = self.remote_verifier.verify(
                        transfer_remote_path,
                        authorized,
                        timeout=self.config.execution.staging_timeout_seconds,
                    )
                    candidate_ready = candidate_verification.verified
                    if (
                        not candidate_ready
                        and candidate_verification.status
                        not in {
                            RemoteVerificationStatus.MISSING,
                            RemoteVerificationStatus.DIGEST_MISMATCH,
                        }
                    ):
                        self._raise_verification_failure(
                            run_id=run_id,
                            input_ordinal=input_ordinal,
                            content_digest=content_digest,
                            verification=candidate_verification,
                        )
                    if (
                        candidate_verification.status
                        is RemoteVerificationStatus.DIGEST_MISMATCH
                        and not self.config.execution.use_rsync
                    ):
                        self._run_candidate_command(
                            run_id=run_id,
                            input_ordinal=input_ordinal,
                            content_digest=content_digest,
                            remote_argv=[
                                "python3",
                                "-c",
                                _REMOTE_RESET_TRANSFER_CANDIDATE,
                                transfer_remote_path,
                            ],
                        )
                transfer = CommandResult(
                    args=[],
                    returncode=0,
                    stdout="",
                    stderr="",
                    stage="staging",
                )
                if not candidate_ready:
                    transfer = self.transport_manager.run_upload(
                        local_path,
                        transfer_remote_path,
                        use_rsync=self.config.execution.use_rsync,
                        check=False,
                        timeout=self.config.execution.staging_timeout_seconds,
                        stage="staging",
                    )
                if transfer.returncode != 0 and self.transport_manager.enabled:
                    self.raise_staging_failure(
                        phase="input_transfer",
                        run_id=run_id,
                        result=transfer,
                        input_ordinal=input_ordinal,
                        content_digest=content_digest,
                    )
                if transfer.returncode != 0 and self.config.execution.use_rsync:
                    fallback_result = self.transport_manager.run_upload(
                        local_path,
                        remote_path,
                        use_rsync=False,
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
                if self.transport_manager.enabled:
                    candidate_verification = self.remote_verifier.verify(
                        transfer_remote_path,
                        authorized,
                        timeout=self.config.execution.staging_timeout_seconds,
                    )
                    if not candidate_verification.verified:
                        cache.pop(cache_key, None)
                        self.store.save_dedup_cache(cache)
                        self._raise_verification_failure(
                            run_id=run_id,
                            input_ordinal=input_ordinal,
                            content_digest=content_digest,
                            verification=candidate_verification,
                        )
                    self._run_candidate_command(
                        run_id=run_id,
                        input_ordinal=input_ordinal,
                        content_digest=content_digest,
                        remote_argv=[
                            "python3",
                            "-c",
                            _REMOTE_REPLACE_AUTHORIZED_INPUT,
                            transfer_remote_path,
                            remote_path,
                        ],
                    )
                    verification = self.remote_verifier.verify(
                        remote_path,
                        authorized,
                        timeout=self.config.execution.staging_timeout_seconds,
                    )
                    if not verification.verified:
                        cache.pop(cache_key, None)
                        self.store.save_dedup_cache(cache)
                        self._raise_verification_failure(
                            run_id=run_id,
                            input_ordinal=input_ordinal,
                            content_digest=content_digest,
                            verification=verification,
                        )
                cache[cache_key] = remote_path
                self.store.save_dedup_cache(cache)

            entries.append(
                {
                    "input_ordinal": input_ordinal,
                    "artifact_id": item.artifact_id,
                    "local_path": str(local_path),
                    "remote_path": remote_path,
                    "checksum": checksum,
                    "kind": authorized.kind.value,
                    "content_digest": content_digest,
                    "authorized_input_digest": authorized.contract_digest,
                    "tree_manifest_digest": (
                        None
                        if authorized.tree_manifest is None
                        else authorized.tree_manifest.manifest_digest
                    ),
                    "verification_status": (
                        "legacy_unverified"
                        if not self.transport_manager.enabled
                        else (
                            verification.status.value
                            if verification is not None
                            else "invalid_receipt"
                        )
                    ),
                    "verification_receipt_digest": (
                        None if verification is None else verification.receipt_digest
                    ),
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
        if not self.transport_manager.enabled:
            return self._download_outputs_legacy(
                run_id,
                expected_outputs,
                remote_run_dir,
            )
        run_dir = safe_remote_run_dir(remote_run_dir)
        layout = self.store.ensure_run_layout(run_id)
        output_root = layout["outputs"]
        entries: list[dict[str, Any]] = []

        for output_ordinal, expected in enumerate(expected_outputs, start=1):
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
            kind = (
                InputKind.FILE
                if expected.kind == "file"
                else InputKind.DIRECTORY
            )
            observation = self.remote_verifier.observe(
                remote_path,
                timeout=self.config.execution.artifact_fetch_timeout_seconds,
                kind=kind,
                stage="output_observation",
            )
            if not observation.observed:
                if (
                    observation.status is RemoteVerificationStatus.MISSING
                    and not expected.required
                ):
                    entries.append(
                        {
                            "output_ordinal": output_ordinal,
                            "remote_path": remote_path,
                            "local_path": str(local_target),
                            "returncode": 1,
                            "verification_status": observation.status.value,
                            "verification_receipt_digest": (
                                observation.receipt_digest
                            ),
                            "skipped": True,
                        }
                    )
                    continue
                synthetic_code = observation.returncode or {
                    RemoteVerificationStatus.MISSING: 64,
                    RemoteVerificationStatus.KIND_MISMATCH: 65,
                    RemoteVerificationStatus.UNSAFE_TREE: 67,
                    RemoteVerificationStatus.METADATA_BOUND_EXCEEDED: 68,
                    RemoteVerificationStatus.INVALID_RECEIPT: 69,
                }.get(observation.status, 70)
                self._raise_output_failure(
                    phase="output_observation",
                    run_id=run_id,
                    output_ordinal=output_ordinal,
                    content_digest=observation.content_digest,
                    result=CommandResult(
                        args=[],
                        returncode=synthetic_code,
                        stdout="",
                        stderr="",
                        timed_out=observation.timed_out,
                        elapsed_seconds=observation.elapsed_seconds,
                        process_started=observation.process_started,
                        stage="output_observation",
                    ),
                )
            assert observation.content_digest is not None
            skipped = self._local_matches(
                local_target,
                kind=kind,
                content_digest=observation.content_digest,
            )
            if not skipped:
                digest_suffix = observation.content_digest.removeprefix("sha256:")[:24]
                candidate_root = (
                    layout["metadata"]
                    / "output_candidates"
                    / f"{output_ordinal:06d}-{digest_suffix}"
                )
                candidate_root.mkdir(parents=True, exist_ok=True)
                candidate = candidate_root / "payload"
                candidate_ready = self._local_matches(
                    candidate,
                    kind=kind,
                    content_digest=observation.content_digest,
                )
                if not candidate_ready:
                    transfer = self.transport_manager.run_download(
                        remote_path,
                        candidate,
                        use_rsync=self.config.execution.use_rsync,
                        check=False,
                        timeout=self.config.execution.artifact_fetch_timeout_seconds,
                        stage="output_fetch",
                    )
                    if transfer.returncode != 0:
                        self._raise_output_failure(
                            phase="output_fetch",
                            run_id=run_id,
                            output_ordinal=output_ordinal,
                            content_digest=observation.content_digest,
                            result=transfer,
                        )
                if not self._local_matches(
                    candidate,
                    kind=kind,
                    content_digest=observation.content_digest,
                ):
                    self._raise_output_failure(
                        phase="output_verification",
                        run_id=run_id,
                        output_ordinal=output_ordinal,
                        content_digest=observation.content_digest,
                        result=CommandResult(
                            args=[],
                            returncode=66,
                            stdout="",
                            stderr="",
                            stage="output_verification",
                        ),
                    )
                self._replace_local_target(candidate, local_target)

            entries.append(
                {
                    "output_ordinal": output_ordinal,
                    "remote_path": remote_path,
                    "local_path": str(local_target),
                    "returncode": 0,
                    "kind": kind.value,
                    "content_digest": observation.content_digest,
                    "verification_status": observation.status.value,
                    "verification_receipt_digest": observation.receipt_digest,
                    "skipped": skipped,
                }
            )

        self.store.write_outputs_manifest(
            run_id, {"run_id": run_id, "entries": entries}
        )
        return entries

    def _download_outputs_legacy(
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
            remote_path = str(run_dir / "out" / relative_path)
            local_target = (output_root / Path(*relative_path.parts)).resolve()
            resolved_output_root = output_root.resolve()
            if (
                local_target != resolved_output_root
                and resolved_output_root not in local_target.parents
            ):
                raise ValueError("expected_outputs.path escapes the local output root")
            local_target.parent.mkdir(parents=True, exist_ok=True)
            transfer = self.transport_manager.run_download(
                remote_path,
                local_target,
                use_rsync=self.config.execution.use_rsync,
                check=False,
                timeout=self.config.execution.artifact_fetch_timeout_seconds,
                stage="artifact_fetch",
            )
            if transfer.returncode != 0 and self.config.execution.use_rsync:
                transfer = self.transport_manager.run_download(
                    remote_path,
                    local_target,
                    use_rsync=False,
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
            run_id,
            {"run_id": run_id, "entries": entries},
        )
        return entries

    @staticmethod
    def _local_matches(
        path: Path,
        *,
        kind: InputKind,
        content_digest: str,
    ) -> bool:
        try:
            authorized = AuthorizedInput.from_path(path)
        except (FileNotFoundError, OSError, ValueError):
            return False
        return authorized.kind is kind and authorized.content_digest == content_digest

    @staticmethod
    def _replace_local_target(candidate: Path, target: Path) -> None:
        if target.exists() or target.is_symlink():
            if target.is_symlink():
                raise ValueError("local output target must not be a symbolic link")
            if target.is_dir():
                shutil.rmtree(target)
            else:
                target.unlink()
        candidate.replace(target)
