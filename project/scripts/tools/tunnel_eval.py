from __future__ import annotations

import csv
import random
from pathlib import Path
from typing import Dict, List, Tuple


def get_version(mode: str) -> str:
    return "mock-tunnel-eval-1.0" if mode == "mock" else "real-tunnel-eval-1.0"


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
    rng = random.Random(29)

    output_path = outputs["tunnel_check"]
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["candidate_id", "bottleneck_radius", "throughput_ok"])
        for candidate_id, _seq in records:
            radius = round(rng.uniform(0.8, 2.5), 2)
            writer.writerow([candidate_id, radius, radius >= 1.2])
