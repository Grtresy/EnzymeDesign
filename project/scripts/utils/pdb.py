from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Tuple

import numpy as np


@dataclass
class AtomRecord:
    atom_name: str
    res_name: str
    chain_id: str
    res_seq: int
    ins_code: str
    x: float
    y: float
    z: float


def parse_pdb_atoms(path: Path) -> List[AtomRecord]:
    atoms: List[AtomRecord] = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if not line.startswith("ATOM"):
                continue
            atom_name = line[12:16].strip()
            res_name = line[17:20].strip()
            chain_id = line[21].strip() or "A"
            res_seq = int(line[22:26].strip())
            ins_code = line[26].strip() or ""
            x = float(line[30:38].strip())
            y = float(line[38:46].strip())
            z = float(line[46:54].strip())
            atoms.append(
                AtomRecord(
                    atom_name=atom_name,
                    res_name=res_name,
                    chain_id=chain_id,
                    res_seq=res_seq,
                    ins_code=ins_code,
                    x=x,
                    y=y,
                    z=z,
                )
            )
    return atoms


def read_ca_coords(path: Path) -> np.ndarray:
    atoms = parse_pdb_atoms(path)
    coords = [(a.x, a.y, a.z) for a in atoms if a.atom_name == "CA"]
    if not coords:
        raise ValueError("No CA atoms found in PDB")
    return np.array(coords, dtype=float)


def write_mock_pdb(sequence: str, path: Path, chain_id: str = "A") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    lines = ["HEADER    MOCK STRUCTURE"]
    x, y, z = 0.0, 0.0, 0.0
    for idx, _res in enumerate(sequence, start=1):
        line = (
            f"ATOM  {idx:5d}  CA  ALA {chain_id}{idx:4d}    "
            f"{x:8.3f}{y:8.3f}{z:8.3f}  1.00 20.00           C"
        )
        lines.append(line)
        x += 1.5
        y += 0.2
        z += 0.1
    lines.append("TER")
    lines.append("END")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def radius_of_gyration(coords: np.ndarray) -> float:
    centroid = coords.mean(axis=0)
    diffs = coords - centroid
    return float(np.sqrt((diffs**2).sum(axis=1).mean()))


def coords_bounds(coords: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
    return coords.min(axis=0), coords.max(axis=0)


def count_residues_from_atoms(atoms: Iterable[AtomRecord]) -> int:
    seen = set()
    for atom in atoms:
        key = (atom.chain_id, atom.res_seq, atom.ins_code)
        seen.add(key)
    return len(seen)

