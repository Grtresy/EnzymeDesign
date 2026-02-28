from __future__ import annotations

import argparse
import json
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

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    server = MCPHpcServer(args.config)

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

    raise ValueError(f"Unknown command: {args.command}")
