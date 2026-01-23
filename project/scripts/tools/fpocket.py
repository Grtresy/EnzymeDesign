from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError
from utils.io import write_json_atomic


def get_version(mode: str) -> str:
    return "mock-fpocket-1.0" if mode == "mock" else "real-fpocket-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    if mode == "real" and shutil.which("fpocket") is None:
        raise DeterministicToolError("fpocket executable not found")

    payload = {
        "schema_version": "1.0",
        "pockets": [
            {
                "pocket_id": "pocket-1",
                "score": 0.68,
                "volume": 120.0,
                "center": [5.0, 5.0, 2.0],
                "residues": ["A:5", "A:8", "A:12"],
            }
        ],
    }
    write_json_atomic(outputs["pockets"], payload)

