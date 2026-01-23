from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import numpy as np

from utils.io import write_json_atomic
from utils.pdb import parse_pdb_atoms


def get_version(mode: str) -> str:
    return "mock-conservation-1.0" if mode == "mock" else "real-conservation-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    atoms = parse_pdb_atoms(pdb_path)
    residues = []
    seen = set()
    for atom in atoms:
        key = (atom.chain_id, atom.res_seq, atom.ins_code)
        if key in seen:
            continue
        seen.add(key)
        uid = f"{atom.chain_id}:{atom.res_seq}{atom.ins_code}".strip()
        residues.append(uid)

    rng = np.random.default_rng(5)
    per_residue = [
        {
            "uid": uid,
            "cons_score": float(rng.uniform(0.2, 0.95)),
            "gap_fraction": float(rng.uniform(0.0, 0.2)),
        }
        for uid in residues
    ]
    payload = {
        "schema_version": "1.0",
        "msa": {"n_seq": 5, "neff": 4.2, "coverage": 0.85},
        "per_residue": per_residue,
    }
    write_json_atomic(outputs["conservation"], payload)

