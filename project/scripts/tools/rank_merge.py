from __future__ import annotations

import csv
from pathlib import Path
from typing import Dict, List


def get_version(mode: str) -> str:
    return "mock-rank-merge-1.0" if mode == "mock" else "real-rank-merge-1.0"


def _load_csv(path: Path) -> Dict[str, Dict[str, str]]:
    data: Dict[str, Dict[str, str]] = {}
    with path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            data[row["candidate_id"]] = row
    return data


def _score(row: dict) -> float:
    plddt = float(row.get("pLDDT", 0.0))
    fast = float(row.get("mean_plddt", 0.0))
    affinity = float(row.get("best_affinity", -6.0))
    tunnel_ok = row.get("throughput_ok", "False") == "True"
    score = 0.4 * (plddt / 100.0) + 0.3 * (fast / 100.0) + 0.2 * (-affinity / 10.0)
    if tunnel_ok:
        score += 0.1
    return round(score, 4)


def run(
    inputs: List[Path],
    outputs: Dict[str, Path],
    params: dict,
    workdir: Path,
    mode: str,
) -> None:
    fast_scores = _load_csv(next(p for p in inputs if p.name == "fast_fold_scores.csv"))
    af3_scores = _load_csv(next(p for p in inputs if p.name == "af3_metrics.csv"))
    docking_scores = _load_csv(next(p for p in inputs if p.name == "docking_scores.csv"))
    tunnel_scores = _load_csv(next(p for p in inputs if p.name == "tunnel_check.csv"))

    merged_rows = []
    for candidate_id, fast_row in fast_scores.items():
        merged = {"candidate_id": candidate_id, **fast_row}
        merged.update(af3_scores.get(candidate_id, {}))
        merged.update(docking_scores.get(candidate_id, {}))
        merged.update(tunnel_scores.get(candidate_id, {}))
        merged["score"] = _score(merged)
        merged_rows.append(merged)

    merged_rows.sort(key=lambda row: row["score"], reverse=True)

    metrics_path = outputs["metrics_merged"]
    metrics_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(merged_rows[0].keys()) if merged_rows else ["candidate_id", "score"]
    with metrics_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows)

    top_path = outputs["top_candidates"]
    with top_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(merged_rows[:10])
