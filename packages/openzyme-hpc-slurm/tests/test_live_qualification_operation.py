from dataclasses import dataclass
from dataclasses import field
import hashlib
import subprocess

from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationInput
from openzyme_contracts import ExternalScientificQualificationWorkload
from openzyme_hpc_slurm import OpenSshSlurmQualificationOperation
from openzyme_hpc_slurm import SlurmAlphaFoldQualificationRoute
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
        if script.startswith("timeout 30s sacct"):
            return 0, "103|COMPLETED\n", ""
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


@dataclass
class _SubmitTimeoutThenObserveRemote:
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("sbatch --parsable"):
            raise subprocess.TimeoutExpired(script, 120)
        if script.startswith("timeout 30s sacct"):
            return 0, "501|COMPLETED\n", ""
        return 0, "", ""


def test_slurm_submit_timeout_reconciles_attempt_name_without_redispatch() -> None:
    remote = _SubmitTimeoutThenObserveRemote()
    state = SlurmQualificationState(
        workspace=".local/state/openzyme-qualification/batch-1-submit-timeout",
        partition="3090",
        command_port=remote,
    )
    operation = OpenSshSlurmQualificationOperation(
        component_id="openzyme.hpc.slurm",
        route_id="openzyme.hpc.slurm.submit@1",
        subject_digest=DIGEST,
        state=state,
    )
    request = _request("submit")

    dispatched = operation.dispatch(request)
    assert dispatched.terminal is False
    assert dispatched.effect_certainty == "dispatch_in_doubt"
    reconciled = operation.reconcile(request)

    assert reconciled.succeeded is True
    assert state.submitted_job_id == "501"
    assert state.submit_job_name is not None
    assert state.submit_job_name.startswith("openzyme-q-terminal-")
    assert sum(script.startswith("sbatch --parsable") for script in remote.scripts) == 1

    restored_state = SlurmQualificationState(
        workspace=state.workspace,
        partition="3090",
        command_port=remote,
    )
    restored = OpenSshSlurmQualificationOperation(
        component_id="openzyme.hpc.slurm",
        route_id="openzyme.hpc.slurm.submit@1",
        subject_digest=DIGEST,
        state=restored_state,
    )
    restored.restore_dispatched_attempt(request)
    assert restored_state.submit_job_name == state.submit_job_name
    assert restored.reconcile(request).succeeded is True
    assert sum(script.startswith("sbatch --parsable") for script in remote.scripts) == 1


@dataclass
class _ResponseLossTimeoutThenObserveRemote:
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("sbatch --parsable"):
            raise subprocess.TimeoutExpired(script, 120)
        if script.startswith("timeout 30s sacct"):
            return 0, "601|COMPLETED\n", ""
        return 0, "", ""


def test_slurm_response_loss_timeout_reconciles_attempt_name_without_redispatch() -> None:
    remote = _ResponseLossTimeoutThenObserveRemote()
    state = SlurmQualificationState(
        workspace=".local/state/openzyme-qualification/batch-1-response-loss",
        partition="3090",
        command_port=remote,
    )
    operation = OpenSshSlurmQualificationOperation(
        component_id="openzyme.hpc.slurm",
        route_id="openzyme.hpc.slurm.reconcile@1",
        subject_digest=DIGEST,
        state=state,
    )
    request = _request("reconcile")

    dispatched = operation.dispatch(request)
    assert dispatched.terminal is False
    assert dispatched.effect_certainty == "dispatch_in_doubt"
    assert operation.reconcile(request).succeeded is True
    assert state.reconcile_job_name is not None
    assert state.reconcile_job_name.startswith("openzyme-q-")
    assert sum(script.startswith("sbatch --parsable") for script in remote.scripts) == 1

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
    assert restored_state.reconcile_job_name == state.reconcile_job_name
    assert restored.reconcile(request).succeeded is True
    assert sum(script.startswith("sbatch --parsable") for script in remote.scripts) == 1
    assert state.cleanup()["command_accepted"] is True
    assert state.reconcile_job_name in remote.scripts[-1]


@dataclass
class _ScientificCleanupTimeoutRemote:
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("rm -rf --"):
            raise subprocess.TimeoutExpired(script, 120)
        return 0, "0" * 64 + "\n", ""


@dataclass
class _EmptyInputResolver:
    def resolve(self, content_digest: str) -> bytes:
        raise AssertionError(content_digest)


def test_scientific_cleanup_timeout_is_one_terminal_route_failure() -> None:
    from openzyme_contracts import ExternalScientificQualificationWorkload
    from openzyme_hpc_slurm import SlurmScientificQualificationRoute

    remote = _ScientificCleanupTimeoutRemote()
    route = SlurmScientificQualificationRoute(
        workspace_root=".local/state/openzyme-qualification/science-timeout",
        workspace_owner_id="science-timeout",
        partition="3090",
        command_port=remote,
        input_resolver=_EmptyInputResolver(),
        software_image_path="/home/grtresy/images/hmmer.sif",
        software_image_digest="sha256:" + "0" * 64,
    )
    workload = ExternalScientificQualificationWorkload.create(
        workload_id="workload.cleanup-timeout",
        driver_component_id="enzymedesign.hmmer.hpc",
        operation="hmmbuild",
        route_kind="hpc-primary",
        argv=("hmmbuild", "output.hmm", "input.fasta"),
        cwd="analysis/hmmer",
        inputs=(),
        expected_output_paths=("output.hmm",),
        compiled_workload_digest=DIGEST,
    )

    outcome = route.dispatch(workload)

    assert outcome.succeeded is False
    assert outcome.error_code == "qualification_compute_remote_cleanup_timeout"
    assert outcome.effect_certainty == "dispatch_in_doubt"
    assert any(".openzyme-qualification-owner" in script for script in remote.scripts)


@dataclass
class _ScientificInputRecordingRemote:
    content: bytes
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("wc -c <"):
            digest = hashlib.sha256(self.content).hexdigest()
            return 0, f"{len(self.content)}\n{digest}\n", ""
        return 0, "", ""


def test_scientific_input_staging_chunks_large_inputs_below_argv_limit() -> None:
    from openzyme_hpc_slurm import SlurmScientificQualificationRoute

    content = b"A" * 216_160
    remote = _ScientificInputRecordingRemote(content)
    route = SlurmScientificQualificationRoute(
        workspace_root=".local/state/openzyme-qualification/science-chunked",
        workspace_owner_id="science-chunked",
        partition="3090",
        command_port=remote,
        input_resolver=_EmptyInputResolver(),
        software_image_path="/home/grtresy/images/vina.sif",
        software_image_digest="sha256:" + "0" * 64,
    )

    route._stage_input(
        ".local/state/openzyme-qualification/science-chunked/input.pdbqt",
        content,
    )

    chunk_scripts = [script for script in remote.scripts if "base64 -d >>" in script]
    assert len(chunk_scripts) > 1
    assert max(len(script) for script in chunk_scripts) < 40_000


@dataclass
class _AlphaFoldResolver:
    content: bytes

    def resolve(self, content_digest: str) -> bytes:
        assert content_digest == DIGEST
        return self.content


@dataclass
class _AlphaFoldRemote:
    input_content: bytes
    resource_digest: str
    drift_resources: bool = False
    fail_job: bool = False
    scripts: list[str] = field(default_factory=list)

    def run_remote(self, script: str):
        self.scripts.append(script)
        if script.startswith("set -eu"):
            observed = "f" * 64 if self.drift_resources else self.resource_digest
            return 0, "\n".join((observed,) * 5) + "\n", ""
        if script.startswith("wc -c <") and "inputs/job.json" in script:
            return (
                0,
                f"{len(self.input_content)}\n{hashlib.sha256(self.input_content).hexdigest()}\n",
                "",
            )
        if script.startswith("test -s"):
            return 0, f"128\n{'a' * 64}\n", ""
        if script.startswith("cat ") and "gpu-identity.txt" in script:
            return 0, "NVIDIA GeForce RTX 3090, GPU-test, 550.54, 8.6\n", ""
        if script.startswith("sbatch --parsable"):
            return 0, "9001\n", ""
        if script.startswith("for i in $(seq 1 120)"):
            if self.fail_job:
                return (
                    2,
                    "OPENZYME_AF3_SACCT\n"
                    "9001|FAILED|1:0|00:00:10|node-test\n"
                    "OPENZYME_AF3_STDOUT\n"
                    "OPENZYME_AF3_STDERR\ninvalid input\n",
                    "",
                )
            return 0, "COMPLETED\n", ""
        return 0, "", ""


def _alphafold_workload(content: bytes) -> ExternalScientificQualificationWorkload:
    return ExternalScientificQualificationWorkload.create(
        workload_id="workload.alphafold.batch-2",
        driver_component_id="enzymedesign.alphafold.hpc",
        operation="predict",
        route_kind="hpc-primary",
        argv=(
            "python",
            "run_alphafold.py",
            "--json_path",
            "inputs/job.json",
            "--output_dir",
            "results/alphafold3",
        ),
        cwd="analysis/alphafold3",
        inputs=(
            ExternalScientificQualificationInput(
                path="inputs/job.json",
                content_digest=DIGEST,
                size_bytes=len(content),
            ),
        ),
        expected_output_paths=(
            "results/alphafold3/openzyme_qualification_20aa/"
            "openzyme_qualification_20aa_model.cif",
            "results/alphafold3/openzyme_qualification_20aa/"
            "openzyme_qualification_20aa_summary_confidences.json",
        ),
        compiled_workload_digest=DIGEST,
    )


def _alphafold_route(
    remote: _AlphaFoldRemote,
    content: bytes,
) -> SlurmAlphaFoldQualificationRoute:
    resource_digest = "sha256:" + remote.resource_digest
    return SlurmAlphaFoldQualificationRoute(
        workspace_root=".local/state/openzyme-qualification/alphafold-test",
        workspace_owner_id="alphafold-test",
        command_port=remote,
        input_resolver=_AlphaFoldResolver(content),
        wrapper_digest=resource_digest,
        image_digest=resource_digest,
        model_parameters_digest=resource_digest,
        database_closure_digest=resource_digest,
        gpu_capability_digest=resource_digest,
    )


def test_alphafold_route_runs_fixed_single_gpu_inference_and_cleans_workspace() -> None:
    content = b'{"modelSeeds":[20260824]}\n'
    remote = _AlphaFoldRemote(input_content=content, resource_digest="0" * 64)
    route = _alphafold_route(remote, content)

    outcome = route.dispatch(_alphafold_workload(content))

    assert outcome.succeeded is True
    submit = next(
        script for script in remote.scripts if script.startswith("sbatch --parsable")
    )
    assert "--wait" not in submit
    assert "-p 3090 -t 00:30:00" in submit
    assert "--gpus=1" in submit
    assert "--norun_data_pipeline" in submit
    assert "--run_inference" in submit
    assert "--num_diffusion_samples=1" in submit
    assert "--num_recycles=1" in submit
    assert remote.scripts[-1].startswith("rm -rf --")
    assert route.cleanup_observation() == {
        "scheduler_cleanup_attempted": True,
        "command_accepted": True,
        "workspace_removed": True,
    }


def test_alphafold_route_rejects_resource_drift_before_dispatch() -> None:
    content = b'{"modelSeeds":[20260824]}\n'
    remote = _AlphaFoldRemote(
        input_content=content,
        resource_digest="0" * 64,
        drift_resources=True,
    )
    route = _alphafold_route(remote, content)

    outcome = route.dispatch(_alphafold_workload(content))

    assert outcome.succeeded is False
    assert outcome.error_code == "qualification_alphafold_resource_identity_drift"
    assert not any(script.startswith("sbatch --parsable") for script in remote.scripts)
    assert remote.scripts[-1].startswith("rm -rf --")
    assert route.cleanup_observation()["command_accepted"] is True


def test_alphafold_route_captures_bounded_job_diagnostics_before_cleanup() -> None:
    content = b'{"modelSeeds":[20260824]}\n'
    remote = _AlphaFoldRemote(
        input_content=content,
        resource_digest="0" * 64,
        fail_job=True,
    )
    route = _alphafold_route(remote, content)

    outcome = route.dispatch(_alphafold_workload(content))

    assert outcome.succeeded is False
    assert outcome.error_code == "qualification_alphafold_job_failed"
    diagnostic_index = next(
        index
        for index, script in enumerate(remote.scripts)
        if "OPENZYME_AF3_SACCT" in script
    )
    cleanup_index = next(
        index
        for index, script in enumerate(remote.scripts)
        if script.startswith("rm -rf --")
    )
    assert diagnostic_index < cleanup_index
    diagnostic_script = remote.scripts[diagnostic_index]
    assert "tail -c 32768" in diagnostic_script
    assert "sacct -n -X -j 9001" in diagnostic_script
