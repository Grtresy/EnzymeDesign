from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ToolInputSlot:
    slot_id: str
    remote_path: str
    required: bool = True
    accepted_formats: tuple[str, ...] = ()
    preprocess_operation: str | None = None


@dataclass(frozen=True, slots=True)
class ToolOutputContract:
    path: str
    kind: str = "file"
    required: bool = True
    non_empty: bool = False


@dataclass(frozen=True, slots=True)
class ToolExecutionContract:
    tool_id: str
    adapter_id: str
    command_template_id: str
    resources: dict[str, Any]
    input_slots: tuple[ToolInputSlot, ...]
    expected_outputs: tuple[ToolOutputContract, ...]
    success_checks: tuple[dict[str, str], ...]
    failure_signatures: tuple[dict[str, str], ...]
    parser_hints: dict[str, Any]
    preprocess_requirements: dict[str, Any]


_CONTRACTS: dict[str, ToolExecutionContract] = {
    "fpocket": ToolExecutionContract(
        tool_id="fpocket",
        adapter_id="fpocket",
        command_template_id="fpocket_sif_v1",
        resources={"cpus": 4, "mem_mb": 4096, "gpus": 0, "time_minutes": 30, "partition": None},
        input_slots=(
            ToolInputSlot(slot_id="structure", remote_path="target.pdb", accepted_formats=("pdb",)),
        ),
        expected_outputs=(
            ToolOutputContract(path="target_out", kind="dir", required=True, non_empty=True),
        ),
        success_checks=(
            {"check_type": "exists", "path": "target_out"},
            {"check_type": "non_empty", "path": "target_out"},
        ),
        failure_signatures=(
            {"pattern": "SIF image not found", "error_code": "SIF_MISSING"},
            {"pattern": "apptainer: command not found", "error_code": "APPTAINER_MISSING"},
            {"pattern": "No such file", "error_code": "INPUT_OR_ENTRYPOINT_MISSING"},
        ),
        parser_hints={"parser": "fpocket", "primary_output": "target_out"},
        preprocess_requirements={},
    ),
    "vina": ToolExecutionContract(
        tool_id="vina",
        adapter_id="vina",
        command_template_id="vina_sif_v1",
        resources={"cpus": 8, "mem_mb": 8192, "gpus": 0, "time_minutes": 60, "partition": None},
        input_slots=(
            ToolInputSlot(
                slot_id="receptor",
                remote_path="receptor.pdbqt",
                accepted_formats=("pdbqt",),
                preprocess_operation="prepare_receptor",
            ),
            ToolInputSlot(
                slot_id="ligand",
                remote_path="ligand.pdbqt",
                accepted_formats=("pdbqt",),
                preprocess_operation="prepare_ligand",
            ),
        ),
        expected_outputs=(
            ToolOutputContract(path="vina_out.pdbqt", kind="file", required=True, non_empty=True),
            ToolOutputContract(path="vina.log", kind="file", required=True, non_empty=True),
        ),
        success_checks=(
            {"check_type": "exists", "path": "vina_out.pdbqt"},
            {"check_type": "exists", "path": "vina.log"},
            {"check_type": "non_empty", "path": "vina.log"},
        ),
        failure_signatures=(
            {"pattern": "SIF image not found", "error_code": "SIF_MISSING"},
            {"pattern": "apptainer: command not found", "error_code": "APPTAINER_MISSING"},
            {"pattern": "Parse error", "error_code": "INPUT_PARSE_ERROR"},
        ),
        parser_hints={"parser": "vina", "pose_output": "vina_out.pdbqt", "log_output": "vina.log"},
        preprocess_requirements={
            "receptor": {"target_format": "pdbqt", "operations": ("prepare_receptor",)},
            "ligand": {"target_format": "pdbqt", "operations": ("smiles_to_3d", "prepare_ligand")},
        },
    ),
    "bio_tools.cdhit": ToolExecutionContract(
        tool_id="bio_tools.cdhit",
        adapter_id="bio_tools.cdhit",
        command_template_id="bio_tools_cdhit_sif_v2",
        resources={"cpus": 2, "mem_mb": 4096, "gpus": 0, "time_minutes": 30, "partition": None},
        input_slots=(
            ToolInputSlot(slot_id="input_fasta", remote_path="input.fasta", accepted_formats=("fasta", "fa", "faa")),
        ),
        expected_outputs=(
            ToolOutputContract(path="bio_tools/cdhit/clustered.fasta", kind="file", required=True, non_empty=True),
            ToolOutputContract(path="bio_tools/cdhit/clusters.csv", kind="file", required=True, non_empty=True),
        ),
        success_checks=(
            {"check_type": "exists", "path": "bio_tools/cdhit/clustered.fasta"},
            {"check_type": "exists", "path": "bio_tools/cdhit/clusters.csv"},
            {"check_type": "non_empty", "path": "bio_tools/cdhit/clustered.fasta"},
            {"check_type": "non_empty", "path": "bio_tools/cdhit/clusters.csv"},
        ),
        failure_signatures=(
            {"pattern": "SIF image not found", "error_code": "SIF_MISSING"},
            {"pattern": "apptainer: command not found", "error_code": "APPTAINER_MISSING"},
            {"pattern": "Fatal|No such file", "error_code": "INPUT_OR_ENTRYPOINT_MISSING"},
        ),
        parser_hints={
            "parser": "bio_tools_cdhit",
            "primary_output": "bio_tools/cdhit/clusters.csv",
            "representative_fasta": "bio_tools/cdhit/clustered.fasta",
            "membership_schema_id": "cdhit_cluster_membership@1",
            "membership_columns": (
                "cluster_id",
                "member_id",
                "representative_id",
                "is_representative",
                "identity_to_representative",
                "member_length",
            ),
            "row_semantics": "one_member_per_row",
            "identity_scale": "fraction_0_to_1",
            "normalized_from": "bio_tools/cdhit/clustered.fasta.clstr",
        },
        preprocess_requirements={},
    ),
    "bio_tools.mafft": ToolExecutionContract(
        tool_id="bio_tools.mafft",
        adapter_id="bio_tools.mafft",
        command_template_id="bio_tools_mafft_sif_v1",
        resources={"cpus": 4, "mem_mb": 8192, "gpus": 0, "time_minutes": 60, "partition": None},
        input_slots=(
            ToolInputSlot(slot_id="input_fasta", remote_path="input.fasta", accepted_formats=("fasta", "fa", "faa")),
        ),
        expected_outputs=(
            ToolOutputContract(path="bio_tools/mafft/alignment.fasta", kind="file", required=True, non_empty=True),
        ),
        success_checks=(
            {"check_type": "exists", "path": "bio_tools/mafft/alignment.fasta"},
            {"check_type": "non_empty", "path": "bio_tools/mafft/alignment.fasta"},
        ),
        failure_signatures=(
            {"pattern": "SIF image not found", "error_code": "SIF_MISSING"},
            {"pattern": "apptainer: command not found", "error_code": "APPTAINER_MISSING"},
            {"pattern": "cannot open|No such file", "error_code": "INPUT_OR_ENTRYPOINT_MISSING"},
        ),
        parser_hints={"parser": "bio_tools_fasta", "primary_output": "bio_tools/mafft/alignment.fasta"},
        preprocess_requirements={},
    ),
    "bio_tools.hmmbuild": ToolExecutionContract(
        tool_id="bio_tools.hmmbuild",
        adapter_id="bio_tools.hmmbuild",
        command_template_id="bio_tools_hmmbuild_sif_v1",
        resources={"cpus": 2, "mem_mb": 4096, "gpus": 0, "time_minutes": 30, "partition": None},
        input_slots=(
            ToolInputSlot(slot_id="alignment", remote_path="alignment.fasta", accepted_formats=("fasta", "fa", "afa", "sto")),
        ),
        expected_outputs=(
            ToolOutputContract(path="bio_tools/hmmbuild/model.hmm", kind="file", required=True, non_empty=True),
        ),
        success_checks=(
            {"check_type": "exists", "path": "bio_tools/hmmbuild/model.hmm"},
            {"check_type": "non_empty", "path": "bio_tools/hmmbuild/model.hmm"},
        ),
        failure_signatures=(
            {"pattern": "SIF image not found", "error_code": "SIF_MISSING"},
            {"pattern": "apptainer: command not found", "error_code": "APPTAINER_MISSING"},
            {"pattern": "No such file|failed to open", "error_code": "INPUT_OR_ENTRYPOINT_MISSING"},
        ),
        parser_hints={"parser": "bio_tools_hmm", "primary_output": "bio_tools/hmmbuild/model.hmm"},
        preprocess_requirements={},
    ),
    "bio_tools.hmmalign": ToolExecutionContract(
        tool_id="bio_tools.hmmalign",
        adapter_id="bio_tools.hmmalign",
        command_template_id="bio_tools_hmmalign_sif_v1",
        resources={"cpus": 2, "mem_mb": 4096, "gpus": 0, "time_minutes": 30, "partition": None},
        input_slots=(
            ToolInputSlot(slot_id="hmm", remote_path="model.hmm", accepted_formats=("hmm",)),
            ToolInputSlot(slot_id="fasta", remote_path="input.fasta", accepted_formats=("fasta", "fa", "faa")),
        ),
        expected_outputs=(
            ToolOutputContract(path="bio_tools/hmmalign/aligned.fasta", kind="file", required=True, non_empty=True),
        ),
        success_checks=(
            {"check_type": "exists", "path": "bio_tools/hmmalign/aligned.fasta"},
            {"check_type": "non_empty", "path": "bio_tools/hmmalign/aligned.fasta"},
        ),
        failure_signatures=(
            {"pattern": "SIF image not found", "error_code": "SIF_MISSING"},
            {"pattern": "apptainer: command not found", "error_code": "APPTAINER_MISSING"},
            {"pattern": "No such file|failed to open", "error_code": "INPUT_OR_ENTRYPOINT_MISSING"},
        ),
        parser_hints={"parser": "bio_tools_fasta", "primary_output": "bio_tools/hmmalign/aligned.fasta"},
        preprocess_requirements={},
    ),
}


def get_hpc_tool_contract(tool_id: str) -> ToolExecutionContract:
    try:
        return _CONTRACTS[tool_id]
    except KeyError as exc:
        raise ValueError(f"No execution contract registered for {tool_id}.") from exc


__all__ = [
    "ToolExecutionContract",
    "ToolInputSlot",
    "ToolOutputContract",
    "get_hpc_tool_contract",
]
