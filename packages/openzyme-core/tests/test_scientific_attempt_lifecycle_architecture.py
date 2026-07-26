from __future__ import annotations

import ast
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
LIFECYCLE_DECISION_MODULES = (
    "packages/openzyme-core/src/openzyme_core/scientific_attempts.py",
    "packages/openzyme-core/src/openzyme_core/agent_runtime.py",
    "packages/openzyme-core/src/openzyme_core/runtime_consistency.py",
    "apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_live.py",
    "apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_tool_policy.py",
)
ATTEMPT_REPOSITORY_MODULE = (
    "packages/openzyme-core/src/openzyme_core/"
    "scientific_attempt_repositories.py"
)


def _attempt_variable(attribute: ast.Attribute) -> str | None:
    value = attribute.value
    if not isinstance(value, ast.Name):
        return None
    if value.id == "attempt" or value.id.endswith("_attempt"):
        return value.id
    return None


def test_business_lifecycle_decisions_do_not_read_raw_attempt_status() -> None:
    violations: list[str] = []
    for relative_path in LIFECYCLE_DECISION_MODULES:
        path = REPOSITORY_ROOT / relative_path
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative_path)
        for node in ast.walk(tree):
            if (
                isinstance(node, ast.Attribute)
                and node.attr == "status"
                and (variable := _attempt_variable(node)) is not None
            ):
                violations.append(
                    f"{relative_path}:{node.lineno}:{variable}.status"
                )

    assert violations == []


def test_attempt_repository_has_no_status_replacement_seam() -> None:
    path = REPOSITORY_ROOT / ATTEMPT_REPOSITORY_MODULE
    tree = ast.parse(
        path.read_text(encoding="utf-8"),
        filename=ATTEMPT_REPOSITORY_MODULE,
    )
    replacements = [
        node.lineno
        for node in ast.walk(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
        and node.name == "replace_status"
    ]

    assert replacements == []
