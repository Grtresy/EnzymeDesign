#!/usr/bin/env python3
"""Fail-closed audit for retired V3 product surfaces.

Historical OpenSpec and offline operator code is intentionally outside this scan. The
audit covers current application/package sources, entry points, workflow manifests,
and the final SQLite baseline. A clean checkout is repository evidence only; it is not
a deployment migration or removal receipt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import tomllib
from typing import Iterable


SCHEMA_VERSION = "openzyme.v3.retired-surface-audit.v2"
RETIRED_NOUN = "arti" + "fact"
SOURCE_SUFFIXES = frozenset(
    {".json", ".js", ".jsx", ".py", ".toml", ".ts", ".tsx"}
)
EXCLUDED_PARTS = frozenset(
    {"__pycache__", ".mypy_cache", ".pytest_cache", ".ruff_cache", "node_modules"}
)
RETIRED_LITERALS = (
    RETIRED_NOUN + ".",
    RETIRED_NOUN + "s.",
    "scientific." + RETIRED_NOUN + ".",
    "sandbox." + "file.",
    "hpc.stage_" + RETIRED_NOUN,
    "hpc.fetch_" + "outputs",
    "execution.pipeline.start",
)
RETIRED_PATHS = (
    "packages/openzyme-core/src/openzyme_core/" + RETIRED_NOUN + "_boundary.py",
    "packages/openzyme-core/src/openzyme_core/" + RETIRED_NOUN + "_projection.py",
    "packages/openzyme-core/src/openzyme_core/" + RETIRED_NOUN + "_tools.py",
    "packages/openzyme-runtime/src/openzyme_runtime/" + RETIRED_NOUN + "_boundary.py",
    "packages/openzyme-runtime/src/openzyme_runtime/" + RETIRED_NOUN + "_projection.py",
    "packages/openzyme-pipeline/src/openzyme_pipeline/" + RETIRED_NOUN + "s.py",
    "packages/openzyme-tools/src/openzyme_tools/catalog.py",
    "packages/openzyme-tools/src/openzyme_tools/contracts.py",
    "packages/openzyme-tools/src/openzyme_tools/execution.py",
    "packages/openzyme-runtime/src/openzyme_runtime/hpc_catalog.py",
    "apps/mcp-hpc-runner/src/mcp_hpc_runner/contracts/hpc_tool_contracts.json",
)


def _canonical_digest(payload: object) -> str:
    encoded = json.dumps(
        payload,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


def _source_roots(root: Path) -> tuple[Path, ...]:
    return tuple(sorted((*root.glob("apps/*/src"), *root.glob("packages/*/src"))))


def _candidate_files(root: Path) -> tuple[Path, ...]:
    candidates = {
        path
        for source_root in _source_roots(root)
        for path in source_root.rglob("*")
        if path.is_file()
        and path.suffix in SOURCE_SUFFIXES
        and not EXCLUDED_PARTS.intersection(path.parts)
    }
    candidates.update(root.glob("apps/*/pyproject.toml"))
    candidates.update(root.glob("packages/*/pyproject.toml"))
    candidates.update(root.glob("docs/v3/workflow-packs/*.workflow.json"))
    candidates.add(
        root
        / "packages/openzyme-core/src/openzyme_core/migrations"
        / "001_file_workspace_final.sql"
    )
    return tuple(sorted(path for path in candidates if path.is_file()))


def _line_number(content: str, offset: int) -> int:
    return content.count("\n", 0, offset) + 1


def _literal_violations(relative: str, content: str) -> list[dict[str, object]]:
    violations: list[dict[str, object]] = []
    folded = content.casefold()
    path_folded = relative.casefold()
    noun = RETIRED_NOUN.casefold()
    if noun in path_folded:
        violations.append(
            {"rule": "retired_path_name", "path": relative, "line": 0, "token": RETIRED_NOUN}
        )
    offset = folded.find(noun)
    if offset >= 0:
        violations.append(
            {
                "rule": "retired_product_vocabulary",
                "path": relative,
                "line": _line_number(content, offset),
                "token": RETIRED_NOUN,
            }
        )
    for literal in RETIRED_LITERALS:
        offset = content.find(literal)
        if offset >= 0:
            violations.append(
                {
                    "rule": "retired_callable_surface",
                    "path": relative,
                    "line": _line_number(content, offset),
                    "token": literal,
                }
            )
    if relative.startswith("apps/mcp-hpc-runner/src/"):
        retired_output_key = "expected_" + "outputs"
        offset = content.find(retired_output_key)
        if offset >= 0:
            violations.append(
                {
                    "rule": "retired_runner_output_contract",
                    "path": relative,
                    "line": _line_number(content, offset),
                    "token": retired_output_key,
                }
            )
    return violations


def _entrypoint_violations(root: Path) -> list[dict[str, object]]:
    expected = {
        "apps/openzyme-host-cli/pyproject.toml": {"openzyme"},
        "apps/mcp-hpc-runner/pyproject.toml": {"mcp-hpc-runner"},
    }
    violations: list[dict[str, object]] = []
    for relative, expected_names in expected.items():
        path = root / relative
        payload = tomllib.loads(path.read_text(encoding="utf-8"))
        observed = set(payload.get("project", {}).get("scripts", {}))
        if observed != expected_names:
            violations.append(
                {
                    "rule": "entrypoint_set_drift",
                    "path": relative,
                    "line": 0,
                    "token": sorted(observed),
                    "expected": sorted(expected_names),
                }
            )
    return violations


def build_report(root: Path) -> dict[str, object]:
    root = root.resolve()
    inventory: list[str] = []
    violations: list[dict[str, object]] = []
    scan_errors: list[dict[str, str]] = []
    for path in _candidate_files(root):
        relative = path.relative_to(root).as_posix()
        inventory.append(relative)
        try:
            content = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            scan_errors.append(
                {"path": relative, "error": f"{exc.__class__.__name__}: {exc}"}
            )
            continue
        violations.extend(_literal_violations(relative, content))
    for relative in RETIRED_PATHS:
        if (root / relative).exists():
            violations.append(
                {
                    "rule": "retired_module_present",
                    "path": relative,
                    "line": 0,
                    "token": relative,
                }
            )
    try:
        violations.extend(_entrypoint_violations(root))
    except (OSError, UnicodeError, tomllib.TOMLDecodeError) as exc:
        scan_errors.append(
            {"path": "entrypoints", "error": f"{exc.__class__.__name__}: {exc}"}
        )
    violations.sort(key=lambda item: (str(item["path"]), int(item["line"]), str(item["rule"])))
    scan_errors.sort(key=lambda item: item["path"])
    payload: dict[str, object] = {
        "schema": SCHEMA_VERSION,
        "inventory": inventory,
        "inventory_digest": _canonical_digest(inventory),
        "violations": violations,
        "scan_errors": scan_errors,
        "repository_only": True,
        "deployment_removal_authorized": False,
    }
    return {**payload, "report_digest": _canonical_digest(payload)}


def _write_report(path: Path, report: dict[str, object]) -> None:
    path.write_text(
        json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def main(argv: Iterable[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary", action="store_true")
    args = parser.parse_args(argv)
    report = build_report(args.root)
    if args.output is not None:
        _write_report(args.output, report)
    if args.summary:
        print(
            json.dumps(
                {
                    "schema": report["schema"],
                    "inventory_count": len(report["inventory"]),
                    "violation_count": len(report["violations"]),
                    "scan_error_count": len(report["scan_errors"]),
                    "report_digest": report["report_digest"],
                },
                sort_keys=True,
            )
        )
    elif args.output is None:
        print(json.dumps(report, indent=2, sort_keys=True, ensure_ascii=False))
    return 1 if report["violations"] or report["scan_errors"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
