#!/usr/bin/env python3
"""Audit active and compatibility V3 seams without guessing external callers.

The audit intentionally treats the checkout as the only provable caller universe.
An empty in-repository caller set never changes ``external_status`` from
``unknown`` for a published import, entrypoint, or retired public call shape.
"""

from __future__ import annotations

import argparse
import ast
from dataclasses import dataclass
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from typing import Any


SCHEMA_VERSION = "openzyme.v3.compat-caller-audit.v1"
AUDIT_SCRIPT_PATH = "scripts/audit-v3-compat-callers.py"
EXCLUDED_PARTS = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "dist",
        "node_modules",
    }
)
PRODUCTION_CLASSIFICATIONS = frozenset({"production", "production_config"})
NON_PYTHON_SOURCE_SUFFIXES = frozenset(
    {".js", ".json", ".jsx", ".sh", ".toml", ".ts", ".tsx", ".yaml", ".yml"}
)
HTTP_METHODS = frozenset({"delete", "get", "patch", "post", "put"})
RAW_LIFECYCLE_METHODS = frozenset(
    {
        "cancel_execution",
        "fetch_execution_artifacts",
        "get_execution_status",
    }
)
RAW_LIFECYCLE_TOOL_NAMES = frozenset(
    {"job.cancel", "job.fetch_artifacts", "job.logs", "job.status"}
)
RAW_LIFECYCLE_KEYS = frozenset({"job_id", "remote_run_dir", "runspec"})
LEGACY_V1_IMPORT_PREFIXES = (
    "enzyme_host_cli",
    "enzyme_host_runtime",
    "enzyme_web_host",
    "mcp_hpc_tool_contracts",
    "mcp_project_memory",
)


@dataclass(frozen=True, slots=True)
class SeamSpec:
    symbol: str
    path: str
    classification: str
    decision: str
    scanner: str
    owner: str
    external_status: str = "unknown"
    module: str | None = None
    name: str | None = None
    literal: str | None = None
    entrypoint: str | None = None


SEAMS = (
    SeamSpec(
        symbol="openzyme_engines.PodmanPipelineSandboxRunner",
        path="packages/openzyme-engines/src/openzyme_engines/podman_sandbox.py",
        classification="active_capability_runner",
        decision="KEEP",
        scanner="python_symbol",
        module="openzyme_engines",
        name="PodmanPipelineSandboxRunner",
        owner="openzyme-engines",
    ),
    SeamSpec(
        symbol="openzyme_runtime.RuntimeFoundation",
        path="packages/openzyme-runtime/src/openzyme_runtime/bootstrap.py",
        classification="active_shared_seam",
        decision="KEEP",
        scanner="python_symbol",
        module="openzyme_runtime",
        name="RuntimeFoundation",
        owner="openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_runtime.ExecutionAdapter",
        path="packages/openzyme-runtime/src/openzyme_runtime/seams.py",
        classification="active_shared_seam",
        decision="KEEP",
        scanner="python_symbol",
        module="openzyme_runtime",
        name="ExecutionAdapter",
        owner="openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_tools.RepoBackedHpcCatalogProvider",
        path="packages/openzyme-tools/src/openzyme_tools/catalog.py",
        classification="active_authoritative_implementation",
        decision="KEEP",
        scanner="python_symbol",
        module="openzyme_tools",
        name="RepoBackedHpcCatalogProvider",
        owner="openzyme-tools",
    ),
    SeamSpec(
        symbol="openzyme_tools.DefaultHpcExecutionRegistry",
        path="packages/openzyme-tools/src/openzyme_tools/execution.py",
        classification="active_authoritative_implementation",
        decision="KEEP",
        scanner="python_symbol",
        module="openzyme_tools",
        name="DefaultHpcExecutionRegistry",
        owner="openzyme-tools",
    ),
    SeamSpec(
        symbol="openzyme_execution.HpcRunnerExecutionAdapter",
        path="packages/openzyme-execution/src/openzyme_execution/adapter.py",
        classification="active_runner_adapter",
        decision="KEEP",
        scanner="python_symbol",
        module="openzyme_execution",
        name="HpcRunnerExecutionAdapter",
        owner="openzyme-execution",
    ),
    SeamSpec(
        symbol="openzyme_runtime.RepoBackedHpcCatalogProvider",
        path="packages/openzyme-runtime/src/openzyme_runtime/hpc_catalog.py",
        classification="compat_import_shim",
        decision="RETIRE-BLOCKED",
        scanner="python_symbol",
        module="openzyme_runtime",
        name="RepoBackedHpcCatalogProvider",
        owner="openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_runtime.LegacyFunctionToolRuntime",
        path="packages/openzyme-runtime/src/openzyme_runtime/tooling.py",
        classification="active_compat_bridge",
        decision="RETIRE-BLOCKED",
        scanner="python_symbol",
        module="openzyme_runtime",
        name="LegacyFunctionToolRuntime",
        owner="openzyme-core/openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_runtime.DesignTool",
        path="packages/openzyme-runtime/src/openzyme_runtime/seams.py",
        classification="unused_public_compat_seam",
        decision="RETIRE-BLOCKED",
        scanner="python_symbol",
        module="openzyme_runtime",
        name="DesignTool",
        owner="openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_runtime.DesignToolContext",
        path="packages/openzyme-runtime/src/openzyme_runtime/seams.py",
        classification="unused_public_compat_seam",
        decision="RETIRE-BLOCKED",
        scanner="python_symbol",
        module="openzyme_runtime",
        name="DesignToolContext",
        owner="openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_runtime.ToolSpec.to_openai_tool",
        path="packages/openzyme-runtime/src/openzyme_runtime/tooling.py",
        classification="active_provider_compat_helper",
        decision="RETIRE-BLOCKED",
        scanner="python_method",
        name="to_openai_tool",
        owner="openzyme-runtime",
    ),
    SeamSpec(
        symbol="openzyme_engines:execution.pipeline.start",
        path="packages/openzyme-engines/src/openzyme_engines/execution.py",
        classification="active_migration_tool_bridge",
        decision="DEPRECATE",
        scanner="exact_literal",
        literal="execution.pipeline.start",
        owner="openzyme-engines",
    ),
    SeamSpec(
        symbol="openzyme_execution.ExecutionOutcome.remote_run_dir",
        path="packages/openzyme-execution/src/openzyme_execution/adapter.py",
        classification="active_compat_dto_field",
        decision="DEPRECATE",
        scanner="execution_dto_field",
        name="remote_run_dir",
        owner="openzyme-execution",
    ),
    SeamSpec(
        symbol="openzyme_execution.ExecutionOutcome.job_id",
        path="packages/openzyme-execution/src/openzyme_execution/adapter.py",
        classification="unused_compat_dto_field",
        decision="RETIRE-BLOCKED",
        scanner="execution_dto_field",
        name="job_id",
        owner="openzyme-execution",
    ),
    SeamSpec(
        symbol="runner.raw_lifecycle_arguments",
        path="packages/openzyme-execution/src/openzyme_execution/adapter.py",
        classification="retired_public_call_shape",
        decision="RETIRED",
        scanner="raw_runner_lifecycle",
        owner="openzyme-execution/mcp-hpc-runner",
    ),
    SeamSpec(
        symbol="host_api.v1_v2_product_routes",
        path="apps/openzyme-host-api/src/openzyme_host_api/app.py",
        classification="retired_product_surface",
        decision="RETIRED",
        scanner="legacy_http_routes",
        owner="openzyme-host-api",
    ),
    SeamSpec(
        symbol="legacy_v1.active_import_or_workspace_member",
        path="legacy/v1",
        classification="archived_workspace_isolation",
        decision="RETIRED",
        scanner="legacy_v1_activation",
        owner="repository",
    ),
    SeamSpec(
        symbol="cli:openzyme",
        path="apps/openzyme-host-cli/pyproject.toml",
        classification="active_primary_entrypoint",
        decision="KEEP",
        scanner="entrypoint",
        entrypoint="openzyme",
        owner="openzyme-host-cli",
    ),
    SeamSpec(
        symbol="cli:enzyme",
        path="apps/openzyme-host-cli/pyproject.toml",
        classification="compat_entrypoint_alias",
        decision="DEPRECATE",
        scanner="entrypoint",
        entrypoint="enzyme",
        owner="openzyme-host-cli",
    ),
    SeamSpec(
        symbol="cli:mcp-hpc-runner",
        path="apps/mcp-hpc-runner/pyproject.toml",
        classification="active_trusted_host_entrypoint",
        decision="KEEP",
        scanner="entrypoint",
        entrypoint="mcp-hpc-runner",
        owner="mcp-hpc-runner",
    ),
    SeamSpec(
        symbol="archive:legacy/v1",
        path="legacy/v1",
        classification="archived_source_tree",
        decision="KEEP",
        scanner="exact_literal",
        literal="legacy/v1",
        owner="repository",
        external_status="not_applicable_archive",
    ),
)


def _is_excluded(path: Path) -> bool:
    return any(part in EXCLUDED_PARTS for part in path.parts)


def _relative(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def _classify_path(relative_path: str) -> str:
    path = Path(relative_path)
    parts = path.parts
    if relative_path.startswith("legacy/") or relative_path.startswith(
        "openspec/changes/archive/"
    ):
        return "archive"
    if "tests" in parts or path.name.startswith("test_") or path.name == "conftest.py":
        return "test_only"
    if (
        path.suffix.lower() in {".md", ".rst"}
        or "docs" in parts
        or path.name == "README.md"
        or relative_path.startswith("openspec/")
    ):
        return "docs_only"
    if path.name == "pyproject.toml":
        return "production_config"
    if relative_path.startswith(("apps/", "packages/")):
        return "production"
    return "auxiliary"


def _candidate_files(root: Path, suffixes: frozenset[str]) -> list[Path]:
    paths: list[Path] = []
    for top_level in (
        ".github",
        "apps",
        "deploy",
        "docker",
        "packages",
        "docs",
        "openspec",
        "scripts",
        "legacy",
    ):
        start = root / top_level
        if not start.exists():
            continue
        for directory, directory_names, file_names in os.walk(start):
            directory_names[:] = sorted(
                name for name in directory_names if name not in EXCLUDED_PARTS
            )
            for file_name in sorted(file_names):
                path = Path(directory) / file_name
                if path.suffix.lower() in suffixes and not _is_excluded(path):
                    paths.append(path)
    for name in ("AGENTS.md", "README.md", "pyproject.toml"):
        path = root / name
        if path.is_file() and path.suffix.lower() in suffixes:
            paths.append(path)
    return sorted(set(paths), key=lambda item: _relative(item, root))


def _module_name(path: Path, root: Path) -> tuple[str | None, bool]:
    relative = Path(_relative(path, root))
    parts = relative.parts
    if "src" not in parts or path.suffix != ".py":
        return None, False
    src_index = parts.index("src")
    module_parts = list(parts[src_index + 1 :])
    if not module_parts:
        return None, False
    module_parts[-1] = Path(module_parts[-1]).stem
    is_package = module_parts[-1] == "__init__"
    if is_package:
        module_parts.pop()
    return ".".join(module_parts), is_package


def _resolved_import_module(
    node: ast.ImportFrom, *, current_module: str | None, is_package: bool
) -> str | None:
    if node.level == 0:
        return node.module
    if current_module is None:
        return None
    package = current_module if is_package else current_module.rpartition(".")[0]
    if not package:
        return None
    relative_name = "." * node.level + (node.module or "")
    try:
        return importlib.util.resolve_name(relative_name, package)
    except (ImportError, ValueError):
        return None


def _caller(
    *, path: str, line: int, evidence: str, caller_kind: str | None = None
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path,
        "line": line,
        "classification": _classify_path(path),
        "evidence": evidence,
    }
    if caller_kind is not None:
        payload["caller_kind"] = caller_kind
    return payload


def _deduplicate(callers: list[dict[str, Any]]) -> list[dict[str, Any]]:
    unique: dict[tuple[str, int, str, str], dict[str, Any]] = {}
    for caller in callers:
        key = (
            str(caller["path"]),
            int(caller["line"]),
            str(caller["evidence"]),
            str(caller.get("caller_kind") or ""),
        )
        unique[key] = caller
    return [unique[key] for key in sorted(unique)]


@dataclass(slots=True)
class PythonIndex:
    root: Path
    trees: dict[str, ast.AST]
    modules: dict[str, tuple[str | None, bool]]
    errors: list[dict[str, Any]]


def _build_python_index(root: Path) -> PythonIndex:
    trees: dict[str, ast.AST] = {}
    modules: dict[str, tuple[str | None, bool]] = {}
    errors: list[dict[str, Any]] = []
    for path in _candidate_files(root, frozenset({".py"})):
        relative = _relative(path, root)
        try:
            trees[relative] = ast.parse(path.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError) as exc:
            errors.append({"path": relative, "error": str(exc)})
            continue
        modules[relative] = _module_name(path, root)
    return PythonIndex(root=root, trees=trees, modules=modules, errors=errors)


def _scan_python_symbol(spec: SeamSpec, index: PythonIndex) -> list[dict[str, Any]]:
    assert spec.module is not None
    assert spec.name is not None
    callers: list[dict[str, Any]] = []
    for relative, tree in index.trees.items():
        if relative == spec.path:
            continue
        current_module, is_package = index.modules[relative]
        module_aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if not isinstance(node, ast.Import):
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
                imported_name = alias.name if alias.asname else alias.name.split(".", maxsplit=1)[0]
                module_aliases[local_name] = imported_name
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                imported_module = _resolved_import_module(
                    node, current_module=current_module, is_package=is_package
                )
                if imported_module is None or not (
                    imported_module == spec.module
                    or imported_module.startswith(f"{spec.module}.")
                ):
                    continue
                for alias in node.names:
                    if alias.name != spec.name:
                        continue
                    caller_kind = (
                        "public_reexport"
                        if relative.endswith("/__init__.py")
                        else "python_import"
                    )
                    callers.append(
                        _caller(
                            path=relative,
                            line=node.lineno,
                            evidence=f"from {imported_module} import {alias.name}",
                            caller_kind=caller_kind,
                        )
                    )
            elif isinstance(node, ast.Attribute):
                dotted = _dotted_attribute(node)
                if dotted is None:
                    continue
                local_name, _, remainder = dotted.partition(".")
                imported_module = module_aliases.get(local_name)
                if imported_module is None:
                    continue
                expanded = imported_module + (f".{remainder}" if remainder else "")
                if expanded != f"{spec.module}.{spec.name}":
                    continue
                callers.append(
                    _caller(
                        path=relative,
                        line=node.lineno,
                        evidence=f"attribute reference {expanded}",
                        caller_kind="python_attribute_reference",
                    )
                )
    callers.extend(_scan_docs_literal(spec.name, index_root=index, definition_path=spec.path))
    return _deduplicate(callers)


def _dotted_attribute(node: ast.Attribute) -> str | None:
    parts = [node.attr]
    value: ast.AST = node.value
    while isinstance(value, ast.Attribute):
        parts.append(value.attr)
        value = value.value
    if not isinstance(value, ast.Name):
        return None
    parts.append(value.id)
    return ".".join(reversed(parts))


def _scan_docs_literal(
    literal: str, *, index_root: PythonIndex, definition_path: str | None = None
) -> list[dict[str, Any]]:
    root = index_root.root
    callers: list[dict[str, Any]] = []
    for path in _candidate_files(root, frozenset({".md", ".rst"})):
        relative = _relative(path, root)
        if relative == definition_path:
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError:
            continue
        for line_number, line in enumerate(lines, start=1):
            if literal in line:
                callers.append(
                    _caller(
                        path=relative,
                        line=line_number,
                        evidence=f"documentation reference to {literal}",
                        caller_kind="documentation_reference",
                    )
                )
    return callers


def _scan_non_python_literal(
    literal: str,
    *,
    root: Path,
) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    for path in _candidate_files(root, NON_PYTHON_SOURCE_SUFFIXES):
        relative = _relative(path, root)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            if literal not in line:
                continue
            callers.append(
                _caller(
                    path=relative,
                    line=line_number,
                    evidence=f"source/config reference to {literal}",
                    caller_kind="source_literal_reference",
                )
            )
    return callers


def _scan_python_method(spec: SeamSpec, index: PythonIndex) -> list[dict[str, Any]]:
    assert spec.name is not None
    callers: list[dict[str, Any]] = []
    for relative, tree in index.trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            if isinstance(node.func, ast.Attribute) and node.func.attr == spec.name:
                callers.append(
                    _caller(
                        path=relative,
                        line=node.lineno,
                        evidence=f"method call .{spec.name}(...) ",
                        caller_kind="method_call",
                    )
                )
    callers.extend(_scan_docs_literal(spec.symbol, index_root=index, definition_path=spec.path))
    return _deduplicate(callers)


def _scan_exact_literal(spec: SeamSpec, index: PythonIndex) -> list[dict[str, Any]]:
    assert spec.literal is not None
    callers: list[dict[str, Any]] = []
    for relative, tree in index.trees.items():
        for node in ast.walk(tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str) and spec.literal in node.value:
                callers.append(
                    _caller(
                        path=relative,
                        line=node.lineno,
                        evidence=f"string reference to {spec.literal}",
                        caller_kind="string_reference",
                    )
                )
    callers.extend(_scan_docs_literal(spec.literal, index_root=index, definition_path=spec.path))
    callers.extend(_scan_non_python_literal(spec.literal, root=index.root))
    return _deduplicate(callers)


def _scan_execution_dto_field(spec: SeamSpec, index: PythonIndex) -> list[dict[str, Any]]:
    assert spec.name is not None
    callers: list[dict[str, Any]] = []
    for relative, tree in index.trees.items():
        if not relative.startswith("packages/openzyme-execution/"):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.ctx, ast.Load) and node.attr == spec.name:
                callers.append(
                    _caller(
                        path=relative,
                        line=node.lineno,
                        evidence=f"attribute read .{spec.name}",
                        caller_kind="dto_field_read",
                    )
                )
            elif isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg == spec.name:
                        callers.append(
                            _caller(
                                path=relative,
                                line=keyword.value.lineno,
                                evidence=f"constructor keyword {spec.name}=...",
                                caller_kind="dto_field_write",
                            )
                        )
    callers.extend(_scan_docs_literal(spec.symbol, index_root=index, definition_path=spec.path))
    return _deduplicate(callers)


def _dict_literal_keys(node: ast.AST) -> set[str]:
    if not isinstance(node, ast.Dict):
        return set()
    return {
        key.value
        for key in node.keys
        if isinstance(key, ast.Constant) and isinstance(key.value, str)
    }


def _string_literal(node: ast.AST) -> str | None:
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _scan_raw_runner_lifecycle(index: PythonIndex) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    for relative, tree in index.trees.items():
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else None
            )
            keyword_names = {keyword.arg for keyword in node.keywords if keyword.arg}
            forbidden_keywords = sorted(keyword_names & RAW_LIFECYCLE_KEYS)
            if function_name in RAW_LIFECYCLE_METHODS and forbidden_keywords:
                callers.append(
                    _caller(
                        path=relative,
                        line=node.lineno,
                        evidence=(
                            f"{function_name}(...) uses raw lifecycle argument(s): "
                            + ", ".join(forbidden_keywords)
                        ),
                        caller_kind="retired_call_shape",
                    )
                )
                continue
            if function_name != "call_tool" or len(node.args) < 2:
                continue
            tool_name = _string_literal(node.args[0])
            if tool_name not in RAW_LIFECYCLE_TOOL_NAMES:
                continue
            forbidden_payload_keys = sorted(_dict_literal_keys(node.args[1]) & RAW_LIFECYCLE_KEYS)
            if forbidden_payload_keys:
                callers.append(
                    _caller(
                        path=relative,
                        line=node.lineno,
                        evidence=(
                            f"call_tool({tool_name!r}, ...) uses raw payload key(s): "
                            + ", ".join(forbidden_payload_keys)
                        ),
                        caller_kind="retired_call_shape",
                    )
                )
    lifecycle_pattern = re.compile(
        r"(?:cancel_execution|fetch_execution_artifacts|get_execution_status|"
        r"job\.(?:cancel|fetch_artifacts|logs|status))"
    )
    forbidden_key_pattern = re.compile(r"\b(job_id|remote_run_dir|runspec)\b")
    for path in _candidate_files(index.root, NON_PYTHON_SOURCE_SUFFIXES):
        relative = _relative(path, index.root)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for match in lifecycle_pattern.finditer(content):
            window = content[match.start() : match.start() + 800]
            keys = sorted(set(forbidden_key_pattern.findall(window)))
            if not keys:
                continue
            callers.append(
                _caller(
                    path=relative,
                    line=content.count("\n", 0, match.start()) + 1,
                    evidence=(
                        f"{match.group(0)} source/config window uses raw key(s): "
                        + ", ".join(keys)
                    ),
                    caller_kind="retired_call_shape",
                )
            )
    return _deduplicate(callers)


def _scan_legacy_http_routes(index: PythonIndex) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    for relative, tree in index.trees.items():
        if not relative.startswith(("apps/", "packages/")):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not node.args:
                continue
            method = node.func.attr if isinstance(node.func, ast.Attribute) else None
            route = _string_literal(node.args[0])
            if method not in HTTP_METHODS or route is None:
                continue
            if not route.startswith(("/v1", "/v2")):
                continue
            callers.append(
                _caller(
                    path=relative,
                    line=node.lineno,
                    evidence=f"{method.upper()} {route}",
                    caller_kind="legacy_http_route",
                )
            )
    legacy_path_pattern = re.compile(r"[\"'`](/v[12](?:/[^\"'`]*)?)[\"'`]")
    for path in _candidate_files(index.root, NON_PYTHON_SOURCE_SUFFIXES):
        relative = _relative(path, index.root)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for line_number, line in enumerate(lines, start=1):
            for match in legacy_path_pattern.finditer(line):
                callers.append(
                    _caller(
                        path=relative,
                        line=line_number,
                        evidence=f"legacy HTTP reference {match.group(1)}",
                        caller_kind="legacy_http_reference",
                    )
                )
    return _deduplicate(callers)


def _scan_legacy_v1_activation(root: Path, index: PythonIndex) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    root_pyproject = root / "pyproject.toml"
    if root_pyproject.is_file():
        try:
            payload = tomllib.loads(root_pyproject.read_text(encoding="utf-8"))
            members = payload.get("tool", {}).get("uv", {}).get("workspace", {}).get("members", [])
        except (OSError, tomllib.TOMLDecodeError):
            members = []
        for member in members:
            value = str(member)
            if value.startswith("legacy/") or value.startswith(
                ("apps/enzyme-", "packages/enzyme-")
            ):
                callers.append(
                    _caller(
                        path="pyproject.toml",
                        line=1,
                        evidence=f"active uv workspace member {value}",
                        caller_kind="legacy_workspace_member",
                    )
                )
    for relative, tree in index.trees.items():
        if _classify_path(relative) not in PRODUCTION_CLASSIFICATIONS:
            continue
        for node in ast.walk(tree):
            modules: list[str] = []
            if isinstance(node, ast.Import):
                modules = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                modules = [node.module]
            for module in modules:
                if module.startswith(LEGACY_V1_IMPORT_PREFIXES):
                    callers.append(
                        _caller(
                            path=relative,
                            line=node.lineno,
                            evidence=f"active import {module}",
                            caller_kind="legacy_import",
                        )
                    )
    return _deduplicate(callers)


def _scan_entrypoint(spec: SeamSpec, root: Path) -> list[dict[str, Any]]:
    assert spec.entrypoint is not None
    path = root / spec.path
    if not path.is_file():
        return []
    try:
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError):
        return []
    target = payload.get("project", {}).get("scripts", {}).get(spec.entrypoint)
    if target is None:
        return []
    return [
        _caller(
            path=spec.path,
            line=_find_line(path, f"{spec.entrypoint} ="),
            evidence=f"project.scripts.{spec.entrypoint} = {target}",
            caller_kind="installed_entrypoint",
        )
    ]


def _find_line(path: Path, needle: str) -> int:
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError:
        return 1
    for line_number, line in enumerate(lines, start=1):
        if needle in line:
            return line_number
    return 1


def _scan(spec: SeamSpec, *, root: Path, index: PythonIndex) -> list[dict[str, Any]]:
    if spec.scanner == "python_symbol":
        return _scan_python_symbol(spec, index)
    if spec.scanner == "python_method":
        return _scan_python_method(spec, index)
    if spec.scanner == "exact_literal":
        return _scan_exact_literal(spec, index)
    if spec.scanner == "execution_dto_field":
        return _scan_execution_dto_field(spec, index)
    if spec.scanner == "raw_runner_lifecycle":
        return _scan_raw_runner_lifecycle(index)
    if spec.scanner == "legacy_http_routes":
        return _scan_legacy_http_routes(index)
    if spec.scanner == "legacy_v1_activation":
        return _scan_legacy_v1_activation(root, index)
    if spec.scanner == "entrypoint":
        return _scan_entrypoint(spec, root)
    raise ValueError(f"unknown scanner: {spec.scanner}")


def build_report(root: Path) -> dict[str, Any]:
    root = root.resolve()
    index = _build_python_index(root)
    records: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for spec in SEAMS:
        callers = [
            caller
            for caller in _scan(spec, root=root, index=index)
            if caller["path"] != AUDIT_SCRIPT_PATH
        ]
        production_callers = [
            caller
            for caller in callers
            if caller["classification"] in PRODUCTION_CLASSIFICATIONS
        ]
        record = {
            "symbol": spec.symbol,
            "path": spec.path,
            "classification": spec.classification,
            "caller_count": len(callers),
            "production_caller_count": len(production_callers),
            "callers": callers,
            "decision": spec.decision,
            "owner": spec.owner,
            "external_status": spec.external_status,
        }
        records.append(record)
        if spec.decision == "RETIRED" and production_callers:
            violations.append(
                {
                    "symbol": spec.symbol,
                    "reason": "retired seam has an in-repository production caller",
                    "callers": production_callers,
                }
            )
        if spec.decision in {"KEEP", "DEPRECATE", "RETIRE-BLOCKED"} and not (
            root / spec.path
        ).exists():
            violations.append(
                {
                    "symbol": spec.symbol,
                    "reason": "declared active or compatibility seam path is missing",
                    "path": spec.path,
                }
            )
    return {
        "schema_version": SCHEMA_VERSION,
        "root": ".",
        "seams": records,
        "violations": violations,
        "scan_errors": sorted(index.errors, key=lambda item: item["path"]),
        "summary": {
            "seam_count": len(records),
            "violation_count": len(violations),
            "scan_error_count": len(index.errors),
        },
    }


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Emit deterministic JSON evidence for OpenZyme V3 compatibility callers."
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="repository root (defaults to the parent of scripts/)",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="emit only summary, violations, and scan errors",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_parser().parse_args(argv)
    report = build_report(args.root)
    output = report
    if args.summary:
        output = {
            "schema_version": report["schema_version"],
            "summary": report["summary"],
            "violations": report["violations"],
            "scan_errors": report["scan_errors"],
        }
    print(json.dumps(output, indent=2, sort_keys=True, ensure_ascii=False))
    if report["scan_errors"]:
        return 2
    if report["violations"]:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
