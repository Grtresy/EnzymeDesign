from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError

from . import diffdock, vina


def get_version(mode: str) -> str:
    return f"mock-docking-1.0" if mode == "mock" else "real-docking-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    try:
        vina.run(inputs, outputs, params, workdir, mode)
    except DeterministicToolError:
        diffdock.run(inputs, outputs, params, workdir, mode)

