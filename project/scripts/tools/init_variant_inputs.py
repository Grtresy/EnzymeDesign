from __future__ import annotations

from pathlib import Path
from typing import Dict, List

from utils.io import write_json_atomic


def get_version(mode: str) -> str:
    return "mock-1.0" if mode == "mock" else "real-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    snapshot_path = outputs["snapshot"]
    inputs_dir = snapshot_path.parent
    inputs_dir.mkdir(parents=True, exist_ok=True)

    fasta_inputs = [p for p in inputs if p.suffix == ".fasta" and p.name != "target.fasta"]
    variant_id = fasta_inputs[0].stem if fasta_inputs else "variant"

    copied_files: List[str] = []
    for path in inputs:
        if not path.exists():
            continue
        dest = inputs_dir / path.name
        dest.write_bytes(path.read_bytes())
        copied_files.append(str(dest))

    repo_root = snapshot_path.parents[4]
    ligands_dir = repo_root / "inputs" / "ligands"
    if ligands_dir.exists():
        dest_ligands = inputs_dir / "ligands"
        dest_ligands.mkdir(parents=True, exist_ok=True)
        for ligand in ligands_dir.glob("*.sdf"):
            dest = dest_ligands / ligand.name
            dest.write_bytes(ligand.read_bytes())
            copied_files.append(str(dest))

    payload = {
        "schema_version": "1.0",
        "variant_id": variant_id,
        "files": copied_files,
    }
    write_json_atomic(snapshot_path, payload)

