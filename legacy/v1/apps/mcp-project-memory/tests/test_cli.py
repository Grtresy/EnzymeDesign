from __future__ import annotations

from pathlib import Path

from mcp_project_memory.cli import _parse_args
from mcp_project_memory.config import load_config
from mcp_project_memory.server import create_server


def test_cli_parses_config_and_serve_subcommand(tmp_path: Path) -> None:
    config_path = tmp_path / "project_memory.toml"
    config_path.write_text("[projects]\n", encoding="utf-8")

    args = _parse_args(["--config", str(config_path), "serve"])
    assert args.command == "serve"
    assert args.config == str(config_path)


def test_server_can_be_created_from_config(tmp_path: Path) -> None:
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

    server = create_server(str(config_path))
    assert server.store.list_project_ids() == ["demo"]


def test_load_config_resolves_relative_paths_from_config_directory(tmp_path: Path) -> None:
    config_dir = tmp_path / "configs"
    config_dir.mkdir()
    config_path = config_dir / "project_memory.toml"
    config_path.write_text(
        'projects_root = "./workspace"\n[projects]\ndemo = "./mapped/demo"\n',
        encoding="utf-8",
    )

    config = load_config(config_path)
    assert config.projects_root == (config_dir / "workspace").resolve()
    assert config.projects["demo"] == (config_dir / "mapped" / "demo").resolve()
