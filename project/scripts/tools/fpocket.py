from __future__ import annotations

import re
import shutil
import subprocess
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
    if mode == "mock":
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
        return

    if shutil.which("fpocket") is None:
        raise DeterministicToolError("fpocket executable not found")

    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    workdir.mkdir(parents=True, exist_ok=True)
    command = ["fpocket", "-f", str(pdb_path)]
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeterministicToolError(f"fpocket failed: {result.stderr.strip()}")

    output_dir = workdir / f"{pdb_path.stem}_out"
    if not output_dir.exists():
        matches = list(workdir.glob("*_out"))
        if matches:
            output_dir = matches[0]
        else:
            raise DeterministicToolError("fpocket output directory not found")

    pockets_dir = output_dir / "pockets"
    if not pockets_dir.exists():
        raise DeterministicToolError("fpocket pockets directory not found")

    pocket_files = sorted(pockets_dir.glob("pocket*_info.txt"))
    if not pocket_files:
        pocket_files = sorted(pockets_dir.glob("*info*.txt"))
    if not pocket_files:
        raise DeterministicToolError("fpocket pocket info files not found")

    pockets = []
    for info_path in pocket_files:
        text = info_path.read_text(encoding="utf-8")
        score_match = re.search(r"Score\s*[:=]\s*([-\d.]+)", text)
        volume_match = re.search(r"Volume\s*[:=]\s*([-\d.]+)", text)
        center_match = re.search(
            r"Center\s*[:=]\s*([-\d.]+)[,\s]+([-\d.]+)[,\s]+([-\d.]+)",
            text,
        )
        residues_match = re.search(r"Residues\s*[:=]\s*(.+)", text)
        if not (score_match and volume_match and center_match and residues_match):
            raise DeterministicToolError(f"Missing pocket descriptors in {info_path.name}")

        residues_raw = residues_match.group(1)
        residues = [
            residue.strip()
            for residue in re.split(r"[,\s]+", residues_raw)
            if residue.strip()
        ]
        pocket_index = re.findall(r"\d+", info_path.stem)
        pocket_id = f"pocket-{pocket_index[0]}" if pocket_index else info_path.stem
        pockets.append(
            {
                "pocket_id": pocket_id,
                "score": float(score_match.group(1)),
                "volume": float(volume_match.group(1)),
                "center": [
                    float(center_match.group(1)),
                    float(center_match.group(2)),
                    float(center_match.group(3)),
                ],
                "residues": residues,
            }
        )

    payload = {"schema_version": "1.0", "pockets": pockets}
    write_json_atomic(outputs["pockets"], payload)
