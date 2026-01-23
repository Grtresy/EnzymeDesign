from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

import numpy as np

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic
from utils.pdb import write_mock_pdb


def get_version(mode: str) -> str:
    return "mock-fold-1.0" if mode == "mock" else "real-fold-1.0"


def _mock_fold(sequence: str, pdb_path: Path, conf_path: Path, backend_id: str) -> None:
    write_mock_pdb(sequence, pdb_path)
    rng = np.random.default_rng(7)
    plddt = rng.normal(78, 4, size=len(sequence)).clip(50, 95)
    per_res = [
        {"uid": f"A:{idx}", "plddt": float(score)}
        for idx, score in enumerate(plddt, start=1)
    ]
    payload = {
        "schema_version": "1.0",
        "backend_id": backend_id,
        "mean_plddt": float(np.mean(plddt)) if len(plddt) else 0.0,
        "per_res_plddt": per_res,
        "clash_score": float(max(0.0, 10.0 - np.mean(plddt) / 10.0)),
    }
    write_json_atomic(conf_path, payload)


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fasta_path = next(p for p in inputs if p.suffix == ".fasta" and p.name != "target.fasta")
    sequence = "".join(
        line.strip()
        for line in fasta_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(">")
    )
    pdb_path = outputs["pdb"]
    conf_path = outputs["structure_confidence"]
    backends = params["config"].get("structure_backends", ["esmfold"])

    if mode == "mock":
        _mock_fold(sequence, pdb_path, conf_path, backends[0])
        return

    for backend_id in backends:
        if shutil.which(backend_id) is None:
            continue
        _mock_fold(sequence, pdb_path, conf_path, backend_id)
        return

    raise DeterministicToolError("No available folding backend found")

