#!/usr/bin/env python3
import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

from utils.schema import build_default_instance, load_schema, validate_json_path

SCHEMA_MAP = {
    "variant": "tool_meta.schema.json",
    "residue_map": "residue_map.schema.json",
    "conservation": "conservation.schema.json",
    "volume_metrics": "geometry_metrics.schema.json",
    "pockets": "pockets.schema.json",
    "tunnels": "tunnels.schema.json",
    "docking": "docking_any.schema.json",
    "score_breakdown": "score_breakdown.schema.json",
}


def schema_path_for_output(output_path: Path, schema_dir: Path) -> Path:
    if output_path.suffix != ".json":
        raise ValueError(f"Output {output_path} is not JSON")
    schema_name = SCHEMA_MAP.get(output_path.stem)
    if not schema_name:
        raise ValueError(f"No schema defined for JSON output {output_path.name}")
    return schema_dir / schema_name


def build_json_payload(tool: str, inputs: Iterable[str], output_path: Path) -> dict:
    stem = output_path.stem
    timestamp = datetime.now(timezone.utc).isoformat()
    inputs_list = list(inputs)
    if stem == "variant":
        return {
            "schema_version": "1.0",
            "tool_name": tool,
            "tool_version": "0.1.0",
            "run_id": "run-placeholder",
            "generated_at": timestamp,
            "inputs": inputs_list,
            "outputs": [str(output_path)],
            "parameters": {},
        }
    if stem == "residue_map":
        return {
            "schema_version": "1.0",
            "source_sequence": "ACDE",
            "target_sequence": "ACDE",
            "mappings": [
                {
                    "source_index": 1,
                    "target_index": 1,
                    "source_residue": "A",
                    "target_residue": "A",
                    "mapping_type": "aligned",
                }
            ],
        }
    if stem == "conservation":
        return {
            "schema_version": "1.0",
            "method": "placeholder",
            "window_size": 5,
            "residues": [
                {
                    "position": 1,
                    "residue": "A",
                    "score": 0.5,
                    "conservation_class": "medium",
                }
            ],
        }
    if stem == "volume_metrics":
        return {
            "schema_version": "1.0",
            "variant_id": "placeholder",
            "metrics": {
                "bond_length_rmsd": 0.1,
                "bond_angle_rmsd": 1.2,
                "clashscore": 5.0,
                "ramachandran_outliers": 0.0,
                "rotamer_outliers": 0.0,
                "packing_density": 0.8,
            },
            "units": {
                "bond_length_rmsd": "angstrom",
                "bond_angle_rmsd": "degree",
            },
        }
    if stem == "pockets":
        return {
            "schema_version": "1.0",
            "pockets": [
                {
                    "pocket_id": "pocket-1",
                    "volume": 120.5,
                    "score": 0.7,
                    "center": [0.0, 0.0, 0.0],
                    "residues": [1, 2, 3],
                }
            ],
        }
    if stem == "tunnels":
        return {
            "schema_version": "1.0",
            "tunnels": [
                {
                    "tunnel_id": "tunnel-1",
                    "length": 15.4,
                    "bottleneck_radius": 1.2,
                    "curvature": 0.3,
                    "path": [
                        {"x": 0.0, "y": 0.0, "z": 0.0, "radius": 1.2},
                        {"x": 1.0, "y": 0.5, "z": 0.2, "radius": 1.5},
                    ],
                }
            ],
        }
    if stem == "docking":
        return {
            "schema_version": "1.0",
            "method": "placeholder",
            "receptor_id": "target",
            "ligand_id": "ligand",
            "poses": [
                {
                    "pose_id": "pose-1",
                    "score": -7.5,
                    "binding_energy": -30.2,
                    "rmsd": 1.1,
                    "interactions": ["H-bond", "hydrophobic"],
                }
            ],
        }
    if stem == "score_breakdown":
        return {
            "schema_version": "1.0",
            "variant_id": "placeholder",
            "total_score": -1.2,
            "components": [
                {
                    "name": "geometry",
                    "score": -0.5,
                    "weight": 0.5,
                    "category": "geometry",
                    "description": "Geometry quality contribution.",
                },
                {
                    "name": "binding",
                    "score": -0.7,
                    "weight": 0.5,
                    "category": "binding",
                    "description": "Binding energy contribution.",
                },
            ],
            "metadata": {
                "tool": tool,
                "generated_at": timestamp,
                "inputs": inputs_list,
            },
        }
    return {"tool": tool, "inputs": inputs_list}


def write_output(path: Path, tool: str, inputs: Iterable[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        payload = build_json_payload(tool, inputs, path)
        path.write_text(json.dumps(payload, indent=2))
    elif path.suffix == ".csv":
        path.write_text("variant_id,score\nplaceholder,0.0\n")
    else:
        path.write_text(f"Generated by {tool}\n")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stub runner for pipeline tools.")
    parser.add_argument("tool", help="Tool name to simulate.")
    parser.add_argument("--input", action="append", default=[], dest="inputs")
    parser.add_argument("--output", action="append", default=[], dest="outputs")
    args = parser.parse_args()

    if not args.outputs:
        raise SystemExit("No outputs provided to run_tool.py")

    schema_dir = Path(__file__).resolve().parents[1] / "schemas"

    for output in args.outputs:
        output_path = Path(output)
        write_output(output_path, args.tool, args.inputs)

        if output_path.suffix == ".json":
            schema_path = schema_path_for_output(output_path, schema_dir)
            try:
                validate_json_path(output_path, schema_path)
            except Exception:
                schema = load_schema(schema_path)
                fallback_payload = build_default_instance(schema)
                output_path.write_text(json.dumps(fallback_payload, indent=2))
                validate_json_path(output_path, schema_path)


if __name__ == "__main__":
    main()
