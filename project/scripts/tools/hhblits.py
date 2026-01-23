from __future__ import annotations

import shutil
import subprocess
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

    config = params.get("config", {})
    hhblits_config = config.get("hhblits", {})
    db_path = hhblits_config.get("db") or config.get("hhblits_db")
    if not db_path:
        raise DeterministicToolError("hhblits database path not configured (hhblits_db)")

    evalue = hhblits_config.get("evalue", 1e-3)
    num_iterations = hhblits_config.get("num_iterations", 3)
    maxseq = hhblits_config.get("maxseq", 10000)
    cpu = hhblits_config.get("cpu", 4)
    extra_args = hhblits_config.get("extra_args", [])

    hhr_path = workdir / "hhblits.hhr"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    hhr_path.parent.mkdir(parents=True, exist_ok=True)

    command = [
        "hhblits",
        "-i",
        str(fasta_path),
        "-d",
        str(db_path),
        "-oa3m",
        str(output_path),
        "-o",
        str(hhr_path),
        "-e",
        str(evalue),
        "-n",
        str(num_iterations),
    ]
    if maxseq:
        command += ["-maxseq", str(maxseq)]
    if cpu:
        command += ["-cpu", str(cpu)]
    if extra_args:
        command += [str(arg) for arg in extra_args]

    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeterministicToolError(
            f"hhblits failed with code {result.returncode}: {result.stderr.strip()}"
        )
    if not output_path.exists():
        raise DeterministicToolError(f"hhblits did not produce output at {output_path}")
    if output_path.stat().st_size == 0:
        raise DeterministicToolError(f"hhblits produced empty output at {output_path}")
