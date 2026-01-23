from __future__ import annotations

from pathlib import Path
from typing import Dict, List

import yaml

from utils.io import read_json


def get_version(mode: str) -> str:
    return "mock-fixed-mask-1.0" if mode == "mock" else "real-fixed-mask-1.0"


def _label(cons_score: float, high: float, low: float) -> str:
    if cons_score >= high:
        return "Fixed"
    if cons_score <= low:
        return "Masked"
    return "Optional"


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    conservation = read_json(next(p for p in inputs if p.name == "conservation.json"))
    thresholds = params.get("config", {}).get("conservation_thresholds", {})
    high = float(thresholds.get("fixed", 0.8))
    low = float(thresholds.get("masked", 0.3))

    regions = []
    for idx, residue in enumerate(conservation.get("per_residue", []), start=1):
        cons_score = float(residue.get("cons_score", 0.0))
        regions.append(
            {
                "index": idx,
                "uid": residue.get("uid", ""),
                "cons_score": cons_score,
                "status": _label(cons_score, high, low),
            }
        )

    payload = {
        "schema_version": "1.0",
        "thresholds": {"fixed": high, "masked": low},
        "regions": regions,
    }
    outputs["fixed_mask_regions"].write_text(
        yaml.safe_dump(payload, sort_keys=False),
        encoding="utf-8",
    )
