from __future__ import annotations

import ast
from pathlib import Path


_FORBIDDEN_SCENARIO_NAMES = frozenset(
    {
        "CoreRepositories",
        "MagicMock",
        "Mock",
        "SimpleNamespace",
        "SQLiteRepositoryProvider",
        "build_local_eval_foundation",
        "v3_legacy_repositories_for_tests",
    }
)
_FORBIDDEN_SCENARIO_MODULES = frozenset(
    {
        "openzyme_host_api.foundation",
        "openzyme_core.repositories",
        "sqlite3",
        "httpx",
        "paramiko",
        "requests",
        "socket",
        "subprocess",
        "urllib.request",
    }
)


class QualificationSourcePolicyError(ValueError):
    code = "architecture_qualification_source_policy_invalid"


def validate_qualification_scenario_sources(
    *,
    repo_root: Path,
    source_files: tuple[str, ...],
) -> None:
    """Keep qualification scenarios on public contracts instead of fixture truth."""

    violations: list[str] = []
    for relative in sorted(set(source_files)):
        path = repo_root / relative
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            raise QualificationSourcePolicyError(
                f"qualification scenario source {relative!r} is unreadable"
            ) from exc
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in _FORBIDDEN_SCENARIO_NAMES:
                violations.append(f"{relative}:{node.lineno}:name:{node.id}")
            elif isinstance(node, ast.Attribute) and node.attr in _FORBIDDEN_SCENARIO_NAMES:
                violations.append(f"{relative}:{node.lineno}:attribute:{node.attr}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name in _FORBIDDEN_SCENARIO_MODULES:
                        violations.append(
                            f"{relative}:{node.lineno}:module:{alias.name}"
                        )
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                if module in _FORBIDDEN_SCENARIO_MODULES:
                    violations.append(f"{relative}:{node.lineno}:module:{module}")
                for alias in node.names:
                    if alias.name in _FORBIDDEN_SCENARIO_NAMES:
                        violations.append(
                            f"{relative}:{node.lineno}:import:{alias.name}"
                        )
    if violations:
        raise QualificationSourcePolicyError(
            "qualification scenarios bypass public boundaries: "
            + ", ".join(sorted(violations))
        )


__all__ = [
    "QualificationSourcePolicyError",
    "validate_qualification_scenario_sources",
]
