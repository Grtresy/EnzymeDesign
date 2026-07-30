from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
import re
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
from .contract_manifest import render_cdhit_membership_normalizer_command
from .errors import FailureMapper
from .errors import HpcOutputFailure
from .errors import HpcStagingFailure
from .logging_utils import prepare_log_payload, redact_text
from .models import RunResult, RunSpec
from .preflight import PreflightError, preflight_manifest, run_preflight
from .preflight import PreflightFailureClass
from .preflight import PreflightResult
from .recovery import classify_pre_effect_failure
from .recovery import classify_direct_dispatch
from .recovery import DirectDispatchObservation
from .recovery import PreEffectFailureClass
from .recovery import safe_transport_failure_receipt
from .remote import CommandResult, CommandRunner, make_remote_shell_command_with_env
from .staging import StagingManager
from .store import ArtifactStore
from .transport import SshCommandCompiler
from .transport import SshTransportManager
from .validation import (
    ensure_valid_runspec,
    run_success_checks,
    validate_expected_outputs,
)


_TOOLCHAIN_IDENTITY_MARKER = "__OPENZYME_TOOLCHAIN_SHA256__"
_REMOTE_TERMINAL_OBSERVATION_SCHEMA_VERSION = "ssh_remote_terminal_observation@1"
_SIF_LOCATOR_PATTERN = re.compile(r"^~/[A-Za-z0-9._/-]+\.sif$")
_SHA256_HEX_PATTERN = re.compile(r"^[0-9a-f]{64}$")
_APPTAINER_EXEC_PATTERN = re.compile(r"(?<![A-Za-z0-9_])apptainer[ \t]+exec(?=[ \t])")
_AOX_TEMPLATE_ENTRYPOINTS = {
    "bio_tools_cdhit_sif_v2": "cd-hit",
    "bio_tools_mafft_sif_v1": "mafft",
    "bio_tools_hmmbuild_sif_v1": "hmmbuild",
    "bio_tools_hmmalign_sif_v1": "hmmalign",
}
_AOX_TEMPLATE_PREFIXES = {
    "bio_tools_cdhit_sif_v2": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/cdhit"; '
    ),
    "bio_tools_mafft_sif_v1": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/mafft"; '
    ),
    "bio_tools_hmmbuild_sif_v1": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/hmmbuild"; '
    ),
    "bio_tools_hmmalign_sif_v1": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/hmmalign"; '
    ),
}
_AOX_APPTAINER_OPTION_ARGUMENTS = [
    "--cleanenv",
    "--bind",
    "$MCP_WORKDIR:/work",
    "--bind",
    "$MCP_OUTDIR:/out",
    "--bind",
    "$MCP_TMPDIR:/tmp",
]
_AOX_FIXED_CANONICAL_PAYLOADS = {
    "bio_tools_mafft_sif_v1": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/mafft"; '
        'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
        '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
        '"$HOME/containers/mafft_7.525.sif" mafft --auto /work/input.fasta '
        '> "$MCP_OUTDIR/bio_tools/mafft/alignment.fasta"'
    ),
    "bio_tools_hmmbuild_sif_v1": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/hmmbuild"; '
        'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
        '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
        '"$HOME/containers/hmmer_3.4.sif" hmmbuild --amino '
        "/out/bio_tools/hmmbuild/model.hmm /work/alignment.fasta "
        '> "$MCP_OUTDIR/bio_tools/hmmbuild/hmmbuild.summary.txt"'
    ),
    "bio_tools_hmmalign_sif_v1": (
        'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/hmmalign"; '
        'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
        '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
        '"$HOME/containers/hmmer_3.4.sif" hmmalign --amino --outformat afa '
        "-o /out/bio_tools/hmmalign/aligned.fasta /work/model.hmm /work/input.fasta"
    ),
}
_CDHIT_CANONICAL_PREFIX = (
    'set -euo pipefail; mkdir -p "$MCP_OUTDIR/bio_tools/cdhit"; '
    'apptainer exec --cleanenv --bind "$MCP_WORKDIR:/work" '
    '--bind "$MCP_OUTDIR:/out" --bind "$MCP_TMPDIR:/tmp" '
    '"$HOME/containers/cd-hit_4.8.1.sif" cd-hit '
    "-i /work/input.fasta -o /out/bio_tools/cdhit/clustered.fasta -c "
)
_CDHIT_CANONICAL_SUFFIX = (
    ' -d 0 -T 1 -M 256 > "$MCP_OUTDIR/bio_tools/cdhit/cdhit.log"; '
    + render_cdhit_membership_normalizer_command()
)
_CDHIT_CANONICAL_PATTERN = re.compile(
    r"\A"
    + re.escape(_CDHIT_CANONICAL_PREFIX)
    + r"(?P<identity>0\.[0-9]*[1-9][0-9]*|1(?:\.0+)?)"
    + re.escape(" -n ")
    + r"(?P<word_size>[1-9][0-9]*)"
    + re.escape(_CDHIT_CANONICAL_SUFFIX)
    + r"\Z"
)


def _require_canonical_aox_payload(payload: str, *, command_template_id: str) -> None:
    if command_template_id == "bio_tools_cdhit_sif_v2":
        matches = _CDHIT_CANONICAL_PATTERN.fullmatch(payload) is not None
    else:
        matches = payload == _AOX_FIXED_CANONICAL_PAYLOADS.get(command_template_id)
    if not matches:
        raise ValueError(
            "runner-attested SIF payload does not match its complete runner-owned canonical template"
        )


def _toolchain_runtime_request(spec: RunSpec) -> dict[str, object] | None:
    request = dict(spec.metadata.get("toolchain_runtime_request") or {})
    if not request:
        return None
    locator = str(request.get("sif_locator") or "")
    if (
        request.get("schema_id") != "mcp_hpc_toolchain_runtime_request@1"
        or request.get("entrypoint_kind") != "sif"
        or _SIF_LOCATOR_PATTERN.fullmatch(locator) is None
        or not str(request.get("tool_id") or "")
        or not str(request.get("adapter_id") or "")
        or not str(request.get("command_template_id") or "")
        or not re.fullmatch(
            r"sha256:[0-9a-f]{64}",
            str(request.get("runner_contract_digest") or ""),
        )
    ):
        raise ValueError("runner-owned toolchain runtime request is invalid")
    return request


def _command_with_toolchain_attestation(
    spec: RunSpec,
    request: dict[str, object] | None,
    *,
    apptainer_executable: str = "/usr/bin/apptainer",
) -> list[str]:
    if request is None:
        return list(spec.command)
    if len(spec.command) != 3 or spec.command[:2] != ["bash", "-lc"]:
        raise ValueError(
            "runner-attested SIF commands must use the canonical bash -lc template"
        )
    locator = str(request["sif_locator"])
    home_relative = locator.removeprefix("~/")
    image_token = f'"$HOME/{home_relative}"'
    if re.search(r"(?:^|[;&|\s])(?:export[ \t]+)?HOME[ \t]*=", spec.command[2]):
        raise ValueError("runner-attested SIF command must not rebind HOME")
    if spec.command[2].count(image_token) != 1:
        raise ValueError(
            "runner-attested SIF command must reference its runner-owned image exactly once"
        )
    if spec.command[2].count(".sif") != 1:
        raise ValueError(
            "runner-attested SIF command must not reference another SIF image"
        )
    payload = spec.command[2]
    if _TOOLCHAIN_IDENTITY_MARKER in payload:
        raise ValueError(
            "runner-attested SIF command must not contain the private identity marker"
        )
    apptainer_matches = list(_APPTAINER_EXEC_PATTERN.finditer(payload))
    if len(apptainer_matches) != 1:
        raise ValueError(
            "runner-attested SIF command must contain exactly one direct apptainer exec"
        )
    apptainer_match = apptainer_matches[0]
    image_start = payload.index(image_token)
    if image_start <= apptainer_match.end():
        raise ValueError(
            "runner-owned image must be an argument of the direct apptainer exec"
        )
    apptainer_arguments = payload[apptainer_match.end() : image_start]
    if (
        not apptainer_arguments
        or not apptainer_arguments[-1].isspace()
        or any(marker in apptainer_arguments for marker in (";", "&", "|", "#", "`", "$(", "\n", "\r"))
    ):
        raise ValueError(
            "runner-owned image must be an argument of one uninterrupted apptainer exec"
        )
    image_end = image_start + len(image_token)
    if image_end < len(payload) and not payload[image_end].isspace():
        raise ValueError(
            "runner-owned image must be a standalone apptainer exec argument"
        )
    try:
        invocation_prefix = shlex.split(
            payload[apptainer_match.end() : image_end],
            posix=True,
        )
    except ValueError as exc:
        raise ValueError(
            "runner-attested apptainer exec arguments are not valid shell words"
        ) from exc
    expected_image_argument = f"$HOME/{home_relative}"
    if not invocation_prefix or invocation_prefix[-1] != expected_image_argument:
        raise ValueError(
            "runner-owned image must be the direct apptainer exec image argument"
        )
    option_arguments = invocation_prefix[:-1]
    if option_arguments != _AOX_APPTAINER_OPTION_ARGUMENTS:
        raise ValueError(
            "runner-attested apptainer exec options do not match its runner-owned template"
        )
    prefix = payload[: apptainer_match.start()]
    last_separator = prefix.rfind(";")
    direct_prefix = prefix[last_separator + 1 :]
    if direct_prefix.strip():
        raise ValueError(
            "runner-attested apptainer exec must begin a direct shell command segment"
        )
    expected_entrypoint = _AOX_TEMPLATE_ENTRYPOINTS.get(
        str(request["command_template_id"])
    )
    entrypoint_tail = payload[image_end:].lstrip()
    if (
        expected_entrypoint is None
        or not entrypoint_tail.startswith(expected_entrypoint)
        or (
            len(entrypoint_tail) > len(expected_entrypoint)
            and not entrypoint_tail[len(expected_entrypoint)].isspace()
        )
    ):
        raise ValueError(
            "runner-attested SIF command entrypoint does not match its runner-owned template"
        )
    expected_prefix = _AOX_TEMPLATE_PREFIXES.get(
        str(request["command_template_id"])
    )
    if prefix != expected_prefix:
        raise ValueError(
            "runner-attested SIF command prefix does not match its runner-owned template"
        )
    _require_canonical_aox_payload(
        payload,
        command_template_id=str(request["command_template_id"]),
    )
    transformed_payload = (
        payload[: apptainer_match.start()]
        + f"command {shlex.quote(apptainer_executable)} exec"
        + apptainer_arguments
        + '"$_oz_sif"'
        + payload[image_end:]
    )
    script = (
        "set -uo pipefail; "
        + 'for _oz_runtime_name in "${!APPTAINER_@}" "${!SINGULARITY_@}"; do '
        + 'if [ -n "$_oz_runtime_name" ] && [ "${!_oz_runtime_name+x}" = x ]; then '
        + 'builtin unset -v -- "$_oz_runtime_name" || exit 87; fi; done; '
        + 'for _oz_runtime_name in "${!APPTAINER_@}" "${!SINGULARITY_@}"; do '
        + 'if [ -n "$_oz_runtime_name" ] && [ "${!_oz_runtime_name+x}" = x ]; then '
        + "exit 87; fi; done; "
        + f'readonly _oz_sif="$HOME/{home_relative}"; '
        + '_oz_digest_before="$(/usr/bin/sha256sum -- "$_oz_sif")"; '
        + 'readonly _oz_digest_before; '
        + '_oz_digest_before_hex="${_oz_digest_before%% *}"; '
        + 'readonly _oz_digest_before_hex; '
        + "if ("
        + transformed_payload
        + "); then _oz_payload_status=0; else _oz_payload_status=$?; fi; "
        + "readonly _oz_payload_status"
        + '; _oz_digest_after="$(/usr/bin/sha256sum -- "$_oz_sif")"; '
        + 'readonly _oz_digest_after; '
        + '_oz_digest_after_hex="${_oz_digest_after%% *}"; '
        + 'readonly _oz_digest_after_hex; '
        + 'if [ "$_oz_digest_before_hex" != "$_oz_digest_after_hex" ]; then '
        + 'exit 86; fi; '
        + 'if [ "$_oz_payload_status" -ne 0 ]; then exit "$_oz_payload_status"; fi; '
        + f"printf '{_TOOLCHAIN_IDENTITY_MARKER}%s\\n' \"$_oz_digest_after_hex\""
    )
    return ["bash", "-lc", script]


def _extract_toolchain_runtime_identity(
    stdout: str,
    request: dict[str, object] | None,
) -> tuple[str, dict[str, object] | None, bool]:
    if request is None:
        return stdout, None, False
    marker_lines = [
        line
        for line in stdout.splitlines()
        if line.startswith(_TOOLCHAIN_IDENTITY_MARKER)
    ]
    clean_stdout = "\n".join(
        line
        for line in stdout.splitlines()
        if not line.startswith(_TOOLCHAIN_IDENTITY_MARKER)
    )
    if stdout.endswith("\n") and clean_stdout:
        clean_stdout += "\n"
    if len(marker_lines) != 1:
        return clean_stdout, None, True
    digest_hex = marker_lines[0].removeprefix(_TOOLCHAIN_IDENTITY_MARKER)
    if _SHA256_HEX_PATTERN.fullmatch(digest_hex) is None:
        return clean_stdout, None, True
    return (
        clean_stdout,
        {
            "schema_id": "mcp_hpc_toolchain_runtime_identity@1",
            "attestation_scope": "same_ssh_login_shell_pre_exec",
            "execution_mode": "ssh",
            "tool_id": request["tool_id"],
            "adapter_id": request["adapter_id"],
            "command_template_id": request["command_template_id"],
            "runner_contract_digest": request["runner_contract_digest"],
            "image_digest": f"sha256:{digest_hex}",
        },
        False,
    )


class SSHRunner:
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
                        selected_mode="ssh",
                        failure_receipt=failure_receipt,
                    )
                    if recovered is not None:
                        continue
                    terminal = self.attempt_journal.terminalize_output_fetch_failure(
                        run_id,
                        spec,
                        selected_mode="ssh",
                        failure_receipt=failure_receipt,
                        safe_failure_code="output_fetch_recovery_exhausted",
                    )
                    return [], terminal, "OUTPUT_FETCH_INTERRUPTED"
                quarantined = self.attempt_journal.quarantine_output_conflict(
                    run_id,
                    spec,
                    selected_mode="ssh",
                    failure_receipt=failure_receipt,
                )
                return [], quarantined, "OUTPUT_CONTRACT_CONFLICT"

    def _closed_attempt_result(
        self,
        spec: RunSpec,
        *,
        run_id: str,
        remote_run_dir: str,
        attempt: RunnerAttempt,
        error_code: str,
    ) -> RunResult:
        metadata = {
            "status": "failed",
            "error_code": error_code,
            "runner_phase": attempt.phase.value,
            "effect_certainty": attempt.effect_certainty.value,
            "retry_eligibility": attempt.retry_eligibility.value,
            "reconciliation_required": attempt.reconciliation_required,
            "runner_attempt_safe_receipt_digest": (
                attempt.safe_receipt_digest
            ),
        }
        self.store.write_json(run_id, "run_result_metadata.json", metadata)
        return RunResult(
            run_id=run_id,
            requested_mode=spec.execution_mode,
            selected_mode="ssh",
            remote_run_dir=remote_run_dir,
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
                    selected_mode="ssh",
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
                    selected_mode="ssh",
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
                selected_mode="ssh",
                reason_code="preflight_transport_recovered",
                failure_receipt={
                    "schema_version": "preflight_transport_failure@1",
                    "failure_class": result.failure_class.value,
                    "manifest_digest": receipt_digest(result.to_dict()),
                },
            )
            if recovered is None:
                return result

    def exec_run(self, spec: RunSpec) -> RunResult:
        ensure_valid_runspec(
            spec,
            limits=self.config.limits,
            allowed_partitions=self.config.slurm.allowed_partitions,
        )
        spec.run_id = spec.run_id or self._make_run_id()
        self.attempt_journal.create(spec, selected_mode="ssh")
        return self._run_existing_attempt(spec, resuming=False)

    def resume_pre_effect(self, spec: RunSpec) -> RunResult:
        if spec.run_id is None:
            raise ValueError("pre-effect recovery requires an exact run id")
        recovered = self.attempt_journal.authorize_restart_pre_effect_recovery(
            spec.run_id,
            spec,
            selected_mode="ssh",
        )
        if recovered is None:
            raise RunnerAttemptError(
                "runner_attempt_not_resumable",
                "runner attempt cannot resume before dispatch",
            )
        if recovered.state is RunnerAttemptState.TERMINAL:
            return self._closed_attempt_result(
                spec,
                run_id=spec.run_id,
                remote_run_dir=self._remote_run_dir(spec.run_id),
                attempt=recovered,
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
            return self._exec_run_attempt(spec, resuming=resuming)
        except RunnerAttemptError:
            raise
        except Exception as exc:
            self._record_attempt_exception(spec.run_id, exc)
            if self.transport_manager.enabled:
                attempt = self.attempt_journal.load(spec.run_id)
                if attempt.state is RunnerAttemptState.RECONCILIATION_REQUIRED:
                    return self._closed_attempt_result(
                        spec,
                        run_id=spec.run_id,
                        remote_run_dir=self._remote_run_dir(spec.run_id),
                        attempt=attempt,
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
                        run_id=spec.run_id,
                        remote_run_dir=self._remote_run_dir(spec.run_id),
                        attempt=attempt,
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
        if attempt.phase is RunnerAttemptPhase.DISPATCHING:
            self.attempt_journal.transition(
                run_id,
                state=RunnerAttemptState.RECONCILIATION_REQUIRED,
                effect_certainty=RunnerEffectCertainty.DISPATCH_IN_DOUBT,
                retry_eligibility=RunnerRetryEligibility.RECONCILE_REQUIRED,
                reconciliation_required=True,
                safe_failure_code="dispatch_in_doubt",
                reason_code="dispatch_outcome_unknown",
            )
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
            safe_failure_code="output_fetch_interrupted",
            reason_code="output_fetch_interrupted",
        )

    def _closed_dispatch_failure(
        self,
        spec: RunSpec,
        *,
        run_id: str,
        remote_run_dir: str,
        effect_certainty: RunnerEffectCertainty,
        error_code: str,
    ) -> RunResult:
        reconciliation_required = (
            effect_certainty is RunnerEffectCertainty.DISPATCH_IN_DOUBT
        )
        terminal_attempt = self.attempt_journal.transition(
            run_id,
            phase=(
                RunnerAttemptPhase.DISPATCHING
                if reconciliation_required
                else RunnerAttemptPhase.TERMINAL
            ),
            state=(
                RunnerAttemptState.RECONCILIATION_REQUIRED
                if reconciliation_required
                else RunnerAttemptState.TERMINAL
            ),
            effect_certainty=effect_certainty,
            retry_eligibility=(
                RunnerRetryEligibility.RECONCILE_REQUIRED
                if reconciliation_required
                else RunnerRetryEligibility.TERMINAL
            ),
            reconciliation_required=reconciliation_required,
            safe_failure_code=error_code.casefold(),
            reason_code=(
                "dispatch_outcome_unknown"
                if reconciliation_required
                else "pre_effect_recovery_exhausted"
            ),
        )
        return self._closed_attempt_result(
            spec,
            run_id=run_id,
            remote_run_dir=remote_run_dir,
            attempt=terminal_attempt,
            error_code=error_code,
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

    def _persist_remote_terminal_observation(
        self,
        *,
        spec: RunSpec,
        started_at: str,
        remote_argv: list[str],
        upload_entries: list[dict[str, object]],
        raw: CommandResult,
        toolchain_runtime_identity: dict[str, object] | None,
        toolchain_identity_failed: bool,
    ) -> dict[str, object]:
        run_id = str(spec.run_id)
        observation: dict[str, object] = {
            "schema_version": _REMOTE_TERMINAL_OBSERVATION_SCHEMA_VERSION,
            "run_id": run_id,
            "selected_mode": "ssh",
            "started_at": started_at,
            "remote_command": list(remote_argv),
            "upload_entries": upload_entries,
            "returncode": raw.returncode,
            "timed_out": raw.timed_out,
            "stage": raw.stage,
            "toolchain_runtime_identity": toolchain_runtime_identity,
            "toolchain_identity_failed": toolchain_identity_failed,
        }
        try:
            self.store.write_json_once(
                run_id,
                "remote_terminal_observation.json",
                observation,
            )
        except FileExistsError:
            if (
                self.store.read_json(run_id, "remote_terminal_observation.json")
                != observation
            ):
                raise ValueError("persisted SSH terminal observation drift")
        return observation

    def _load_remote_terminal_observation(
        self,
        spec: RunSpec,
        *,
        attempt: RunnerAttempt,
    ) -> dict[str, object]:
        run_id = str(spec.run_id)
        observation = self.store.read_json(
            run_id,
            "remote_terminal_observation.json",
        )
        if (
            observation.get("schema_version")
            != _REMOTE_TERMINAL_OBSERVATION_SCHEMA_VERSION
            or observation.get("run_id") != run_id
            or observation.get("selected_mode") != "ssh"
            or isinstance(observation.get("returncode"), bool)
            or not isinstance(observation.get("returncode"), int)
            or not isinstance(observation.get("remote_command"), list)
            or not all(
                isinstance(item, str)
                for item in list(observation.get("remote_command") or [])
            )
            or not isinstance(observation.get("toolchain_identity_failed"), bool)
            or attempt.receipt_digests.get("remote_terminal")
            != receipt_digest(observation)
        ):
            raise ValueError("persisted SSH terminal observation is invalid")
        return observation

    def _output_entries(self, run_id: str) -> list[dict[str, object]]:
        manifest = self.store.read_json(run_id, "outputs_manifest.json")
        if manifest.get("run_id") != run_id:
            raise ValueError("persisted output manifest belongs to another run")
        entries = list(manifest.get("entries") or [])
        if not all(isinstance(item, dict) for item in entries):
            raise ValueError("persisted output manifest entries are invalid")
        return [dict(item) for item in entries]

    def _complete_terminal_result(
        self,
        spec: RunSpec,
        terminal_observation: dict[str, object],
    ) -> RunResult:
        run_id = str(spec.run_id)
        attempt = self.attempt_journal.load_bound(
            run_id,
            spec,
            selected_mode="ssh",
        )
        if attempt.effect_certainty is not RunnerEffectCertainty.TERMINAL_KNOWN:
            raise RunnerAttemptError(
                "runner_terminal_evidence_missing",
                "runner cannot materialize a result without terminal evidence",
            )
        expected_remote_receipt = receipt_digest(terminal_observation)
        if attempt.receipt_digests.get("remote_terminal") != expected_remote_receipt:
            raise ValueError("SSH terminal receipt drift")

        stdout = self.store.read_log(run_id, "stdout.log")
        stderr = self.store.read_log(run_id, "stderr.log")
        returncode = int(terminal_observation["returncode"])
        toolchain_identity_failed = bool(
            terminal_observation["toolchain_identity_failed"]
        )
        toolchain_runtime_identity = terminal_observation.get(
            "toolchain_runtime_identity"
        )
        artifact_entries = (
            self._output_entries(run_id)
            if (
                spec.expected_outputs
                and returncode == 0
                and not toolchain_identity_failed
            )
            else []
        )

        outputs_root = self.store.run_root(run_id) / "outputs"
        missing_outputs, empty_outputs = validate_expected_outputs(
            outputs_root, spec.expected_outputs
        )
        success_check_failures = run_success_checks(outputs_root, spec)
        mapped_error = self.failure_mapper.map_error(stderr, spec.failure_signatures)
        error_code = mapped_error.code if mapped_error else None
        if toolchain_identity_failed and returncode == 0:
            error_code = "TOOLCHAIN_IDENTITY_MISSING"

        status = "completed"
        if (
            returncode != 0
            or toolchain_identity_failed
            or missing_outputs
            or empty_outputs
            or success_check_failures
        ):
            status = "failed"
            if error_code is None:
                if returncode == 124:
                    error_code = "COMMAND_TIMEOUT"
                elif returncode != 0:
                    error_code = "RUN_FAILED"
                elif missing_outputs or empty_outputs or success_check_failures:
                    error_code = "OUTPUT_VALIDATION_FAILED"
                else:
                    error_code = "RUN_FAILED"

        artifacts = {
            str(entry["remote_path"]): str(entry["local_path"])
            for entry in artifact_entries
            if entry.get("returncode", 1) == 0
            and entry.get("remote_path")
            and entry.get("local_path")
        }
        if status != "completed":
            artifacts = {}
        terminal_receipt = {
            "status": status,
            "exit_code": returncode,
            "error_code": error_code,
            "artifacts": sorted(artifacts),
        }
        if attempt.state is RunnerAttemptState.ACTIVE:
            attempt = self.attempt_journal.transition(
                run_id,
                phase=RunnerAttemptPhase.TERMINAL,
                state=RunnerAttemptState.TERMINAL,
                retry_eligibility=RunnerRetryEligibility.TERMINAL,
                reconciliation_required=False,
                safe_failure_code=(
                    None if status == "completed" else "payload_failed"
                ),
                receipt_digests={"run_result": receipt_digest(terminal_receipt)},
                reason_code=(
                    "run_succeeded" if status == "completed" else "run_failed"
                ),
            )
        elif (
            attempt.state is not RunnerAttemptState.TERMINAL
            or attempt.receipt_digests.get("run_result")
            != receipt_digest(terminal_receipt)
        ):
            raise RunnerAttemptError(
                "runner_terminal_result_unrecoverable",
                "runner terminal result evidence is incomplete",
            )

        metadata = {
            "started_at": terminal_observation["started_at"],
            "finished_at": datetime.now(tz=UTC).isoformat(),
            "remote_command": terminal_observation["remote_command"],
            "upload_entries": terminal_observation.get("upload_entries", []),
            "stage": terminal_observation.get("stage"),
            "status": status,
            "exit_code": returncode,
            "error_code": error_code,
            "validation": {
                "missing_outputs": missing_outputs,
                "empty_outputs": empty_outputs,
                "success_check_failures": success_check_failures,
            },
            "toolchain_runtime_identity": toolchain_runtime_identity,
            "runner_attempt_safe_receipt_digest": attempt.safe_receipt_digest,
            "runner_phase": attempt.phase.value,
            "effect_certainty": attempt.effect_certainty.value,
            "retry_eligibility": attempt.retry_eligibility.value,
            "reconciliation_required": attempt.reconciliation_required,
        }
        self.store.write_json(run_id, "run_result_metadata.json", metadata)
        return RunResult(
            run_id=run_id,
            requested_mode=spec.execution_mode,
            selected_mode="ssh",
            remote_run_dir=self._remote_run_dir(run_id),
            status=status,
            exit_code=returncode,
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

    def recover_terminal_outcome(self, spec: RunSpec) -> RunResult:
        """Recover one exact terminal outcome without re-entering dispatch."""

        if spec.run_id is None:
            raise ValueError("terminal recovery requires an exact run id")
        run_id = spec.run_id
        attempt = self.attempt_journal.load_bound(
            run_id,
            spec,
            selected_mode="ssh",
        )
        terminal_observation = self._load_remote_terminal_observation(
            spec,
            attempt=attempt,
        )
        should_fetch = bool(
            spec.expected_outputs
            and int(terminal_observation["returncode"]) == 0
            and not bool(terminal_observation["toolchain_identity_failed"])
        )
        if attempt.state is RunnerAttemptState.ACTIVE and should_fetch:
            if attempt.phase is RunnerAttemptPhase.REMOTE_TERMINAL:
                attempt = self.attempt_journal.transition(
                    run_id,
                    phase=RunnerAttemptPhase.OUTPUTS_FETCHING,
                    reason_code="restart_outputs_fetching",
                )
            if attempt.phase is RunnerAttemptPhase.OUTPUTS_FETCHING:
                attempt = self.attempt_journal.authorize_restart_output_fetch_recovery(
                    run_id,
                    spec,
                    selected_mode="ssh",
                )
                if attempt is None:
                    raise RunnerAttemptError(
                        "runner_output_fetch_not_resumable",
                        "runner output fetch cannot resume safely",
                    )
                if attempt.state is RunnerAttemptState.TERMINAL:
                    return self._closed_attempt_result(
                        spec,
                        run_id=run_id,
                        remote_run_dir=self._remote_run_dir(run_id),
                        attempt=attempt,
                        error_code="OUTPUT_FETCH_INTERRUPTED",
                    )
                (
                    _,
                    output_failure_attempt,
                    output_failure_code,
                ) = self._fetch_outputs_with_recovery(
                    spec,
                    run_id,
                    self._remote_run_dir(run_id),
                )
                if output_failure_attempt is not None:
                    assert output_failure_code is not None
                    return self._closed_attempt_result(
                        spec,
                        run_id=run_id,
                        remote_run_dir=self._remote_run_dir(run_id),
                        attempt=output_failure_attempt,
                        error_code=output_failure_code,
                    )
                attempt = self.attempt_journal.transition(
                    run_id,
                    phase=RunnerAttemptPhase.OUTPUTS_VERIFIED,
                    retry_eligibility=RunnerRetryEligibility.TERMINAL,
                    receipt_digests={
                        "outputs_manifest": receipt_digest(
                            self.store.read_json(run_id, "outputs_manifest.json")
                        )
                    },
                    reason_code="outputs_verified_after_restart",
                )
            if attempt.phase not in {
                RunnerAttemptPhase.OUTPUTS_VERIFIED,
                RunnerAttemptPhase.TERMINAL,
            }:
                raise RunnerAttemptError(
                    "runner_output_fetch_phase_invalid",
                    "runner output fetch phase cannot be recovered",
                )
        elif attempt.state is RunnerAttemptState.ACTIVE and attempt.phase not in {
            RunnerAttemptPhase.REMOTE_TERMINAL,
            RunnerAttemptPhase.OUTPUTS_VERIFIED,
        }:
            raise RunnerAttemptError(
                "runner_terminal_phase_invalid",
                "runner terminal outcome cannot be recovered from this phase",
            )
        return self._complete_terminal_result(spec, terminal_observation)

    def _exec_run_attempt(
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
        started_at = datetime.now(tz=UTC).isoformat()
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

        if self.config.execution.create_remote_dir_for_ssh:
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

        toolchain_request = _toolchain_runtime_request(spec)
        attested_command = _command_with_toolchain_attestation(
            spec,
            toolchain_request,
            apptainer_executable=self.config.execution.apptainer_executable,
        )
        remote_argv = make_remote_shell_command_with_env(
            remote_work_dir, attested_command, env
        )
        self._advance_attempt_phase(
            run_id,
            RunnerAttemptPhase.DISPATCH_PREPARED,
            reason_code="dispatch_prepared",
        )
        self.attempt_journal.transition(
            run_id,
            phase=RunnerAttemptPhase.DISPATCHING,
            reason_code="payload_transmission_started",
        )
        while True:
            raw = self.transport_manager.run_ssh(
                remote_argv,
                check=False,
                timeout=self.config.execution.remote_execution_timeout_seconds,
                stage="remote_execution",
            )
            dispatch_observation = classify_direct_dispatch(raw)
            if dispatch_observation is DirectDispatchObservation.TERMINAL_OBSERVED:
                break
            if dispatch_observation is DirectDispatchObservation.DISPATCH_IN_DOUBT:
                return self._closed_dispatch_failure(
                    spec,
                    run_id=run_id,
                    remote_run_dir=remote_run_dir,
                    effect_certainty=RunnerEffectCertainty.DISPATCH_IN_DOUBT,
                    error_code="DISPATCH_IN_DOUBT",
                )
            recovered = self.attempt_journal.authorize_pre_effect_recovery(
                run_id,
                spec,
                selected_mode="ssh",
                reason_code="dispatch_pre_accept_recovered",
                failure_receipt=safe_transport_failure_receipt(
                    raw,
                    phase="dispatch_pre_accept",
                ),
            )
            if recovered is None:
                return self._closed_dispatch_failure(
                    spec,
                    run_id=run_id,
                    remote_run_dir=remote_run_dir,
                    effect_certainty=RunnerEffectCertainty.NO_EFFECT,
                    error_code="PRE_EFFECT_RECOVERY_EXHAUSTED",
                )
        raw_stdout, toolchain_runtime_identity, toolchain_identity_failed = (
            _extract_toolchain_runtime_identity(raw.stdout, toolchain_request)
        )
        stdout = redact_text(raw_stdout, self.config.logging.redact_patterns)
        stderr = redact_text(raw.stderr, self.config.logging.redact_patterns)
        self.store.write_log(run_id, "stdout.log", stdout)
        self.store.write_log(run_id, "stderr.log", stderr)

        terminal_observation = self._persist_remote_terminal_observation(
            spec=spec,
            started_at=started_at,
            remote_argv=remote_argv,
            upload_entries=upload_entries,
            raw=raw,
            toolchain_runtime_identity=toolchain_runtime_identity,
            toolchain_identity_failed=toolchain_identity_failed,
        )
        self.attempt_journal.transition(
            run_id,
            phase=RunnerAttemptPhase.REMOTE_TERMINAL,
            state=RunnerAttemptState.ACTIVE,
            effect_certainty=RunnerEffectCertainty.TERMINAL_KNOWN,
            retry_eligibility=(
                RunnerRetryEligibility.VERIFY_THEN_RETRY
                if (
                    spec.expected_outputs
                    and raw.returncode == 0
                    and not toolchain_identity_failed
                )
                else RunnerRetryEligibility.TERMINAL
            ),
            reconciliation_required=False,
            receipt_digests={
                "remote_terminal": receipt_digest(terminal_observation)
            },
            reason_code="remote_terminal_observed",
        )

        if (
            spec.expected_outputs
            and raw.returncode == 0
            and not toolchain_identity_failed
        ):
            self.attempt_journal.transition(
                run_id,
                phase=RunnerAttemptPhase.OUTPUTS_FETCHING,
                reason_code="outputs_fetching",
            )
            (
                _,
                output_failure_attempt,
                output_failure_code,
            ) = self._fetch_outputs_with_recovery(
                spec,
                run_id,
                remote_run_dir,
            )
            if output_failure_attempt is not None:
                assert output_failure_code is not None
                return self._closed_attempt_result(
                    spec,
                    run_id=run_id,
                    remote_run_dir=remote_run_dir,
                    attempt=output_failure_attempt,
                    error_code=output_failure_code,
                )
            self.attempt_journal.transition(
                run_id,
                phase=RunnerAttemptPhase.OUTPUTS_VERIFIED,
                retry_eligibility=RunnerRetryEligibility.TERMINAL,
                receipt_digests={
                    "outputs_manifest": receipt_digest(
                        self.store.read_json(run_id, "outputs_manifest.json")
                    )
                },
                reason_code="outputs_verified",
            )
        return self._complete_terminal_result(spec, terminal_observation)
