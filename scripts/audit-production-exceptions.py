#!/usr/bin/env python3
"""Fail-closed AST audit for the file-workspace cutover production boundaries.

The audit is intentionally scoped to production modules owned or modified by the
fourteen cutover changes and their closure change. It does not claim that unrelated
legacy subsystems have no broad catches. Every broad catch in this scope must either
re-raise the original exception, raise a typed successor with explicit chaining, or
consume the bound exception in a structured diagnostic/failure projection. Silent
pass/continue and unbound fallback returns are always violations.
"""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
from pathlib import Path
from typing import Iterable


SCHEMA_ID = "openzyme.production_exception_audit@1"

CUTOVER_SOURCES: dict[str, tuple[str, ...]] = {
    "apps/mcp-hpc-runner/src/mcp_hpc_runner/workspace_revision_jobs.py": (
        "apps/mcp-hpc-runner/tests/test_workspace_revision_job_wire.py",
    ),
    "apps/openzyme-host-api/src/openzyme_host_api/app.py": (
        "apps/openzyme-host-api/tests/test_api.py",
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
    ),
    "apps/openzyme-host-api/src/openzyme_host_api/v3_service.py": (
        "apps/openzyme-host-api/tests/test_runtime_commands.py",
    ),
    "apps/openzyme-host-api/src/openzyme_host_api/workspace_revision_execution.py": (
        "apps/openzyme-host-api/tests/test_workspace_revision_execution_boundary.py",
    ),
    "packages/openzyme-core/src/openzyme_core/agent_git_workspace_recovery.py": (
        "packages/openzyme-core/tests/test_agent_git_workspaces.py",
    ),
    "packages/openzyme-core/src/openzyme_core/bio_research_tools.py": (
        "packages/openzyme-core/tests/test_bio_research_tools.py",
    ),
    "packages/openzyme-core/src/openzyme_core/deployment_schema_proofs.py": (
        "packages/openzyme-core/tests/test_migrations.py",
    ),
    "packages/openzyme-core/src/openzyme_core/device_fresh_reset.py": (
        "packages/openzyme-core/tests/test_device_fresh_reset.py",
    ),
    "packages/openzyme-core/src/openzyme_core/failure_repositories.py": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
    ),
    "packages/openzyme-core/src/openzyme_core/file_workspace_projection.py": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
    ),
    "packages/openzyme-core/src/openzyme_core/harness.py": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
        "packages/openzyme-core/tests/test_harness_strategy_properties.py",
    ),
    "packages/openzyme-core/src/openzyme_core/migration_assets.py": (
        "packages/openzyme-core/tests/test_migrations.py",
    ),
    "packages/openzyme-core/src/openzyme_core/mutation_authority.py": (
        "packages/openzyme-core/tests/test_mutation_quiescence.py",
    ),
    "packages/openzyme-core/src/openzyme_core/repositories.py": (
        "packages/openzyme-core/tests/test_production_exception_audit.py",
    ),
    "packages/openzyme-core/src/openzyme_core/workspace_file_handoffs.py": (
        "packages/openzyme-core/tests/test_bio_research_tools.py",
    ),
    "packages/openzyme-core/src/openzyme_core/workspace_publications.py": (
        "packages/openzyme-core/tests/test_agent_git_workspaces.py",
    ),
    "packages/openzyme-domain/src/openzyme_domain/failures.py": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
    ),
    "packages/openzyme-domain/src/openzyme_domain/workspace_job_wire.py": (
        "packages/openzyme-domain/tests/test_workspace_job_wire.py",
    ),
    "packages/openzyme-execution/src/openzyme_execution/workspace_revision.py": (
        "packages/openzyme-execution/tests/test_workspace_revision_adapter.py",
    ),
    "packages/openzyme-runtime/src/openzyme_runtime/failure_observations.py": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
    ),
    "packages/openzyme-runtime/src/openzyme_runtime/public_diagnostics.py": (
        "packages/openzyme-runtime/tests/test_public_diagnostics.py",
    ),
    "packages/openzyme-runtime/src/openzyme_runtime/tooling.py": (
        "packages/openzyme-core/tests/test_failure_diagnostics.py",
    ),
}

# SQLite invokes this callback from a trigger. It cannot safely emit another SQLite
# diagnostic from inside the callback, so the only valid failure behavior is a
# deterministic deny (0). The direct test injects a failing conversion and proves it.
REVIEWED_UNBOUND_HANDLERS: dict[tuple[str, str], str] = {
    (
        "packages/openzyme-core/src/openzyme_core/repositories.py",
        "_mutation_write_allowed",
    ): "packages/openzyme-core/tests/test_production_exception_audit.py::test_sqlite_mutation_callback_fails_closed_without_raising",
}


def _digest(value: object) -> str:
    encoded = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=True,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _qualified_function(
    handler: ast.ExceptHandler,
    parents: dict[ast.AST, ast.AST],
) -> str:
    current: ast.AST = handler
    names: list[str] = []
    while current in parents:
        current = parents[current]
        if isinstance(current, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.append(current.name)
        elif isinstance(current, ast.ClassDef):
            names.append(current.name)
    return ".".join(reversed(names)) or "<module>"


def _is_broad(handler: ast.ExceptHandler) -> bool:
    return handler.type is None or (
        isinstance(handler.type, ast.Name)
        and handler.type.id in {"Exception", "BaseException"}
    )


def _references_bound_exception(handler: ast.ExceptHandler) -> bool:
    return bool(
        handler.name
        and any(
            isinstance(node, ast.Name)
            and isinstance(node.ctx, ast.Load)
            and node.id == handler.name
            for node in ast.walk(handler)
        )
    )


def _handler_violations(
    *,
    path: str,
    handler: ast.ExceptHandler,
    function: str,
) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []

    def add(rule: str, detail: str) -> None:
        result.append(
            {
                "detail": detail,
                "function": function,
                "line": handler.lineno,
                "path": path,
                "rule": rule,
            }
        )

    if handler.type is None:
        add("bare_except", "bare except is forbidden")
        return result
    nodes = tuple(ast.walk(handler))
    if any(isinstance(node, ast.Pass) for node in nodes):
        add("silent_pass", "broad catch contains pass")
    if any(isinstance(node, ast.Continue) for node in nodes):
        add("silent_continue", "broad catch continues with hidden fallback")
    for raised in (node for node in nodes if isinstance(node, ast.Raise)):
        if raised.exc is not None and raised.cause is None:
            add(
                "cause_not_chained",
                "typed replacement exception must use raise ... from exc",
            )
    if any(isinstance(node, ast.Raise) and node.exc is None for node in nodes):
        return result
    if any(
        isinstance(node, ast.Raise) and node.exc is not None and node.cause is not None
        for node in nodes
    ):
        return result
    if _references_bound_exception(handler):
        return result
    reviewed_test = REVIEWED_UNBOUND_HANDLERS.get((path, function))
    if reviewed_test is None:
        add(
            "unrecorded_broad_catch",
            "broad catch neither preserves nor records the caught exception",
        )
    return result


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    violations: list[dict[str, object]] = []
    scan_errors: list[dict[str, object]] = []
    handlers: list[dict[str, object]] = []
    for relative, test_refs in sorted(CUTOVER_SOURCES.items()):
        source = root / relative
        missing_tests = [test_ref for test_ref in test_refs if not (root / test_ref).is_file()]
        if missing_tests:
            scan_errors.append(
                {
                    "detail": f"missing direct evidence files: {missing_tests}",
                    "path": relative,
                }
            )
            continue
        try:
            tree = ast.parse(source.read_text(encoding="utf-8"), filename=relative)
        except (OSError, SyntaxError, UnicodeError) as exc:
            scan_errors.append(
                {
                    "detail": f"{type(exc).__name__}: {exc}",
                    "path": relative,
                }
            )
            continue
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node
        for handler in (node for node in ast.walk(tree) if isinstance(node, ast.ExceptHandler)):
            if not _is_broad(handler):
                continue
            function = _qualified_function(handler, parents)
            handlers.append(
                {
                    "exception_type": ast.unparse(handler.type),
                    "function": function,
                    "line": handler.lineno,
                    "path": relative,
                    "test_refs": list(test_refs),
                }
            )
            violations.extend(
                _handler_violations(path=relative, handler=handler, function=function)
            )
    for (relative, function), test_ref in REVIEWED_UNBOUND_HANDLERS.items():
        test_path, _, selector = test_ref.partition("::")
        target = root / test_path
        if not target.is_file() or (selector and f"def {selector}(" not in target.read_text()):
            scan_errors.append(
                {
                    "detail": f"reviewed handler test is missing: {test_ref}",
                    "path": relative,
                    "function": function,
                }
            )
    handlers.sort(key=lambda item: (str(item["path"]), int(item["line"])))
    violations.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["rule"])))
    scan_errors.sort(key=lambda item: (str(item["path"]), str(item.get("function", ""))))
    payload: dict[str, object] = {
        "schema_id": SCHEMA_ID,
        "scope": "fourteen_file_workspace_cutover_changes_and_closure",
        "source_files": sorted(CUTOVER_SOURCES),
        "broad_handlers": handlers,
        "violations": violations,
        "scan_errors": scan_errors,
        "outside_scope_claimed_clean": False,
        "deployment_mutation_authorized": False,
    }
    return {**payload, "report_digest": _digest(payload)}


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(args.root)
    if args.summary:
        report = {
            "schema_id": report["schema_id"],
            "source_count": len(report["source_files"]),
            "broad_handler_count": len(report["broad_handlers"]),
            "violation_count": len(report["violations"]),
            "scan_error_count": len(report["scan_errors"]),
            "report_digest": report["report_digest"],
        }
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 1 if report.get("violations") or report.get("scan_errors") else 0


if __name__ == "__main__":
    raise SystemExit(main())
