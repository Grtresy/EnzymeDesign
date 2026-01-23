from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic


def get_version(mode: str) -> str:
    return "mock-diffdock-1.0" if mode == "mock" else "real-diffdock-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    if mode == "real" and shutil.which("diffdock") is None:
        raise DeterministicToolError("diffdock executable not found")

    payload = {
        "schema_version": "1.0",
        "method": "diffdock",
        "best_affinity": None,
        "top_confidence": 0.62,
        "poses": [
            {"rank": 1, "score": 0.62, "path": "poses/diffdock_pose_1.sdf"}
        ],
    }
    write_json_atomic(outputs["docking"], payload)

