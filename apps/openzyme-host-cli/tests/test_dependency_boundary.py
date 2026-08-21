from __future__ import annotations

import ast
from pathlib import Path
import tomllib


CLI_ROOT = Path(__file__).parents[1]


def test_cli_runtime_dependencies_are_client_contracts_and_http_only() -> None:
    project = tomllib.loads((CLI_ROOT / "pyproject.toml").read_text())["project"]

    assert set(project["dependencies"]) == {
        "httpx>=0.28,<1.0",
        "openzyme-client",
        "openzyme-contracts",
    }


def test_cli_sources_do_not_import_runtime_or_host_internals() -> None:
    forbidden_roots = {
        "openzyme_core",
        "openzyme_domain",
        "openzyme_host_api",
        "openzyme_runtime",
        "openzyme_runtime_llm",
        "openzyme_store_sqlite",
    }
    for source_path in sorted((CLI_ROOT / "src/openzyme_host_cli").glob("*.py")):
        tree = ast.parse(source_path.read_text())
        imported_roots = {
            node.module.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom) and node.module is not None
        }
        imported_roots.update(
            alias.name.split(".", 1)[0]
            for node in ast.walk(tree)
            if isinstance(node, ast.Import)
            for alias in node.names
        )
        assert forbidden_roots.isdisjoint(imported_roots), source_path.name
