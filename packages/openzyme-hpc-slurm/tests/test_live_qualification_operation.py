from dataclasses import dataclass
from dataclasses import field
import subprocess

from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_hpc_slurm import OpenSshSlurmQualificationOperation
from openzyme_hpc_slurm import SlurmQualificationState


DIGEST = "sha256:" + "1" * 64


@dataclass
class _Remote:
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("sbatch --parsable") and "openzyme-q-terminal" in script:
            return 0, "101\n", ""
        if script.startswith("for i in $(seq 1 30)"):
            return 0, "COMPLETED\n", ""
        if script.startswith("job=$(sbatch"):
            return 0, "102\n", ""
        if script.startswith("squeue -h -n"):
            return 0, "103\n", ""
        return 0, "", ""


def _request(operation: str) -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.slurm.{operation}",
        plan_digest=DIGEST,
        unit_digest=DIGEST,
        operation=operation,
        timeout_seconds=120,
        input_digest=DIGEST,
        expected_result_schema_digest=DIGEST,
        credential_locator_id="credential.hpc.diannan.qualification",
    )


def test_slurm_qualification_submit_observe_cancel_and_restore_reconcile() -> None:
    remote = _Remote()
    state = SlurmQualificationState(
        workspace=".local/state/openzyme-qualification/batch-1-test",
        partition="3090",
        command_port=remote,
    )
    operation = OpenSshSlurmQualificationOperation(
        component_id="openzyme.hpc.slurm",
        route_id="openzyme.hpc.slurm.submit@1",
        subject_digest=DIGEST,
        state=state,
    )
    for operation_id in ("submit", "observe", "cancel"):
        assert operation.dispatch(_request(operation_id)).succeeded is True

    request = _request("reconcile")
    assert operation.dispatch(request).terminal is False
    restored_state = SlurmQualificationState(
        workspace=state.workspace,
        partition="3090",
        command_port=remote,
    )
    restored = OpenSshSlurmQualificationOperation(
        component_id="openzyme.hpc.slurm",
        route_id="openzyme.hpc.slurm.reconcile@1",
        subject_digest=DIGEST,
        state=restored_state,
    )
    restored.restore_dispatched_attempt(request)

    assert restored.reconcile(request).succeeded is True
    assert state.cleanup()["command_accepted"] is True
    assert all("-p 3090" in script for script in remote.scripts if "sbatch" in script)


@dataclass
class _TimeoutThenObserveRemote:
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("job=$(sbatch"):
            raise subprocess.TimeoutExpired(script, 120)
        if script.startswith("timeout 30s sacct"):
            return 0, "204|CANCELLED by 1000\n", ""
        return 0, "", ""


def test_slurm_cancel_timeout_reconciles_exact_attempt_without_redispatch() -> None:
    remote = _TimeoutThenObserveRemote()
    state = SlurmQualificationState(
        workspace=".local/state/openzyme-qualification/batch-1-timeout",
        partition="3090",
        command_port=remote,
    )
    operation = OpenSshSlurmQualificationOperation(
        component_id="openzyme.hpc.slurm",
        route_id="openzyme.hpc.slurm.cancel@1",
        subject_digest=DIGEST,
        state=state,
    )
    request = _request("cancel")

    dispatched = operation.dispatch(request)
    assert dispatched.terminal is False
    assert dispatched.effect_certainty == "dispatch_in_doubt"
    assert operation.reconcile(request).succeeded is True
    assert sum(script.startswith("job=$(sbatch") for script in remote.scripts) == 1
    assert state.cancel_job_name is not None
