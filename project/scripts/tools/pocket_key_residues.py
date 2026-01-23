from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import read_json


def get_version(mode: str) -> str:
    return "mock-pocket-keys-1.0" if mode == "mock" else "real-pocket-keys-1.0"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    pockets = read_json(next(p for p in inputs if p.name == "pockets.json"))
    pocket_list = pockets.get("pockets") or []
    pocket = max(pocket_list, key=lambda item: item.get("volume", 0.0), default=None)
    residues = pocket.get("residues", []) if pocket else []
    payload = {
        "schema_version": "1.0",
        "pocket_id": pocket.get("pocket_id") if pocket else None,
        "key_residues": [{"uid": uid, "source": "fpocket"} for uid in residues],
    }
    outputs["pocket_key_residues"].write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
