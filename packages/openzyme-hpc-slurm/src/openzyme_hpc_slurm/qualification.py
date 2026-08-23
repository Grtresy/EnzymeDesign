from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import base64
import re
import shlex
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
    reconcile_job_name: str | None = None

    def __post_init__(self) -> None:
        if (
            not _safe_scoped_remote_path(self.workspace)
            or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,31}", self.partition) is None
        ):
            raise ValueError("Slurm qualification scope is invalid")

    def cleanup(self) -> dict[str, object]:
        returncode, _stdout, _stderr = self.command_port.run_remote(
            f"if test -f {self.workspace}/job-id; then scancel $(cat {self.workspace}/job-id) >/dev/null 2>&1 || true; fi; "
            f"if test -f {self.workspace}/cancel-job-id; then scancel $(cat {self.workspace}/cancel-job-id) >/dev/null 2>&1 || true; fi"
        )
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
            self._execute(request.operation)
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
        if request.operation != "reconcile" or self.state.reconcile_job_name is None:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "Slurm reconcile requires the exact response-loss submit attempt",
            )
        output = self._run(
            f"squeue -h -n {self.state.reconcile_job_name} -o '%i' | head -n 2"
        )
        job_ids = tuple(line for line in output.splitlines() if line.strip())
        succeeded = len(job_ids) == 1
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
        if request.operation != "reconcile":
            raise ExternalQualificationError(
                "qualification_probe_restore_not_reconcilable",
                "only the Slurm response-loss operation can be restored",
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

    def _execute(self, operation: str) -> None:
        workspace = self.state.workspace
        if operation == "submit":
            output = self._run(
                f"sbatch --parsable -p {self.state.partition} -t 00:01:00 -c 1 "
                f"-J openzyme-q-terminal -o {workspace}/terminal-%j.out "
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
            output = self._run(
                f"job=$(sbatch --parsable -p {self.state.partition} -t 00:02:00 -c 1 -J openzyme-q-cancel -o {workspace}/cancel-%j.out --wrap 'sleep 90'); job=${{job%%;*}}; printf '%s' \"$job\" > {workspace}/cancel-job-id; scancel \"$job\"; printf '%s' \"$job\""
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

    def _dispatch_response_loss(self, request: ExternalQualificationProbeRequest) -> None:
        suffix = canonical_sha256_digest(
            {"attempt_id": request.attempt_id}
        ).removeprefix("sha256:")[:16]
        name = f"openzyme-q-{suffix}"
        self._run(
            f"sbatch --parsable -p {self.state.partition} -t 00:02:00 -c 1 -J {name} -o {self.state.workspace}/reconcile-%j.out --wrap 'sleep 60' >/dev/null"
        )
        self.state.reconcile_job_name = name

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
    partition: str
    command_port: SlurmQualificationRemoteCommandPort = field(repr=False)
    input_resolver: SlurmScientificQualificationInputResolver = field(repr=False)
    software_image_path: str
    software_image_digest: str
    route_kind: str = "hpc-primary"

    def __post_init__(self) -> None:
        if (
            not _safe_scoped_remote_path(self.workspace_root)
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
        try:
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
                encoded = base64.b64encode(content).decode("ascii")
                self._run(
                    f"mkdir -p {shlex.quote(remote_path.rsplit('/', 1)[0])}; "
                    f"printf '%s' {shlex.quote(encoded)} | base64 -d > {shlex.quote(remote_path)}"
                )
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
            return ExternalScientificQualificationRouteOutcome(
                workload_digest=workload.workload_digest,
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
            return self._failure(workload, exc.error_code)
        finally:
            returncode, _stdout, _stderr = self.command_port.run_remote(
                f"rm -rf -- {shlex.quote(run_root)}"
            )
            if returncode != 0:
                raise ExternalQualificationError(
                    "qualification_compute_remote_cleanup_failed",
                    "scientific Slurm qualification workspace cleanup failed",
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
    ) -> ExternalScientificQualificationRouteOutcome:
        return ExternalScientificQualificationRouteOutcome(
            workload_digest=workload.workload_digest,
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
    "SlurmQualificationState",
    "SlurmQualificationOperationPort",
    "SlurmQualificationProbeBridge",
]
