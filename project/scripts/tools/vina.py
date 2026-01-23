from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic


def get_version(mode: str) -> str:
    return "mock-vina-1.0" if mode == "mock" else "real-vina-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    if mode == "real" and shutil.which("vina") is None:
        raise DeterministicToolError("vina executable not found")

    payload = {
        "schema_version": "1.0",
        "method": "vina",
        "best_affinity": -7.2,
        "top_confidence": None,
        "poses": [
            {"rank": 1, "score": -7.2, "path": "poses/vina_pose_1.pdbqt"},
            {"rank": 2, "score": -6.4, "path": "poses/vina_pose_2.pdbqt"},
        ],
    }
    write_json_atomic(outputs["docking"], payload)

