from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict, List

from utils.errors import DeterministicToolError


def get_version(mode: str) -> str:
    return "mock-hhblits-1.0" if mode == "mock" else "real-hhblits-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fasta_path = next(p for p in inputs if p.suffix == ".fasta")
    output_path = outputs["msa"]
    sequence = "".join(
        line.strip()
        for line in fasta_path.read_text(encoding="utf-8").splitlines()
        if not line.startswith(">")
    )

    if mode == "mock":
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(">query\n" + sequence + "\n>mock1\n" + sequence + "\n", encoding="utf-8")
        return

    if shutil.which("hhblits") is None:
        raise DeterministicToolError("hhblits executable not found")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(">query\n" + sequence + "\n", encoding="utf-8")

