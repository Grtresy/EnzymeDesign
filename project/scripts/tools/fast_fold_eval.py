from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple


def get_version(mode: str) -> str:
    return "mock-fast-fold-1.0" if mode == "mock" else "real-fast-fold-1.0"


def _read_fasta(path: Path) -> List[Tuple[str, str]]:
    records = []
    current_id = None
    seq = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if current_id:
                records.append((current_id, "".join(seq)))
            current_id = line[1:].strip()
            seq = []
        else:
            seq.append(line.strip())
    if current_id:
        records.append((current_id, "".join(seq)))
    return records


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fasta_path = next(p for p in inputs if p.suffix == ".fasta")
    records = _read_fasta(fasta_path)
    rng = random.Random(11)

    output_path = outputs["fast_fold_scores"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "mean_plddt", "length", "rough_rmsd"])
        for candidate_id, seq in records:
            mean_plddt = round(rng.uniform(65.0, 92.0), 2)
            rough_rmsd = round(rng.uniform(1.5, 4.0), 2)
            writer.writerow([candidate_id, mean_plddt, len(seq), rough_rmsd])
