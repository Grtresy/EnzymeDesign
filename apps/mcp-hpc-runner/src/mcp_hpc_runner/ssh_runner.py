from __future__ import annotations

from datetime import UTC, datetime
from pathlib import PurePosixPath
import re
import shlex
import uuid

from .config import RunnerConfig
from .contract_manifest import render_cdhit_membership_normalizer_command
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


_TOOLCHAIN_IDENTITY_MARKER = "__OPENZYME_TOOLCHAIN_SHA256__"
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
        result = self.command_runner.run(
            mkdir_cmd,
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

    def exec_run(self, spec: RunSpec) -> RunResult:
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

        if self.config.execution.create_remote_dir_for_ssh:
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
        ssh_cmd = wrap_ssh(self.config.cluster.ssh_target, remote_argv)
        raw = self.command_runner.run(
            ssh_cmd,
            check=False,
            timeout=self.config.execution.remote_execution_timeout_seconds,
            stage="remote_execution",
        )

        raw_stdout, toolchain_runtime_identity, toolchain_identity_failed = (
            _extract_toolchain_runtime_identity(raw.stdout, toolchain_request)
        )
        stdout = redact_text(raw_stdout, self.config.logging.redact_patterns)
        stderr = redact_text(raw.stderr, self.config.logging.redact_patterns)
        self.store.write_log(run_id, "stdout.log", stdout)
        self.store.write_log(run_id, "stderr.log", stderr)

        artifact_entries = []
        if (
            spec.expected_outputs
            and raw.returncode == 0
            and not toolchain_identity_failed
        ):
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
        # A failed payload cannot emit the success-only identity marker. Preserve
        # its primary runner/transport failure; missing or malformed identity is
        # authoritative only when the remote command otherwise reports success.
        if toolchain_identity_failed and raw.returncode == 0:
            error_code = "TOOLCHAIN_IDENTITY_MISSING"

        status = "completed"
        if (
            raw.returncode != 0
            or toolchain_identity_failed
            or missing_outputs
            or empty_outputs
            or success_check_failures
        ):
            status = "failed"
            if error_code is None:
                if raw.returncode == 124:
                    error_code = "COMMAND_TIMEOUT"
                elif raw.returncode != 0:
                    error_code = "RUN_FAILED"
                elif missing_outputs or empty_outputs or success_check_failures:
                    error_code = "OUTPUT_VALIDATION_FAILED"
                else:
                    error_code = "RUN_FAILED"

        metadata = {
            "started_at": started_at,
            "finished_at": datetime.now(tz=UTC).isoformat(),
            "remote_command": remote_argv,
            "stage": raw.stage,
            "status": status,
            "exit_code": raw.returncode,
            "error_code": error_code,
            "upload_entries": upload_entries,
            "validation": {
                "missing_outputs": missing_outputs,
                "empty_outputs": empty_outputs,
                "success_check_failures": success_check_failures,
            },
            "toolchain_runtime_identity": toolchain_runtime_identity,
        }

        self.store.write_json(run_id, "run_result_metadata.json", metadata)

        artifacts = {
            entry["remote_path"]: entry["local_path"]
            for entry in artifact_entries
            if entry.get("returncode", 1) == 0
        }
        if status != "completed":
            # Failed or partially validated outputs remain runner-private
            # diagnostics. They are never projected as fetchable artifacts.
            artifacts = {}

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
