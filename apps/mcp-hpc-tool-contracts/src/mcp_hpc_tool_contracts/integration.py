from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from .constants import ADAPTER_IDS
from .runner_client import RunnerClient
from .service import run_adapter


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-hpc-tool-contracts-integration")
    parser.add_argument("--params-file", type=Path, required=True)
    parser.add_argument("--runner-config", type=Path, default=None)
    parser.add_argument("--runner-bin", type=str, default=None)
    parser.add_argument("--async", action="store_true", dest="asynchronous")
    parser.add_argument("--wait", action="store_true")
    parser.add_argument("--poll-seconds", type=int, default=10)
    parser.add_argument("--max-polls", type=int, default=120)
    parser.add_argument("--pretty", action="store_true")
    return parser.parse_args(argv)


def _load_params(path: Path) -> dict[str, dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("Integration params file must be a JSON object")
    resolved: dict[str, dict[str, Any]] = {}
    for adapter_id in ADAPTER_IDS:
        if adapter_id not in payload:
            continue
        adapter_params = payload[adapter_id]
        if not isinstance(adapter_params, dict):
            raise ValueError(f"Params for adapter '{adapter_id}' must be a JSON object")
        resolved[adapter_id] = adapter_params
    return resolved


def run_smoke_suite(
    adapter_payloads: dict[str, dict[str, Any]],
    *,
    runner_config: str | Path | None,
    runner_bin: str | None = None,
    asynchronous: bool,
    wait: bool,
    poll_seconds: int,
    max_polls: int,
) -> dict[str, Any]:
    resolved_bin = runner_bin or os.getenv("HPC_TOOL_CONTRACTS_RUNNER_BIN", "mcp-hpc-runner")
    client = RunnerClient(runner_bin=resolved_bin, runner_config=runner_config)
    results: dict[str, Any] = {}
    for adapter_id in ADAPTER_IDS:
        if adapter_id not in adapter_payloads:
            continue
        result = run_adapter(
            adapter_id,
            adapter_payloads[adapter_id],
            asynchronous=asynchronous,
            wait=wait,
            poll_seconds=poll_seconds,
            max_polls=max_polls,
            runner_client=client,
        )
        results[adapter_id] = result
    return results


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    payloads = _load_params(args.params_file)
    if not payloads:
        raise ValueError("No adapter payloads found in params file")
    results = run_smoke_suite(
        payloads,
        runner_config=args.runner_config,
        runner_bin=args.runner_bin,
        asynchronous=args.asynchronous,
        wait=args.wait,
        poll_seconds=args.poll_seconds,
        max_polls=args.max_polls,
    )
    if args.pretty:
        print(json.dumps(results, indent=2, sort_keys=True))
    else:
        print(json.dumps(results))
    return 0
