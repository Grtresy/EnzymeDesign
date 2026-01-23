from __future__ import annotations

import csv
import json
import shutil
import subprocess
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
    if mode == "mock":
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
        return

    if shutil.which("diffdock") is None:
        raise DeterministicToolError("diffdock executable not found")

    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    repo_root = Path(__file__).resolve().parents[2]
    ligand_dir = repo_root / "inputs" / "ligands"
    ligand_files = sorted(ligand_dir.glob("*.sdf")) + sorted(ligand_dir.glob("*.pdbqt"))
    if not ligand_files:
        raise DeterministicToolError("No ligand files found for docking")
    ligand_path = ligand_files[0]

    output_dir = workdir / "diffdock_out"
    output_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "diffdock",
        "--protein",
        str(pdb_path),
        "--ligand",
        str(ligand_path),
        "--out_dir",
        str(output_dir),
    ]
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeterministicToolError(f"diffdock failed: {result.stderr.strip()}")

    poses = []
    ranking_csv = next(iter(sorted(output_dir.glob("*.csv"))), None)
    if ranking_csv:
        with ranking_csv.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for row in reader:
                rank = int(row.get("rank", len(poses) + 1))
                score = float(row.get("score", 0.0))
                path = row.get("path") or row.get("pose") or f"poses/diffdock_pose_{rank}.sdf"
                poses.append({"rank": rank, "score": score, "path": path})

    ranking_json = output_dir / "results.json"
    if not poses and ranking_json.exists():
        data = json.loads(ranking_json.read_text(encoding="utf-8"))
        for entry in data:
            rank = int(entry.get("rank", len(poses) + 1))
            score = float(entry.get("score", 0.0))
            path = entry.get("path") or f"poses/diffdock_pose_{rank}.sdf"
            poses.append({"rank": rank, "score": score, "path": path})

    if not poses:
        raise DeterministicToolError("No docking poses parsed from diffdock output")

    top_confidence = max(pose["score"] for pose in poses)
    payload = {
        "schema_version": "1.0",
        "method": "diffdock",
        "best_affinity": None,
        "top_confidence": top_confidence,
        "poses": poses,
    }
    write_json_atomic(outputs["docking"], payload)
