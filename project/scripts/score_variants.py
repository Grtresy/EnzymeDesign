#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from utils.hashing import sha256_paths
from utils.io import read_json, write_json_atomic
from utils.schema import load_schema, validate_json


def clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def load_config(repo_root: Path) -> dict:
    config_path = repo_root / "config" / "config.yaml"
    target_spec_path = repo_root / "config" / "target_spec.yaml"
    config = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    target_spec = yaml.safe_load(target_spec_path.read_text(encoding="utf-8")) or {}
    config["target_spec"] = target_spec
    return config


def decision_map(csv_path: Path) -> Dict[str, Dict[str, str]]:
    decisions: Dict[str, Dict[str, str]] = {}
    with csv_path.open("r", encoding="utf-8") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            decisions[row["variant_id"]] = row
    return decisions


def score_shrink(metrics: dict, target_spec: dict) -> float:
    shrink_mode = metrics.get("shrink_mode", "both")
    delta_length = metrics["delta_length"]
    delta_volume = metrics["delta_volume"]
    delta_rg = metrics["delta_rg"]
    delta_sasa = metrics["delta_sasa"]
    wt_length = metrics["wt_length"]
    wt_volume = metrics["wt_volume_protein"]
    allow_len = target_spec.get("allow_shrink_by_length", True)
    allow_compact = target_spec.get("allow_shrink_by_compactness", True)

    len_score = clamp((-delta_length) / max(1.0, wt_length * 0.3)) if allow_len else 0.0
    vol_score = clamp((-delta_volume) / max(1.0, wt_volume * 0.3)) if allow_compact else 0.0
    rg_score = clamp((-delta_rg) / max(1.0, metrics["wt_rg"] * 0.3)) if allow_compact else 0.0
    sasa_score = (
        clamp((-delta_sasa) / max(1.0, metrics["wt_sasa_total"] * 0.3))
        if allow_compact
        else 0.0
    )

    if shrink_mode == "length":
        return clamp(0.7 * len_score + 0.3 * vol_score)
    if shrink_mode == "compact":
        length_penalty = 0.1 if delta_length < 0 else 0.0
        return clamp(0.5 * vol_score + 0.3 * rg_score + 0.2 * sasa_score - length_penalty)
    return clamp(0.6 * vol_score + 0.4 * len_score)


def score_struct(conf: dict) -> float:
    mean_plddt = conf.get("mean_plddt", 0.0)
    clash_score = conf.get("clash_score", 10.0)
    return clamp((mean_plddt / 100.0) * clamp(1.0 - clash_score / 20.0))


def score_mutation_risk(residue_map: dict, key_residues: dict) -> float:
    existing = set(residue_map.get("index", {}).get("by_auth", {}).keys())
    protected = {r["uid"] for r in key_residues.get("protected_residues", [])}
    active = {r["uid"] for r in key_residues.get("active_site_residues", [])}
    if protected.intersection(existing) != protected:
        return 0.0
    if active.intersection(existing) != active:
        return 0.2
    return 1.0


def score_conservation(conservation: dict, residue_map: dict) -> float:
    high_cons = [r for r in conservation.get("per_residue", []) if r["cons_score"] > 0.8]
    existing = set(residue_map.get("index", {}).get("by_auth", {}).keys())
    if not high_cons:
        return 0.5
    touched = sum(1 for r in high_cons if r["uid"] in existing)
    return clamp(1.0 - (touched / len(high_cons)) * 0.5)


def score_function_guard(
    pockets: dict | None, tunnels: dict | None, docking: dict | None, target_spec: dict
) -> float:
    if pockets is None and tunnels is None and docking is None:
        return 0.0
    score = 1.0
    guard = target_spec.get("function_guard", {})
    if pockets is not None:
        min_volume = guard.get("pocket_volume_min", 0.0)
        pocket_ok = any(p["volume"] >= min_volume for p in pockets.get("pockets", []))
        score *= 0.8 if pocket_ok else 0.4
    if tunnels is not None:
        min_bottleneck = guard.get("tunnel_bottleneck_min", 0.0)
        tunnel_ok = any(t["bottleneck_radius"] >= min_bottleneck for t in tunnels.get("tunnels", []))
        score *= 0.8 if tunnel_ok else 0.4
    if docking is not None:
        affinity_threshold = guard.get("docking_affinity_threshold", -6.0)
        best_affinity = docking.get("best_affinity")
        docking_ok = best_affinity is not None and best_affinity <= affinity_threshold
        score *= 0.8 if docking_ok else 0.5
    return clamp(score)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Score variants")
    parser.add_argument("--structure-conf", required=True)
    parser.add_argument("--geometry", required=True)
    parser.add_argument("--conservation", required=True)
    parser.add_argument("--residue-map", required=True)
    parser.add_argument("--key-residues", required=True)
    parser.add_argument("--hitl-decisions", required=True)
    parser.add_argument("--pockets", default="")
    parser.add_argument("--tunnels", default="")
    parser.add_argument("--docking", default="")
    parser.add_argument("--output", required=True)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_path = Path(args.output)
    repo_root = Path(__file__).resolve().parents[1]
    schema_dir = repo_root / "schemas"
    started_at = datetime.now(timezone.utc).isoformat()
    config = load_config(repo_root)
    target_spec = config.get("target_spec", {})
    weights = config.get("scoring", {}).get("weights", {})

    structure_conf = read_json(Path(args.structure_conf))
    geometry = read_json(Path(args.geometry))
    conservation = read_json(Path(args.conservation))
    residue_map = read_json(Path(args.residue_map))
    key_residues = read_json(Path(args.key_residues))
    hitl = decision_map(Path(args.hitl_decisions))

    pockets = read_json(Path(args.pockets)) if args.pockets else None
    tunnels = read_json(Path(args.tunnels)) if args.tunnels else None
    docking = read_json(Path(args.docking)) if args.docking else None

    if pockets is not None and pockets.get("pockets") is None:
        pockets = None
    if tunnels is not None and tunnels.get("tunnels") is None:
        tunnels = None
    if docking is not None and docking.get("poses") is None:
        docking = None

    variant_id = output_path.parents[2].name
    decisions = hitl.get(variant_id, {})

    missing_penalties: Dict[str, float] = {}
    needs_review = False
    top_reasons: List[str] = []

    subscores: Dict[str, Any] = {
        "S_shrink": score_shrink(geometry, target_spec),
        "S_struct": score_struct(structure_conf),
        "S_mut_risk": score_mutation_risk(residue_map, key_residues),
        "S_cons": score_conservation(conservation, residue_map),
        "S_function_guard": None,
    }

    if pockets is None or tunnels is None or docking is None:
        if target_spec.get("features", {}).get("pockets", False) and pockets is None:
            missing_penalties["pockets"] = config.get("scoring", {}).get("missing_penalty", 0.05)
        if target_spec.get("features", {}).get("tunnels", False) and tunnels is None:
            missing_penalties["tunnels"] = config.get("scoring", {}).get("missing_penalty", 0.05)
        if target_spec.get("features", {}).get("docking", False) and docking is None:
            missing_penalties["docking"] = config.get("scoring", {}).get("missing_penalty", 0.05)
        if missing_penalties:
            needs_review = True
            top_reasons.append("optional modules missing")
    else:
        subscores["S_function_guard"] = score_function_guard(pockets, tunnels, docking, target_spec)

    checks = {
        "structure_ok": True,
        "metrics_ok": True,
        "optional_ok": not bool(missing_penalties),
    }

    weighted_score = 0.0
    weight_sum = 0.0
    for key, value in subscores.items():
        if value is None:
            continue
        weight = weights.get(key, 0.0)
        weighted_score += weight * value
        weight_sum += weight

    final_score = weighted_score / weight_sum if weight_sum else 0.0
    final_score -= sum(missing_penalties.values())

    if subscores["S_mut_risk"] < 0.5:
        needs_review = True
        top_reasons.append("protected residues affected")

    decision = decisions.get("decision", "").lower()
    if decision == "drop":
        final_score = config.get("scoring", {}).get("drop_score", -1.0)
        needs_review = True
        top_reasons.append(decisions.get("reason", "hitl drop"))
    elif decision == "keep":
        final_score += config.get("scoring", {}).get("keep_bonus", 0.0)
    elif decision:
        needs_review = True
        top_reasons.append(decisions.get("reason", "hitl review"))

    payload = {
        "schema_version": "1.0",
        "variant_id": variant_id,
        "checks": checks,
        "subscores": subscores,
        "missing_penalties": missing_penalties,
        "final_score": float(final_score),
        "needs_review": needs_review,
        "top_reasons": top_reasons,
    }

    validate_json(payload, load_schema(schema_dir / "score_breakdown.schema.json"))
    write_json_atomic(output_path, payload)

    meta = {
        "schema_version": "1.0",
        "tool": "score_variants",
        "tool_version": "1.0",
        "params": {"weights": weights},
        "inputs": [
            args.structure_conf,
            args.geometry,
            args.conservation,
            args.residue_map,
            args.key_residues,
            args.hitl_decisions,
        ],
        "outputs": [str(output_path)],
        "inputs_sha256": sha256_paths(
            [
                Path(args.structure_conf),
                Path(args.geometry),
                Path(args.conservation),
                Path(args.residue_map),
                Path(args.key_residues),
                Path(args.hitl_decisions),
            ]
        ),
        "outputs_sha256": sha256_paths([output_path]),
        "cache_key": "na",
        "cache_hit": False,
        "exit_code": 0,
        "retries": 0,
        "started_at": started_at,
        "ended_at": datetime.now(timezone.utc).isoformat(),
        "warnings": [],
        "errors": [],
    }
    validate_json(meta, load_schema(schema_dir / "tool_meta.schema.json"))
    write_json_atomic(output_path.with_suffix(".json.meta.json"), meta)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
