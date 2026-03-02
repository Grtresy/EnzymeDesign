from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .cluster_profile import ClusterProfile
from .registry import get_adapter, list_adapters
from .runner_client import RunnerClient
from .service import compile_adapter, run_adapter


class MCPToolContractsServer:
    def __init__(
        self,
        runner_config: str | Path | None = None,
        cluster_config: str | Path | None = None,
    ) -> None:
        self.runner_config = runner_config
        self.profile = (
            ClusterProfile.from_toml(cluster_config)
            if cluster_config
            else ClusterProfile.empty()
        )

    def _tools(self) -> list[dict[str, Any]]:
        tools: list[dict[str, Any]] = []
        for adapter in list_adapters():
            schema = dict(adapter["parameter_schema"])
            schema.setdefault("properties", {})
            schema["properties"] = {
                **schema["properties"],
                "_execute": {"type": "boolean", "default": True},
                "_async": {"type": "boolean", "default": False},
                "_wait": {"type": "boolean", "default": False},
            }
            tools.append(
                {
                    "name": adapter["id"],
                    "description": adapter["description"],
                    "inputSchema": schema,
                }
            )
        return tools

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = dict(arguments or {})
        _execute = bool(args.pop("_execute", True))
        _async = bool(args.pop("_async", False))
        _wait = bool(args.pop("_wait", False))

        get_adapter(name)
        if not _execute:
            return compile_adapter(name, args, profile=self.profile).to_dict()

        client = RunnerClient(runner_config=self.runner_config)
        return run_adapter(
            name,
            args,
            profile=self.profile,
            asynchronous=_async,
            wait=_wait,
            runner_client=client,
        )

    def _handle_rpc(self, request: dict[str, Any]) -> dict[str, Any]:
        rpc_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method == "initialize":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "serverInfo": {
                        "name": "mcp-hpc-tool-contracts",
                        "version": "0.1.0",
                    },
                    "capabilities": {"tools": {}},
                },
            }

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"tools": self._tools()},
            }

        if method == "tools/call":
            tool_name = str(params["name"])
            tool_args = params.get("arguments") or {}
            result = self.call_tool(tool_name, tool_args)
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(result)}],
                    "isError": False,
                },
            }

        return {
            "jsonrpc": "2.0",
            "id": rpc_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        }

    def serve_stdio(self) -> None:
        for raw in sys.stdin:
            line = raw.strip()
            if not line:
                continue
            try:
                request = json.loads(line)
                response = self._handle_rpc(request)
            except Exception as exc:  # noqa: BLE001
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32000, "message": str(exc)},
                }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-hpc-tool-contracts-server")
    parser.add_argument("--runner-config", type=Path, default=None)
    parser.add_argument("--cluster-config", type=Path, default=None)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    # --cluster-config takes precedence; fall back to --runner-config which also
    # embeds [adapters.*] sections in the same toml file.
    cluster_cfg = args.cluster_config or args.runner_config
    server = MCPToolContractsServer(
        runner_config=args.runner_config,
        cluster_config=cluster_cfg,
    )
    server.serve_stdio()
    return 0
