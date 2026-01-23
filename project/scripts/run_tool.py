#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

import yaml

from utils.errors import DeterministicToolError, TransientToolError
from utils.hashing import sha256_json, sha256_paths
from utils.io import write_json_atomic
from utils.schema import load_schema, validate_json


SCHEMA_MAP = {
    "snapshot": "snapshot.schema.json",
    "residue_map": "residue_map.schema.json",
    "conservation": "conservation.schema.json",
    "geometry_metrics": "geometry_metrics.schema.json",
    "pockets": "pockets.schema.json",
    "tunnels": "tunnels.schema.json",
    "docking": "docking_any.schema.json",
    "structure_confidence": "structure_confidence.schema.json",
    "score_breakdown": "score_breakdown.schema.json",
}
TOOL_META_SCHEMA = "tool_meta.schema.json"
SCHEMA_VERSION = "1.0"
OPTIONAL_TOOLS = {"fpocket", "caver", "docking"}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def schema_for_output(path: Path, schema_dir: Path) -> Path | None:
    if path.suffix != ".json":
        return None
    schema_name = SCHEMA_MAP.get(path.stem)
    if not schema_name:
        return None
    return schema_dir / schema_name


def output_map(paths: List[Path]) -> Dict[str, Path]:
    mapping: Dict[str, Path] = {}
    for path in paths:
        if path.suffix == ".pdb":
            mapping["pdb"] = path
        elif path.suffix == ".a3m":
            mapping["msa"] = path
        elif path.name == "structure_confidence.json":
            mapping["structure_confidence"] = path
        elif path.suffix == ".json":
            mapping[path.stem] = path
        else:
            mapping[path.stem] = path
    return mapping


def ensure_cache_dir(cache_dir: Path) -> None:
    cache_dir.mkdir(parents=True, exist_ok=True)


def cache_restore(cache_dir: Path, outputs: List[Path], mode: str) -> bool:
    if not cache_dir.exists():
        return False
    for output in outputs:
        cached = cache_dir / output.name
        if not cached.exists():
            return False
    for output in outputs:
        cached = cache_dir / output.name
        output.parent.mkdir(parents=True, exist_ok=True)
        if output.exists():
            output.unlink()
        if mode == "symlink":
            output.symlink_to(cached)
            continue
        if mode == "hardlink":
            try:
                output.hardlink_to(cached)
                continue
            except OSError:
                mode = "copy"
        shutil.copy2(cached, output)
    return True


def cache_store(cache_dir: Path, outputs: List[Path]) -> None:
    ensure_cache_dir(cache_dir)
    temp_dir = cache_dir.with_name(cache_dir.name + ".tmp")
    if temp_dir.exists():
        shutil.rmtree(temp_dir)
    temp_dir.mkdir(parents=True, exist_ok=True)
    for output in outputs:
        shutil.copy2(output, temp_dir / output.name)
    if cache_dir.exists():
        shutil.rmtree(cache_dir)
    temp_dir.rename(cache_dir)


def write_meta(
    meta_path: Path,
    tool: str,
    tool_version: str,
    params: dict,
    inputs: List[Path],
    outputs: List[Path],
    cache_key: str,
    cache_hit: bool,
    exit_code: int,
    retries: int,
    warnings: List[str],
    errors: List[str],
    started_at: str,
    ended_at: str,
    schema_dir: Path,
) -> None:
    meta = {
        "schema_version": SCHEMA_VERSION,
        "tool": tool,
        "tool_version": tool_version,
        "params": params,
        "inputs": [str(p) for p in inputs],
        "outputs": [str(p) for p in outputs],
        "inputs_sha256": sha256_paths(inputs),
        "outputs_sha256": sha256_paths(outputs),
        "cache_key": cache_key,
        "cache_hit": cache_hit,
        "exit_code": exit_code,
        "retries": retries,
        "started_at": started_at,
        "ended_at": ended_at,
        "warnings": warnings,
        "errors": errors,
    }
    schema_path = schema_dir / TOOL_META_SCHEMA
    validate_json(meta, load_schema(schema_path))
    write_json_atomic(meta_path, meta)


def validate_outputs(outputs: List[Path], schema_dir: Path) -> None:
    for output in outputs:
        schema_path = schema_for_output(output, schema_dir)
        if not schema_path:
            continue
        data = json.loads(output.read_text(encoding="utf-8"))
        validate_json(data, load_schema(schema_path))


def write_null_output(tool: str, outputs: List[Path]) -> None:
    payloads = {}
    for output in outputs:
        if output.suffix != ".json":
            continue
        if output.stem == "pockets":
            payloads[output] = {"schema_version": "1.0", "pockets": None}
        elif output.stem == "tunnels":
            payloads[output] = {"schema_version": "1.0", "tunnels": None}
        elif output.stem == "docking":
            payloads[output] = {
                "schema_version": "1.0",
                "method": "none",
                "best_affinity": None,
                "top_confidence": None,
                "poses": None,
            }
    for path, payload in payloads.items():
        write_json_atomic(path, payload)


def run_tool(tool: str, inputs: List[Path], outputs: List[Path], mode: str, config: dict) -> None:
    workdir = Path(outputs[0]).parents[2] / "work" / tool
    workdir.mkdir(parents=True, exist_ok=True)
    sys.path.append(str(Path(__file__).resolve().parent))
    if tool == "fold_structure":
        module_name = "tools.fold"
    elif tool == "init_variant_inputs":
        module_name = "tools.init_variant_inputs"
    elif tool == "residue_map":
        module_name = "tools.residue_map"
    elif tool == "hhblits":
        module_name = "tools.hhblits"
    elif tool == "conservation":
        module_name = "tools.conservation"
    elif tool == "volume_metrics":
        module_name = "tools.volume_metrics"
    elif tool == "fpocket":
        module_name = "tools.fpocket"
    elif tool == "caver":
        module_name = "tools.caver"
    elif tool == "docking":
        module_name = "tools.docking"
    else:
        raise DeterministicToolError(f"Unknown tool {tool}")

    module = __import__(module_name, fromlist=["run", "get_version"])
    params = {
        "mode": mode,
        "config": config,
        "tool": tool,
    }
    module.run(inputs=inputs, outputs=output_map(outputs), params=params, workdir=workdir, mode=mode)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Unified tool runner")
    parser.add_argument("tool", help="Tool name")
    parser.add_argument("--input", dest="inputs", action="append", required=True)
    parser.add_argument("--output", dest="outputs", action="append", required=True)
    parser.add_argument("--mode", choices=["mock", "real"], default=None)
    parser.add_argument("--fail-tool", default=None)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    repo_root = Path(__file__).resolve().parents[1]
    config_path = repo_root / "config" / "config.yaml"
    target_spec_path = repo_root / "config" / "target_spec.yaml"
    config = load_yaml(config_path)
    target_spec = load_yaml(target_spec_path)
    config["target_spec"] = target_spec
    mode = args.mode or config.get("mode", "mock")

    inputs = [Path(p) for p in args.inputs]
    outputs = [Path(p) for p in args.outputs]

    schema_dir = repo_root / "schemas"
    tool = args.tool
    fail_tool = args.fail_tool or config.get("fail_tool")
    if fail_tool and fail_tool == tool:
        raise DeterministicToolError(f"Forced failure for tool {tool}")

    module_name = "tools.fold" if tool == "fold_structure" else f"tools.{tool}"
    module = __import__(module_name, fromlist=["get_version"])
    tool_version = module.get_version(mode)

    params = {
        "mode": mode,
        "tool": tool,
        "config": config,
        "target_spec": target_spec,
    }
    cache_key = sha256_json(
        {
            "tool": tool,
            "tool_version": tool_version,
            "schema_version": SCHEMA_VERSION,
            "inputs_sha": sha256_paths(inputs),
            "params": params,
        }
    )
    cache_dir = repo_root / config.get("cache", {}).get("dir", "cache") / tool / cache_key
    cache_mode = config.get("cache", {}).get("mode", "copy")

    started_at = utc_now()
    warnings: List[str] = []
    errors: List[str] = []
    retries = 0

    if cache_restore(cache_dir, outputs, cache_mode):
        validate_outputs(outputs, schema_dir)
        for output in outputs:
            if output.suffix == ".json":
                meta_path = output.with_suffix(output.suffix + ".meta.json")
                write_meta(
                    meta_path,
                    tool,
                    tool_version,
                    params,
                    inputs,
                    outputs,
                    cache_key,
                    True,
                    0,
                    retries,
                    warnings,
                    errors,
                    started_at,
                    utc_now(),
                    schema_dir,
                )
        return 0

    max_retries = config.get("retries", {}).get("max_retries", 0)
    backoff = config.get("retries", {}).get("backoff_seconds", 1)

    while True:
        try:
            run_tool(tool, inputs, outputs, mode, config)
            validate_outputs(outputs, schema_dir)
            cache_store(cache_dir, outputs)
            for output in outputs:
                if output.suffix == ".json":
                    meta_path = output.with_suffix(output.suffix + ".meta.json")
                    write_meta(
                        meta_path,
                        tool,
                        tool_version,
                        params,
                        inputs,
                        outputs,
                        cache_key,
                        False,
                        0,
                        retries,
                        warnings,
                        errors,
                        started_at,
                        utc_now(),
                        schema_dir,
                    )
            return 0
        except TransientToolError as exc:
            retries += 1
            errors.append(str(exc))
            if retries > max_retries:
                raise
            time.sleep(backoff * retries)
        except DeterministicToolError as exc:
            errors.append(str(exc))
            if tool in OPTIONAL_TOOLS:
                write_null_output(tool, outputs)
                validate_outputs(outputs, schema_dir)
                for output in outputs:
                    if output.suffix == ".json":
                        meta_path = output.with_suffix(output.suffix + ".meta.json")
                        write_meta(
                            meta_path,
                            tool,
                            tool_version,
                            params,
                            inputs,
                            outputs,
                            cache_key,
                            False,
                            1,
                            retries,
                            warnings,
                            errors,
                            started_at,
                            utc_now(),
                            schema_dir,
                        )
                return 0
            raise


if __name__ == "__main__":
    raise SystemExit(main())
