from __future__ import annotations

import csv
import shutil
import subprocess
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
    if mode == "mock":
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
        return

    if shutil.which("caver.sh") is None:
        raise DeterministicToolError("caver executable not found")

    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    output_dir = workdir / "caver_out"
    output_dir.mkdir(parents=True, exist_ok=True)

    command = ["caver.sh", "-p", str(pdb_path), "-o", str(output_dir)]
    result = subprocess.run(command, cwd=workdir, capture_output=True, text=True)
    if result.returncode != 0:
        raise DeterministicToolError(f"caver failed: {result.stderr.strip()}")

    csv_files = sorted(output_dir.rglob("*.csv"))
    if not csv_files:
        raise DeterministicToolError("caver output CSV not found")

    tunnels = []
    for csv_path in csv_files:
        with csv_path.open("r", encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            if not reader.fieldnames:
                continue
            for row in reader:
                tunnel_id = row.get("tunnel_id") or row.get("id") or row.get("tunnel")
                if tunnel_id is None:
                    continue
                tunnel_id = f"tunnel-{tunnel_id}" if str(tunnel_id).isdigit() else str(tunnel_id)
                lining_raw = row.get("lining_residues") or row.get("lining") or ""
                lining_residues = [
                    residue.strip()
                    for residue in lining_raw.replace(";", ",").split(",")
                    if residue.strip()
                ]
                tunnels.append(
                    {
                        "tunnel_id": tunnel_id,
                        "length": float(row.get("length", 0.0)),
                        "bottleneck_radius": float(row.get("bottleneck_radius", 0.0)),
                        "throughput": float(row.get("throughput", 0.0)),
                        "curvature": float(row.get("curvature", 0.0)),
                        "lining_residues": lining_residues,
                    }
                )
        if tunnels:
            break

    if not tunnels:
        raise DeterministicToolError("No tunnels parsed from caver output")

    payload = {"schema_version": "1.0", "tunnels": tunnels}
    write_json_atomic(outputs["tunnels"], payload)
