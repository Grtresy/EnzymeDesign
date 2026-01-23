from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple


def get_version(mode: str) -> str:
    return "mock-docking-eval-1.0" if mode == "mock" else "real-docking-eval-1.0"


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
    rng = random.Random(23)

    output_path = outputs["docking_scores"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "best_affinity", "top_confidence"])
        for candidate_id, _seq in records:
            writer.writerow(
                [
                    candidate_id,
                    round(rng.uniform(-9.5, -5.0), 2),
                    round(rng.uniform(0.4, 0.9), 2),
                ]
            )
