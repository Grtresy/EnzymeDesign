from __future__ import annotations

import json
from pathlib import Path

import pytest

from enzyme_host_cli.workspace import allocate_episode_id
from enzyme_host_cli.workspace import find_project_root
from enzyme_host_cli.workspace import init_project
from enzyme_host_cli.workspace import read_cli_state
from enzyme_host_cli.workspace import set_current_episode


def test_init_project_creates_workspace_skeleton(tmp_path: Path) -> None:
    context = init_project(tmp_path, "demo-project")

    assert context.root == tmp_path / "demo-project"
    assert (context.root / "enzyme.yaml").exists()
    assert (context.root / "data" / "inputs").is_dir()
    assert (context.root / "data" / "refs").is_dir()
    assert (context.root / "episodes").is_dir()
    assert (context.root / ".enzyme" / "cli_state.json").exists()

    cli_state = json.loads((context.root / ".enzyme" / "cli_state.json").read_text(encoding="utf-8"))
    assert cli_state["current_episode_id"] is None
    assert cli_state["project_id"] == "demo-project"


def test_allocate_episode_id_is_deterministic(tmp_path: Path) -> None:
    context = init_project(tmp_path, "demo-project")
    (context.root / "episodes" / "0001").mkdir()
    (context.root / "episodes" / "0002").mkdir()

    assert allocate_episode_id(context.root) == "0003"


def test_find_project_root_walks_parents(tmp_path: Path) -> None:
    context = init_project(tmp_path, "demo-project")
    nested = context.root / "episodes" / "0001"
    nested.mkdir(parents=True)

    assert find_project_root(nested) == context.root


def test_set_current_episode_updates_cli_state(tmp_path: Path) -> None:
    context = init_project(tmp_path, "demo-project")

    state = set_current_episode(context.root, "0001")

    assert state.current_episode_id == "0001"
    assert read_cli_state(context.root).current_episode_id == "0001"


def test_init_project_rejects_duplicate_directory(tmp_path: Path) -> None:
    init_project(tmp_path, "demo-project")

    with pytest.raises(RuntimeError):
        init_project(tmp_path, "demo-project")
