from __future__ import annotations

from pathlib import Path
import sys

from mcp_hpc_tool_contracts.constants import ADAPTER_IDS
from mcp_hpc_tool_contracts.registry import compile_adapter, list_adapters


def _import_runner_validation() -> tuple[object, object]:
    repo_root = Path(__file__).resolve().parents[3]
    runner_src = repo_root / "apps" / "mcp-hpc-runner" / "src"
    sys.path.insert(0, str(runner_src))
    from mcp_hpc_runner.models import RunSpec  # type: ignore[import-not-found]
    from mcp_hpc_runner.validation import (  # type: ignore[import-not-found]
        validate_runspec,
    )

    return RunSpec, validate_runspec


def _adapter_params(tmp_path: Path) -> dict[str, dict[str, object]]:
    query = tmp_path / "query.fasta"
    query.write_text(">q\nACDEFGHIKLMNPQRSTVWY\n", encoding="utf-8")
    af3_json = tmp_path / "af3.json"
    af3_json.write_text('{"name": "sample"}\n', encoding="utf-8")
    target = tmp_path / "target.pdb"
    target.write_text("ATOM\n", encoding="utf-8")
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text("RECEPTOR\n", encoding="utf-8")
    ligand = tmp_path / "ligand.pdbqt"
    ligand.write_text("LIGAND\n", encoding="utf-8")

    return {
        "hhblits": {"query_fasta": str(query), "db_prefix": "uniclust30"},
        "chai_fold": {"input_fasta": str(query)},
        "alphafold3": {"input_json": str(af3_json)},
        "colabfold": {"input_fasta": str(query)},
        "fpocket": {"structure_path": str(target)},
        "tunnels": {"structure_path": str(target), "mode": "detect"},
        "vina": {
            "receptor_path": str(receptor),
            "ligand_path": str(ligand),
            "center_x": 0,
            "center_y": 0,
            "center_z": 0,
            "size_x": 20,
            "size_y": 20,
            "size_z": 20,
        },
    }


def test_adapter_registry_has_stable_ordering() -> None:
    listed = [entry["id"] for entry in list_adapters()]
    assert tuple(listed) == ADAPTER_IDS


def test_all_adapters_compile_runspec_that_passes_runner_validation(
    tmp_path: Path,
) -> None:
    RunSpec, validate_runspec = _import_runner_validation()
    payloads = _adapter_params(tmp_path)

    for adapter_id in ADAPTER_IDS:
        compiled = compile_adapter(adapter_id, payloads[adapter_id])
        spec = RunSpec.from_dict(compiled.runspec)
        errors = validate_runspec(spec)
        assert errors == [], f"{adapter_id} validation errors: {errors}"
