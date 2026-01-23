from __future__ import annotations

import json
import math
import random
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

TOOL_VERSION = "0.1.0"


class MissingExternalToolError(RuntimeError):
    pass


@dataclass(frozen=True)
class ToolRunResult:
    outputs: dict[str, str]
    command: list[str] | None = None


def ensure_dir(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)


def write_json(path: Path, payload: dict) -> None:
    ensure_dir(path.parent)
    path.write_text(json.dumps(payload, indent=2))


def minimal_pdb_text() -> str:
    lines = [
        "ATOM      1  N   ALA A   1       0.000   0.000   0.000  1.00 20.00           N",
        "ATOM      2  CA  ALA A   1       1.458   0.000   0.000  1.00 20.00           C",
        "ATOM      3  C   ALA A   1       2.028   1.410   0.000  1.00 20.00           C",
        "ATOM      4  O   ALA A   1       1.329   2.347   0.000  1.00 20.00           O",
        "TER",
        "END",
    ]
    return "\n".join(lines) + "\n"


def write_minimal_pdb(path: Path) -> None:
    ensure_dir(path.parent)
    path.write_text(minimal_pdb_text())


def build_structure_confidence(
    residues: Iterable[tuple[int, str]], model: str = "mockfold"
) -> dict:
    residues_list = [
        {
            "position": position,
            "residue": residue,
            "confidence": 82.0,
            "metric": "plddt",
        }
        for position, residue in residues
    ]
    global_confidence = (
        sum(item["confidence"] for item in residues_list) / len(residues_list)
        if residues_list
        else 0.0
    )
    return {
        "schema_version": "1.0",
        "model": model,
        "global_confidence": global_confidence,
        "residues": residues_list,
    }


def build_conservation(residues: Iterable[tuple[int, str]]) -> dict:
    entries = [
        {
            "position": position,
            "residue": residue,
            "score": 0.5,
            "conservation_class": "medium",
        }
        for position, residue in residues
    ]
    return {
        "schema_version": "1.0",
        "method": "mock",
        "window_size": 5,
        "residues": entries,
    }


def build_residue_map(source: str, target: str) -> dict:
    mappings = []
    for index, (src, tgt) in enumerate(zip(source, target), start=1):
        mappings.append(
            {
                "source_index": index,
                "target_index": index,
                "source_residue": src,
                "target_residue": tgt,
                "mapping_type": "aligned",
            }
        )
    return {
        "schema_version": "1.0",
        "source_sequence": source,
        "target_sequence": target,
        "mappings": mappings,
    }


def build_pockets() -> dict:
    return {
        "schema_version": "1.0",
        "pockets": [
            {
                "pocket_id": "pocket-1",
                "volume": 120.5,
                "score": 0.7,
                "center": [0.0, 0.0, 0.0],
                "residues": [1],
            }
        ],
    }


def build_tunnels() -> dict:
    return {
        "schema_version": "1.0",
        "tunnels": [
            {
                "tunnel_id": "tunnel-1",
                "length": 15.4,
                "bottleneck_radius": 1.2,
                "curvature": 0.3,
                "path": [
                    {"x": 0.0, "y": 0.0, "z": 0.0, "radius": 1.2},
                    {"x": 1.0, "y": 0.5, "z": 0.2, "radius": 1.5},
                ],
            }
        ],
    }


def build_docking(method: str) -> dict:
    return {
        "schema_version": "1.0",
        "method": method,
        "receptor_id": "receptor",
        "ligand_id": "ligand",
        "poses": [
            {
                "pose_id": "pose-1",
                "score": -7.5,
                "binding_energy": -30.2,
                "rmsd": 1.1,
                "interactions": ["H-bond", "hydrophobic"],
            }
        ],
    }


def require_executable(name: str) -> str:
    executable = shutil.which(name)
    if not executable:
        raise MissingExternalToolError(
            f"Missing external tool '{name}'. Install it or use mock mode."
        )
    return executable


def random_unit_vector(rng: random.Random) -> tuple[float, float, float]:
    phi = rng.uniform(0.0, 2.0 * math.pi)
    costheta = rng.uniform(-1.0, 1.0)
    theta = math.acos(costheta)
    return (
        math.sin(theta) * math.cos(phi),
        math.sin(theta) * math.sin(phi),
        math.cos(theta),
    )
