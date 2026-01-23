from __future__ import annotations

import re
import shutil
import subprocess
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
    if mode == "mock":
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
        return

    if shutil.which("vina") is None:
        raise DeterministicToolError("vina executable not found")

    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    repo_root = Path(__file__).resolve().parents[2]
    ligand_dir = repo_root / "inputs" / "ligands"
    ligand_files = sorted(ligand_dir.glob("*.sdf")) + sorted(ligand_dir.glob("*.pdbqt"))
    if not ligand_files:
        raise DeterministicToolError("No ligand files found for docking")
    ligand_path = ligand_files[0]

    poses_dir = workdir / "poses"
    poses_dir.mkdir(parents=True, exist_ok=True)
    log_path = workdir / "vina.log"
    pose_path = poses_dir / "vina_pose_1.pdbqt"

    command = [
        "vina",
        "--receptor",
        str(pdb_path),
        "--ligand",
        str(ligand_path),
        "--out",
        str(pose_path),
        "--log",
        str(log_path),
    ]
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeterministicToolError(f"vina failed: {result.stderr.strip()}")

    if not log_path.exists():
        raise DeterministicToolError("vina log file not found")

    poses = []
    for line in log_path.read_text(encoding="utf-8").splitlines():
        match = re.match(r"\s*(\d+)\s+(-?\d+(?:\.\d+)?)", line)
        if not match:
            continue
        rank = int(match.group(1))
        score = float(match.group(2))
        pose_file = poses_dir / f"vina_pose_{rank}.pdbqt"
        poses.append({"rank": rank, "score": score, "path": str(pose_file.relative_to(workdir))})

    if not poses:
        raise DeterministicToolError("No docking poses parsed from vina log")

    best_affinity = min(pose["score"] for pose in poses)
    payload = {
        "schema_version": "1.0",
        "method": "vina",
        "best_affinity": best_affinity,
        "top_confidence": None,
        "poses": poses,
    }
    write_json_atomic(outputs["docking"], payload)
