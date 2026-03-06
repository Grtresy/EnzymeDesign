from __future__ import annotations

import anyio
import json
from pathlib import Path

import pytest

from mcp_project_memory.server import create_server


@pytest.fixture
def config_path(tmp_path: Path) -> Path:
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
    return config_path


def test_list_tools_has_expected_surface(config_path: Path) -> None:
    server = create_server(str(config_path))

    async def run() -> None:
        tools = await server.mcp.list_tools()
        assert [tool.name for tool in tools] == [
            "update_episode_state",
            "record_decision",
            "confirm_plan",
            "save_structure_annotations",
            "import_experiment_results",
            "archive_episode",
        ]

    anyio.run(run)


def test_resources_are_listed_and_tool_writes_are_readable(config_path: Path) -> None:
    server = create_server(str(config_path))

    async def run() -> None:
        resources = await server.mcp.list_resources()
        resource_uris = {str(resource.uri) for resource in resources}
        assert "enzyme://project/demo/episodes" in resource_uris
        assert "enzyme://project/demo/episode/ep1/state" in resource_uris

        result_blocks = await server.mcp.call_tool(
            "update_episode_state",
            {
                "project_id": "demo",
                "episode_id": "ep1",
                "state": {"status": "ready"},
            },
        )
        payload = json.loads(result_blocks[0][0].text)
        assert payload["status"] == "ready"

        contents = list(await server.mcp.read_resource("enzyme://project/demo/episode/ep1/state"))
        assert json.loads(contents[0].content)["status"] == "ready"

    anyio.run(run)


def test_refresh_resources_removes_deleted_files(config_path: Path) -> None:
    server = create_server(str(config_path))
    state_path = config_path.parent / "workspace" / "demo" / "episodes" / "ep1" / "state.json"

    async def run() -> None:
        resource_uris = {str(resource.uri) for resource in await server.mcp.list_resources()}
        assert "enzyme://project/demo/episode/ep1/state" in resource_uris

        state_path.unlink()
        server.refresh_resources()

        refreshed_uris = {str(resource.uri) for resource in await server.mcp.list_resources()}
        assert "enzyme://project/demo/episode/ep1/state" not in refreshed_uris

    anyio.run(run)


def test_record_decision_refreshes_resources_for_new_workspace(tmp_path: Path) -> None:
    project_root = tmp_path / "workspace" / "demo"
    config_path = tmp_path / "project_memory.toml"
    config_path.write_text(
        f'[projects]\ndemo = "{project_root}"\n',
        encoding="utf-8",
    )
    server = create_server(str(config_path))

    async def run() -> None:
        initial_uris = {str(resource.uri) for resource in await server.mcp.list_resources()}
        assert "enzyme://project/demo/episodes" not in initial_uris

        await server.mcp.call_tool(
            "record_decision",
            {
                "project_id": "demo",
                "episode_id": "ep1",
                "type": "approve",
                "reason": "ready to proceed",
                "author": "alice",
            },
        )

        refreshed_uris = {str(resource.uri) for resource in await server.mcp.list_resources()}
        assert "enzyme://project/demo/episodes" in refreshed_uris

        contents = list(await server.mcp.read_resource("enzyme://project/demo/episodes"))
        payload = json.loads(contents[0].content)
        assert payload["episodes"][0]["episode_id"] == "ep1"

    anyio.run(run)
