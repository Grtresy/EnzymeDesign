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
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys
import tomllib
from types import MappingProxyType
from typing import Any, Callable, Mapping


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
        symbol="openzyme-aox-cutover:--attempt-authority-consumption",
        path=(
            "apps/openzyme-host-api/src/openzyme_host_api/"
            "aox_cutover_cli.py"
        ),
        classification="compat_cli_option_assertion",
        decision="DEPRECATE",
        scanner="cli_option_argv",
        literal="--attempt-authority-consumption",
        owner="openzyme-host-api",
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


def _repository_files(root: Path) -> tuple[Path, ...]:
    """Build the supported repository inventory with one deterministic walk."""

    supported_suffixes = (
        frozenset({".py", ".md", ".rst"}) | NON_PYTHON_SOURCE_SUFFIXES
    )
    supported_top_levels = frozenset(
        {
            ".github",
            "apps",
            "deploy",
            "docker",
            "packages",
            "docs",
            "openspec",
            "scripts",
            "legacy",
        }
    )
    supported_root_files = frozenset({"AGENTS.md", "README.md", "pyproject.toml"})
    paths: list[Path] = []
    for directory, directory_names, file_names in os.walk(root):
        directory_path = Path(directory)
        if directory_path == root:
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name in supported_top_levels and name not in EXCLUDED_PARTS
            )
        else:
            directory_names[:] = sorted(
                name for name in directory_names if name not in EXCLUDED_PARTS
            )
        for file_name in sorted(file_names):
            path = directory_path / file_name
            if directory_path == root and file_name not in supported_root_files:
                continue
            if (
                path.suffix.lower() in supported_suffixes
                and not _is_excluded(path.relative_to(root))
            ):
                paths.append(path)
    return tuple(sorted(set(paths), key=lambda item: _relative(item, root)))


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


@dataclass(frozen=True, slots=True)
class IndexedTextFile:
    path: str
    suffix: str
    content: str
    lines: tuple[str, ...]
    digest: str


@dataclass(frozen=True, slots=True)
class ImportReference:
    path: str
    line: int
    module: str
    name: str
    caller_kind: str


@dataclass(frozen=True, slots=True)
class AttributeReference:
    path: str
    line: int
    expanded: str


@dataclass(frozen=True, slots=True)
class MethodCallReference:
    path: str
    line: int
    name: str


@dataclass(frozen=True, slots=True)
class StringReference:
    path: str
    line: int
    value: str
    is_cli_option_definition: bool


@dataclass(frozen=True, slots=True)
class AttributeReadReference:
    path: str
    line: int
    name: str


@dataclass(frozen=True, slots=True)
class KeywordReference:
    path: str
    line: int
    name: str


@dataclass(frozen=True, slots=True)
class ImportModuleReference:
    path: str
    line: int
    module: str


@dataclass(frozen=True, slots=True)
class IndexedCaller:
    path: str
    line: int
    evidence: str
    caller_kind: str

    def to_report(self) -> dict[str, Any]:
        return _caller(
            path=self.path,
            line=self.line,
            evidence=self.evidence,
            caller_kind=self.caller_kind,
        )


@dataclass(frozen=True, slots=True)
class IndexedScanError:
    path: str
    error: str

    def to_report(self) -> dict[str, str]:
        return {"path": self.path, "error": self.error}


@dataclass(frozen=True, slots=True)
class RepositoryIndex:
    root: Path
    inventory: tuple[str, ...]
    text_files: Mapping[str, IndexedTextFile]
    toml_payloads: Mapping[str, Mapping[str, Any]]
    import_references: tuple[ImportReference, ...]
    attribute_references: tuple[AttributeReference, ...]
    method_calls: tuple[MethodCallReference, ...]
    string_references: tuple[StringReference, ...]
    attribute_reads: tuple[AttributeReadReference, ...]
    keyword_references: tuple[KeywordReference, ...]
    import_modules: tuple[ImportModuleReference, ...]
    raw_lifecycle_callers: tuple[IndexedCaller, ...]
    legacy_http_callers: tuple[IndexedCaller, ...]
    docs_literal_hits: Mapping[str, tuple[tuple[str, int], ...]]
    source_literal_hits: Mapping[str, tuple[tuple[str, int], ...]]
    errors: tuple[IndexedScanError, ...]
    read_counts: Mapping[str, int]

    def find_line(self, relative_path: str, needle: str) -> int:
        indexed = self.text_files.get(relative_path)
        if indexed is None:
            return 1
        for line_number, line in enumerate(indexed.lines, start=1):
            if needle in line:
                return line_number
        return 1


def _registered_text_literals() -> tuple[tuple[str, ...], tuple[str, ...]]:
    docs: set[str] = set()
    source: set[str] = set()
    for spec in SEAMS:
        if spec.scanner == "python_symbol" and spec.name is not None:
            docs.add(spec.name)
        elif spec.scanner == "python_method":
            docs.add(spec.symbol)
        elif spec.scanner == "exact_literal" and spec.literal is not None:
            docs.add(spec.literal)
            source.add(spec.literal)
        elif spec.scanner == "cli_option_argv" and spec.literal is not None:
            source.add(spec.literal)
        elif spec.scanner == "execution_dto_field":
            docs.add(spec.symbol)
    return tuple(sorted(docs)), tuple(sorted(source))


def _freeze_toml_value(value: Any) -> Any:
    if isinstance(value, dict):
        return MappingProxyType(
            {str(key): _freeze_toml_value(item) for key, item in value.items()}
        )
    if isinstance(value, list):
        return tuple(_freeze_toml_value(item) for item in value)
    return value


def _build_repository_index(
    root: Path,
    *,
    read_text: Callable[[Path], str] | None = None,
) -> RepositoryIndex:
    root = root.resolve()
    reader = read_text or (lambda path: path.read_text(encoding="utf-8"))
    paths = _repository_files(root)
    docs_literals, source_literals = _registered_text_literals()
    docs_literal_hits: dict[str, list[tuple[str, int]]] = {
        literal: [] for literal in docs_literals
    }
    source_literal_hits: dict[str, list[tuple[str, int]]] = {
        literal: [] for literal in source_literals
    }
    text_files: dict[str, IndexedTextFile] = {}
    toml_payloads: dict[str, Mapping[str, Any]] = {}
    import_references: list[ImportReference] = []
    attribute_references: list[AttributeReference] = []
    method_calls: list[MethodCallReference] = []
    string_references: list[StringReference] = []
    attribute_reads: list[AttributeReadReference] = []
    keyword_references: list[KeywordReference] = []
    import_modules: list[ImportModuleReference] = []
    raw_lifecycle_callers: list[IndexedCaller] = []
    legacy_http_callers: list[IndexedCaller] = []
    errors: list[IndexedScanError] = []
    read_counts: dict[str, int] = {}
    lifecycle_pattern = re.compile(
        r"(?:cancel_execution|fetch_execution_artifacts|get_execution_status|"
        r"job\.(?:cancel|fetch_artifacts|logs|status))"
    )
    forbidden_key_pattern = re.compile(r"\b(job_id|remote_run_dir|runspec)\b")
    legacy_path_pattern = re.compile(r"[\"'`](/v[12](?:/[^\"'`]*)?)[\"'`]")

    for path in paths:
        relative = _relative(path, root)
        read_counts[relative] = read_counts.get(relative, 0) + 1
        try:
            content = reader(path)
        except (OSError, UnicodeDecodeError) as exc:
            errors.append(IndexedScanError(path=relative, error=str(exc)))
            continue
        lines = tuple(content.splitlines())
        suffix = path.suffix.lower()
        text_files[relative] = IndexedTextFile(
            path=relative,
            suffix=suffix,
            content=content,
            lines=lines,
            digest=f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}",
        )

        if suffix in {".md", ".rst"}:
            for line_number, line in enumerate(lines, start=1):
                for literal in docs_literals:
                    if literal in line:
                        docs_literal_hits[literal].append((relative, line_number))

        if suffix in NON_PYTHON_SOURCE_SUFFIXES:
            for line_number, line in enumerate(lines, start=1):
                for literal in source_literals:
                    if literal in line:
                        source_literal_hits[literal].append(
                            (relative, line_number)
                        )
                for match in legacy_path_pattern.finditer(line):
                    legacy_http_callers.append(
                        IndexedCaller(
                            path=relative,
                            line=line_number,
                            evidence=f"legacy HTTP reference {match.group(1)}",
                            caller_kind="legacy_http_reference",
                        )
                    )
            for match in lifecycle_pattern.finditer(content):
                window = content[match.start() : match.start() + 800]
                keys = sorted(set(forbidden_key_pattern.findall(window)))
                if not keys:
                    continue
                raw_lifecycle_callers.append(
                    IndexedCaller(
                        path=relative,
                        line=content.count("\n", 0, match.start()) + 1,
                        evidence=(
                            f"{match.group(0)} source/config window uses raw key(s): "
                            + ", ".join(keys)
                        ),
                        caller_kind="retired_call_shape",
                    )
                )

        if suffix == ".toml":
            try:
                payload = tomllib.loads(content)
            except tomllib.TOMLDecodeError as exc:
                errors.append(IndexedScanError(path=relative, error=str(exc)))
            else:
                toml_payloads[relative] = _freeze_toml_value(payload)

        if suffix != ".py":
            continue
        try:
            tree = ast.parse(content, filename=relative)
        except SyntaxError as exc:
            errors.append(IndexedScanError(path=relative, error=str(exc)))
            continue
        current_module, is_package = _module_name(path, root)
        nodes = tuple(ast.walk(tree))
        cli_option_definition_ids = {
            id(argument)
            for node in nodes
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "add_argument"
            for argument in node.args
            if isinstance(argument, ast.Constant)
            and isinstance(argument.value, str)
            and argument.value.startswith("-")
        }
        module_aliases: dict[str, str] = {}
        for node in nodes:
            if not isinstance(node, ast.Import):
                continue
            for alias in node.names:
                local_name = alias.asname or alias.name.split(".", maxsplit=1)[0]
                imported_name = (
                    alias.name
                    if alias.asname
                    else alias.name.split(".", maxsplit=1)[0]
                )
                module_aliases[local_name] = imported_name
        for node in nodes:
            if isinstance(node, ast.Import):
                import_modules.extend(
                    ImportModuleReference(
                        path=relative,
                        line=node.lineno,
                        module=alias.name,
                    )
                    for alias in node.names
                )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    import_modules.append(
                        ImportModuleReference(
                            path=relative,
                            line=node.lineno,
                            module=node.module,
                        )
                    )
                imported_module = _resolved_import_module(
                    node,
                    current_module=current_module,
                    is_package=is_package,
                )
                if imported_module is not None:
                    import_references.extend(
                        ImportReference(
                            path=relative,
                            line=node.lineno,
                            module=imported_module,
                            name=alias.name,
                            caller_kind=(
                                "public_reexport"
                                if relative.endswith("/__init__.py")
                                else "python_import"
                            ),
                        )
                        for alias in node.names
                    )
            if isinstance(node, ast.Attribute):
                if isinstance(node.ctx, ast.Load):
                    attribute_reads.append(
                        AttributeReadReference(
                            path=relative,
                            line=node.lineno,
                            name=node.attr,
                        )
                    )
                dotted = _dotted_attribute(node)
                if dotted is not None:
                    local_name, _, remainder = dotted.partition(".")
                    imported_module = module_aliases.get(local_name)
                    if imported_module is not None:
                        attribute_references.append(
                            AttributeReference(
                                path=relative,
                                line=node.lineno,
                                expanded=imported_module
                                + (f".{remainder}" if remainder else ""),
                            )
                        )
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                string_references.append(
                    StringReference(
                        path=relative,
                        line=node.lineno,
                        value=node.value,
                        is_cli_option_definition=(
                            id(node) in cli_option_definition_ids
                        ),
                    )
                )
            if not isinstance(node, ast.Call):
                continue
            function_name = (
                node.func.attr
                if isinstance(node.func, ast.Attribute)
                else node.func.id
                if isinstance(node.func, ast.Name)
                else None
            )
            if isinstance(node.func, ast.Attribute):
                method_calls.append(
                    MethodCallReference(
                        path=relative,
                        line=node.lineno,
                        name=node.func.attr,
                    )
                )
            keyword_references.extend(
                KeywordReference(
                    path=relative,
                    line=keyword.value.lineno,
                    name=keyword.arg,
                )
                for keyword in node.keywords
                if keyword.arg is not None
            )
            keyword_names = {
                keyword.arg for keyword in node.keywords if keyword.arg
            }
            forbidden_keywords = sorted(keyword_names & RAW_LIFECYCLE_KEYS)
            if function_name in RAW_LIFECYCLE_METHODS and forbidden_keywords:
                raw_lifecycle_callers.append(
                    IndexedCaller(
                        path=relative,
                        line=node.lineno,
                        evidence=(
                            f"{function_name}(...) uses raw lifecycle argument(s): "
                            + ", ".join(forbidden_keywords)
                        ),
                        caller_kind="retired_call_shape",
                    )
                )
            elif function_name == "call_tool" and len(node.args) >= 2:
                tool_name = _string_literal(node.args[0])
                if tool_name in RAW_LIFECYCLE_TOOL_NAMES:
                    forbidden_payload_keys = sorted(
                        _dict_literal_keys(node.args[1]) & RAW_LIFECYCLE_KEYS
                    )
                    if forbidden_payload_keys:
                        raw_lifecycle_callers.append(
                            IndexedCaller(
                                path=relative,
                                line=node.lineno,
                                evidence=(
                                    f"call_tool({tool_name!r}, ...) uses raw "
                                    "payload key(s): "
                                    + ", ".join(forbidden_payload_keys)
                                ),
                                caller_kind="retired_call_shape",
                            )
                        )
            method = (
                node.func.attr if isinstance(node.func, ast.Attribute) else None
            )
            route = _string_literal(node.args[0]) if node.args else None
            if (
                relative.startswith(("apps/", "packages/"))
                and method in HTTP_METHODS
                and route is not None
                and route.startswith(("/v1", "/v2"))
            ):
                legacy_http_callers.append(
                    IndexedCaller(
                        path=relative,
                        line=node.lineno,
                        evidence=f"{method.upper()} {route}",
                        caller_kind="legacy_http_route",
                    )
                )

    return RepositoryIndex(
        root=root,
        inventory=tuple(_relative(path, root) for path in paths),
        text_files=MappingProxyType(text_files),
        toml_payloads=MappingProxyType(toml_payloads),
        import_references=tuple(import_references),
        attribute_references=tuple(attribute_references),
        method_calls=tuple(method_calls),
        string_references=tuple(string_references),
        attribute_reads=tuple(attribute_reads),
        keyword_references=tuple(keyword_references),
        import_modules=tuple(import_modules),
        raw_lifecycle_callers=tuple(raw_lifecycle_callers),
        legacy_http_callers=tuple(legacy_http_callers),
        docs_literal_hits=MappingProxyType(
            {
                literal: tuple(hits)
                for literal, hits in docs_literal_hits.items()
            }
        ),
        source_literal_hits=MappingProxyType(
            {
                literal: tuple(hits)
                for literal, hits in source_literal_hits.items()
            }
        ),
        errors=tuple(errors),
        read_counts=MappingProxyType(read_counts),
    )


def _scan_python_symbol(
    spec: SeamSpec,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    assert spec.module is not None
    assert spec.name is not None
    callers: list[dict[str, Any]] = []
    for reference in index.import_references:
        if reference.path == spec.path:
            continue
        if not (
            reference.module == spec.module
            or reference.module.startswith(f"{spec.module}.")
        ):
            continue
        if reference.name != spec.name:
            continue
        callers.append(
            _caller(
                path=reference.path,
                line=reference.line,
                evidence=f"from {reference.module} import {reference.name}",
                caller_kind=reference.caller_kind,
            )
        )
    expected_attribute = f"{spec.module}.{spec.name}"
    callers.extend(
        _caller(
            path=reference.path,
            line=reference.line,
            evidence=f"attribute reference {reference.expanded}",
            caller_kind="python_attribute_reference",
        )
        for reference in index.attribute_references
        if reference.path != spec.path
        and reference.expanded == expected_attribute
    )
    callers.extend(
        _scan_docs_literal(
            spec.name,
            index=index,
            definition_path=spec.path,
        )
    )
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
    literal: str,
    *,
    index: RepositoryIndex,
    definition_path: str | None = None,
) -> list[dict[str, Any]]:
    return [
        _caller(
            path=relative,
            line=line_number,
            evidence=f"documentation reference to {literal}",
            caller_kind="documentation_reference",
        )
        for relative, line_number in index.docs_literal_hits.get(literal, ())
        if relative != definition_path
    ]


def _scan_non_python_literal(
    literal: str,
    *,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    return [
        _caller(
            path=relative,
            line=line_number,
            evidence=f"source/config reference to {literal}",
            caller_kind="source_literal_reference",
        )
        for relative, line_number in index.source_literal_hits.get(literal, ())
    ]


def _scan_python_method(
    spec: SeamSpec,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    assert spec.name is not None
    callers = [
        _caller(
            path=reference.path,
            line=reference.line,
            evidence=f"method call .{spec.name}(...) ",
            caller_kind="method_call",
        )
        for reference in index.method_calls
        if reference.name == spec.name
    ]
    callers.extend(
        _scan_docs_literal(
            spec.symbol,
            index=index,
            definition_path=spec.path,
        )
    )
    return _deduplicate(callers)


def _scan_exact_literal(
    spec: SeamSpec,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    assert spec.literal is not None
    callers = [
        _caller(
            path=reference.path,
            line=reference.line,
            evidence=f"string reference to {spec.literal}",
            caller_kind="string_reference",
        )
        for reference in index.string_references
        if spec.literal in reference.value
    ]
    callers.extend(
        _scan_docs_literal(
            spec.literal,
            index=index,
            definition_path=spec.path,
        )
    )
    callers.extend(_scan_non_python_literal(spec.literal, index=index))
    return _deduplicate(callers)


def _scan_cli_option_argv(
    spec: SeamSpec,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    assert spec.literal is not None
    callers = [
        _caller(
            path=reference.path,
            line=reference.line,
            evidence=f"CLI argv option {spec.literal}",
            caller_kind="cli_argv_option",
        )
        for reference in index.string_references
        if reference.value == spec.literal
        and not reference.is_cli_option_definition
    ]
    callers.extend(_scan_non_python_literal(spec.literal, index=index))
    return _deduplicate(callers)


def _scan_execution_dto_field(
    spec: SeamSpec,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    assert spec.name is not None
    callers = [
        _caller(
            path=reference.path,
            line=reference.line,
            evidence=f"attribute read .{spec.name}",
            caller_kind="dto_field_read",
        )
        for reference in index.attribute_reads
        if reference.path.startswith("packages/openzyme-execution/")
        and reference.name == spec.name
    ]
    callers.extend(
        _caller(
            path=reference.path,
            line=reference.line,
            evidence=f"constructor keyword {spec.name}=...",
            caller_kind="dto_field_write",
        )
        for reference in index.keyword_references
        if reference.path.startswith("packages/openzyme-execution/")
        and reference.name == spec.name
    )
    callers.extend(
        _scan_docs_literal(
            spec.symbol,
            index=index,
            definition_path=spec.path,
        )
    )
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


def _scan_raw_runner_lifecycle(
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    return _deduplicate(
        [reference.to_report() for reference in index.raw_lifecycle_callers]
    )


def _scan_legacy_http_routes(
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    return _deduplicate(
        [reference.to_report() for reference in index.legacy_http_callers]
    )


def _scan_legacy_v1_activation(
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    callers: list[dict[str, Any]] = []
    payload = index.toml_payloads.get("pyproject.toml")
    members: object = []
    if payload is not None:
        members = (
            payload.get("tool", {})
            .get("uv", {})
            .get("workspace", {})
            .get("members", [])
        )
    if isinstance(members, (list, tuple)):
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
    for reference in index.import_modules:
        if _classify_path(reference.path) not in PRODUCTION_CLASSIFICATIONS:
            continue
        if reference.module.startswith(LEGACY_V1_IMPORT_PREFIXES):
            callers.append(
                _caller(
                    path=reference.path,
                    line=reference.line,
                    evidence=f"active import {reference.module}",
                    caller_kind="legacy_import",
                )
            )
    return _deduplicate(callers)


def _scan_entrypoint(
    spec: SeamSpec,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    assert spec.entrypoint is not None
    payload = index.toml_payloads.get(spec.path)
    if payload is None:
        return []
    target = payload.get("project", {}).get("scripts", {}).get(spec.entrypoint)
    if target is None:
        return []
    return [
        _caller(
            path=spec.path,
            line=index.find_line(spec.path, f"{spec.entrypoint} ="),
            evidence=f"project.scripts.{spec.entrypoint} = {target}",
            caller_kind="installed_entrypoint",
        )
    ]


def _scan(
    spec: SeamSpec,
    *,
    index: RepositoryIndex,
) -> list[dict[str, Any]]:
    if spec.scanner == "python_symbol":
        return _scan_python_symbol(spec, index)
    if spec.scanner == "python_method":
        return _scan_python_method(spec, index)
    if spec.scanner == "exact_literal":
        return _scan_exact_literal(spec, index)
    if spec.scanner == "cli_option_argv":
        return _scan_cli_option_argv(spec, index)
    if spec.scanner == "execution_dto_field":
        return _scan_execution_dto_field(spec, index)
    if spec.scanner == "raw_runner_lifecycle":
        return _scan_raw_runner_lifecycle(index)
    if spec.scanner == "legacy_http_routes":
        return _scan_legacy_http_routes(index)
    if spec.scanner == "legacy_v1_activation":
        return _scan_legacy_v1_activation(index)
    if spec.scanner == "entrypoint":
        return _scan_entrypoint(spec, index)
    raise ValueError(f"unknown scanner: {spec.scanner}")


def build_report(
    root: Path,
    *,
    read_text: Callable[[Path], str] | None = None,
) -> dict[str, Any]:
    root = root.resolve()
    index = _build_repository_index(root, read_text=read_text)
    records: list[dict[str, Any]] = []
    violations: list[dict[str, Any]] = []
    for spec in SEAMS:
        callers = [
            caller
            for caller in _scan(spec, index=index)
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
        "scan_errors": [
            error.to_report()
            for error in sorted(index.errors, key=lambda item: item.path)
        ],
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
