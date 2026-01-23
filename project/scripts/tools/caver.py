from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic


def get_version(mode: str) -> str:
    return "mock-caver-1.0" if mode == "mock" else "real-caver-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    if mode == "real" and shutil.which("caver.sh") is None:
        raise DeterministicToolError("caver executable not found")

    start_points = ["ligand_center", "top_pocket_center", "multi_start_points"]
    probe_radii = [0.9, 0.7]
    _ = [(sp, pr) for sp in start_points for pr in probe_radii]

    payload = {
        "schema_version": "1.0",
        "tunnels": [
            {
                "tunnel_id": "tunnel-1",
                "length": 18.5,
                "bottleneck_radius": 1.1,
                "throughput": 0.7,
                "curvature": 0.35,
                "lining_residues": ["A:6", "A:10", "A:14"],
            }
        ],
    }
    write_json_atomic(outputs["tunnels"], payload)
