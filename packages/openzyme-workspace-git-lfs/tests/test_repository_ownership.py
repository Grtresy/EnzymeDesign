from __future__ import annotations

import ast
from pathlib import Path

from openzyme_workspace_git_lfs import AgentGitWorkspaceRepository


def test_agent_git_workspace_repository_is_adapter_owned() -> None:
    assert AgentGitWorkspaceRepository.__module__ == (
        "openzyme_workspace_git_lfs.agent_git_workspace_repositories"
    )
    source = (
        Path(__file__).parents[1]
        / "src/openzyme_workspace_git_lfs/agent_git_workspace_repositories.py"
    )
    tree = ast.parse(source.read_text())
    imported_roots = {
        node.module.split(".", 1)[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }

    assert "openzyme_core" not in imported_roots
    assert "openzyme_store_sqlite" not in imported_roots
