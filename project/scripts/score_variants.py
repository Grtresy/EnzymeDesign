#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from utils.schema import load_schema, validate_json


@dataclass(frozen=True)
class ScoreComponent:
    name: str
    score: float | None
    weight: float
    category: str
    description: str


def clamp(value: float, minimum: float = 0.0, maximum: float = 1.0) -> float:
    return max(minimum, min(maximum, value))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def normalize_score(value: float, *, max_value: float) -> float:
    if max_value <= 0:
        return 0.0
    return clamp(value / max_value)


def compute_structure_score(structure: dict[str, Any], geometry: dict[str, Any]) -> float:
    confidence = float(structure.get("global_confidence", 0.0))
    confidence_score = normalize_score(confidence, max_value=100.0)
    metrics = geometry.get("metrics", {})
    clashscore = float(metrics.get("clashscore", 50.0))
    rama = float(metrics.get("ramachandran_outliers", 5.0))
    rotamer = float(metrics.get("rotamer_outliers", 5.0))
    bond_length = float(metrics.get("bond_length_rmsd", 0.5))
    bond_angle = float(metrics.get("bond_angle_rmsd", 5.0))
    density = float(metrics.get("packing_density", 0.0))

    geometry_scores = [
        1.0 - normalize_score(clashscore, max_value=50.0),
        1.0 - normalize_score(rama, max_value=5.0),
        1.0 - normalize_score(rotamer, max_value=5.0),
        1.0 - normalize_score(bond_length, max_value=0.5),
        1.0 - normalize_score(bond_angle, max_value=5.0),
        normalize_score(density, max_value=1.0),
    ]
    geometry_score = sum(geometry_scores) / len(geometry_scores)
    return clamp((confidence_score + geometry_score) / 2.0)


def compute_conservation_score(conservation: dict[str, Any]) -> float:
    residues = conservation.get("residues", [])
    if not residues:
        return 0.0
    scores = [float(res.get("score", 0.0)) for res in residues]
    average = sum(scores) / len(scores)
    max_score = max(scores)
    if max_score <= 1.0:
        return clamp(average)
    if max_score <= 100.0:
        return clamp(average / 100.0)
    return clamp(average / max_score)


def extract_positions(items: list[Any]) -> set[int]:
    positions: set[int] = set()
    for item in items:
        if isinstance(item, int):
            positions.add(item)
        elif isinstance(item, dict):
            position = item.get("position") or item.get("pos")
            if isinstance(position, int):
                positions.add(position)
    return positions


def parse_key_residue_data(payload: dict[str, Any]) -> tuple[set[int], list[dict[str, Any]]]:
    key_positions: set[int] = set()
    if "key_residues" in payload:
        key_positions |= extract_positions(payload.get("key_residues", []))
    if "critical_positions" in payload:
        key_positions |= extract_positions(payload.get("critical_positions", []))
    if "residues" in payload:
        residues = payload.get("residues", [])
        for entry in residues:
            if not isinstance(entry, dict):
                continue
            if entry.get("is_key") or entry.get("role") in {"key", "critical"}:
                position = entry.get("position")
                if isinstance(position, int):
                    key_positions.add(position)
    mutations = payload.get("mutations") or payload.get("changes") or []
    if not isinstance(mutations, list):
        mutations = []
    return key_positions, mutations


def compute_mutation_risk(key_payload: dict[str, Any]) -> float:
    key_positions, mutations = parse_key_residue_data(key_payload)
    if not mutations:
        return 1.0
    risks: list[float] = []
    for mutation in mutations:
        if not isinstance(mutation, dict):
            continue
        risk = mutation.get("risk")
        if risk is None:
            impact = mutation.get("impact")
            impact_map = {"low": 0.2, "medium": 0.5, "high": 0.8}
            risk = impact_map.get(str(impact).lower(), None) if impact is not None else None
        if risk is None:
            position = mutation.get("position")
            if isinstance(position, int) and position in key_positions:
                risk = 0.8
            else:
                risk = 0.3
        risk_value = float(risk)
        if risk_value > 1.0:
            risk_value = risk_value / 100.0
        risks.append(clamp(risk_value))
    if not risks:
        return 1.0
    average_risk = sum(risks) / len(risks)
    return clamp(1.0 - average_risk)


def compute_function_guard_score(
    key_payload: dict[str, Any], docking: dict[str, Any] | None
) -> float:
    key_positions, mutations = parse_key_residue_data(key_payload)
    mutated_positions = extract_positions(mutations)
    if key_positions:
        impacted = len(key_positions & mutated_positions)
        key_guard = 1.0 - (impacted / len(key_positions))
    else:
        key_guard = 1.0

    docking_guard: float | None = None
    if docking:
        poses = docking.get("poses", [])
        if poses:
            scores = [float(pose.get("score", 0.0)) for pose in poses]
            best_score = min(scores)
            docking_guard = clamp((-best_score) / 15.0)
    if docking_guard is None:
        return clamp(key_guard)
    return clamp((key_guard + docking_guard) / 2.0)


def compute_shrink_score(
    shrink_mode: str, pockets: dict[str, Any] | None, tunnels: dict[str, Any] | None
) -> float | None:
    length_score: float | None = None
    compact_score: float | None = None
    if tunnels:
        tunnel_lengths = [float(tunnel.get("length", 0.0)) for tunnel in tunnels.get("tunnels", [])]
        if tunnel_lengths:
            avg_length = sum(tunnel_lengths) / len(tunnel_lengths)
            length_score = 1.0 - clamp((avg_length - 5.0) / 45.0)
    if pockets:
        pocket_volumes = [float(pocket.get("volume", 0.0)) for pocket in pockets.get("pockets", [])]
        if pocket_volumes:
            avg_volume = sum(pocket_volumes) / len(pocket_volumes)
            compact_score = 1.0 - clamp((avg_volume - 50.0) / 450.0)

    if shrink_mode == "length":
        return length_score
    if shrink_mode == "compact":
        return compact_score
    if length_score is None or compact_score is None:
        return None
    return clamp((length_score + compact_score) / 2.0)


def resolve_variant_id(
    explicit_id: str | None, geometry: dict[str, Any] | None, output_path: Path
) -> str:
    if explicit_id:
        return explicit_id
    if geometry and isinstance(geometry.get("variant_id"), str):
        return geometry["variant_id"]
    return output_path.parent.name


def main() -> None:
    parser = argparse.ArgumentParser(description="Score variants and emit score_breakdown.json")
    parser.add_argument("--structure-confidence", type=Path)
    parser.add_argument("--geometry-metrics", type=Path)
    parser.add_argument("--conservation", type=Path)
    parser.add_argument("--key-residues", type=Path)
    parser.add_argument("--hitl-decisions", type=Path)
    parser.add_argument("--pockets", type=Path)
    parser.add_argument("--tunnels", type=Path)
    parser.add_argument("--docking", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--variant-id")
    parser.add_argument("--shrink-mode", choices=["length", "compact", "both"], default="both")
    parser.add_argument("--missing-penalty", type=float, default=-0.2)
    parser.add_argument("--keep-bonus", type=float, default=0.1)
    parser.add_argument(
        "--schema-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "schemas",
    )
    args = parser.parse_args()

    missing_penalties: list[dict[str, Any]] = []
    missing_modules: set[str] = set()

    def mark_missing(module: str, reason: str) -> None:
        if module in missing_modules:
            return
        missing_modules.add(module)
        missing_penalties.append(
            {"module": module, "penalty": args.missing_penalty, "reason": reason}
        )

    def read_optional(path: Path | None, label: str) -> dict[str, Any] | None:
        if path is None:
            return None
        if not path.exists():
            mark_missing(label, f"Missing file {path}")
            return None
        return load_json(path)

    structure = read_optional(args.structure_confidence, "structure_confidence")
    geometry = read_optional(args.geometry_metrics, "geometry_metrics")
    conservation = read_optional(args.conservation, "conservation")
    key_residues = read_optional(args.key_residues, "key_residues")
    hitl = read_optional(args.hitl_decisions, "hitl_decisions")
    pockets = read_optional(args.pockets, "pockets")
    tunnels = read_optional(args.tunnels, "tunnels")
    docking = read_optional(args.docking, "docking")

    components: list[ScoreComponent] = []

    if structure is None or geometry is None:
        if structure is None:
            mark_missing("structure_confidence", "Required for S_struct")
        if geometry is None:
            mark_missing("geometry_metrics", "Required for S_struct")
        s_struct = None
    else:
        s_struct = compute_structure_score(structure, geometry)
    components.append(
        ScoreComponent(
            name="S_struct",
            score=s_struct,
            weight=0.2,
            category="geometry",
            description="Structure confidence and geometry quality.",
        )
    )

    if conservation is None:
        mark_missing("conservation", "Required for S_cons")
        s_cons = None
    else:
        s_cons = compute_conservation_score(conservation)
    components.append(
        ScoreComponent(
            name="S_cons",
            score=s_cons,
            weight=0.15,
            category="stability",
            description="Conservation-derived stability contribution.",
        )
    )

    if key_residues is None:
        mark_missing("key_residues", "Required for S_mut_risk and S_function_guard")
        s_mut_risk = None
        s_function_guard = None
    else:
        s_mut_risk = compute_mutation_risk(key_residues)
        s_function_guard = compute_function_guard_score(key_residues, docking)
    components.append(
        ScoreComponent(
            name="S_mut_risk",
            score=s_mut_risk,
            weight=0.15,
            category="stability",
            description="Mutation risk penalty (higher is safer).",
        )
    )
    components.append(
        ScoreComponent(
            name="S_function_guard",
            score=s_function_guard,
            weight=0.1,
            category="activity",
            description="Guard against key residue disruption.",
        )
    )

    shrink_score = compute_shrink_score(args.shrink_mode, pockets, tunnels)
    if shrink_score is None:
        if args.shrink_mode in {"length", "both"} and tunnels is None:
            mark_missing("tunnels", "Required for shrink_mode length")
        if args.shrink_mode in {"compact", "both"} and pockets is None:
            mark_missing("pockets", "Required for shrink_mode compact")
    components.append(
        ScoreComponent(
            name="S_shrink",
            score=shrink_score,
            weight=0.4,
            category="binding",
            description=f"Shrink main score using mode {args.shrink_mode}.",
        )
    )

    if hitl is None:
        mark_missing("hitl_decisions", "Missing HITL decision")
        decision = "review"
        keep_bonus = 0.0
    else:
        decision = str(hitl.get("decision", "review")).lower()
        keep_bonus = float(hitl.get("bonus", args.keep_bonus)) if decision == "keep" else 0.0

    total_score = 0.0
    for component in components:
        if component.score is None:
            continue
        total_score += component.score * component.weight

    apply_missing_penalties = decision != "keep"
    missing_penalty_total = (
        sum(item["penalty"] for item in missing_penalties) if apply_missing_penalties else 0.0
    )
    total_score += missing_penalty_total

    if decision == "keep":
        total_score += keep_bonus
        components.append(
            ScoreComponent(
                name="HITL_keep_bonus",
                score=keep_bonus,
                weight=1.0,
                category="other",
                description="HITL keep bonus applied.",
            )
        )
    elif decision == "drop":
        total_score = -1.0
        components.append(
            ScoreComponent(
                name="HITL_drop",
                score=-1.0,
                weight=0.0,
                category="other",
                description="HITL drop overrides final score.",
            )
        )

    needs_review = bool(missing_penalties) or decision in {"review", "drop"}

    variant_id = resolve_variant_id(args.variant_id, geometry, args.output)
    inputs = [
        str(path)
        for path in [
            args.structure_confidence,
            args.geometry_metrics,
            args.conservation,
            args.key_residues,
            args.hitl_decisions,
            args.pockets,
            args.tunnels,
            args.docking,
        ]
        if path is not None
    ]

    payload = {
        "schema_version": "1.0",
        "variant_id": variant_id,
        "total_score": total_score,
        "components": [
            {
                "name": component.name,
                "score": component.score,
                "weight": component.weight,
                "category": component.category,
                "description": component.description,
            }
            for component in components
        ],
        "missing_penalties": missing_penalties,
        "needs_review": needs_review,
        "metadata": {
            "tool": "score_variants",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "inputs": inputs,
        },
    }

    schema_path = args.schema_dir / "score_breakdown.schema.json"
    schema = load_schema(schema_path)
    validate_json(payload, schema, str(args.output))

    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, indent=2), encoding="utf-8")


if __name__ == "__main__":
    main()
