from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import read_json, write_json_atomic


def get_version(mode: str) -> str:
    return "mock-prompt-builder-1.0" if mode == "mock" else "real-prompt-builder-1.0"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _read_fasta(path: Path) -> str:
    lines = [line.strip() for line in path.read_text(encoding="utf-8").splitlines()]
    return "".join(line for line in lines if line and not line.startswith(">"))


def _mask_sequence(sequence: str, masked_positions: List[int]) -> str:
    chars = list(sequence)
    for pos in masked_positions:
        if 1 <= pos <= len(chars):
            chars[pos - 1] = "X"
    return "".join(chars)


def _collect_mask_positions(fixed_mask: dict) -> List[int]:
    positions = []
    for entry in fixed_mask.get("regions", []):
        if entry.get("status") == "Masked":
            positions.append(int(entry.get("index", 0)))
    return sorted({pos for pos in positions if pos > 0})


def _collect_key_residues(data: dict) -> List[str]:
    residues = []
    for item in data.get("protected_residues", []):
        if item.get("uid"):
            residues.append(item["uid"])
    for item in data.get("key_residues", []):
        if item.get("uid"):
            residues.append(item["uid"])
    for item in data.get("lining_residues", []):
        if item.get("uid"):
            residues.append(item["uid"])
    return sorted(set(residues))


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fasta_path = next(p for p in inputs if p.suffix == ".fasta")
    pdb_path = next(p for p in inputs if p.suffix == ".pdb")
    fixed_mask = _load_yaml(next(p for p in inputs if p.name == "fixed_mask_regions.yaml"))
    key_lit = _load_yaml(next(p for p in inputs if p.name == "key_residues_from_lit.yaml"))
    pocket_keys = _load_yaml(next(p for p in inputs if p.name == "pocket_key_residues.yaml"))
    tunnel_keys = _load_yaml(next(p for p in inputs if p.name == "tunnel_lining_residues.yaml"))
    tunnel_geom = read_json(next(p for p in inputs if p.name == "tunnel_geometry.json"))

    sequence = _read_fasta(fasta_path)
    masked_positions = _collect_mask_positions(fixed_mask)
    masked_sequence = _mask_sequence(sequence, masked_positions)
    key_residues = _collect_key_residues(key_lit)
    key_residues += _collect_key_residues(pocket_keys)
    key_residues += _collect_key_residues(tunnel_keys)
    key_residues = sorted(set(key_residues))

    prompt_pack = {
        "schema_version": "1.0",
        "target_id": params.get("config", {}).get("target_id", "target"),
        "tracks": {
            "sequence": {
                "raw": sequence,
                "masked": masked_sequence,
                "mask_positions": masked_positions,
                "key_residues": key_residues,
            },
            "structure": {
                "reference_pdb": str(pdb_path),
                "masked_positions": masked_positions,
            },
            "secondary_structure": {
                "policy": "core_fixed_linker_flexible",
                "max_loop_length": 8,
            },
            "sasa": {
                "channel_polarity": "mixed",
                "surface_preference": "hydrophilic",
                "tunnel_geometry": tunnel_geom,
            },
        },
    }
    write_json_atomic(outputs["prompt_pack"], prompt_pack)

    request = {
        "schema_version": "1.0",
        "num_samples": params.get("config", {}).get("esm3", {}).get("num_samples", 50),
        "temperature": params.get("config", {}).get("esm3", {}).get("temperature", 0.7),
        "max_length_delta": params.get("config", {}).get("esm3", {}).get("max_length_delta", 20),
        "prompt_pack_path": str(outputs["prompt_pack"]),
    }
    outputs["esm3_request"].write_text(
        yaml.safe_dump(request, sort_keys=False),
        encoding="utf-8",
    )
