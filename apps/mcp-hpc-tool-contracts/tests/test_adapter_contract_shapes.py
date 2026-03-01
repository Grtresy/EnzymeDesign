from __future__ import annotations

from pathlib import Path

import pytest

from mcp_hpc_tool_contracts.constants import HHBLITS_SPACK_FALLBACK
from mcp_hpc_tool_contracts.invocation import InvocationSelection
from mcp_hpc_tool_contracts.registry import compile_adapter


def _make_inputs(tmp_path: Path) -> dict[str, str]:
    query = tmp_path / "query.fasta"
    query.write_text(">q\nACDE\n", encoding="utf-8")
    af3 = tmp_path / "input.json"
    af3.write_text("{}", encoding="utf-8")
    pdb = tmp_path / "target.pdb"
    pdb.write_text("ATOM\n", encoding="utf-8")
    receptor = tmp_path / "receptor.pdbqt"
    receptor.write_text("R\n", encoding="utf-8")
    ligand = tmp_path / "ligand.pdbqt"
    ligand.write_text("L\n", encoding="utf-8")
    return {
        "query": str(query),
        "af3": str(af3),
        "pdb": str(pdb),
        "receptor": str(receptor),
        "ligand": str(ligand),
    }


def test_fold_adapters_require_non_empty_output_dirs(tmp_path: Path) -> None:
    files = _make_inputs(tmp_path)
    for adapter_id, payload in {
        "chai_fold": {"input_fasta": files["query"]},
        "alphafold3": {"input_json": files["af3"]},
        "colabfold": {"input_fasta": files["query"]},
    }.items():
        compiled = compile_adapter(adapter_id, payload)
        first_output = compiled.runspec["expected_outputs"][0]
        assert first_output["kind"] == "dir"
        assert first_output["non_empty"] is True
        assert compiled.runspec["success_checks"][0]["check_type"] == "non_empty"


def test_hhblits_contract_declares_non_empty_msa_outputs(tmp_path: Path) -> None:
    files = _make_inputs(tmp_path)
    compiled = compile_adapter("hhblits", {"query_fasta": files["query"]})
    paths = [entry["path"] for entry in compiled.runspec["expected_outputs"]]
    assert any(path.endswith(".a3m") for path in paths)
    assert any(path.endswith(".hhr") for path in paths)
    assert all(entry["non_empty"] for entry in compiled.runspec["expected_outputs"])


def test_hhblits_spack_fallback_uses_hhblits_outputs(
    tmp_path: Path, monkeypatch
) -> None:
    files = _make_inputs(tmp_path)

    def _force_spack(**kwargs):
        fallback = kwargs["fallback"]
        return InvocationSelection(selected=fallback, fallback=[])

    monkeypatch.setattr(
        "mcp_hpc_tool_contracts.registry.select_invocation", _force_spack
    )
    compiled = compile_adapter("hhblits", {"query_fasta": files["query"]})

    assert compiled.invocation_mode == "spack"
    command = compiled.runspec["command"]
    assert command[0] == HHBLITS_SPACK_FALLBACK
    assert "--tblout" not in command
    assert "-oa3m" in command
    assert "-o" in command


def test_hhblits_rejects_non_hhblits_spack_fallback(
    tmp_path: Path, monkeypatch
) -> None:
    files = _make_inputs(tmp_path)
    monkeypatch.setattr(
        "mcp_hpc_tool_contracts.registry.HHBLITS_SPACK_FALLBACK",
        "/opt/spack/opt/spack/linux-icelake/hmmer-3.4/bin/jackhmmer",
    )

    with pytest.raises(ValueError, match="must point to a hhblits binary"):
        compile_adapter("hhblits", {"query_fasta": files["query"]})


def test_fpocket_default_output_matches_remote_input_stem(tmp_path: Path) -> None:
    structure = tmp_path / "protein.pdb"
    structure.write_text("ATOM\n", encoding="utf-8")

    compiled = compile_adapter("fpocket", {"structure_path": str(structure)})

    # Input is staged to out/inputs/ so fpocket writes its output next to it in out/.
    assert compiled.runspec["inputs"][0]["remote_path"] == "inputs/protein.pdb"
    assert compiled.runspec["inputs"][0]["stage_to"] == "out"
    assert compiled.runspec["expected_outputs"][0]["path"] == "inputs/protein_out"
    assert "/out/inputs/protein.pdb" in compiled.runspec["command"]


def test_tunnels_records_backend_metadata(tmp_path: Path) -> None:
    files = _make_inputs(tmp_path)
    compiled = compile_adapter(
        "tunnels",
        {"structure_path": files["pdb"], "mode": "dock", "backend": "caverdock"},
    )
    metadata = compiled.runspec["metadata"]["tool_contract"]
    assert metadata["tunnel_mode"] == "dock"
    assert metadata["tunnel_backend"] == "caverdock"


def test_tunnels_wrapper_entrypoint_matches_mode(tmp_path: Path, monkeypatch) -> None:
    files = _make_inputs(tmp_path)

    def _force_wrapper(**kwargs):
        wrapper = kwargs["wrapper"]
        return InvocationSelection(selected=wrapper, fallback=[])

    monkeypatch.setattr(
        "mcp_hpc_tool_contracts.registry.select_invocation", _force_wrapper
    )

    detect = compile_adapter(
        "tunnels", {"structure_path": files["pdb"], "mode": "detect"}
    )
    dock = compile_adapter("tunnels", {"structure_path": files["pdb"], "mode": "dock"})

    assert detect.runspec["command"][0] == "/opt/tools/caver"
    assert dock.runspec["command"][0] == "/opt/tools/caverdock"


def test_vina_contract_declares_directory_and_artifact_checks(tmp_path: Path) -> None:
    files = _make_inputs(tmp_path)
    compiled = compile_adapter(
        "vina",
        {
            "receptor_path": files["receptor"],
            "ligand_path": files["ligand"],
            "center_x": 0,
            "center_y": 0,
            "center_z": 0,
            "size_x": 20,
            "size_y": 20,
            "size_z": 20,
        },
    )
    assert any(
        item["kind"] == "dir" and item["non_empty"]
        for item in compiled.runspec["expected_outputs"]
    )
    checks = [item["path"] for item in compiled.runspec["success_checks"]]
    assert any(path.endswith("vina_out.pdbqt") for path in checks)
    assert any(path.endswith("vina.log") for path in checks)
