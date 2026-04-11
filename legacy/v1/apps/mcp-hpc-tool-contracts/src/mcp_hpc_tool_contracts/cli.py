from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .registry import list_adapters
from .runner_client import RunnerClient
from .server import MCPToolContractsServer
from .service import compile_adapter, run_adapter


def _parse_params(args: argparse.Namespace) -> dict[str, Any]:
    if args.params_file:
        text = Path(args.params_file).read_text(encoding="utf-8")
        payload = json.loads(text)
    else:
        payload = json.loads(args.params_json)
    if not isinstance(payload, dict):
        raise ValueError("Adapter parameters must be a JSON object")
    return payload


def _print(payload: Any, pretty: bool) -> None:
    if pretty:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(json.dumps(payload))


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-hpc-tool-contracts")
    parser.add_argument(
        "--runner-config",
        type=Path,
        default=None,
        help="Path to mcp-hpc-runner config for run commands",
    )

    subparsers = parser.add_subparsers(dest="command", required=True)

    list_cmd = subparsers.add_parser("list-adapters", help="List available adapter ids")
    list_cmd.add_argument("--pretty", action="store_true")

    compile_cmd = subparsers.add_parser("compile", help="Compile params into RunSpec")
    compile_cmd.add_argument("--adapter", required=True)
    compile_group = compile_cmd.add_mutually_exclusive_group(required=True)
    compile_group.add_argument("--params-json")
    compile_group.add_argument("--params-file", type=Path)
    compile_cmd.add_argument("--pretty", action="store_true")

    run_cmd = subparsers.add_parser("run", help="Compile and run via mcp-hpc-runner")
    run_cmd.add_argument("--adapter", required=True)
    run_group = run_cmd.add_mutually_exclusive_group(required=True)
    run_group.add_argument("--params-json")
    run_group.add_argument("--params-file", type=Path)
    run_cmd.add_argument("--async", action="store_true", dest="asynchronous")
    run_cmd.add_argument("--wait", action="store_true")
    run_cmd.add_argument("--poll-seconds", type=int, default=5)
    run_cmd.add_argument("--max-polls", type=int, default=120)
    run_cmd.add_argument("--pretty", action="store_true")

    serve_cmd = subparsers.add_parser("serve", help="Run MCP stdio server")
    serve_cmd.add_argument("--runner-config", type=Path, default=None)

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])

    if args.command == "list-adapters":
        _print(list_adapters(), args.pretty)
        return 0

    if args.command == "compile":
        params = _parse_params(args)
        compiled = compile_adapter(args.adapter, params)
        _print(compiled.to_dict(), args.pretty)
        return 0

    if args.command == "run":
        params = _parse_params(args)
        client = RunnerClient(runner_config=args.runner_config)
        result = run_adapter(
            args.adapter,
            params,
            asynchronous=args.asynchronous,
            wait=args.wait,
            poll_seconds=args.poll_seconds,
            max_polls=args.max_polls,
            runner_client=client,
        )
        _print(result, args.pretty)
        return 0

    if args.command == "serve":
        server = MCPToolContractsServer(runner_config=args.runner_config)
        server.serve_stdio()
        return 0

    raise ValueError(f"Unknown command: {args.command}")
