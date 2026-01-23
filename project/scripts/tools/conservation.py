from __future__ import annotations

import math
from pathlib import Path
from typing import Dict, List

import numpy as np

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic
from utils.pdb import parse_pdb_atoms


def get_version(mode: str) -> str:
    return "mock-conservation-1.0" if mode == "mock" else "real-conservation-1.0"


def _strip_a3m_insertions(sequence: str) -> str:
    return "".join(ch for ch in sequence if not ch.islower())


def _read_a3m(path: Path) -> List[str]:
    sequences: List[str] = []
    current: List[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith(">"):
            if current:
                sequences.append(_strip_a3m_insertions("".join(current)).upper())
                current = []
            continue
        current.append(line.strip())
    if current:
        sequences.append(_strip_a3m_insertions("".join(current)).upper())
    return [seq for seq in sequences if seq]


def _alignment_length(sequences: List[str]) -> int:
    lengths = {len(seq) for seq in sequences}
    if not lengths:
        return 0
    if len(lengths) != 1:
        raise DeterministicToolError("MSA sequences have inconsistent lengths")
    return lengths.pop()


def _compute_conservation(sequences: List[str]) -> tuple[List[dict], dict]:
    n_seq = len(sequences)
    aln_len = _alignment_length(sequences)
    if n_seq == 0 or aln_len == 0:
        raise DeterministicToolError("MSA has no sequences or alignment length")

    per_position = []
    gap_fractions = []
    max_entropy = math.log(20.0)

    for idx in range(aln_len):
        column = [seq[idx] for seq in sequences]
        gaps = sum(1 for ch in column if ch in {"-", "."})
        gap_fraction = gaps / n_seq
        gap_fractions.append(gap_fraction)
        residues = [ch for ch in column if ch not in {"-", "."}]
        if residues:
            counts: Dict[str, int] = {}
            for ch in residues:
                counts[ch] = counts.get(ch, 0) + 1
            entropy = 0.0
            for count in counts.values():
                prob = count / len(residues)
                entropy -= prob * math.log(prob)
            cons_score = 1.0 - (entropy / max_entropy if max_entropy else 0.0)
        else:
            cons_score = 0.0
        per_position.append(
            {
                "cons_score": float(max(0.0, min(cons_score, 1.0))),
                "gap_fraction": float(gap_fraction),
            }
        )

    msa_stats = {
        "n_seq": n_seq,
        "neff": float(n_seq),
        "coverage": float(1.0 - (sum(gap_fractions) / len(gap_fractions))),
    }
    return per_position, msa_stats


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    msa_path = next((p for p in inputs if p.suffix == ".a3m"), None)
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

    if mode == "mock":
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
        return

    if msa_path is None:
        raise DeterministicToolError("MSA input (.a3m) is required for conservation in real mode")

    sequences = _read_a3m(msa_path)
    per_position, msa_stats = _compute_conservation(sequences)

    if len(per_position) != len(residues):
        raise DeterministicToolError(
            f"MSA alignment length {len(per_position)} does not match residues {len(residues)}"
        )

    per_residue = [
        {"uid": uid, **per_position[idx]} for idx, uid in enumerate(residues)
    ]
    payload = {
        "schema_version": "1.0",
        "msa": msa_stats,
        "per_residue": per_residue,
    }
    write_json_atomic(outputs["conservation"], payload)
