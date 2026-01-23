from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import read_json, write_json_atomic


def get_version(mode: str) -> str:
    return "mock-update-constraints-1.0" if mode == "mock" else "real-update-constraints-1.0"


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _read_failures(path: Path) -> List[str]:
    failures = []
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            if row.get("throughput_ok") == "False":
                failures.append(row["candidate_id"])
    return failures


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fixed_mask = _load_yaml(next(p for p in inputs if p.name == "fixed_mask_regions.yaml"))
    prompt_pack = read_json(next(p for p in inputs if p.name == "prompt_pack.json"))
    tunnel_check = next(p for p in inputs if p.name == "tunnel_check.csv")

    failures = _read_failures(tunnel_check)
    fixed_mask["update_notes"] = {
        "mode": mode,
        "tunnel_failures": failures,
    }
    outputs["fixed_mask_regions_updated"].write_text(
        yaml.safe_dump(fixed_mask, sort_keys=False),
        encoding="utf-8",
    )

    prompt_pack["update_notes"] = {"tunnel_failures": failures}
    write_json_atomic(outputs["prompt_pack_updated"], prompt_pack)
