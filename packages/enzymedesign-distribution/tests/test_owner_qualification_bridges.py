from dataclasses import dataclass

import pytest

from enzymedesign_docking_preprocess import PreprocessQualificationProbeBridge
from enzymedesign_hmmer import HmmerQualificationProbeBridge
from enzymedesign_structure import FpocketQualificationProbeBridge
from enzymedesign_vina import VinaQualificationProbeBridge
from openzyme_hpc_slurm import SlurmQualificationProbeBridge
from openzyme_hpc_ssh import SshQualificationProbeBridge
from openzyme_process_podman import PodmanQualificationProbeBridge
from openzyme_workspace_git_lfs import GitLfsQualificationProbeBridge
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationOperationObservation
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeRequest


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64


@dataclass
class _TerminalPort:
    component_id: str
    route_id: str
    subject_digest: str
    driver_component_id: str
    workload_input_digest: str
    result_schema_digest: str
    formal_compute_only: bool = True
    local_only: bool = True
    hosted_sync_allowed: bool = False
    qualification_isolated: bool = True
    image_digest_pinned: bool = True
    qualification_workspace_only: bool = True
    qualification_account_only: bool = True
    same_attempt_reconcile: bool = True
    calls: int = 0

    def dispatch(self, request):
        self.calls += 1
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty="terminal_known",
            terminal=True,
            succeeded=True,
            output_digest=DIGEST,
            receipt_digest=OTHER_DIGEST,
            error_code=None,
            external_effect_performed=True,
            credential_material_accessed=False,
        )

    def reconcile(self, request):
        raise AssertionError("terminal qualification must not require reconcile")


@pytest.mark.parametrize(
    ("bridge_type", "component_id", "operation", "route_id"),
    [
        pytest.param(
            GitLfsQualificationProbeBridge,
            "openzyme.workspace.git.lfs",
            "clone",
            "openzyme.workspace.git.lfs.clone@1",
            id="git-lfs",
        ),
        pytest.param(
            PodmanQualificationProbeBridge,
            "openzyme.process.podman",
            "container-start",
            "openzyme.process.podman.container-start@1",
            id="podman",
        ),
        pytest.param(
            SshQualificationProbeBridge,
            "openzyme.hpc.ssh",
            "helper-identity",
            "openzyme.hpc.ssh.helper-identity@1",
            id="ssh",
        ),
        pytest.param(
            SlurmQualificationProbeBridge,
            "openzyme.hpc.slurm",
            "submit",
            "openzyme.hpc.slurm.submit@1",
            id="slurm",
        ),
        pytest.param(
            HmmerQualificationProbeBridge,
            "enzymedesign.hmmer.local",
            "hmmbuild",
            "enzymedesign.hmmer.local.hmmbuild@1",
            id="hmmer",
        ),
        pytest.param(
            VinaQualificationProbeBridge,
            "enzymedesign.vina.local",
            "dock",
            "enzymedesign.vina.local.dock@1",
            id="vina",
        ),
        pytest.param(
            FpocketQualificationProbeBridge,
            "enzymedesign.fpocket.local",
            "detect",
            "enzymedesign.fpocket.local.detect@1",
            id="fpocket",
        ),
        pytest.param(
            PreprocessQualificationProbeBridge,
            "enzymedesign.docking.preprocess",
            "smiles_to_3d",
            "enzymedesign.docking.preprocess.rdkit.smiles_to_3d@1",
            id="preprocess",
        ),
    ],
)
def test_adapter_owned_bridge_routes_one_exact_operation_without_fallback(
    bridge_type,
    component_id: str,
    operation: str,
    route_id: str,
) -> None:
    binding = ExternalQualificationBridgeBinding.create(
        component_id=component_id,
        operation=operation,
        route_id=route_id,
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
    )
    request = ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.{component_id}.{operation}",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=60,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id=None,
    )
    port = _TerminalPort(
        component_id=component_id,
        route_id=route_id,
        subject_digest=binding.subject_digest,
        driver_component_id=component_id,
        workload_input_digest=binding.input_digest,
        result_schema_digest=binding.expected_result_schema_digest,
    )
    bridge = bridge_type(binding=binding, operation_port=port)

    outcome = bridge.dispatch(request)

    assert outcome.disposition is ExternalQualificationProbeDisposition.SUCCEEDED
    assert outcome.fallback_performed is False
    assert port.calls == 1


def test_scientific_bridge_rejects_raw_non_compute_operation_port() -> None:
    binding = ExternalQualificationBridgeBinding.create(
        component_id="enzymedesign.hmmer.local",
        operation="hmmbuild",
        route_id="enzymedesign.hmmer.local.hmmbuild@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
    )
    port = _TerminalPort(
        component_id=binding.component_id,
        route_id=binding.route_id,
        subject_digest=binding.subject_digest,
        driver_component_id=binding.component_id,
        workload_input_digest=binding.input_digest,
        result_schema_digest=binding.expected_result_schema_digest,
        formal_compute_only=False,
    )

    with pytest.raises(ValueError, match="formal Compute"):
        HmmerQualificationProbeBridge(binding=binding, operation_port=port)


def test_git_bridge_rejects_any_hosted_sync_capability() -> None:
    binding = ExternalQualificationBridgeBinding.create(
        component_id="openzyme.workspace.git.lfs",
        operation="clone",
        route_id="openzyme.workspace.git.lfs.clone@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
    )
    port = _TerminalPort(
        component_id=binding.component_id,
        route_id=binding.route_id,
        subject_digest=binding.subject_digest,
        driver_component_id=binding.component_id,
        workload_input_digest=binding.input_digest,
        result_schema_digest=binding.expected_result_schema_digest,
        hosted_sync_allowed=True,
    )

    with pytest.raises(ValueError, match="local-only"):
        GitLfsQualificationProbeBridge(binding=binding, operation_port=port)
