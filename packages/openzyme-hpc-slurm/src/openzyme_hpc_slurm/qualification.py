from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import base64
import hashlib
import re
import shlex
import subprocess
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOperationObservation
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationRouteOutcome
from openzyme_contracts import ExternalScientificQualificationWorkload
from openzyme_contracts import canonical_sha256_digest


SLURM_QUALIFICATION_OPERATIONS = ("cancel", "observe", "reconcile", "submit")


def _safe_scoped_remote_path(value: str) -> bool:
    relative = value[1:] if value.startswith("/") else value
    return (
        bool(relative)
        and not value.endswith("/")
        and re.fullmatch(r"/?[A-Za-z0-9.][A-Za-z0-9._/-]{0,190}", value)
        is not None
        and all(segment not in {"", ".", ".."} for segment in relative.split("/"))
    )


class SlurmQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    qualification_account_only: bool
    same_attempt_reconcile: bool


class SlurmQualificationRemoteCommandPort(Protocol):
    def run_remote(self, script: str) -> tuple[int, str, str]: ...


class SlurmScientificQualificationInputResolver(Protocol):
    def resolve(self, content_digest: str) -> bytes: ...


@dataclass(slots=True)
class SlurmQualificationState:
    workspace: str
    partition: str
    command_port: SlurmQualificationRemoteCommandPort = field(repr=False)
    submitted_job_id: str | None = None
    submit_job_name: str | None = None
    cancel_job_name: str | None = None
    reconcile_job_name: str | None = None

    def __post_init__(self) -> None:
        if (
            not _safe_scoped_remote_path(self.workspace)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", self.partition) is None
        ):
            raise ValueError("Slurm qualification scope is invalid")

    def cleanup(self) -> dict[str, object]:
        cleanup = (
            f"if test -f {self.workspace}/job-id; then scancel $(cat {self.workspace}/job-id) >/dev/null 2>&1 || true; fi; "
            f"if test -f {self.workspace}/cancel-job-id; then scancel $(cat {self.workspace}/cancel-job-id) >/dev/null 2>&1 || true; fi"
        )
        if self.cancel_job_name is not None:
            cleanup += f"; scancel -n {self.cancel_job_name} >/dev/null 2>&1 || true"
        if self.submit_job_name is not None:
            cleanup += f"; scancel -n {self.submit_job_name} >/dev/null 2>&1 || true"
        if self.reconcile_job_name is not None:
            cleanup += f"; scancel -n {self.reconcile_job_name} >/dev/null 2>&1 || true"
        returncode, _stdout, _stderr = self.command_port.run_remote(cleanup)
        return {"scheduler_cleanup_attempted": True, "command_accepted": returncode == 0}


@dataclass(slots=True)
class OpenSshSlurmQualificationOperation:
    component_id: str
    route_id: str
    subject_digest: str
    state: SlurmQualificationState = field(repr=False)
    qualification_account_only: bool = True
    same_attempt_reconcile: bool = True

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        try:
            if request.operation == "reconcile":
                self._dispatch_response_loss(request)
                return self._observation(
                    request,
                    terminal=False,
                    succeeded=False,
                    effect_certainty="dispatch_in_doubt",
                    error_code="qualification_response_lost_after_slurm_acceptance",
                )
            self._execute(request)
        except subprocess.TimeoutExpired:
            return self._observation(
                request,
                terminal=False,
                succeeded=False,
                effect_certainty="dispatch_in_doubt",
                error_code="qualification_slurm_command_timeout_in_doubt",
            )
        except ExternalQualificationError as exc:
            return self._observation(
                request,
                terminal=True,
                succeeded=False,
                effect_certainty="terminal_known",
                error_code=exc.error_code,
            )
        return self._observation(
            request,
            terminal=True,
            succeeded=True,
            effect_certainty="terminal_known",
        )

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationOperationObservation:
        try:
            return self._reconcile(request)
        except subprocess.TimeoutExpired:
            return self._observation(
                request,
                terminal=True,
                succeeded=False,
                effect_certainty="dispatch_in_doubt",
                error_code="qualification_slurm_reconcile_timeout_in_doubt",
            )
        except ExternalQualificationError as exc:
            return self._observation(
                request,
                terminal=True,
                succeeded=False,
                effect_certainty="terminal_known",
                error_code=exc.error_code,
            )

    def _reconcile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationOperationObservation:
        if request.operation == "submit" and self.state.submit_job_name is not None:
            output = self._run(
                "timeout 30s sacct -n -X -S now-1hour "
                f"-u \"$USER\" --name {self.state.submit_job_name} "
                "-o JobIDRaw,State -P"
            )
            rows = tuple(line for line in output.splitlines() if line.strip())
            fields = rows[0].split("|", 1) if len(rows) == 1 else ()
            succeeded = (
                len(fields) == 2
                and re.fullmatch(r"[0-9]+", fields[0]) is not None
                and bool(fields[1])
            )
            if succeeded:
                self.state.submitted_job_id = fields[0]
            return self._observation(
                request,
                terminal=True,
                succeeded=succeeded,
                effect_certainty="terminal_known",
                error_code=(
                    None
                    if succeeded
                    else "qualification_slurm_submit_reconcile_failed"
                ),
            )
        if request.operation == "cancel" and self.state.cancel_job_name is not None:
            output = self._run(
                "timeout 30s sacct -n -X -S now-1hour "
                f"-u \"$USER\" --name {self.state.cancel_job_name} "
                "-o JobIDRaw,State -P"
            )
            rows = tuple(line for line in output.splitlines() if line.strip())
            succeeded = len(rows) == 1 and rows[0].split("|", 1)[-1].startswith(
                "CANCELLED"
            )
            return self._observation(
                request,
                terminal=True,
                succeeded=succeeded,
                effect_certainty="terminal_known",
                error_code=None if succeeded else "qualification_slurm_cancel_reconcile_failed",
            )
        if request.operation != "reconcile" or self.state.reconcile_job_name is None:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "Slurm reconcile requires the exact response-loss submit attempt",
            )
        output = self._run(
            "timeout 30s sacct -n -X -S now-1hour "
            f"-u \"$USER\" --name {self.state.reconcile_job_name} "
            "-o JobIDRaw,State -P"
        )
        rows = tuple(line for line in output.splitlines() if line.strip())
        fields = rows[0].split("|", 1) if len(rows) == 1 else ()
        succeeded = (
            len(fields) == 2
            and re.fullmatch(r"[0-9]+", fields[0]) is not None
            and bool(fields[1])
        )
        return self._observation(
            request,
            terminal=True,
            succeeded=succeeded,
            effect_certainty="terminal_known",
            error_code=None if succeeded else "qualification_slurm_reconcile_failed",
        )

    def restore_dispatched_attempt(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> None:
        if request.operation == "submit":
            self.state.submit_job_name = self._attempt_job_name(
                request,
                prefix="openzyme-q-terminal",
            )
            return
        if request.operation == "cancel":
            self.state.cancel_job_name = self._attempt_job_name(
                request,
                prefix="openzyme-q-cancel",
            )
            return
        if request.operation != "reconcile":
            raise ExternalQualificationError(
                "qualification_probe_restore_not_reconcilable",
                "only a reconcilable Slurm operation can be restored",
            )
        suffix = canonical_sha256_digest(
            {"attempt_id": request.attempt_id}
        ).removeprefix("sha256:")[:16]
        self.state.reconcile_job_name = f"openzyme-q-{suffix}"

    def _run(self, script: str) -> str:
        returncode, stdout, _stderr = self.state.command_port.run_remote(script)
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_slurm_command_failed",
                "Slurm qualification command failed",
            )
        return stdout.strip()

    def _execute(self, request: ExternalQualificationProbeRequest) -> None:
        workspace = self.state.workspace
        operation = request.operation
        if operation == "submit":
            name = self._attempt_job_name(request, prefix="openzyme-q-terminal")
            self.state.submit_job_name = name
            output = self._run(
                f"sbatch --parsable -p {self.state.partition} -t 00:01:00 -c 1 "
                f"-J {name} -o {workspace}/terminal-%j.out "
                "--wrap 'printf OPENZYME_SLURM_OK'"
            )
            job_id = output.split(";", 1)[0]
            if re.fullmatch(r"[0-9]+", job_id) is None:
                raise ExternalQualificationError(
                    "qualification_slurm_job_id_invalid",
                    "Slurm submit returned an invalid job identity",
                )
            self.state.submitted_job_id = job_id
            self._run(f"printf '%s' {job_id} > {workspace}/job-id")
        elif operation == "observe":
            job_id = self.state.submitted_job_id or self._run(f"cat {workspace}/job-id")
            state = self._run(
                f"for i in $(seq 1 30); do s=$(sacct -n -X -j {job_id} -o State -P | head -n 1 | cut -d'|' -f1); case \"$s\" in COMPLETED*) printf '%s' \"$s\"; exit 0;; FAILED*|CANCELLED*|TIMEOUT*) printf '%s' \"$s\"; exit 2;; esac; sleep 2; done; exit 3"
            )
            if not state.startswith("COMPLETED"):
                raise ExternalQualificationError(
                    "qualification_slurm_terminal_job_failed",
                    "Slurm terminal qualification job did not complete",
                )
        elif operation == "cancel":
            name = self._attempt_job_name(request, prefix="openzyme-q-cancel")
            self.state.cancel_job_name = name
            output = self._run(
                f"job=$(sbatch --parsable -p {self.state.partition} -t 00:02:00 -c 1 -J {name} -o {workspace}/cancel-%j.out --wrap 'sleep 90'); job=${{job%%;*}}; printf '%s' \"$job\" > {workspace}/cancel-job-id; scancel \"$job\"; printf '%s' \"$job\""
            )
            if re.fullmatch(r"[0-9]+", output) is None:
                raise ExternalQualificationError(
                    "qualification_slurm_cancel_job_id_invalid",
                    "Slurm cancel qualification returned an invalid job identity",
                )
        else:
            raise ExternalQualificationError(
                "qualification_slurm_operation_unsupported",
                "Slurm qualification operation is unsupported",
            )

    @staticmethod
    def _attempt_job_name(
        request: ExternalQualificationProbeRequest,
        *,
        prefix: str,
    ) -> str:
        suffix = canonical_sha256_digest(
            {"attempt_id": request.attempt_id}
        ).removeprefix("sha256:")[:12]
        return f"{prefix}-{suffix}"

    def _dispatch_response_loss(self, request: ExternalQualificationProbeRequest) -> None:
        suffix = canonical_sha256_digest(
            {"attempt_id": request.attempt_id}
        ).removeprefix("sha256:")[:16]
        name = f"openzyme-q-{suffix}"
        self.state.reconcile_job_name = name
        self._run(
            f"sbatch --parsable -p {self.state.partition} -t 00:02:00 -c 1 -J {name} -o {self.state.workspace}/reconcile-%j.out --wrap 'sleep 60' >/dev/null"
        )

    @staticmethod
    def _observation(
        request: ExternalQualificationProbeRequest,
        *,
        terminal: bool,
        succeeded: bool,
        effect_certainty: str,
        error_code: str | None = None,
    ) -> ExternalQualificationOperationObservation:
        payload = {
            "attempt_id": request.attempt_id,
            "operation": request.operation,
            "terminal": terminal,
            "succeeded": succeeded,
            "partition": "3090",
        }
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty=effect_certainty,
            terminal=terminal,
            succeeded=succeeded,
            output_digest=canonical_sha256_digest(payload) if succeeded else None,
            receipt_digest=canonical_sha256_digest(payload),
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=True,
            fallback_performed=False,
        )


@dataclass(slots=True)
class SlurmScientificQualificationRoute:
    workspace_root: str
    workspace_owner_id: str
    partition: str
    command_port: SlurmQualificationRemoteCommandPort = field(repr=False)
    input_resolver: SlurmScientificQualificationInputResolver = field(repr=False)
    software_image_path: str
    software_image_digest: str
    route_kind: str = "hpc-primary"

    def __post_init__(self) -> None:
        if (
            not _safe_scoped_remote_path(self.workspace_root)
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.workspace_owner_id
            )
            is None
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", self.partition) is None
            or not self.software_image_path.startswith("/")
            or self.software_image_path.endswith("/")
            or any(
                segment in {"", ".", ".."}
                for segment in self.software_image_path[1:].split("/")
            )
            or re.fullmatch(r"sha256:[0-9a-f]{64}", self.software_image_digest)
            is None
        ):
            raise ValueError("scientific Slurm qualification scope is invalid")

    def dispatch(
        self,
        workload: ExternalScientificQualificationWorkload,
    ) -> ExternalScientificQualificationRouteOutcome:
        run_root = f"{self.workspace_root}/scientific/{workload.workload_id}"
        outcome: ExternalScientificQualificationRouteOutcome | None = None
        cleanup_error_code: str | None = None
        try:
            self._ensure_workspace_scope()
            observed_image_digest = self._run(
                f"sha256sum {shlex.quote(self.software_image_path)} | cut -d' ' -f1"
            )
            if f"sha256:{observed_image_digest}" != self.software_image_digest:
                raise ExternalQualificationError(
                    "qualification_compute_image_digest_drift",
                    "scientific Slurm image differs from prepared target identity",
                )
            self._run(
                f"test ! -e {shlex.quote(run_root)}; "
                f"mkdir -p -m 700 {shlex.quote(run_root)}"
            )
            for item in workload.inputs:
                content = self.input_resolver.resolve(item.content_digest)
                if len(content) != item.size_bytes or canonical_sha256_digest(
                    {"content_hex": content.hex()}
                ) != item.content_digest:
                    raise ExternalQualificationError(
                        "qualification_compute_input_digest_mismatch",
                        "scientific qualification input bytes drifted",
                    )
                remote_path = f"{run_root}/{workload.cwd}/{item.path}"
                self._stage_input(remote_path, content)
            cwd = f"{run_root}/{workload.cwd}"
            for output_path in workload.expected_output_paths:
                remote_path = f"{cwd}/{output_path}"
                self._run(f"mkdir -p {shlex.quote(remote_path.rsplit('/', 1)[0])}")
            if workload.operation == "hmmsearch":
                setup = shlex.join(
                    (
                        "apptainer",
                        "exec",
                        self.software_image_path,
                        "hmmbuild",
                        "inputs/model.hmm",
                        "inputs/alignment.fasta",
                    )
                )
                self._submit_wait(workload, cwd, setup, suffix="setup")
            self._submit_wait(
                workload,
                cwd,
                shlex.join(
                    ("apptainer", "exec", self.software_image_path, *workload.argv)
                ),
                suffix="run",
            )
            outputs: list[dict[str, object]] = []
            for output_path in workload.expected_output_paths:
                remote_path = f"{cwd}/{output_path}"
                output = self._run(
                    f"test -s {shlex.quote(remote_path)}; "
                    f"wc -c < {shlex.quote(remote_path)}; sha256sum {shlex.quote(remote_path)} | cut -d' ' -f1"
                ).splitlines()
                if len(output) != 2 or re.fullmatch(r"[0-9a-f]{64}", output[1]) is None:
                    raise ExternalQualificationError(
                        "qualification_compute_expected_output_missing",
                        "scientific Slurm output observation is incomplete",
                    )
                outputs.append(
                    {
                        "path": output_path,
                        "size_bytes": int(output[0]),
                        "content_digest": f"sha256:{output[1]}",
                    }
                )
            payload = {
                "workload_digest": workload.workload_digest,
                "partition": self.partition,
                "outputs": outputs,
                "route_kind": self.route_kind,
            }
            outcome = ExternalScientificQualificationRouteOutcome(
                workload_digest=workload.workload_digest,
                effect_certainty="terminal_known",
                terminal=True,
                succeeded=True,
                output_digest=canonical_sha256_digest(payload),
                receipt_digest=canonical_sha256_digest(
                    {**payload, "workspace_cleanup_required": True}
                ),
                error_code=None,
                external_effect_performed=True,
                credential_material_accessed=True,
            )
        except ExternalQualificationError as exc:
            outcome = self._failure(workload, exc.error_code)
        except subprocess.TimeoutExpired:
            outcome = self._failure(
                workload,
                "qualification_compute_remote_timeout_in_doubt",
                effect_certainty="dispatch_in_doubt",
            )
        except OSError:
            outcome = self._failure(
                workload,
                "qualification_compute_remote_transport_in_doubt",
                effect_certainty="dispatch_in_doubt",
            )
        finally:
            try:
                returncode, _stdout, _stderr = self.command_port.run_remote(
                    f"rm -rf -- {shlex.quote(run_root)}"
                )
                if returncode != 0:
                    cleanup_error_code = "qualification_compute_remote_cleanup_failed"
            except subprocess.TimeoutExpired:
                cleanup_error_code = "qualification_compute_remote_cleanup_timeout"
        if cleanup_error_code is not None:
            return self._failure(
                workload,
                cleanup_error_code,
                effect_certainty=(
                    "dispatch_in_doubt"
                    if cleanup_error_code.endswith("_timeout")
                    else "terminal_known"
                ),
            )
        assert outcome is not None
        return outcome

    def _ensure_workspace_scope(self) -> None:
        workspace = shlex.quote(self.workspace_root)
        owner_marker = shlex.quote(
            f"{self.workspace_root}/.openzyme-qualification-owner"
        )
        owner_id = shlex.quote(self.workspace_owner_id)
        self._run(
            f"if test -e {workspace}; then "
            f"test -d {workspace} && test -f {owner_marker} && "
            f"test \"$(cat {owner_marker})\" = {owner_id}; "
            f"else mkdir -p -m 700 {workspace} && "
            f"printf '%s' {owner_id} > {owner_marker} && "
            f"chmod 600 {owner_marker}; fi"
        )

    def _stage_input(self, remote_path: str, content: bytes) -> None:
        parent = shlex.quote(remote_path.rsplit("/", 1)[0])
        target = shlex.quote(remote_path)
        self._run(f"mkdir -p {parent}; : > {target}")
        encoded = base64.b64encode(content).decode("ascii")
        for offset in range(0, len(encoded), 32_768):
            chunk = shlex.quote(encoded[offset : offset + 32_768])
            self._run(f"printf '%s' {chunk} | base64 -d >> {target}")
        observed = self._run(
            f"wc -c < {target}; sha256sum {target} | cut -d' ' -f1"
        ).splitlines()
        expected_sha256 = hashlib.sha256(content).hexdigest()
        if observed != [str(len(content)), expected_sha256]:
            raise ExternalQualificationError(
                "qualification_compute_remote_input_verification_failed",
                "scientific qualification staged input differs from exact source bytes",
            )

    def reconcile(
        self,
        workload: ExternalScientificQualificationWorkload,
    ) -> ExternalScientificQualificationRouteOutcome:
        return self._failure(workload, "qualification_compute_reconcile_without_dispatch")

    def _run(self, script: str) -> str:
        returncode, stdout, _stderr = self.command_port.run_remote(script)
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_compute_remote_command_failed",
                "scientific Slurm qualification command failed",
            )
        return stdout.strip()

    def _submit_wait(
        self,
        workload: ExternalScientificQualificationWorkload,
        cwd: str,
        command: str,
        *,
        suffix: str,
    ) -> None:
        job_name = (
            "openzyme-science-"
            f"{workload.workload_digest.removeprefix('sha256:')[:12]}-{suffix}"
        )
        self._run(
            "sbatch --wait --parsable "
            f"-p {shlex.quote(self.partition)} -t 00:10:00 -c 1 "
            f"-J {shlex.quote(job_name)} --chdir={shlex.quote(cwd)} "
            f"-o {shlex.quote(cwd + '/slurm-%j.out')} "
            f"--wrap {shlex.quote(command)}"
        )

    @staticmethod
    def _failure(
        workload: ExternalScientificQualificationWorkload,
        error_code: str,
        *,
        effect_certainty: str = "terminal_known",
    ) -> ExternalScientificQualificationRouteOutcome:
        return ExternalScientificQualificationRouteOutcome(
            workload_digest=workload.workload_digest,
            effect_certainty=effect_certainty,
            terminal=True,
            succeeded=False,
            output_digest=None,
            receipt_digest=None,
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=True,
        )


@dataclass(slots=True)
class SlurmAlphaFoldQualificationRoute:
    """Run one fixed AlphaFold 3 inference through the exact Diannan route."""

    workspace_root: str
    workspace_owner_id: str
    command_port: SlurmQualificationRemoteCommandPort = field(repr=False)
    input_resolver: SlurmScientificQualificationInputResolver = field(repr=False)
    wrapper_digest: str
    image_digest: str
    model_parameters_digest: str
    database_closure_digest: str
    gpu_capability_digest: str
    partition: str = "3090"
    route_kind: str = "hpc-primary"

    def __post_init__(self) -> None:
        if (
            not _safe_scoped_remote_path(self.workspace_root)
            or re.fullmatch(
                r"[A-Za-z0-9][A-Za-z0-9._-]{0,63}", self.workspace_owner_id
            )
            is None
            or self.partition != "3090"
        ):
            raise ValueError("AlphaFold Slurm qualification scope is invalid")
        for value in (
            self.wrapper_digest,
            self.image_digest,
            self.model_parameters_digest,
            self.database_closure_digest,
            self.gpu_capability_digest,
        ):
            if re.fullmatch(r"sha256:[0-9a-f]{64}", value) is None:
                raise ValueError("AlphaFold resource identity is invalid")

    def dispatch(
        self,
        workload: ExternalScientificQualificationWorkload,
    ) -> ExternalScientificQualificationRouteOutcome:
        run_root = f"{self.workspace_root}/alphafold/{workload.workload_id}"
        outcome: ExternalScientificQualificationRouteOutcome | None = None
        cleanup_error: str | None = None
        try:
            self._ensure_workspace_scope()
            self._verify_resources()
            if workload.argv != (
                "python",
                "run_alphafold.py",
                "--json_path",
                "inputs/job.json",
                "--output_dir",
                "results/alphafold3",
            ):
                raise ExternalQualificationError(
                    "qualification_alphafold_workload_profile_drift",
                    "AlphaFold workload differs from the fixed Batch-2 profile",
                )
            self._run(
                f"test ! -e {shlex.quote(run_root)}; "
                f"mkdir -p -m 700 {shlex.quote(run_root)}"
            )
            for item in workload.inputs:
                content = self.input_resolver.resolve(item.content_digest)
                if len(content) != item.size_bytes:
                    raise ExternalQualificationError(
                        "qualification_compute_input_digest_mismatch",
                        "AlphaFold qualification input size drifted",
                    )
                self._stage_input(
                    f"{run_root}/{workload.cwd}/{item.path}", content
                )
            cwd = f"{run_root}/{workload.cwd}"
            self._run(f"mkdir -p {shlex.quote(cwd + '/results/alphafold3')}")
            command = (
                "gpu=$(nvidia-smi --query-gpu=name,uuid,driver_version,compute_cap "
                "--format=csv,noheader); printf '%s\\n' \"$gpu\" > gpu-identity.txt; "
                "printf '%s\\n' \"$gpu\" | grep -q '3090'; "
                "/opt/tools/alphafold3 --json_path inputs/job.json "
                "--output_dir results/alphafold3 --norun_data_pipeline "
                "--run_inference --num_diffusion_samples=1 --num_recycles=1 "
                "--buckets=64"
            )
            job_name = (
                "openzyme-af3-"
                f"{workload.workload_digest.removeprefix('sha256:')[:12]}"
            )
            submit_script = (
                "sbatch --parsable -p 3090 -t 00:30:00 "
                "--gpus=1 --cpus-per-task=8 --mem=64G "
                f"-J {shlex.quote(job_name)} --chdir={shlex.quote(cwd)} "
                f"-o {shlex.quote(cwd + '/slurm-%j.out')} "
                f"-e {shlex.quote(cwd + '/slurm-%j.err')} "
                f"--wrap {shlex.quote(command)}"
            )
            job_id = self._run(submit_script).split(";", 1)[0]
            if re.fullmatch(r"[0-9]+", job_id) is None:
                raise ExternalQualificationError(
                    "qualification_alphafold_job_id_invalid",
                    "AlphaFold Slurm submit returned an invalid job identity",
                )
            poll_script = (
                "for i in $(seq 1 120); do "
                f"state=$(sacct -n -X -j {job_id} -o State -P | head -n 1 | cut -d'|' -f1); "
                "case \"$state\" in "
                "COMPLETED*) printf '%s\\n' \"$state\"; exit 0;; "
                "FAILED*|CANCELLED*|TIMEOUT*|OUT_OF_MEMORY*) "
                "printf '%s\\n' OPENZYME_AF3_SACCT; "
                f"sacct -n -X -j {job_id} "
                "-o JobIDRaw,State,ExitCode,Elapsed,NodeList -P; "
                "printf '%s\\n' OPENZYME_AF3_STDOUT; "
                f"tail -c 32768 {shlex.quote(cwd + '/slurm-' + job_id + '.out')} 2>&1 || true; "
                "printf '%s\\n' OPENZYME_AF3_STDERR; "
                f"tail -c 32768 {shlex.quote(cwd + '/slurm-' + job_id + '.err')} 2>&1 || true; "
                "exit 2;; esac; sleep 15; done; exit 3"
            )
            poll_returncode, poll_stdout, _poll_stderr = (
                self.command_port.run_remote(poll_script)
            )
            if poll_returncode == 3:
                raise ExternalQualificationError(
                    "qualification_alphafold_job_observation_timeout_in_doubt",
                    "AlphaFold Slurm job did not reach terminal state in 30 minutes",
                )
            if poll_returncode != 0:
                raise ExternalQualificationError(
                    "qualification_alphafold_job_failed",
                    "AlphaFold Slurm job failed; protected diagnostics were captured",
                )
            if not poll_stdout.strip().startswith("COMPLETED"):
                raise ExternalQualificationError(
                    "qualification_alphafold_job_terminal_state_invalid",
                    "AlphaFold Slurm terminal state is invalid",
                )
            outputs: list[dict[str, object]] = []
            for output_path in workload.expected_output_paths:
                remote = f"{cwd}/{output_path}"
                observed = self._run(
                    f"test -s {shlex.quote(remote)}; "
                    f"wc -c < {shlex.quote(remote)}; "
                    f"sha256sum {shlex.quote(remote)} | cut -d' ' -f1"
                ).splitlines()
                if len(observed) != 2 or re.fullmatch(
                    r"[0-9a-f]{64}", observed[1]
                ) is None:
                    raise ExternalQualificationError(
                        "qualification_alphafold_expected_output_missing",
                        "AlphaFold terminal output observation is incomplete",
                    )
                outputs.append(
                    {
                        "path": output_path,
                        "size_bytes": int(observed[0]),
                        "content_digest": f"sha256:{observed[1]}",
                    }
                )
            gpu_observation = self._run(
                f"cat {shlex.quote(cwd + '/gpu-identity.txt')}"
            )
            if "3090" not in gpu_observation:
                raise ExternalQualificationError(
                    "qualification_alphafold_gpu_identity_mismatch",
                    "AlphaFold job did not observe one RTX 3090 GPU",
                )
            payload = {
                "workload_digest": workload.workload_digest,
                "partition": self.partition,
                "gpu_observation_digest": canonical_sha256_digest(
                    {"gpu_observation": gpu_observation}
                ),
                "outputs": outputs,
                "route_kind": self.route_kind,
                "inference_only": True,
                "seed": 20260824,
            }
            outcome = ExternalScientificQualificationRouteOutcome(
                workload_digest=workload.workload_digest,
                effect_certainty="terminal_known",
                terminal=True,
                succeeded=True,
                output_digest=canonical_sha256_digest(payload),
                receipt_digest=canonical_sha256_digest(
                    {**payload, "workspace_cleanup_required": True}
                ),
                error_code=None,
                external_effect_performed=True,
                credential_material_accessed=True,
            )
        except ExternalQualificationError as exc:
            outcome = self._failure(workload, exc.error_code)
        except subprocess.TimeoutExpired:
            outcome = self._failure(
                workload,
                "qualification_alphafold_remote_timeout_in_doubt",
                effect_certainty="dispatch_in_doubt",
            )
        except OSError:
            outcome = self._failure(
                workload,
                "qualification_alphafold_transport_in_doubt",
                effect_certainty="dispatch_in_doubt",
            )
        finally:
            try:
                returncode, _stdout, _stderr = self.command_port.run_remote(
                    f"rm -rf -- {shlex.quote(run_root)}"
                )
                if returncode != 0:
                    cleanup_error = "qualification_alphafold_cleanup_failed"
            except subprocess.TimeoutExpired:
                cleanup_error = "qualification_alphafold_cleanup_timeout"
        if cleanup_error is not None:
            return self._failure(
                workload,
                cleanup_error,
                effect_certainty=(
                    "dispatch_in_doubt"
                    if cleanup_error.endswith("_timeout")
                    else "terminal_known"
                ),
            )
        assert outcome is not None
        return outcome

    def reconcile(
        self,
        workload: ExternalScientificQualificationWorkload,
    ) -> ExternalScientificQualificationRouteOutcome:
        return self._failure(
            workload, "qualification_alphafold_reconcile_without_dispatch"
        )

    def _verify_resources(self) -> None:
        script = r"""set -eu
root=/opt/tools_env/alphafold3
database=$(readlink -f "$root/databases")
printf '%s\n' \
  "$(sha256sum /opt/tools/alphafold3 | cut -d' ' -f1)" \
  "$(sha256sum "$root/alphafold3.sif" | cut -d' ' -f1)" \
  "$(sha256sum "$root/models/af3.bin" | cut -d' ' -f1)" \
  "$({ printf 'schema=alphafold3-database-metadata-closure-v1\0root=%s\0' "$database"; find "$database" -type f -printf '%P\0%s\0%T@\0%D\0%i\0' | sort -z; } | sha256sum | cut -d' ' -f1)" \
  "$(sinfo -h -p 3090 -o '%P|%a|%D|%G' | sort | sha256sum | cut -d' ' -f1)"
"""
        lines = self._run(script).splitlines()
        expected = [
            self.wrapper_digest.removeprefix("sha256:"),
            self.image_digest.removeprefix("sha256:"),
            self.model_parameters_digest.removeprefix("sha256:"),
            self.database_closure_digest.removeprefix("sha256:"),
            self.gpu_capability_digest.removeprefix("sha256:"),
        ]
        if lines != expected:
            raise ExternalQualificationError(
                "qualification_alphafold_resource_identity_drift",
                "AlphaFold resource closure changed before dispatch",
            )

    def _ensure_workspace_scope(self) -> None:
        workspace = shlex.quote(self.workspace_root)
        owner_marker = shlex.quote(
            f"{self.workspace_root}/.openzyme-qualification-owner"
        )
        owner_id = shlex.quote(self.workspace_owner_id)
        self._run(
            f"if test -e {workspace}; then test -d {workspace} && "
            f"test -f {owner_marker} && test \"$(cat {owner_marker})\" = {owner_id}; "
            f"else mkdir -p -m 700 {workspace} && printf '%s' {owner_id} > "
            f"{owner_marker} && chmod 600 {owner_marker}; fi"
        )

    def _stage_input(self, remote_path: str, content: bytes) -> None:
        parent = shlex.quote(remote_path.rsplit("/", 1)[0])
        target = shlex.quote(remote_path)
        self._run(f"mkdir -p {parent}; : > {target}")
        encoded = base64.b64encode(content).decode("ascii")
        for offset in range(0, len(encoded), 32_768):
            chunk = shlex.quote(encoded[offset : offset + 32_768])
            self._run(f"printf '%s' {chunk} | base64 -d >> {target}")
        observed = self._run(
            f"wc -c < {target}; sha256sum {target} | cut -d' ' -f1"
        ).splitlines()
        if observed != [str(len(content)), hashlib.sha256(content).hexdigest()]:
            raise ExternalQualificationError(
                "qualification_compute_remote_input_verification_failed",
                "AlphaFold staged input differs from the exact fixed bytes",
            )

    def _run(self, script: str) -> str:
        returncode, stdout, _stderr = self.command_port.run_remote(script)
        if returncode != 0:
            raise ExternalQualificationError(
                "qualification_alphafold_remote_command_failed",
                "AlphaFold Slurm qualification command failed",
            )
        return stdout.strip()

    @staticmethod
    def _failure(
        workload: ExternalScientificQualificationWorkload,
        error_code: str,
        *,
        effect_certainty: str = "terminal_known",
    ) -> ExternalScientificQualificationRouteOutcome:
        return ExternalScientificQualificationRouteOutcome(
            workload_digest=workload.workload_digest,
            effect_certainty=effect_certainty,
            terminal=True,
            succeeded=False,
            output_digest=None,
            receipt_digest=None,
            error_code=error_code,
            external_effect_performed=True,
            credential_material_accessed=True,
        )


@dataclass(slots=True)
class SlurmQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: SlurmQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.hpc.slurm":
            raise ValueError("Slurm bridge requires the selected Adapter binding")
        if (
            self.operation_port.component_id != self.binding.component_id
            or self.operation_port.route_id != self.binding.route_id
            or self.operation_port.subject_digest != self.binding.subject_digest
            or not self.operation_port.qualification_account_only
            or not self.operation_port.same_attempt_reconcile
        ):
            raise ValueError(
                "Slurm qualification port must bind one exact qualification account"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=SLURM_QUALIFICATION_OPERATIONS,
        )

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.dispatch(request)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.reconcile(request)

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None:
        self._bridge.restore_dispatched_attempt(request)


__all__ = [
    "SLURM_QUALIFICATION_OPERATIONS",
    "OpenSshSlurmQualificationOperation",
    "SlurmQualificationRemoteCommandPort",
    "SlurmScientificQualificationInputResolver",
    "SlurmScientificQualificationRoute",
    "SlurmAlphaFoldQualificationRoute",
    "SlurmQualificationState",
    "SlurmQualificationOperationPort",
    "SlurmQualificationProbeBridge",
]
