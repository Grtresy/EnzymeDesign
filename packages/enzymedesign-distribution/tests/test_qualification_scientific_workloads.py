import json

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
        ("enzymedesign.vina.local", "dock", "local", "python"),
        ("enzymedesign.vina.hpc", "dock", "hpc-primary", "vina"),
        ("enzymedesign.fpocket.local", "detect", "local", "fpocket"),
        ("enzymedesign.fpocket.hpc", "detect", "hpc-primary", "fpocket"),
        ("enzymedesign.alphafold.hpc", "predict", "hpc-primary", "python"),
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
        effect_certainty="terminal_known",
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


def test_real_program_fixtures_are_nontrivial_and_wheel_owned() -> None:
    vina = build_selected_driver_scientific_compiler(
        component_id="enzymedesign.vina.local",
        operation="dock",
        route_kind="local",
    ).compile(_request("dock"))
    fpocket = build_selected_driver_scientific_compiler(
        component_id="enzymedesign.fpocket.local",
        operation="detect",
        route_kind="local",
    ).compile(_request("detect"))

    vina_sizes = tuple(item.size_bytes for item in vina.inputs)
    fpocket_sizes = tuple(item.size_bytes for item in fpocket.inputs)
    assert max(vina_sizes) > 100_000
    assert min(vina_sizes) > 100
    assert fpocket_sizes[0] > 200_000


def test_scientific_compilers_expect_the_programs_actual_output_paths() -> None:
    hmmbuild = build_selected_driver_scientific_compiler(
        component_id="enzymedesign.hmmer.local",
        operation="hmmbuild",
        route_kind="local",
    ).compile(_request("hmmbuild"))
    fpocket = build_selected_driver_scientific_compiler(
        component_id="enzymedesign.fpocket.local",
        operation="detect",
        route_kind="local",
    ).compile(_request("detect"))

    assert hmmbuild.expected_output_paths == ("results/hmmer/model.hmm",)
    assert tuple(item.path for item in fpocket.inputs) == ("structure.pdb",)
    assert fpocket.argv == ("fpocket", "-f", "structure.pdb")
    assert fpocket.expected_output_paths == ("structure_out/structure_info.txt",)


def test_alphafold_compiler_freezes_20aa_seeded_inference_contract() -> None:
    workload = build_selected_driver_scientific_compiler(
        component_id="enzymedesign.alphafold.hpc",
        operation="predict",
        route_kind="hpc-primary",
    ).compile(_request("predict"))

    assert workload.argv == (
        "python",
        "run_alphafold.py",
        "--json_path",
        "inputs/job.json",
        "--output_dir",
        "results/alphafold3",
    )
    job = json.loads(
        SCIENTIFIC_QUALIFICATION_INPUTS.resolve(workload.inputs[0].content_digest)
    )
    assert job["modelSeeds"] == [20260824]
    assert job["sequences"][0]["protein"]["sequence"] == "ACDEFGHIKLMNPQRSTVWY"
    assert job["sequences"][0]["protein"]["id"] == "A"
    assert workload.expected_output_paths == (
        "results/alphafold3/openzyme_qualification_20aa/"
        "openzyme_qualification_20aa_model.cif",
        "results/alphafold3/openzyme_qualification_20aa/"
        "openzyme_qualification_20aa_summary_confidences.json",
    )
