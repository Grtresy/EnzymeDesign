from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

from .server import MCPHpcServer


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-hpc-runner")
    parser.add_argument("--config", type=Path, default=None, help="Path to TOML config")

    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("serve", help="Run the stdio MCP server")

    list_tools = subparsers.add_parser("list-tools", help="Print tool metadata as JSON")
    list_tools.add_argument("--pretty", action="store_true")

    call_tool = subparsers.add_parser("call-tool", help="Invoke a tool directly")
    call_tool.add_argument("--name", required=True, help="Tool name")
    call_tool.add_argument(
        "--arguments",
        default="{}",
        help="JSON arguments object",
    )

    transport_soak = subparsers.add_parser(
        "transport-soak",
        help="Run an explicitly opted-in, non-scientific real-SSH transport soak",
    )
    transport_soak.add_argument("--iterations", type=int, default=32)
    transport_soak.add_argument("--replace-every", type=int, default=8)
    transport_soak.add_argument("--confirm-real-ssh", action="store_true")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.command == "transport-soak":
        if not args.confirm_real_ssh or os.environ.get(
            "OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN"
        ) != "true":
            raise ValueError(
                "transport-soak requires --confirm-real-ssh and "
                "OPENZYME_HPC_TRANSPORT_SOAK_OPT_IN=true"
            )
        if args.iterations < 1 or args.iterations > 1_000:
            raise ValueError("transport-soak iterations must be between 1 and 1000")
        if args.replace_every < 0 or args.replace_every > args.iterations:
            raise ValueError(
                "transport-soak replace-every must be between 0 and iterations"
            )
    server = MCPHpcServer(args.config)
    closed = False
    try:
        if args.command == "serve":
            server.serve_stdio()
            return 0

        if args.command == "list-tools":
            tools = server._tools()  # noqa: SLF001
            if args.pretty:
                print(json.dumps(tools, indent=2))
            else:
                print(json.dumps(tools))
            return 0

        if args.command == "call-tool":
            payload = json.loads(args.arguments)
            result = server.call_tool(args.name, payload)
            print(json.dumps(result, indent=2, sort_keys=True))
            return 0

        if args.command == "transport-soak":
            if not server.transport_manager.enabled:
                raise ValueError(
                    "transport-soak requires ssh_transport.mode=controlmaster_v1"
                )
            observed_generations: set[int] = set()
            for iteration in range(args.iterations):
                result = server.transport_manager.run_ssh(
                    ["true"],
                    check=False,
                    timeout=server.config.execution.preflight_timeout_seconds,
                    stage="transport_soak",
                )
                observed_generations.add(
                    server.transport_manager.current_generation
                )
                if result.returncode != 0 or result.timed_out:
                    raise RuntimeError(
                        "real-SSH transport soak stopped on an ambiguous or failed channel"
                    )
                if (
                    args.replace_every
                    and (iteration + 1) % args.replace_every == 0
                    and iteration + 1 < args.iterations
                ):
                    current = server.transport_manager.current_generation
                    server.transport_manager.replace_degraded_generation(
                        expected_generation=current
                    )
            shutdown = server.close()
            closed = True
            report = {
                "schema_version": "ssh_transport_soak_report@1",
                "kind": "non_scientific_real_ssh",
                "iterations": args.iterations,
                "generation_count": len(observed_generations),
                "clean_shutdown": bool(shutdown.get("clean")),
            }
            print(json.dumps(report, indent=2, sort_keys=True))
            return 0

        raise ValueError(f"Unknown command: {args.command}")
    finally:
        if not closed:
            server.close()
