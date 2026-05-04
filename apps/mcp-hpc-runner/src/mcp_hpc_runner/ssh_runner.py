from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
import uuid

from .config import RunnerConfig
from .errors import FailureMapper
from .logging_utils import prepare_log_payload, redact_text
from .models import RunResult, RunSpec
from .preflight import PreflightError, preflight_manifest, run_preflight
from .remote import CommandRunner, make_remote_shell_command_with_env, wrap_ssh
from .staging import StagingManager
from .store import ArtifactStore
from .validation import (
    ensure_valid_runspec,
    run_success_checks,
    validate_expected_outputs,
)


class SSHRunner:
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

    def _ensure_remote_layout(self, remote_run_dir: str) -> None:
        mkdir_cmd = wrap_ssh(
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
        self.command_runner.run(
            mkdir_cmd,
            check=True,
            timeout=self.config.execution.staging_timeout_seconds,
            stage="staging",
        )

    def exec_run(self, spec: RunSpec) -> RunResult:
        ensure_valid_runspec(spec)
        started_at = datetime.now(tz=UTC).isoformat()
        run_id = spec.run_id or self._make_run_id()
        remote_run_dir = self._remote_run_dir(run_id)
        self.store.ensure_run_layout(run_id)
        self.store.write_json(run_id, "runspec.json", spec.to_dict())

        if self.config.execution.create_remote_dir_for_ssh:
            self._ensure_remote_layout(remote_run_dir)

        upload_entries = self.staging.upload_inputs(run_id, spec.inputs, remote_run_dir)

        preflight_result = run_preflight(
            spec, remote_run_dir, self.config, self.command_runner
        )
        adapter_id = spec.metadata.get("tool_contract", {}).get("adapter_id", spec.name)
        pf_manifest = preflight_manifest(run_id, adapter_id, preflight_result)
        self.store.write_preflight_manifest(run_id, pf_manifest)
        if not preflight_result.passed:
            raise PreflightError(pf_manifest)

        remote_work_dir = str(PurePosixPath(remote_run_dir) / "work")

        env = {
            # Convenience (short names): keep to low-collision variables.
            "WORKDIR": str(PurePosixPath(remote_run_dir) / "work"),
            "OUTDIR": str(PurePosixPath(remote_run_dir) / "out"),
            # Namespaced (preferred).
            "MCP_RUN_DIR": str(remote_run_dir),
            "MCP_WORKDIR": str(PurePosixPath(remote_run_dir) / "work"),
            "MCP_OUTDIR": str(PurePosixPath(remote_run_dir) / "out"),
            "MCP_TMPDIR": str(PurePosixPath(remote_run_dir) / "tmp"),
            "MCP_LOGDIR": str(PurePosixPath(remote_run_dir) / "logs"),
        }

        remote_argv = make_remote_shell_command_with_env(
            remote_work_dir, spec.command, env
        )
        ssh_cmd = wrap_ssh(self.config.cluster.ssh_target, remote_argv)
        raw = self.command_runner.run(
            ssh_cmd,
            check=False,
            timeout=self.config.execution.remote_execution_timeout_seconds,
            stage="remote_execution",
        )

        stdout = redact_text(raw.stdout, self.config.logging.redact_patterns)
        stderr = redact_text(raw.stderr, self.config.logging.redact_patterns)
        self.store.write_log(run_id, "stdout.log", stdout)
        self.store.write_log(run_id, "stderr.log", stderr)

        artifact_entries = []
        if spec.expected_outputs:
            artifact_entries = self.staging.download_outputs(
                run_id, spec.expected_outputs, remote_run_dir
            )

        outputs_root = self.store.run_root(run_id) / "outputs"
        missing_outputs, empty_outputs = validate_expected_outputs(
            outputs_root, spec.expected_outputs
        )
        success_check_failures = run_success_checks(outputs_root, spec)

        mapped_error = self.failure_mapper.map_error(stderr, spec.failure_signatures)
        error_code = mapped_error.code if mapped_error else None

        status = "completed"
        if (
            raw.returncode != 0
            or missing_outputs
            or empty_outputs
            or success_check_failures
        ):
            status = "failed"
            if error_code is None:
                error_code = (
                    "COMMAND_TIMEOUT"
                    if raw.returncode == 124
                    else
                    "OUTPUT_VALIDATION_FAILED"
                    if missing_outputs or empty_outputs
                    else "RUN_FAILED"
                )

        metadata = {
            "started_at": started_at,
            "finished_at": datetime.now(tz=UTC).isoformat(),
                "remote_command": remote_argv,
                "stage": raw.stage,
                "upload_entries": upload_entries,
            "validation": {
                "missing_outputs": missing_outputs,
                "empty_outputs": empty_outputs,
                "success_check_failures": success_check_failures,
            },
        }

        self.store.write_json(run_id, "run_result_metadata.json", metadata)

        artifacts = {
            entry["remote_path"]: entry["local_path"]
            for entry in artifact_entries
            if entry.get("returncode", 1) == 0
        }

        return RunResult(
            run_id=run_id,
            requested_mode=spec.execution_mode,
            selected_mode="ssh",
            remote_run_dir=remote_run_dir,
            status=status,
            exit_code=raw.returncode,
            stdout=stdout,
            stderr=stderr,
            error_code=error_code,
            artifacts=artifacts,
            logs={
                "stdout": prepare_log_payload(
                    stdout, self.config.logging.inline_log_limit
                ),
                "stderr": prepare_log_payload(
                    stderr, self.config.logging.inline_log_limit
                ),
            },
            metadata=metadata,
        )
