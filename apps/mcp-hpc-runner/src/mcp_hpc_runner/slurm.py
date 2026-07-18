from __future__ import annotations

from datetime import UTC, datetime
import hashlib
from pathlib import Path, PurePosixPath
import shlex
import uuid

from .config import RunnerConfig
from .errors import FailureMapper
from .logging_utils import prepare_log_payload, redact_text
from .models import JobHandle, JobStatus, RunResult, RunSpec
from .preflight import PreflightError, preflight_manifest, run_preflight
from .remote import CommandRunner, wrap_ssh
from .staging import StagingManager
from .store import ArtifactStore
from .validation import (
    ensure_safe_slurm_token,
    ensure_valid_runspec,
    run_success_checks,
    safe_remote_run_dir,
    validate_expected_outputs,
)


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
    ) -> None:
        self.config = config
        self.store = store
        self.staging = staging
        self.command_runner = command_runner
        self.failure_mapper = failure_mapper

    def _make_run_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def _remote_run_dir(self, run_id: str) -> str:
        return str(PurePosixPath(self.config.cluster.remote_base_dir) / run_id)

    def _ensure_remote_layout(self, run_id: str, remote_run_dir: str) -> None:
        cmd = wrap_ssh(
            self.config.cluster.ssh_target,
            [
                "mkdir",
                "-p",
                str(PurePosixPath(remote_run_dir) / "work"),
                str(PurePosixPath(remote_run_dir) / "out"),
                str(PurePosixPath(remote_run_dir) / "tmp"),
                str(PurePosixPath(remote_run_dir) / "logs"),
            ],
        )
        result = self.command_runner.run(
            cmd,
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

    def _transfer_runner_control_file(
        self,
        *,
        run_id: str,
        local_script: Path,
        remote_script: str,
    ) -> None:
        content_digest = f"sha256:{hashlib.sha256(local_script.read_bytes()).hexdigest()}"
        upload_cmd = self.staging.build_upload_command(
            local_script,
            remote_script,
            use_rsync=self.config.execution.use_rsync,
        )
        upload = self.command_runner.run(
            upload_cmd,
            check=False,
            timeout=self.config.execution.staging_timeout_seconds,
            stage="staging",
        )
        if upload.returncode == 0:
            return
        if self.config.execution.use_rsync:
            fallback_cmd = self.staging.build_upload_command(
                local_script,
                remote_script,
                use_rsync=False,
            )
            fallback = self.command_runner.run(
                fallback_cmd,
                check=False,
                timeout=self.config.execution.staging_timeout_seconds,
                stage="staging",
            )
            if fallback.returncode == 0:
                return
            upload = fallback
        self.staging.raise_staging_failure(
            phase="runner_control_transfer",
            run_id=run_id,
            result=upload,
            content_digest=content_digest,
        )

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
        run_id = spec.run_id or self._make_run_id()
        remote_run_dir = self._remote_run_dir(run_id)
        self.store.ensure_run_layout(run_id)
        self.store.write_json(run_id, "runspec.json", spec.to_dict())
        self._ensure_remote_layout(run_id, remote_run_dir)
        upload_entries = self.staging.upload_inputs(run_id, spec.inputs, remote_run_dir)

        preflight_result = run_preflight(
            spec, remote_run_dir, self.config, self.command_runner
        )
        adapter_id = spec.metadata.get("tool_contract", {}).get("adapter_id", spec.name)
        pf_manifest = preflight_manifest(run_id, adapter_id, preflight_result)
        self.store.write_preflight_manifest(run_id, pf_manifest)
        if not preflight_result.passed:
            raise PreflightError(pf_manifest)

        script = self.build_sbatch_script(spec, remote_run_dir)
        local_script = self.store.run_root(run_id) / "metadata" / "job.sbatch"
        local_script.parent.mkdir(parents=True, exist_ok=True)
        local_script.write_text(script, encoding="utf-8")

        remote_script = str(PurePosixPath(remote_run_dir) / "logs" / "job.sbatch")
        self._transfer_runner_control_file(
            run_id=run_id,
            local_script=local_script,
            remote_script=remote_script,
        )

        submit_cmd = wrap_ssh(
            self.config.cluster.ssh_target,
            ["sbatch", "--parsable", remote_script],
        )
        submit = self.command_runner.run(submit_cmd, check=False)
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

        metadata = {
            "submitted_at": datetime.now(tz=UTC).isoformat(),
            "upload_entries": upload_entries,
            "sbatch_script": str(local_script),
            "submit_stdout": submit.stdout.strip(),
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
        squeue_cmd = wrap_ssh(
            self.config.cluster.ssh_target,
            ["squeue", "-h", "-j", handle.job_id, "-o", "%T"],
        )
        squeue = self.command_runner.run(squeue_cmd, check=False)
        raw_state = squeue.stdout.strip()

        mapped_squeue_state = _map_slurm_state(raw_state)
        if (
            squeue.returncode == 0
            and raw_state
            and mapped_squeue_state in {"queued", "running"}
        ):
            return JobStatus(
                run_id=handle.run_id,
                job_id=handle.job_id,
                state=mapped_squeue_state,
                raw_state=raw_state,
            )

        sacct_cmd = wrap_ssh(
            self.config.cluster.ssh_target,
            [
                "sacct",
                "-j",
                handle.job_id,
                "--format=State,ExitCode",
                "--parsable2",
                "--noheader",
            ],
        )
        sacct = self.command_runner.run(sacct_cmd, check=False)
        raw = sacct.stdout.strip().splitlines()[0] if sacct.stdout.strip() else ""
        state_token = raw.split("|")[0] if raw else ""
        exit_code = None
        if raw and "|" in raw:
            exit_token = raw.split("|")[1]
            try:
                exit_code = int(exit_token.split(":")[0])
            except ValueError:
                exit_code = None

        return JobStatus(
            run_id=handle.run_id,
            job_id=handle.job_id,
            state=_map_slurm_state(state_token),
            raw_state=state_token,
            exit_code=exit_code,
        )

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

        out_tail_cmd = wrap_ssh(
            self.config.cluster.ssh_target,
            ["tail", "-n", str(tail_lines), out_path],
        )
        err_tail_cmd = wrap_ssh(
            self.config.cluster.ssh_target,
            ["tail", "-n", str(tail_lines), err_path],
        )
        out_tail = self.command_runner.run(out_tail_cmd, check=False)
        err_tail = self.command_runner.run(err_tail_cmd, check=False)

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
        cancel_cmd = wrap_ssh(
            self.config.cluster.ssh_target, ["scancel", handle.job_id]
        )
        cancelled = self.command_runner.run(cancel_cmd, check=False)
        stderr = redact_text(cancelled.stderr, self.config.logging.redact_patterns)
        mapped = self.failure_mapper.map_error(stderr)
        return RunResult(
            run_id=handle.run_id,
            requested_mode="sbatch",
            selected_mode="sbatch",
            remote_run_dir=handle.remote_run_dir,
            status="cancelled" if cancelled.returncode == 0 else "failed",
            exit_code=cancelled.returncode,
            job_id=handle.job_id,
            stdout=cancelled.stdout.strip(),
            stderr=stderr,
            error_code=(mapped.code if mapped else None),
            logs={
                "cancel": prepare_log_payload(
                    cancelled.stdout + stderr, self.config.logging.inline_log_limit
                )
            },
        )

    def fetch_artifacts(self, spec: RunSpec, handle: JobHandle) -> RunResult:
        self._validate_handle(handle)
        job_status = self.status(handle)
        if job_status.state != "completed" or job_status.exit_code != 0:
            active = job_status.state in {"queued", "running", "unknown"}
            return RunResult(
                run_id=handle.run_id,
                requested_mode="sbatch",
                selected_mode="sbatch",
                remote_run_dir=handle.remote_run_dir,
                status=job_status.state if active else "failed",
                exit_code=job_status.exit_code,
                job_id=handle.job_id,
                error_code=(
                    "JOB_NOT_TERMINAL" if active else "JOB_TERMINAL_FAILED"
                ),
                artifacts={},
                metadata={"job_status": job_status.to_dict()},
            )
        entries = self.staging.download_outputs(
            handle.run_id,
            spec.expected_outputs,
            handle.remote_run_dir,
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

        metadata = {
            "job_status": job_status.to_dict(),
            "validation": {
                "missing_outputs": missing_outputs,
                "empty_outputs": empty_outputs,
                "success_check_failures": success_check_failures,
            }
        }

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
