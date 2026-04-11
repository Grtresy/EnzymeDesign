from __future__ import annotations

import json
import os
from pathlib import Path
import select
import subprocess

import pytest
from mcp.types import LATEST_PROTOCOL_VERSION


def _write_message(process: subprocess.Popen[str], payload: dict[str, object]) -> None:
    assert process.stdin is not None
    process.stdin.write(json.dumps(payload) + "\n")
    process.stdin.flush()


def _read_message(process: subprocess.Popen[str], timeout: float = 5.0) -> dict[str, object]:
    assert process.stdout is not None
    ready, _, _ = select.select([process.stdout], [], [], timeout)
    if not ready:
        stderr = ""
        if process.stderr is not None:
            ready_err, _, _ = select.select([process.stderr], [], [], 0)
            if ready_err:
                stderr = process.stderr.read()
        raise AssertionError(f"Timed out waiting for stdio response. stderr:\n{stderr}")
    line = process.stdout.readline()
    assert line, "Server closed stdout before responding"
    return json.loads(line)


def test_stdio_roundtrip_raw_jsonrpc(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace" / "demo"
    episode_dir = project_root / "episodes" / "ep1"
    episode_dir.mkdir(parents=True, exist_ok=True)
    (project_root / "enzyme.yaml").write_text("name: demo\n", encoding="utf-8")
    (episode_dir / "goal.md").write_text("# Goal\n", encoding="utf-8")
    (episode_dir / "state.json").write_text('{"status":"draft"}\n', encoding="utf-8")
    (episode_dir / "plan.yaml").write_text('{"steps":["a"]}\n', encoding="utf-8")
    (episode_dir / "annotations.json").write_text('{"notes":["x"]}\n', encoding="utf-8")
    config_path = tmp_path / "project_memory.toml"
    config_path.write_text(
        f'[projects]\ndemo = "{project_root}"\n',
        encoding="utf-8",
    )

    repo_root = Path(__file__).resolve().parents[3]
    python_bin = repo_root / ".venv" / "bin" / "python3"
    env = {
        key: value
        for key, value in os.environ.items()
        if key in {"HOME", "LOGNAME", "PATH", "SHELL", "TERM", "USER"}
    }
    pythonpath = str(repo_root / "apps" / "mcp-project-memory" / "src")
    env["PYTHONPATH"] = (
        f"{pythonpath}{os.pathsep}{env['PYTHONPATH']}"
        if env.get("PYTHONPATH")
        else pythonpath
    )

    process = subprocess.Popen(
        [
            str(python_bin),
            "-m",
            "mcp_project_memory.cli",
            "--config",
            str(config_path),
            "serve",
        ],
        cwd=repo_root,
        env=env,
        text=True,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        bufsize=1,
    )

    try:
        _write_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 0,
                "method": "initialize",
                "params": {
                    "protocolVersion": LATEST_PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": {"name": "pytest", "version": "0.1.0"},
                },
            },
        )
        initialize_response = _read_message(process)
        assert initialize_response["id"] == 0
        assert initialize_response["result"]["protocolVersion"] == LATEST_PROTOCOL_VERSION

        _write_message(
            process,
            {
                "jsonrpc": "2.0",
                "method": "notifications/initialized",
            },
        )

        _write_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
            },
        )
        tools_response = _read_message(process)
        tool_names = [tool["name"] for tool in tools_response["result"]["tools"]]
        assert "archive_episode" in tool_names

        _write_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "resources/list",
            },
        )
        resources_response = _read_message(process)
        resource_uris = {resource["uri"] for resource in resources_response["result"]["resources"]}
        assert "enzyme://project/demo/episode/ep1/state" in resource_uris

        _write_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "update_episode_state",
                    "arguments": {
                        "project_id": "demo",
                        "episode_id": "ep1",
                        "state": {"status": "active"},
                    },
                },
            },
        )
        tool_response = _read_message(process)
        tool_payload = json.loads(tool_response["result"]["content"][0]["text"])
        assert tool_payload["status"] == "active"

        _write_message(
            process,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "resources/read",
                "params": {"uri": "enzyme://project/demo/episode/ep1/state"},
            },
        )
        resource_response = _read_message(process)
        state_payload = json.loads(resource_response["result"]["contents"][0]["text"])
        assert state_payload["status"] == "active"
    finally:
        if process.stdin is not None:
            process.stdin.close()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)

    stderr = process.stderr.read() if process.stderr is not None else ""
    assert process.returncode == 0, stderr
