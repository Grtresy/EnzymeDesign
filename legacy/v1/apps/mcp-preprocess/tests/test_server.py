from __future__ import annotations

import json

from mcp_preprocess.server import MCPPreprocessServer


def test_tools_list_has_four_tools() -> None:
    server = MCPPreprocessServer()
    response = server._handle_rpc({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})

    tools = response["result"]["tools"]
    assert [tool["name"] for tool in tools] == [
        "convert_format",
        "smiles_to_3d",
        "prepare_receptor",
        "prepare_ligand",
    ]


def test_tools_call_returns_error_payload() -> None:
    server = MCPPreprocessServer()
    response = server._handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "prepare_ligand", "arguments": {}},
        }
    )

    assert response["result"]["isError"] is True
    payload = json.loads(response["result"]["content"][0]["text"])
    assert "error" in payload


def test_initialize_negotiates_protocol_and_ignores_initialized_notification() -> None:
    server = MCPPreprocessServer()
    init_response = server._handle_rpc(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {"protocolVersion": "2025-03-26"},
        }
    )
    assert init_response is not None
    assert init_response["result"]["protocolVersion"] == "2025-03-26"

    notif_response = server._handle_rpc(
        {
            "jsonrpc": "2.0",
            "method": "notifications/initialized",
            "params": {},
        }
    )
    assert notif_response is None


def test_ping_and_shutdown_supported() -> None:
    server = MCPPreprocessServer()
    ping_response = server._handle_rpc({"jsonrpc": "2.0", "id": 7, "method": "ping"})
    assert ping_response is not None
    assert ping_response["result"] == {}

    shutdown_response = server._handle_rpc(
        {"jsonrpc": "2.0", "id": 8, "method": "shutdown"}
    )
    assert shutdown_response is not None
    assert shutdown_response["result"] == {}


def test_unknown_notification_is_ignored() -> None:
    server = MCPPreprocessServer()
    response = server._handle_rpc(
        {"jsonrpc": "2.0", "method": "notifications/some_future_event", "params": {}}
    )
    assert response is None
