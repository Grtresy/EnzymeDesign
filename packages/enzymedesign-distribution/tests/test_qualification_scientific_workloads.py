import pytest

from enzymedesign_distribution import PreprocessScientificQualificationCompiler
from enzymedesign_distribution import SCIENTIFIC_QUALIFICATION_INPUTS
from enzymedesign_distribution import build_selected_driver_scientific_compiler
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationRouteOutcome
from openzyme_contracts import canonical_sha256_digest


DIGEST = "sha256:" + "1" * 64


def _request(operation: str) -> ExternalQualificationProbeRequest:
    return ExternalQualificationProbeRequest.create(
        attempt_id=f"attempt.scientific.{operation}",
        plan_digest=DIGEST,
        unit_digest=canonical_sha256_digest({"operation": operation}),
        operation=operation,
        timeout_seconds=600,
        input_digest=DIGEST,
        expected_result_schema_digest=DIGEST,
        credential_locator_id=None,
    )


@pytest.mark.parametrize(
    ("component_id", "operation", "route_kind", "executable"),
    (
        ("enzymedesign.hmmer.local", "hmmbuild", "local", "hmmbuild"),
        ("enzymedesign.hmmer.hpc", "hmmsearch", "hpc-primary", "hmmsearch"),
        ("enzymedesign.vina.local", "dock", "local", "vina"),
        ("enzymedesign.vina.hpc", "dock", "hpc-primary", "vina"),
        ("enzymedesign.fpocket.local", "detect", "local", "fpocket"),
        ("enzymedesign.fpocket.hpc", "detect", "hpc-primary", "fpocket"),
    ),
)
def test_selected_driver_compiler_builds_exact_formal_workload_and_validates_result(
    component_id: str,
    operation: str,
    route_kind: str,
    executable: str,
) -> None:
    compiler = build_selected_driver_scientific_compiler(
        component_id=component_id,
        operation=operation,
        route_kind=route_kind,
    )

    workload = compiler.compile(_request(operation))

    assert workload.driver_component_id == component_id
    assert workload.route_kind == route_kind
    assert workload.argv[0] == executable
    assert workload.inputs
    for item in workload.inputs:
        assert len(SCIENTIFIC_QUALIFICATION_INPUTS.resolve(item.content_digest)) == (
            item.size_bytes
        )
    outcome = ExternalScientificQualificationRouteOutcome(
        workload_digest=workload.workload_digest,
        terminal=True,
        succeeded=True,
        output_digest=DIGEST,
        receipt_digest=canonical_sha256_digest(
            {"workload_digest": workload.workload_digest}
        ),
        error_code=None,
        external_effect_performed=True,
        credential_material_accessed=route_kind == "hpc-primary",
    )
    compiler.validate_terminal_result(workload, outcome)


@pytest.mark.parametrize(
    ("software", "operation", "executable"),
    (
        ("rdkit", "smiles_to_3d", "python"),
        ("meeko", "prepare_ligand", "mk_prepare_ligand.py"),
        ("openbabel", "convert_format", "obabel"),
        ("openbabel", "prepare_ligand", "obabel"),
        ("openbabel", "prepare_receptor", "obabel"),
    ),
)
def test_preprocess_compiler_builds_bounded_real_software_smoke(
    software: str,
    operation: str,
    executable: str,
) -> None:
    compiler = PreprocessScientificQualificationCompiler(
        operation=operation,
        software=software,
    )

    workload = compiler.compile(_request(operation))

    assert workload.driver_component_id == "enzymedesign.docking.preprocess"
    assert workload.argv[0] == executable
    assert workload.expected_output_paths
    for item in workload.inputs:
        assert SCIENTIFIC_QUALIFICATION_INPUTS.resolve(item.content_digest)
