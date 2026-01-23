#!/usr/bin/env python3
import argparse
import hashlib
import json
import os
import shutil
import time
import uuid
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
TOOL_META_SCHEMA = "tool_meta.schema.json"
TOOL_VERSION = "0.1.0"
META_SCHEMA_VERSION = "1.0"
DEFAULT_CACHE_MODE = "copy"
OPTIONAL_TOOLS = {"pockets", "tunnels", "docking"}


class ToolError(RuntimeError):
    pass


class TransientToolError(ToolError):
    pass


class DeterministicToolError(ToolError):
    pass


def schema_path_for_output(output_path: Path, schema_dir: Path) -> Path:
    if output_path.suffix != ".json":
        raise ValueError(f"Output {output_path} is not JSON")
    schema_name = SCHEMA_MAP.get(output_path.stem)
    if not schema_name:
        raise ValueError(f"No schema defined for JSON output {output_path.name}")
    return schema_dir / schema_name


def build_json_payload(
    tool: str, inputs: Iterable[str], output_path: Path, overrides: dict | None = None
) -> dict:
    stem = output_path.stem
    timestamp = datetime.now(timezone.utc).isoformat()
    inputs_list = list(inputs)
    if stem == "variant":
        return {
            "schema_version": "1.0",
            "tool_name": tool,
            "tool_version": TOOL_VERSION,
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
        payload = {
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
        if overrides:
            payload.update(overrides)
        return payload
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
    if overrides:
        return {**{"tool": tool, "inputs": inputs_list}, **overrides}
    return {"tool": tool, "inputs": inputs_list}


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_text(content)
    temp_path.replace(path)


def atomic_write_bytes(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp_path = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    temp_path.write_bytes(content)
    temp_path.replace(path)


def write_output(
    path: Path,
    tool: str,
    inputs: Iterable[str],
    *,
    overrides: dict | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        payload = build_json_payload(tool, inputs, path, overrides=overrides)
        atomic_write_text(path, json.dumps(payload, indent=2))
    elif path.suffix == ".csv":
        atomic_write_text(path, "variant_id,score\nplaceholder,0.0\n")
    else:
        atomic_write_text(path, f"Generated by {tool}\n")


def parse_params(param_items: list[str]) -> dict:
    params = {}
    for item in param_items:
        if "=" not in item:
            params[item] = True
            continue
        key, value = item.split("=", 1)
        try:
            params[key] = json.loads(value)
        except json.JSONDecodeError:
            params[key] = value
    return params


def compute_inputs_hash(inputs: Iterable[str]) -> str:
    hasher = hashlib.sha256()
    for input_path in sorted(inputs):
        hasher.update(input_path.encode("utf-8"))
        path = Path(input_path)
        if not path.exists():
            hasher.update(b":missing")
            continue
        if path.is_file():
            hasher.update(path.read_bytes())
        else:
            hasher.update(b":nonfile")
    return hasher.hexdigest()


def compute_cache_key(
    tool: str,
    inputs: Iterable[str],
    params: dict,
    *,
    tool_version: str,
    schema_version: str,
) -> str:
    payload = {
        "tool": tool,
        "input_hash": compute_inputs_hash(inputs),
        "params": params,
        "tool_version": tool_version,
        "schema_version": schema_version,
    }
    encoded = json.dumps(payload, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def cache_root() -> Path:
    env_dir = os.getenv("RUN_TOOL_CACHE_DIR")
    if env_dir:
        return Path(env_dir)
    return Path(__file__).resolve().parents[1] / ".cache" / "run_tool"


def cache_paths(cache_dir: Path, cache_key: str, outputs: Iterable[Path]) -> dict[Path, Path]:
    cache_entries = {}
    for output in outputs:
        cache_entries[output] = cache_dir / cache_key / output.name
        if output.suffix == ".json":
            cache_entries[meta_path_for_output(output)] = cache_dir / cache_key / meta_path_for_output(output).name
    return cache_entries


def meta_path_for_output(output_path: Path) -> Path:
    return output_path.with_suffix(output_path.suffix + ".meta.json")


def build_meta_payload(
    tool: str,
    inputs: Iterable[str],
    outputs: Iterable[Path],
    params: dict,
    *,
    run_id: str,
    needs_review: bool = False,
    review_reason: str | None = None,
) -> dict:
    payload = {
        "schema_version": META_SCHEMA_VERSION,
        "tool_name": tool,
        "tool_version": TOOL_VERSION,
        "run_id": run_id,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "inputs": list(inputs),
        "outputs": [str(output) for output in outputs],
        "parameters": dict(params),
    }
    if needs_review:
        payload["parameters"]["needs_review"] = True
        if review_reason:
            payload["parameters"]["needs_review_reason"] = review_reason
    return payload


def atomic_copy_to_cache(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp_path = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    shutil.copy2(source, temp_path)
    temp_path.replace(destination)


def link_or_copy(source: Path, destination: Path, mode_order: list[str]) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        destination.unlink()
    for mode in mode_order:
        try:
            if mode == "hardlink":
                os.link(source, destination)
                return
            if mode == "symlink":
                os.symlink(source, destination)
                return
            if mode == "copy":
                shutil.copy2(source, destination)
                return
        except OSError:
            continue
    raise RuntimeError(f"Failed to restore cache for {destination} using {mode_order}")


def cache_restore(
    cache_dir: Path,
    cache_key: str,
    outputs: list[Path],
    mode: str,
) -> bool:
    cache_entries = cache_paths(cache_dir, cache_key, outputs)
    if not all(entry.exists() for entry in cache_entries.values()):
        return False
    mode_order = [mode, "hardlink", "copy", "symlink"]
    seen = []
    for value in mode_order:
        if value not in seen:
            seen.append(value)
    mode_order = seen
    for source_path, cache_path in cache_entries.items():
        link_or_copy(cache_path, source_path, mode_order)
    return True


def cache_store(cache_dir: Path, cache_key: str, outputs: list[Path]) -> None:
    cache_entries = cache_paths(cache_dir, cache_key, outputs)
    for source_path, cache_path in cache_entries.items():
        if source_path.exists():
            atomic_copy_to_cache(source_path, cache_path)


def should_fail(tool: str, params: dict, context: dict) -> None:
    forced_transient = os.getenv("RUN_TOOL_TRANSIENT_FAIL")
    if forced_transient == tool:
        raise TransientToolError(f"Transient failure injected for {tool}")
    forced_deterministic = os.getenv("RUN_TOOL_DETERMINISTIC_FAIL")
    if forced_deterministic == tool:
        raise DeterministicToolError(f"Deterministic failure injected for {tool}")

    if tool == "volume_metrics" and context.get("structure_repaired") is False:
        for input_path in context.get("inputs", []):
            path = Path(input_path)
            if path.exists() and "REPAIR" in path.read_text(errors="ignore"):
                raise DeterministicToolError("structure_invalid")
    if tool == "tunnels":
        if params.get("start_point") == "invalid" or params.get("probe_radius") == 0:
            raise DeterministicToolError("caver_settings_invalid")


def execute_with_retry(
    func,
    *,
    retries: int = 3,
    base_delay: float = 0.5,
) -> None:
    attempt = 0
    while True:
        try:
            func()
            return
        except TransientToolError:
            attempt += 1
            if attempt > retries:
                raise
            time.sleep(base_delay * (2 ** (attempt - 1)))


def run_stub_tool(
    tool: str,
    inputs: list[str],
    outputs: list[Path],
    params: dict,
    *,
    backend: str | None = None,
    docking_method: str | None = None,
    structure_repaired: bool = False,
    caver_settings: dict | None = None,
) -> None:
    context = {
        "inputs": inputs,
        "structure_repaired": structure_repaired,
    }
    should_fail(tool, params, context)
    overrides = {}
    if docking_method:
        overrides["method"] = docking_method
    for output in outputs:
        if tool == "fold_structure" and output.suffix == ".pdb":
            atomic_write_text(output, f"Generated by {tool} using {backend or 'default'}\n")
        else:
            write_output(output, tool, inputs, overrides=overrides or None)


def write_null_outputs(outputs: list[Path]) -> None:
    for output in outputs:
        if output.suffix == ".json":
            atomic_write_text(output, "null\n")
        else:
            atomic_write_text(output, "")


def validate_json_outputs(outputs: list[Path], schema_dir: Path) -> None:
    for output in outputs:
        if output.suffix != ".json":
            continue
        if output.read_text().strip() == "null":
            continue
        schema_path = schema_path_for_output(output, schema_dir)
        try:
            validate_json_path(output, schema_path)
        except Exception:
            schema = load_schema(schema_path)
            fallback_payload = build_default_instance(schema)
            atomic_write_text(output, json.dumps(fallback_payload, indent=2))
            validate_json_path(output, schema_path)


def write_meta_files(
    tool: str,
    inputs: list[str],
    outputs: list[Path],
    params: dict,
    schema_dir: Path,
    *,
    needs_review: bool = False,
    review_reason: str | None = None,
) -> None:
    run_id = str(uuid.uuid4())
    meta_schema = schema_dir / TOOL_META_SCHEMA
    payload = build_meta_payload(
        tool,
        inputs,
        outputs,
        params,
        run_id=run_id,
        needs_review=needs_review,
        review_reason=review_reason,
    )
    for output in outputs:
        if output.suffix != ".json":
            continue
        meta_path = meta_path_for_output(output)
        atomic_write_text(meta_path, json.dumps(payload, indent=2))
        validate_json_path(meta_path, meta_schema)


def run_with_fallbacks(
    tool: str,
    inputs: list[str],
    outputs: list[Path],
    params: dict,
) -> tuple[bool, str | None]:
    review_reason = None
    if tool == "fold_structure":
        backends = ["esmfold", "colabfold", "alphafold"]
        for backend in backends:
            try:
                execute_with_retry(
                    lambda: run_stub_tool(
                        tool,
                        inputs,
                        outputs,
                        params,
                        backend=backend,
                    )
                )
                params["backend_used"] = backend
                return True, None
            except DeterministicToolError:
                continue
        review_reason = "fold_structure_backend_failed"
    elif tool == "volume_metrics":
        try:
            execute_with_retry(
                lambda: run_stub_tool(
                    tool,
                    inputs,
                    outputs,
                    params,
                    structure_repaired=False,
                )
            )
            return True, None
        except DeterministicToolError:
            execute_with_retry(
                lambda: run_stub_tool(
                    tool,
                    inputs,
                    outputs,
                    params,
                    structure_repaired=True,
                )
            )
            params["structure_repaired"] = True
            return True, None
    elif tool == "docking":
        for method in ["vina", "diffdock"]:
            try:
                execute_with_retry(
                    lambda: run_stub_tool(
                        tool,
                        inputs,
                        outputs,
                        params,
                        docking_method=method,
                    )
                )
                params["docking_method"] = method
                return True, None
            except DeterministicToolError:
                continue
        review_reason = "docking_backends_failed"
    elif tool == "tunnels":
        try:
            execute_with_retry(lambda: run_stub_tool(tool, inputs, outputs, params))
            return True, None
        except DeterministicToolError:
            fallback_params = dict(params)
            fallback_params["start_point"] = "center_of_mass"
            fallback_params["probe_radius"] = 1.5
            execute_with_retry(lambda: run_stub_tool(tool, inputs, outputs, fallback_params))
            params.update(
                {
                    "start_point": fallback_params["start_point"],
                    "probe_radius": fallback_params["probe_radius"],
                }
            )
            return True, None
    else:
        if tool in OPTIONAL_TOOLS:
            try:
                execute_with_retry(lambda: run_stub_tool(tool, inputs, outputs, params))
                return True, None
            except ToolError:
                return False, "optional_tool_failed"
        execute_with_retry(lambda: run_stub_tool(tool, inputs, outputs, params))
        return True, None

    if tool in OPTIONAL_TOOLS:
        return False, review_reason or "optional_tool_failed"
    raise DeterministicToolError(f"{tool} failed with no fallback")


def main() -> None:
    parser = argparse.ArgumentParser(description="Stub runner for pipeline tools.")
    parser.add_argument("tool", help="Tool name to simulate.")
    parser.add_argument("--input", action="append", default=[], dest="inputs")
    parser.add_argument("--output", action="append", default=[], dest="outputs")
    parser.add_argument("--param", action="append", default=[], dest="params")
    args = parser.parse_args()

    if not args.outputs:
        raise SystemExit("No outputs provided to run_tool.py")

    schema_dir = Path(__file__).resolve().parents[1] / "schemas"
    outputs = [Path(output) for output in args.outputs]
    params = parse_params(args.params)
    cache_mode = params.get("cache_mode", os.getenv("RUN_TOOL_CACHE_MODE", DEFAULT_CACHE_MODE))

    cache_key = compute_cache_key(
        args.tool,
        args.inputs,
        params,
        tool_version=TOOL_VERSION,
        schema_version=META_SCHEMA_VERSION,
    )
    cache_dir = cache_root()
    if cache_restore(cache_dir, cache_key, outputs, cache_mode):
        return

    succeeded, review_reason = run_with_fallbacks(args.tool, args.inputs, outputs, params)
    if not succeeded:
        write_null_outputs(outputs)

    validate_json_outputs(outputs, schema_dir)
    write_meta_files(
        args.tool,
        args.inputs,
        outputs,
        params,
        schema_dir,
        needs_review=not succeeded,
        review_reason=review_reason,
    )
    cache_store(cache_dir, cache_key, outputs)


if __name__ == "__main__":
    main()
