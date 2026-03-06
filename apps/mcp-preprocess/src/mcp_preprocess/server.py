from __future__ import annotations

import argparse
import json
import sys
from typing import Any

from preprocess_backend import convert_format, prepare_ligand, prepare_receptor, smiles_to_3d


class MCPPreprocessServer:
    def __init__(self) -> None:
        self._shutdown_requested = False

    def _tools(self) -> list[dict[str, Any]]:
        return [
            {
                "name": "convert_format",
                "description": "Convert molecular files across supported formats (CIF/PDB/SDF/MOL2/PDBQT). For Vina-ready charge models, use prepare_receptor/prepare_ligand.",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "fmt_out": {"type": "string"},
                        "output_path": {"type": "string"},
                    },
                    "required": ["input_path", "fmt_out"],
                },
            },
            {
                "name": "smiles_to_3d",
                "description": "Generate 3D conformers from a SMILES string and write an SDF",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "smiles": {"type": "string"},
                        "output_path": {"type": "string"},
                        "n_confs": {"type": "integer", "minimum": 1, "default": 1},
                    },
                    "required": ["smiles"],
                },
            },
            {
                "name": "prepare_receptor",
                "description": "Prepare receptor PDB into PDBQT using Meeko",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "output_path": {"type": "string"},
                    },
                    "required": ["input_path"],
                },
            },
            {
                "name": "prepare_ligand",
                "description": "Prepare ligand to PDBQT from a file or SMILES string using Meeko",
                "inputSchema": {
                    "type": "object",
                    "properties": {
                        "input_path": {"type": "string"},
                        "smiles": {"type": "string"},
                        "output_path": {"type": "string"},
                    },
                    "additionalProperties": False,
                    # Keep this as docs only: Claude rejects top-level oneOf/anyOf
                    # in custom tool input schemas.
                    "description": "Provide at least one of input_path or smiles.",
                },
            },
        ]

    def call_tool(self, name: str, arguments: dict[str, Any] | None) -> dict[str, Any]:
        args = dict(arguments or {})

        if name == "convert_format":
            result = convert_format(
                input_path=str(args["input_path"]),
                fmt_out=str(args["fmt_out"]),
                output_path=args.get("output_path"),
            )
            return result.to_dict()

        if name == "smiles_to_3d":
            result = smiles_to_3d(
                smiles=str(args["smiles"]),
                output_path=args.get("output_path"),
                n_confs=int(args.get("n_confs", 1)),
            )
            return result.to_dict()

        if name == "prepare_receptor":
            result = prepare_receptor(
                input_path=str(args["input_path"]),
                output_path=args.get("output_path"),
            )
            return result.to_dict()

        if name == "prepare_ligand":
            result = prepare_ligand(
                input_path=args.get("input_path"),
                smiles=args.get("smiles"),
                output_path=args.get("output_path"),
            )
            return result.to_dict()

        raise ValueError(f"Unknown tool: {name}")

    def _handle_rpc(self, request: dict[str, Any]) -> dict[str, Any] | None:
        is_notification = "id" not in request
        rpc_id = request.get("id")
        method = request.get("method")
        params = request.get("params") or {}

        if method == "initialize":
            negotiated_protocol = str(params.get("protocolVersion", "2025-03-26"))
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "protocolVersion": negotiated_protocol,
                    "serverInfo": {
                        "name": "mcp-preprocess",
                        "version": "0.1.0",
                    },
                    "capabilities": {"tools": {}},
                },
            }

        if method == "notifications/initialized":
            return None

        if method == "notifications/cancelled":
            return None

        if method == "notifications/exit":
            self._shutdown_requested = True
            return None

        if method == "ping":
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

        if method == "shutdown":
            self._shutdown_requested = True
            return {"jsonrpc": "2.0", "id": rpc_id, "result": {}}

        if method == "tools/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"tools": self._tools()},
            }

        if method == "resources/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"resources": []},
            }

        if method == "prompts/list":
            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {"prompts": []},
            }

        if method == "tools/call":
            tool_name = str(params["name"])
            tool_args = params.get("arguments") or {}
            try:
                result = self.call_tool(tool_name, tool_args)
                payload = result
                is_error = False
            except Exception as exc:  # noqa: BLE001
                payload = {"error": str(exc), "tool": tool_name}
                is_error = True

            return {
                "jsonrpc": "2.0",
                "id": rpc_id,
                "result": {
                    "content": [{"type": "text", "text": json.dumps(payload)}],
                    "isError": is_error,
                },
            }

        if is_notification:
            return None

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
                if response is None:
                    continue
            except Exception as exc:  # noqa: BLE001
                response = {
                    "jsonrpc": "2.0",
                    "id": None,
                    "error": {"code": -32000, "message": str(exc)},
                }
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()
            if self._shutdown_requested:
                break


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="mcp-preprocess-server")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    _parse_args(argv or sys.argv[1:])
    server = MCPPreprocessServer()
    server.serve_stdio()
    return 0
