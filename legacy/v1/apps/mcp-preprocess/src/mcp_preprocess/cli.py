from __future__ import annotations

import argparse
import sys

from .server import MCPPreprocessServer


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-preprocess")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("serve", help="Run MCP preprocess stdio server")

    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.command == "serve":
        MCPPreprocessServer().serve_stdio()
        return 0

    raise ValueError(f"Unknown command: {args.command}")
