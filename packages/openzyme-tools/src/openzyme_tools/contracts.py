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
