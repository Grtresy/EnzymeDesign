from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic
from utils.metrics import monte_carlo_volume_sasa
from utils.pdb import read_ca_coords, radius_of_gyration, write_mock_pdb


def get_version(mode: str) -> str:
    return "mock-volume-1.0" if mode == "mock" else "real-volume-1.0"


def _read_sequence(path: Path) -> str:
    return "".join(
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(">")
    )


def _compute_metrics(variant_pdb: Path, wt_pdb: Path) -> tuple[float, float, float, float]:
    coords_var = read_ca_coords(variant_pdb)
    coords_wt = read_ca_coords(wt_pdb)
    rg_var = radius_of_gyration(coords_var)
    rg_wt = radius_of_gyration(coords_wt)
    var_mc = monte_carlo_volume_sasa(coords_var)
    wt_mc = monte_carlo_volume_sasa(coords_wt)
    return rg_var, rg_wt, var_mc.volume, wt_mc.volume, var_mc.sasa, wt_mc.sasa


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    pdb_path = next(p for p in inputs if p.suffix == ".pdb" and "reference" not in p.name)
    wt_pdb = next(p for p in inputs if p.suffix == ".pdb" and "reference" in p.name)
    wt_fasta = next(p for p in inputs if p.name == "target.fasta")
    variant_fasta = next(p for p in inputs if p.suffix == ".fasta" and p.name != "target.fasta")

    wt_seq = _read_sequence(wt_fasta)
    var_seq = _read_sequence(variant_fasta)

    try:
        rg_var, rg_wt, vol_var, vol_wt, sasa_var, sasa_wt = _compute_metrics(pdb_path, wt_pdb)
    except Exception:
        if mode == "mock":
            write_mock_pdb(var_seq, pdb_path)
            rg_var, rg_wt, vol_var, vol_wt, sasa_var, sasa_wt = _compute_metrics(pdb_path, wt_pdb)
        else:
            raise DeterministicToolError("Failed to parse PDB for volume metrics")

    shrink_mode = params["config"].get("target_spec", {}).get("shrink_mode", "both")
    payload = {
        "schema_version": "1.0",
        "seq_length": len(var_seq),
        "wt_length": len(wt_seq),
        "delta_length": len(var_seq) - len(wt_seq),
        "rg": rg_var,
        "wt_rg": rg_wt,
        "delta_rg": rg_var - rg_wt,
        "sasa_total": sasa_var,
        "wt_sasa_total": sasa_wt,
        "delta_sasa": sasa_var - sasa_wt,
        "volume_protein": vol_var,
        "wt_volume_protein": vol_wt,
        "delta_volume": vol_var - vol_wt,
        "volume_method": params["config"].get("target_spec", {}).get("volume_method", "mock"),
        "shrink_mode": shrink_mode,
        "notes": [],
    }
    write_json_atomic(outputs["geometry_metrics"], payload)

