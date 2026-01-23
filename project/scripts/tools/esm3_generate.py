from __future__ import annotations

import random
from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import read_json, write_json_atomic


AMINO_ACIDS = list("ACDEFGHIKLMNPQRSTVWY")


def get_version(mode: str) -> str:
    return "mock-esm3-generate-1.0" if mode == "mock" else "real-esm3-generate-1.0"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _mutate_sequence(sequence: str, positions: List[int], rng: random.Random) -> str:
    chars = list(sequence)
    for pos in positions:
        if 1 <= pos <= len(chars):
            chars[pos - 1] = rng.choice(AMINO_ACIDS)
    return "".join(chars)


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    prompt_pack = read_json(next(p for p in inputs if p.name == "prompt_pack.json"))
    request = _load_yaml(next(p for p in inputs if p.name == "esm3_request.yaml"))
    masked_sequence = prompt_pack["tracks"]["sequence"]["masked"]
    mask_positions = prompt_pack["tracks"]["sequence"].get("mask_positions", [])

    num_samples = int(request.get("num_samples", 50))
    seed = int(request.get("seed", 13))
    rng = random.Random(seed)

    sequences = []
    fasta_lines = []
    for idx in range(1, num_samples + 1):
        seq = _mutate_sequence(masked_sequence, mask_positions, rng)
        seq_id = f"cand_{idx:04d}"
        fasta_lines.append(f">{seq_id}")
        fasta_lines.append(seq)
        sequences.append({"candidate_id": seq_id, "sequence": seq})

    outputs["candidates"].write_text("\n".join(fasta_lines) + "\n", encoding="utf-8")
    metadata = {
        "schema_version": "1.0",
        "prompt_pack_id": prompt_pack.get("target_id", "target"),
        "num_candidates": num_samples,
        "seed": seed,
        "mask_positions": mask_positions,
        "candidates": sequences,
    }
    write_json_atomic(outputs["metadata"], metadata)
