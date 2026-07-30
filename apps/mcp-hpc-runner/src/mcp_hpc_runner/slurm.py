from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
import shlex
from typing import Any
import uuid

from .attempts import receipt_digest
from .attempts import runner_phase_precedes
from .attempts import safe_runner_exception_code
from .attempts import RunnerAttempt
from .attempts import RunnerAttemptError
from .attempts import RunnerAttemptJournal
from .attempts import RunnerAttemptPhase
from .attempts import RunnerAttemptState
from .attempts import RunnerEffectCertainty
from .attempts import RunnerRetryEligibility
from .config import RunnerConfig
from .errors import FailureMapper
from .errors import HpcOutputFailure
from .errors import HpcStagingFailure
from .logging_utils import prepare_log_payload, redact_text
from .models import JobHandle, JobStatus, RunResult, RunSpec
from .preflight import PreflightError, preflight_manifest, run_preflight
from .preflight import PreflightFailureClass
from .preflight import PreflightResult
from .recovery import classify_pre_effect_failure
from .recovery import PreEffectFailureClass
from .recovery import safe_transport_failure_receipt
from .remote import CommandResult, CommandRunner
from .staging import StagingManager
from .store import ArtifactStore
from .transport import SshCommandCompiler
from .transport import SshTransportManager
from .validation import (
    ensure_safe_slurm_token,
    ensure_valid_runspec,
    run_success_checks,
    safe_remote_run_dir,
    validate_expected_outputs,
)
from .verification import AuthorizedInput
from .verification import RemoteVerificationStatus


def _map_slurm_state(raw: str) -> str:
    upper = raw.strip().upper()
    if not upper:
        return "unknown"
    if upper in {"PENDING", "CONFIGURING", "REQUEUE_FED"}:
        return "queued"
    if upper in {"RUNNING", "COMPLETING"}:
        return "running"
    if upper in {"COMPLETED"}:
        return "completed"
    if upper in {"CANCELLED", "PREEMPTED"}:
        return "cancelled"
    if upper in {"FAILED", "TIMEOUT", "OUT_OF_MEMORY", "NODE_FAIL"}:
        return "failed"
    return "unknown"


class SlurmRunner:
    def __init__(
        self,
        config: RunnerConfig,
        store: ArtifactStore,
        staging: StagingManager,
        command_runner: CommandRunner,
        failure_mapper: FailureMapper,
        ssh_compiler: SshCommandCompiler | None = None,
        transport_manager: SshTransportManager | None = None,
        attempt_journal: RunnerAttemptJournal | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.staging = staging
        self.command_runner = command_runner
        self.failure_mapper = failure_mapper
        self.ssh_compiler = ssh_compiler or SshCommandCompiler.legacy(
            config.cluster.ssh_target
        )
        self.transport_manager = transport_manager or staging.transport_manager
        self.attempt_journal = attempt_journal or RunnerAttemptJournal(
            store,
            config,
            self.transport_manager,
        )

    @property
    def command_runner(self) -> CommandRunner:
        return self._command_runner

    @command_runner.setter
    def command_runner(self, value: CommandRunner) -> None:
        self._command_runner = value
        manager = getattr(self, "transport_manager", None)
        if manager is not None:
            manager.command_runner = value

    def _make_run_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _remote_run_dir(self, run_id: str) -> str:
        return str(PurePosixPath(self.config.cluster.remote_base_dir) / run_id)

    def _ensure_remote_layout(self, run_id: str, remote_run_dir: str) -> None:
        result = self.transport_manager.run_ssh(
            [
                "mkdir",
                "-p",
                str(PurePosixPath(remote_run_dir) / "work"),
                str(PurePosixPath(remote_run_dir) / "out"),
                str(PurePosixPath(remote_run_dir) / "tmp"),
                str(PurePosixPath(remote_run_dir) / "logs"),
            ],
            check=False,
            timeout=self.config.execution.staging_timeout_seconds,
            stage="staging",
        )
        if result.returncode != 0:
            self.staging.raise_staging_failure(
                phase="remote_layout",
                run_id=run_id,
                result=result,
            )

    @staticmethod
    def _staging_failure_result(failure: HpcStagingFailure) -> CommandResult:
        return CommandResult(
            args=[failure.executable],
            returncode=failure.returncode,
            stdout="",
            stderr="",
            timed_out=failure.timed_out,
            elapsed_seconds=failure.elapsed_seconds,
            process_started=failure.process_started,
            stage=failure.phase,
        )

    @staticmethod
    def _output_failure_result(failure: HpcOutputFailure) -> CommandResult:
        return CommandResult(
            args=[failure.executable],
            returncode=failure.returncode,
            stdout="",
            stderr="",
            timed_out=failure.timed_out,
            elapsed_seconds=failure.elapsed_seconds,
            process_started=failure.process_started,
            stage=failure.phase,
        )

    def _fetch_outputs_with_recovery(
        self,
        spec: RunSpec,
        run_id: str,
        remote_run_dir: str,
    ) -> tuple[list[dict[str, object]], RunnerAttempt | None, str | None]:
        while True:
            try:
                return (
                    self.staging.download_outputs(
                        run_id,
                        spec.expected_outputs,
                        remote_run_dir,
                    ),
                    None,
                    None,
                )
            except HpcOutputFailure as exc:
                result = self._output_failure_result(exc)
                failure_receipt = exc.to_safe_diagnostic()
                if (
                    classify_pre_effect_failure(result)
                    is PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                ):
                    recovered = self.attempt_journal.authorize_output_fetch_recovery(
                        run_id,
                        spec,
                        selected_mode="sbatch",
                        failure_receipt=failure_receipt,
                    )
                    if recovered is not None:
                        continue
                    terminal = self.attempt_journal.terminalize_output_fetch_failure(
                        run_id,
                        spec,
                        selected_mode="sbatch",
                        failure_receipt=failure_receipt,
                        safe_failure_code="output_fetch_recovery_exhausted",
                    )
                    return [], terminal, "OUTPUT_FETCH_INTERRUPTED"
                quarantined = self.attempt_journal.quarantine_output_conflict(
                    run_id,
                    spec,
                    selected_mode="sbatch",
                    failure_receipt=failure_receipt,
                )
                return [], quarantined, "OUTPUT_CONTRACT_CONFLICT"

    @staticmethod
    def _attempt_metadata(
        attempt: RunnerAttempt,
        *,
        status: str | None = None,
        error_code: str | None = None,
    ) -> dict[str, object]:
        return {
            **({} if status is None else {"status": status}),
            **({} if error_code is None else {"error_code": error_code}),
            "runner_attempt_safe_receipt_digest": attempt.safe_receipt_digest,
            "runner_phase": attempt.phase.value,
            "effect_certainty": attempt.effect_certainty.value,
            "retry_eligibility": attempt.retry_eligibility.value,
            "reconciliation_required": attempt.reconciliation_required,
        }

    def _closed_attempt_result(
        self,
        spec: RunSpec,
        attempt: RunnerAttempt,
        *,
        error_code: str,
    ) -> RunResult:
        run_id = str(spec.run_id)
        metadata = self._attempt_metadata(
            attempt,
            status="failed",
            error_code=error_code,
        )
        self.store.write_json(run_id, "run_result_metadata.json", metadata)
        return RunResult(
            run_id=run_id,
            requested_mode=spec.execution_mode,
            selected_mode="sbatch",
            remote_run_dir=self._remote_run_dir(run_id),
            status="failed",
            error_code=error_code,
            artifacts={},
            logs={},
            metadata=metadata,
        )

    def _ensure_remote_layout_with_recovery(
        self,
        spec: RunSpec,
        run_id: str,
        remote_run_dir: str,
    ) -> None:
        while True:
            try:
                self._ensure_remote_layout(run_id, remote_run_dir)
                return
            except HpcStagingFailure as exc:
                result = self._staging_failure_result(exc)
                if (
                    classify_pre_effect_failure(result)
                    is not PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                ):
                    raise
                recovered = self.attempt_journal.authorize_pre_effect_recovery(
                    run_id,
                    spec,
                    selected_mode="sbatch",
                    reason_code="remote_layout_transport_recovered",
                    failure_receipt=safe_transport_failure_receipt(
                        result,
                        phase="remote_layout",
                    ),
                )
                if recovered is None:
                    raise

    def _upload_inputs_with_recovery(
        self,
        spec: RunSpec,
        run_id: str,
        remote_run_dir: str,
        *,
        verify_before_transfer: bool = False,
    ) -> list[dict[str, object]]:
        while True:
            try:
                if self.transport_manager.enabled:
                    return self.staging.upload_inputs(
                        run_id,
                        spec.inputs,
                        remote_run_dir,
                        verify_before_transfer=verify_before_transfer,
                    )
                return self.staging.upload_inputs(
                    run_id,
                    spec.inputs,
                    remote_run_dir,
                )
            except HpcStagingFailure as exc:
                result = self._staging_failure_result(exc)
                if (
                    classify_pre_effect_failure(result)
                    is not PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                ):
                    raise
                recovered = self.attempt_journal.authorize_pre_effect_recovery(
                    run_id,
                    spec,
                    selected_mode="sbatch",
                    reason_code="input_staging_transport_recovered",
                    failure_receipt=safe_transport_failure_receipt(
                        result,
                        phase=exc.phase,
                    ),
                )
                if recovered is None:
                    raise
                verify_before_transfer = True

    def _run_preflight_with_recovery(
        self,
        spec: RunSpec,
        run_id: str,
        remote_run_dir: str,
        upload_entries: list[dict[str, object]],
    ) -> PreflightResult:
        while True:
            result = run_preflight(
                spec,
                remote_run_dir,
                self.config,
                self.transport_manager,
                verified_inputs=upload_entries,
            )
            if (
                result.passed
                or result.failure_class
                is not PreflightFailureClass.AUTHENTICATED_TRANSPORT
            ):
                return result
            recovered = self.attempt_journal.authorize_pre_effect_recovery(
                run_id,
                spec,
                selected_mode="sbatch",
                reason_code="preflight_transport_recovered",
                failure_receipt={
                    "schema_version": "preflight_transport_failure@1",
                    "failure_class": result.failure_class.value,
                    "manifest_digest": receipt_digest(result.to_dict()),
                },
            )
            if recovered is None:
                return result

    def _transfer_runner_control_file(
        self,
        *,
        run_id: str,
        local_script: Path,
        remote_script: str,
        verify_before_transfer: bool = False,
    ) -> str | None:
        authorized = AuthorizedInput.from_path(local_script)
        content_digest = authorized.content_digest
        if self.transport_manager.enabled and verify_before_transfer:
            existing = self.staging.remote_verifier.verify(
                remote_script,
                authorized,
                timeout=self.config.execution.staging_timeout_seconds,
            )
            if existing.verified:
                return existing.receipt_digest
            if existing.status not in {
                RemoteVerificationStatus.MISSING,
                RemoteVerificationStatus.DIGEST_MISMATCH,
            }:
                self.staging.raise_staging_failure(
                    phase="runner_control_transfer",
                    run_id=run_id,
                    result=CommandResult(
                        args=[],
                        returncode=existing.returncode or 69,
                        stdout="",
                        stderr="",
                        timed_out=existing.timed_out,
                        elapsed_seconds=existing.elapsed_seconds,
                        process_started=existing.process_started,
                        stage="input_verification",
                    ),
                    content_digest=content_digest,
                )
        upload = self.transport_manager.run_upload(
            local_script,
            remote_script,
            use_rsync=self.config.execution.use_rsync,
            check=False,
            timeout=self.config.execution.staging_timeout_seconds,
            stage="staging",
        )
        if upload.returncode == 0:
            pass
        elif self.transport_manager.enabled:
            self.staging.raise_staging_failure(
                phase="runner_control_transfer",
                run_id=run_id,
                result=upload,
                content_digest=content_digest,
            )
        elif self.config.execution.use_rsync:
            fallback = self.transport_manager.run_upload(
                local_script,
                remote_script,
                use_rsync=False,
                check=False,
                timeout=self.config.execution.staging_timeout_seconds,
                stage="staging",
            )
            if fallback.returncode == 0:
                return None
            upload = fallback
            self.staging.raise_staging_failure(
                phase="runner_control_transfer",
                run_id=run_id,
                result=upload,
                content_digest=content_digest,
            )
        elif upload.returncode != 0:
            self.staging.raise_staging_failure(
                phase="runner_control_transfer",
                run_id=run_id,
                result=upload,
                content_digest=content_digest,
            )
        if not self.transport_manager.enabled:
            return None
        verification = self.staging.remote_verifier.verify(
            remote_script,
            authorized,
            timeout=self.config.execution.staging_timeout_seconds,
        )
        if not verification.verified:
            self.staging.raise_staging_failure(
                phase="runner_control_transfer",
                run_id=run_id,
                result=CommandResult(
                    args=[],
                    returncode=verification.returncode or 66,
                    stdout="",
                    stderr="",
                    timed_out=verification.timed_out,
                    elapsed_seconds=verification.elapsed_seconds,
                    process_started=verification.process_started,
                    stage="input_verification",
                ),
                content_digest=content_digest,
            )
        return verification.receipt_digest

    def _transfer_runner_control_file_with_recovery(
        self,
        spec: RunSpec,
        *,
        run_id: str,
        local_script: Path,
        remote_script: str,
    ) -> str | None:
        verify_before_transfer = False
        while True:
            try:
                return self._transfer_runner_control_file(
                    run_id=run_id,
                    local_script=local_script,
                    remote_script=remote_script,
                    verify_before_transfer=verify_before_transfer,
                )
            except HpcStagingFailure as exc:
                result = self._staging_failure_result(exc)
                if (
                    classify_pre_effect_failure(result)
                    is not PreEffectFailureClass.AUTHENTICATED_TRANSPORT
                ):
                    raise
                recovered = self.attempt_journal.authorize_pre_effect_recovery(
                    run_id,
                    spec,
                    selected_mode="sbatch",
                    reason_code="runner_control_transport_recovered",
                    failure_receipt=safe_transport_failure_receipt(
                        result,
                        phase="runner_control_transfer",
                    ),
                )
                if recovered is None:
                    raise
                verify_before_transfer = True

    def _partition_for(self, spec: RunSpec) -> str | None:
        if spec.resources.partition:
            return spec.resources.partition
        if spec.resources.gpus > 0:
            return (
                self.config.slurm.gpu_partition or self.config.slurm.default_partition
            )
        return self.config.slurm.default_partition

    def build_sbatch_script(self, spec: RunSpec, remote_run_dir: str) -> str:
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        validated_run_dir = safe_remote_run_dir(remote_run_dir)
        partition = self._partition_for(spec)
        if partition:
            if spec.resources.partition:
                partition_field = "resources.partition"
            elif spec.resources.gpus > 0 and self.config.slurm.gpu_partition:
                partition_field = "slurm.gpu_partition"
            else:
                partition_field = "slurm.default_partition"
            partition = ensure_safe_slurm_token(partition, field=partition_field)
        run_dir = str(validated_run_dir)
        work_dir = str(validated_run_dir / "work")
        out_dir = str(validated_run_dir / "out")
        tmp_dir = str(validated_run_dir / "tmp")
        log_dir = str(validated_run_dir / "logs")
        # IMPORTANT: Slurm only honors #SBATCH directives that appear before the
        # first non-comment executable line. Keep all directives at the top.
        lines = [
            "#!/usr/bin/env bash",
            f"#SBATCH --job-name={spec.name}",
            f"#SBATCH --cpus-per-task={spec.resources.cpus}",
            f"#SBATCH --mem={spec.resources.mem_mb}",
            f"#SBATCH --time={spec.resources.time_minutes}",
            f"#SBATCH --output={validated_run_dir / 'logs' / 'slurm-%j.out'}",
            f"#SBATCH --error={validated_run_dir / 'logs' / 'slurm-%j.err'}",
        ]
        if partition:
            lines.append(f"#SBATCH --partition={partition}")
        if spec.resources.gpus > 0:
            if self.config.slurm.gpu_flag_style == "gres":
                lines.append(f"#SBATCH --gres=gpu:{spec.resources.gpus}")
            else:
                lines.append(f"#SBATCH --gpus={spec.resources.gpus}")

        lines.append("set -euo pipefail")

        # Export layout hints for the job payload.
        lines.extend(
            [
                # Convenience (short names): keep to low-collision variables.
                f"export WORKDIR={shlex.quote(work_dir)}",
                f"export OUTDIR={shlex.quote(out_dir)}",
                # Namespaced (preferred).
                f"export MCP_RUN_DIR={shlex.quote(run_dir)}",
                f"export MCP_WORKDIR={shlex.quote(work_dir)}",
                f"export MCP_OUTDIR={shlex.quote(out_dir)}",
                f"export MCP_TMPDIR={shlex.quote(tmp_dir)}",
                f"export MCP_LOGDIR={shlex.quote(log_dir)}",
            ]
        )

        # Normalize to absolute paths for the job, even when remote_run_dir is
        # configured as a home-relative path (e.g. "mcp_runs/<id>"). Use
        # SLURM_SUBMIT_DIR as the anchor because it's set even if the job cannot
        # chdir into the submit directory at startup.
        lines.extend(
            [
                'anchor="${SLURM_SUBMIT_DIR:-$HOME}"',
                'if [[ "$WORKDIR" != /* ]]; then WORKDIR="$anchor/$WORKDIR"; fi',
                'if [[ "$OUTDIR" != /* ]]; then OUTDIR="$anchor/$OUTDIR"; fi',
                'if [[ "$MCP_WORKDIR" != /* ]]; then MCP_WORKDIR="$anchor/$MCP_WORKDIR"; fi',
                'if [[ "$MCP_OUTDIR" != /* ]]; then MCP_OUTDIR="$anchor/$MCP_OUTDIR"; fi',
                'if [[ "$MCP_TMPDIR" != /* ]]; then MCP_TMPDIR="$anchor/$MCP_TMPDIR"; fi',
                'if [[ "$MCP_LOGDIR" != /* ]]; then MCP_LOGDIR="$anchor/$MCP_LOGDIR"; fi',
                'if [[ "$MCP_RUN_DIR" != /* ]]; then MCP_RUN_DIR="$anchor/$MCP_RUN_DIR"; fi',
                "export WORKDIR OUTDIR MCP_RUN_DIR MCP_WORKDIR MCP_OUTDIR MCP_TMPDIR MCP_LOGDIR",
                'mkdir -p "$WORKDIR" "$OUTDIR" "$MCP_TMPDIR" "$MCP_LOGDIR"',
            ]
        )

        # Bind work/out/tmp into any apptainer container launched by wrapper-mode
        # scripts.  This lets wrappers that invoke their own `apptainer exec`
        # (e.g. alphafold3) access inputs and write outputs at /work and /out.
        lines.append(
            'export APPTAINER_BINDPATH="$MCP_WORKDIR:/work,$MCP_OUTDIR:/out,$MCP_TMPDIR:/tmp"'
        )

        # Pre-create subdirectories required by expected outputs (e.g. hhblits/).
        out_subdirs: set[str] = set()
        for output in spec.expected_outputs:
            parent = str(PurePosixPath(output.path).parent)
            if parent and parent != ".":
                out_subdirs.add(parent)
        for subdir in sorted(out_subdirs):
            lines.append(f'mkdir -p "$OUTDIR/{subdir}"')

        command = shlex.join(spec.command)

        # Match ssh backend behavior: run the payload in a login shell so the
        # job sees user profile (/etc/profile, ~/.bash_profile, etc.).
        inner = f"cd $WORKDIR && {command}"
        lines.append(f"bash -lc {shlex.quote(inner)}")
        return "\n".join(lines) + "\n"

    def submit(self, spec: RunSpec) -> RunResult:
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        spec.run_id = spec.run_id or self._make_run_id()
        self.attempt_journal.create(spec, selected_mode="sbatch")
        return self._run_existing_attempt(spec, resuming=False)

    def resume_pre_effect(self, spec: RunSpec) -> RunResult:
        if spec.run_id is None:
            raise ValueError("pre-effect recovery requires an exact run id")
        recovered = self.attempt_journal.authorize_restart_pre_effect_recovery(
            spec.run_id,
            spec,
            selected_mode="sbatch",
        )
        if recovered is None:
            raise RunnerAttemptError(
                "runner_attempt_not_resumable",
                "runner attempt cannot resume before dispatch",
            )
        if recovered.state is RunnerAttemptState.TERMINAL:
            return self._closed_attempt_result(
                spec,
                recovered,
                error_code="PRE_EFFECT_RECOVERY_EXHAUSTED",
            )
        return self._run_existing_attempt(spec, resuming=True)

    def _run_existing_attempt(
        self,
        spec: RunSpec,
        *,
        resuming: bool,
    ) -> RunResult:
        try:
            return self._submit_attempt(spec, resuming=resuming)
        except RunnerAttemptError:
            raise
        except Exception as exc:
            self._record_attempt_exception(spec.run_id, exc)
            if self.transport_manager.enabled:
                attempt = self.attempt_journal.load(spec.run_id)
                if attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED:
                    return self._closed_attempt_result(
                        spec,
                        attempt,
                        error_code="DISPATCH_IN_DOUBT",
                    )
                if attempt.state is RunnerAttemptState.TERMINAL:
                    fallback = (
                        "PRE_EFFECT_RECOVERY_EXHAUSTED"
                        if attempt.safe_failure_code
                        == "pre_effect_recovery_exhausted"
                        else (
                            "PREFLIGHT_FAILED"
                            if isinstance(exc, PreflightError)
                            else "PRE_EFFECT_RUNNER_FAILED"
                        )
                    )
                    return self._closed_attempt_result(
                        spec,
                        attempt,
                        error_code=safe_runner_exception_code(
                            exc,
                            fallback=fallback,
                        ),
                    )
            raise

    def _record_attempt_exception(self, run_id: str, exc: Exception) -> None:
        attempt = self.attempt_journal.load(run_id)
        if attempt.state in {
            RunnerAttemptState.TERMINAL,
            RunnerAttemptState.RECONCILIATION_REQUIRED,
            RunnerAttemptState.QUARANTINED,
        }:
            return
        if attempt.effect_certainty is RunnerEffectCertainty.NO_EFFECT:
            failure_code = attempt.safe_failure_code or (
                safe_runner_exception_code(
                    exc,
                    fallback=(
                        "deterministic_preflight_failed"
                        if isinstance(exc, PreflightError)
                        else "pre_effect_runner_failed"
                    ),
                )
            )
            self.attempt_journal.transition(
                run_id,
                phase=RunnerAttemptPhase.TERMINAL,
                state=RunnerAttemptState.TERMINAL,
                retry_eligibility=RunnerRetryEligibility.TERMINAL,
                safe_failure_code=failure_code,
                reason_code=failure_code,
            )
            return
        if attempt.effect_certainty is RunnerEffectCertainty.DISPATCH_IN_DOUBT:
            self.attempt_journal.transition(
                run_id,
                state=RunnerAttemptState.RECONCILIATION_REQUIRED,
                retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
                reconciliation_required=True,
                safe_failure_code="dispatch_in_doubt",
                reason_code="dispatch_outcome_unknown",
            )
            return
        self.attempt_journal.transition(
            run_id,
            retry_eligibility=RunnerRetryEligibility.VERIFY_THEN_RETRY,
            safe_failure_code="slurm_reconciliation_required",
            reason_code="slurm_reconciliation_required",
        )

    def _advance_attempt_phase(
        self,
        run_id: str,
        phase: RunnerAttemptPhase,
        *,
        reason_code: str,
        **changes: Any,
    ) -> RunnerAttempt:
        current = self.attempt_journal.load(run_id)
        if not runner_phase_precedes(current.phase, phase):
            return current
        return self.attempt_journal.transition(
            run_id,
            phase=phase,
            reason_code=reason_code,
            **changes,
        )

    def _submit_attempt(
        self,
        spec: RunSpec,
        *,
        resuming: bool = False,
    ) -> RunResult:
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        run_id = spec.run_id or self._make_run_id()
        remote_run_dir = self._remote_run_dir(run_id)
        self.store.ensure_run_layout(run_id)
        self.store.write_json(run_id, "runspec.json", spec.to_dict())
        generation = self.transport_manager.ensure_ready()
        attempt = self._advance_attempt_phase(
            run_id,
            RunnerAttemptPhase.TRANSPORT_READY,
            reason_code="transport_ready",
            transport_generation=generation,
        )
        self._ensure_remote_layout_with_recovery(spec, run_id, remote_run_dir)
        attempt = self._advance_attempt_phase(
            run_id,
            RunnerAttemptPhase.REMOTE_LAYOUT_READY,
            reason_code="remote_layout_ready",
            transport_generation=self.transport_manager.current_generation,
        )
        attempt = self._advance_attempt_phase(
            run_id,
            RunnerAttemptPhase.INPUT_STAGING,
            reason_code="input_staging_started",
        )
        upload_entries = self._upload_inputs_with_recovery(
            spec,
            run_id,
            remote_run_dir,
            verify_before_transfer=resuming,
        )
        if self.transport_manager.enabled:
            if any(
                entry.get("verification_status") != "verified"
                for entry in upload_entries
            ):
                raise RuntimeError("persistent transport input verification is incomplete")
            attempt = self._advance_attempt_phase(
                run_id,
                RunnerAttemptPhase.INPUTS_VERIFIED,
                reason_code="inputs_verified",
                receipt_digests={
                    "inputs_manifest": receipt_digest(
                        self.store.read_json(run_id, "inputs_manifest.json")
                    )
                },
            )

        if self.transport_manager.enabled:
            preflight_result = self._run_preflight_with_recovery(
                spec,
                run_id,
                remote_run_dir,
                upload_entries,
            )
        else:
            preflight_result = run_preflight(
                spec,
                remote_run_dir,
                self.config,
                self.transport_manager,
            )
        adapter_id = spec.metadata.get("tool_contract", {}).get("adapter_id", spec.name)
        pf_body = preflight_manifest(run_id, adapter_id, preflight_result)
        if preflight_result.passed:
            attempt = self._advance_attempt_phase(
                run_id,
                RunnerAttemptPhase.PREFLIGHT_PASSED,
                receipt_digests={"preflight_manifest": receipt_digest(pf_body)},
                safe_failure_code=None,
                reason_code="preflight_passed",
            )
        else:
            current = self.attempt_journal.load(run_id)
            attempt = self.attempt_journal.transition(
                run_id,
                phase=current.phase,
                receipt_digests={"preflight_manifest": receipt_digest(pf_body)},
                safe_failure_code=(
                    f"preflight_{preflight_result.failure_class.value}"
                ),
                reason_code="preflight_failed",
            )
        pf_manifest = preflight_manifest(
            run_id,
            adapter_id,
            preflight_result,
            runner_attempt_link={
                "schema_version": "runner_attempt_link@1",
                "attempt_id": attempt.attempt_id,
                "state_version": attempt.state_version,
                "safe_receipt_digest": attempt.safe_receipt_digest,
                "manifest_body_digest": attempt.receipt_digests[
                    "preflight_manifest"
                ],
            },
        )
        self.store.write_preflight_manifest(run_id, pf_manifest)
        if not preflight_result.passed:
            raise PreflightError(pf_manifest)

        script = self.build_sbatch_script(spec, remote_run_dir)
        local_script = self.store.run_root(run_id) / "metadata" / "job.sbatch"
        local_script.parent.mkdir(parents=True, exist_ok=True)
        local_script.write_text(script, encoding="utf-8")

        remote_script = str(PurePosixPath(remote_run_dir) / "logs" / "job.sbatch")
        control_receipt = self._transfer_runner_control_file_with_recovery(
            spec,
            run_id=run_id,
            local_script=local_script,
            remote_script=remote_script,
        )

        self._advance_attempt_phase(
            run_id,
            RunnerAttemptPhase.DISPATCH_PREPARED,
            reason_code="dispatch_prepared",
            receipt_digests=(
                {}
                if control_receipt is None
                else {"slurm_control_script": control_receipt}
            ),
        )
        self.attempt_journal.transition(
            run_id,
            phase=RunnerAttemptPhase.DISPATCHING,
            effect_certainty=RunnerEffectCertainty.DISPATCH_IN_DOUBT,
            retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
            reconciliation_required=True,
            reason_code="payload_transmission_started",
        )
        submit = self.transport_manager.run_ssh(
            ["sbatch", "--parsable", remote_script],
            check=False,
        )
        stderr = redact_text(submit.stderr, self.config.logging.redact_patterns)

        job_id = None
        if submit.returncode == 0:
            token = submit.stdout.strip().split(";")[0]
            job_id = token if token else None

        handle = (
            JobHandle(run_id=run_id, job_id=job_id, remote_run_dir=remote_run_dir)
            if job_id
            else None
        )
        if handle:
            self.store.write_json(run_id, "job_handle.json", handle.to_dict())

        if handle is not None:
            attempt = self.attempt_journal.transition(
                run_id,
                phase=RunnerAttemptPhase.REMOTE_PENDING,
                effect_certainty=RunnerEffectCertainty.EFFECT_KNOWN,
                retry_eligibility=RunnerRetryEligibility.VERIFY_THEN_RETRY,
                reconciliation_required=False,
                receipt_digests={"slurm_handle": receipt_digest(handle.to_dict())},
                reason_code="slurm_handle_persisted",
            )
        else:
            attempt = self.attempt_journal.transition(
                run_id,
                state=RunnerAttemptState.RECONCILIATION_REQUIRED,
                retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
                reconciliation_required=True,
                safe_failure_code="dispatch_in_doubt",
                reason_code="slurm_receipt_missing",
            )

        metadata = {
            "submitted_at": datetime.now(tz=UTC).isoformat(),
            "upload_entries": upload_entries,
            "sbatch_script": str(local_script),
            "submit_stdout": submit.stdout.strip(),
            "runner_attempt_safe_receipt_digest": attempt.safe_receipt_digest,
            "runner_phase": attempt.phase.value,
            "effect_certainty": attempt.effect_certainty.value,
            "retry_eligibility": attempt.retry_eligibility.value,
            "reconciliation_required": attempt.reconciliation_required,
        }
        self.store.write_json(run_id, "submit_metadata.json", metadata)

        mapped = self.failure_mapper.map_error(stderr, spec.failure_signatures)
        return RunResult(
            run_id=run_id,
            requested_mode=spec.execution_mode,
            selected_mode="sbatch",
            remote_run_dir=remote_run_dir,
            status="submitted" if submit.returncode == 0 and job_id else "failed",
            exit_code=submit.returncode,
            job_id=job_id,
            stdout=submit.stdout.strip(),
            stderr=stderr,
            error_code=(mapped.code if mapped else None),
            metadata=metadata,
            logs={
                "submit": prepare_log_payload(
                    submit.stdout + stderr, self.config.logging.inline_log_limit
                )
            },
        )

    def load_handle(self, run_id: str) -> JobHandle:
        return JobHandle.from_dict(self.store.read_json(run_id, "job_handle.json"))

    def _validate_handle(self, handle: JobHandle) -> None:
        self.store.run_root(handle.run_id)
        ensure_safe_slurm_token(handle.job_id, field="job_handle.job_id")
        actual_run_dir = safe_remote_run_dir(
            handle.remote_run_dir,
            field="job_handle.remote_run_dir",
        )
        expected_run_dir = safe_remote_run_dir(
            self._remote_run_dir(handle.run_id),
            field="configured run directory",
        )
        if actual_run_dir != expected_run_dir:
            raise ValueError(
                "job_handle.remote_run_dir must equal the configured run directory "
                f"for run_id {handle.run_id!r}"
            )

    def status(self, handle: JobHandle) -> JobStatus:
        self._validate_handle(handle)
        squeue = self.transport_manager.run_ssh(
            ["squeue", "-h", "-j", handle.job_id, "-o", "%T"],
            check=False,
        )
        raw_state = squeue.stdout.strip()

        mapped_squeue_state = _map_slurm_state(raw_state)
        if (
            squeue.returncode == 0
            and raw_state
            and mapped_squeue_state in {"queued", "running"}
        ):
            status = JobStatus(
                run_id=handle.run_id,
                job_id=handle.job_id,
                state=mapped_squeue_state,
                raw_state=raw_state,
            )
            self._record_status_observation(status)
            return status

        sacct = self.transport_manager.run_ssh(
            [
                "sacct",
                "-j",
                handle.job_id,
                "--format=State,ExitCode",
                "--parsable2",
                "--noheader",
            ],
            check=False,
        )
        raw = sacct.stdout.strip().splitlines()[0] if sacct.stdout.strip() else ""
        state_token = raw.split("|")[0] if raw else ""
        exit_code = None
        if raw and "|" in raw:
            exit_token = raw.split("|")[1]
            try:
                exit_code = int(exit_token.split(":")[0])
            except ValueError:
                exit_code = None

        status = JobStatus(
            run_id=handle.run_id,
            job_id=handle.job_id,
            state=_map_slurm_state(state_token),
            raw_state=state_token,
            exit_code=exit_code,
        )
        self._record_status_observation(status)
        return status

    def _record_status_observation(self, status: JobStatus) -> None:
        if not self.attempt_journal.has_attempt(status.run_id):
            return
        current = self.attempt_journal.load(status.run_id)
        if current.state is RunnerAttemptState.TERMINAL:
            return
        terminal = status.state in {"completed", "failed", "cancelled"}
        observed_phase = (
            RunnerAttemptPhase.REMOTE_TERMINAL
            if terminal
            else RunnerAttemptPhase.REMOTE_PENDING
        )
        next_phase = (
            observed_phase
            if runner_phase_precedes(current.phase, observed_phase)
            else current.phase
        )
        observed_retry = (
            RunnerRetryEligibility.VERIFY_THEN_RETRY
            if status.state == "completed" and status.exit_code == 0
            else (
                RunnerRetryEligibility.TERMINAL
                if terminal
                else RunnerRetryEligibility.VERIFY_THEN_RETRY
            )
        )
        self.attempt_journal.transition(
            status.run_id,
            phase=next_phase,
            state=(
                RunnerAttemptState.ACTIVE
                if current.state is RunnerAttemptState.RECONCILIATION_REQUIRED
                else current.state
            ),
            effect_certainty=(
                RunnerEffectCertainty.TERMINAL_KNOWN
                if terminal
                else RunnerEffectCertainty.EFFECT_KNOWN
            ),
            retry_eligibility=(
                current.retry_eligibility
                if current.retry_eligibility is RunnerRetryEligibility.TERMINAL
                else observed_retry
            ),
            reconciliation_required=False,
            receipt_digests={
                f"slurm_status_v{current.state_version + 1}": (
                    receipt_digest(status.to_dict())
                )
            },
            reason_code=(
                "slurm_terminal_observed" if terminal else "slurm_status_observed"
            ),
        )

    def _output_entries(self, run_id: str) -> list[dict[str, object]]:
        manifest = self.store.read_json(run_id, "outputs_manifest.json")
        if manifest.get("run_id") != run_id:
            raise ValueError("persisted output manifest belongs to another run")
        entries = list(manifest.get("entries") or [])
        if not all(isinstance(item, dict) for item in entries):
            raise ValueError("persisted output manifest entries are invalid")
        return [dict(item) for item in entries]

    def logs(self, handle: JobHandle, tail_lines: int = 200) -> dict[str, object]:
        if tail_lines < 1 or tail_lines > self.config.limits.max_tail_lines:
            raise ValueError(
                f"tail_lines must be between 1 and {self.config.limits.max_tail_lines}"
            )
        self._validate_handle(handle)
        out_path = str(
            PurePosixPath(handle.remote_run_dir) / "logs" / f"slurm-{handle.job_id}.out"
        )
        err_path = str(
            PurePosixPath(handle.remote_run_dir) / "logs" / f"slurm-{handle.job_id}.err"
        )

        out_tail = self.transport_manager.run_ssh(
            ["tail", "-n", str(tail_lines), out_path],
            check=False,
        )
        err_tail = self.transport_manager.run_ssh(
            ["tail", "-n", str(tail_lines), err_path],
            check=False,
        )

        stdout = redact_text(out_tail.stdout, self.config.logging.redact_patterns)
        stderr = redact_text(err_tail.stdout, self.config.logging.redact_patterns)

        self.store.write_log(handle.run_id, "slurm_tail_stdout.log", stdout)
        self.store.write_log(handle.run_id, "slurm_tail_stderr.log", stderr)

        return {
            "run_id": handle.run_id,
            "job_id": handle.job_id,
            "remote_stdout_path": out_path,
            "remote_stderr_path": err_path,
            "stdout": prepare_log_payload(stdout, self.config.logging.inline_log_limit),
            "stderr": prepare_log_payload(stderr, self.config.logging.inline_log_limit),
        }

    def cancel(self, handle: JobHandle) -> RunResult:
        self._validate_handle(handle)
        current = (
            self.attempt_journal.load(handle.run_id)
            if self.attempt_journal.has_attempt(handle.run_id)
            else None
        )
        if current is not None and (
            current.state is RunnerAttemptState.TERMINAL
            or current.effect_certainty is RunnerEffectCertainty.TERMINAL_KNOWN
        ):
            return RunResult(
                run_id=handle.run_id,
                requested_mode="sbatch",
                selected_mode="sbatch",
                remote_run_dir=handle.remote_run_dir,
                status="failed",
                job_id=handle.job_id,
                error_code="RUN_ALREADY_TERMINAL",
                artifacts={},
                metadata=self._attempt_metadata(current),
            )
        cancelled = self.transport_manager.run_ssh(
            ["scancel", handle.job_id],
            check=False,
        )
        stderr = redact_text(cancelled.stderr, self.config.logging.redact_patterns)
        mapped = self.failure_mapper.map_error(stderr)
        if current is not None:
            effect_certainty = current.effect_certainty
            attempt_state = current.state
            retry_eligibility = current.retry_eligibility
            reconciliation_required = current.reconciliation_required
            if effect_certainty is RunnerEffectCertainty.DISPATCH_IN_DOUBT:
                # The persisted exact Slurm handle is acceptance proof.  It is
                # sufficient to leave submission reconciliation without ever
                # submitting a replacement job.
                effect_certainty = RunnerEffectCertainty.EFFECT_KNOWN
                attempt_state = RunnerAttemptState.ACTIVE
                retry_eligibility = RunnerRetryEligibility.VERIFY_THEN_RETRY
                reconciliation_required = False
            current = self.attempt_journal.transition(
                handle.run_id,
                phase=RunnerAttemptPhase.REMOTE_PENDING,
                state=attempt_state,
                effect_certainty=effect_certainty,
                retry_eligibility=retry_eligibility,
                reconciliation_required=reconciliation_required,
                receipt_digests={
                    f"slurm_cancel_request_v{current.state_version + 1}": (
                        receipt_digest(
                            {
                                "returncode": cancelled.returncode,
                                "timed_out": cancelled.timed_out,
                                "process_started": cancelled.process_started,
                            }
                        )
                    )
                },
                reason_code=(
                    "slurm_cancel_requested"
                    if cancelled.returncode == 0
                    else "slurm_cancel_request_failed"
                ),
            )
        return RunResult(
            run_id=handle.run_id,
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=handle.remote_run_dir,
            # A successful scancel command proves only that the cancellation
            # request was accepted.  The job remains nonterminal until an
            # exact-handle status observation proves a Slurm terminal state.
            status="pending",
            exit_code=cancelled.returncode,
            job_id=handle.job_id,
            stdout=cancelled.stdout.strip(),
            stderr=stderr,
            error_code=(
                None
                if cancelled.returncode == 0
                else (mapped.code if mapped else "CANCEL_REQUEST_FAILED")
            ),
            logs={
                "cancel": prepare_log_payload(
                    cancelled.stdout + stderr, self.config.logging.inline_log_limit
                )
            },
            metadata=(
                {} if current is None else self._attempt_metadata(current)
            ),
        )

    def fetch_artifacts(self, spec: RunSpec, handle: JobHandle) -> RunResult:
        self._validate_handle(handle)
        job_status = self.status(handle)
        if job_status.state != "completed" or job_status.exit_code != 0:
            active = job_status.state in {"queued", "running", "unknown"}
            observed_attempt = None
            if not active and self.attempt_journal.has_attempt(handle.run_id):
                observed_attempt = self.attempt_journal.transition(
                    handle.run_id,
                    phase=RunnerAttemptPhase.TERMINAL,
                    state=RunnerAttemptState.TERMINAL,
                    effect_certainty=RunnerEffectCertainty.TERMINAL_KNOWN,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    reconciliation_required=False,
                    safe_failure_code="slurm_terminal_failed",
                    reason_code="slurm_terminal_failed",
                )
            elif self.attempt_journal.has_attempt(handle.run_id):
                observed_attempt = self.attempt_journal.load(handle.run_id)
            return RunResult(
                run_id=handle.run_id,
                requested_mode="sbatch",
                selected_mode="sbatch",
                remote_run_dir=handle.remote_run_dir,
                status=(
                    job_status.state
                    if job_status.state in {"queued", "running"}
                    else ("pending" if active else "failed")
                ),
                exit_code=job_status.exit_code,
                job_id=handle.job_id,
                error_code=(
                    "JOB_NOT_TERMINAL" if active else "JOB_TERMINAL_FAILED"
                ),
                artifacts={},
                metadata={
                    "job_status": job_status.to_dict(),
                    **(
                        {}
                        if observed_attempt is None
                        else self._attempt_metadata(observed_attempt)
                    ),
                },
            )
        current_attempt = (
            self.attempt_journal.load_bound(
                handle.run_id,
                spec,
                selected_mode="sbatch",
            )
            if self.attempt_journal.has_attempt(handle.run_id)
            else None
        )
        if (
            current_attempt is not None
            and current_attempt.state is RunnerAttemptState.TERMINAL
            and current_attempt.safe_failure_code is not None
        ):
            return self._closed_attempt_result(
                spec,
                current_attempt,
                error_code=(
                    "OUTPUT_FETCH_INTERRUPTED"
                    if current_attempt.safe_failure_code
                    == "output_fetch_recovery_exhausted"
                    else "JOB_TERMINAL_FAILED"
                ),
            )
        if (
            current_attempt is not None
            and current_attempt.state is RunnerAttemptState.ACTIVE
            and current_attempt.phase is RunnerAttemptPhase.OUTPUTS_FETCHING
        ):
            current_attempt = (
                self.attempt_journal.authorize_restart_output_fetch_recovery(
                    handle.run_id,
                    spec,
                    selected_mode="sbatch",
                )
            )
            if current_attempt is None:
                raise RunnerAttemptError(
                    "runner_output_fetch_not_resumable",
                    "Slurm output fetch cannot resume safely",
                )
            if current_attempt.state is RunnerAttemptState.TERMINAL:
                return self._closed_attempt_result(
                    spec,
                    current_attempt,
                    error_code="OUTPUT_FETCH_INTERRUPTED",
                )

        reuse_verified_outputs = (
            current_attempt is not None
            and (
                current_attempt.state is RunnerAttemptState.TERMINAL
                or current_attempt.phase is RunnerAttemptPhase.OUTPUTS_VERIFIED
            )
        )
        if reuse_verified_outputs:
            entries = self._output_entries(handle.run_id)
            output_failure_attempt = None
            output_failure_code = None
        else:
            if current_attempt is not None and (
                current_attempt.phase is not RunnerAttemptPhase.OUTPUTS_FETCHING
            ):
                current_attempt = self.attempt_journal.transition(
                    handle.run_id,
                    phase=RunnerAttemptPhase.OUTPUTS_FETCHING,
                    retry_eligibility=RunnerRetryEligibility.VERIFY_THEN_RETRY,
                    reason_code="outputs_fetching",
                )
            entries, output_failure_attempt, output_failure_code = (
                self._fetch_outputs_with_recovery(
                    spec,
                    handle.run_id,
                    handle.remote_run_dir,
                )
            )
        if output_failure_attempt is not None:
            assert output_failure_code is not None
            return RunResult(
                run_id=handle.run_id,
                requested_mode="sbatch",
                selected_mode="sbatch",
                remote_run_dir=handle.remote_run_dir,
                status="failed",
                job_id=handle.job_id,
                error_code=output_failure_code,
                artifacts={},
                metadata={
                    "job_status": job_status.to_dict(),
                    **self._attempt_metadata(output_failure_attempt),
                },
            )

        outputs_root = self.store.run_root(handle.run_id) / "outputs"
        missing_outputs, empty_outputs = validate_expected_outputs(
            outputs_root, spec.expected_outputs
        )
        success_check_failures = run_success_checks(outputs_root, spec)
        status = "completed"
        error_code = None
        if missing_outputs or empty_outputs or success_check_failures:
            status = "failed"
            error_code = "OUTPUT_VALIDATION_FAILED"

        artifacts = {
            entry["remote_path"]: entry["local_path"]
            for entry in entries
            if entry.get("returncode", 1) == 0
        }
        if status != "completed":
            artifacts = {}

        if current_attempt is not None:
            if current_attempt.state is RunnerAttemptState.ACTIVE and (
                current_attempt.phase is not RunnerAttemptPhase.OUTPUTS_VERIFIED
            ):
                current_attempt = self.attempt_journal.transition(
                    handle.run_id,
                    phase=RunnerAttemptPhase.OUTPUTS_VERIFIED,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    receipt_digests={
                        "outputs_manifest": receipt_digest(
                            self.store.read_json(
                                handle.run_id,
                                "outputs_manifest.json",
                            )
                        )
                    },
                    reason_code="outputs_verified",
                )
            outputs_receipt = current_attempt.receipt_digests.get(
                "outputs_manifest"
            )
            if outputs_receipt is None:
                raise RunnerAttemptError(
                    "runner_outputs_receipt_missing",
                    "verified Slurm outputs have no immutable receipt",
                )
            terminal_receipt = {
                "status": status,
                "error_code": error_code,
                "artifacts": sorted(artifacts),
                "outputs_receipt": outputs_receipt,
            }
            if current_attempt.state is RunnerAttemptState.ACTIVE:
                terminal_attempt = self.attempt_journal.transition(
                    handle.run_id,
                    phase=RunnerAttemptPhase.TERMINAL,
                    state=RunnerAttemptState.TERMINAL,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    reconciliation_required=False,
                    safe_failure_code=(
                        None
                        if status == "completed"
                        else "output_validation_failed"
                    ),
                    receipt_digests={
                        "run_result": receipt_digest(terminal_receipt)
                    },
                    reason_code=(
                        "run_succeeded"
                        if status == "completed"
                        else "run_failed"
                    ),
                )
            elif current_attempt.receipt_digests.get("run_result") != receipt_digest(
                terminal_receipt
            ):
                raise RunnerAttemptError(
                    "runner_terminal_result_unrecoverable",
                    "Slurm terminal result evidence is incomplete",
                )
            else:
                terminal_attempt = current_attempt
        else:
            terminal_attempt = None

        metadata = {
            "job_status": job_status.to_dict(),
            "status": status,
            "exit_code": job_status.exit_code,
            "error_code": error_code,
            "validation": {
                "missing_outputs": missing_outputs,
                "empty_outputs": empty_outputs,
                "success_check_failures": success_check_failures,
            },
            **(
                {}
                if terminal_attempt is None
                else {
                    "runner_attempt_safe_receipt_digest": (
                        terminal_attempt.safe_receipt_digest
                    ),
                    "runner_phase": terminal_attempt.phase.value,
                    "effect_certainty": terminal_attempt.effect_certainty.value,
                    "retry_eligibility": terminal_attempt.retry_eligibility.value,
                    "reconciliation_required": (
                        terminal_attempt.reconciliation_required
                    ),
                }
            ),
        }
        self.store.write_json(handle.run_id, "run_result_metadata.json", metadata)

        return RunResult(
            run_id=handle.run_id,
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=handle.remote_run_dir,
            status=status,
            job_id=handle.job_id,
            error_code=error_code,
            artifacts=artifacts,
            metadata=metadata,
        )
