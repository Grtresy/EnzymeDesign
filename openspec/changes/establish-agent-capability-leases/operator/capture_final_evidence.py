#!/usr/bin/env python3
"""Capture one sealed C2 final-evidence bundle from current verified sources."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import tempfile
import xml.etree.ElementTree as ElementTree
from pathlib import Path
from typing import Any

import verify_agent_capability_lease as verifier


OPEN_SPEC_COMMAND = (
    "DO_NOT_TRACK=1 openspec validate establish-agent-capability-leases "
    "--type change --strict --no-interactive"
)
OPEN_SPEC_RESULT = "Change 'establish-agent-capability-leases' is valid"


def _load_json_object(path: Path) -> dict[str, Any]:
    return verifier.load_json_object(path)


def _snapshot_entries(paths: list[str]) -> list[dict[str, Any]]:
    entries = []
    for path in paths:
        source = verifier.REPOSITORY_ROOT / path
        if source.is_symlink() or not source.is_file():
            raise ValueError(f"C2 snapshot source is not a regular file: {path}")
        content = source.read_bytes()
        entries.append(
            {
                "path": path,
                "size": len(content),
                "sha256": verifier.digest_bytes(content),
            }
        )
    return entries


def _verify_mainline(output_root: Path) -> dict[str, Any]:
    completed = subprocess.run(
        (
            verifier.FOCUSED_PYTHON,
            "scripts/run-test-gate.py",
            "verify-mainline-authoritative",
            str(output_root),
        ),
        cwd=verifier.REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    return json.loads(completed.stdout.strip().splitlines()[-1])


def _mainline_validation(output_root: Path) -> dict[str, Any]:
    plan = _load_json_object(output_root / "mainline-authoritative-plan.json")
    receipt = _load_json_object(output_root / "mainline-authoritative-receipt.json")
    verification = _verify_mainline(output_root)
    source_identity = plan["source_identity"]
    return {
        "status": "passed",
        "command": "./scripts/check-mainline.sh",
        "verification_command": "verify-mainline-authoritative",
        "profile_id": "mainline_authoritative",
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
        "plan_digest": plan["self_digest"],
        "receipt_digest": receipt["self_digest"],
        "source_identity_digest": verifier.digest_value(source_identity),
        "source_identity": source_identity,
        "plan_schema_id": plan["schema_id"],
        "receipt_schema_id": receipt["schema_id"],
        "receipt_plan_digest": receipt["plan_digest"],
        "receipt_source_identity_digest": receipt["source_identity_digest"],
        "verification_result": verification,
        "plan": plan,
        "receipt": receipt,
        "terminal_status": "pass",
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "verified_current_sources": True,
    }


def _openspec_validation() -> dict[str, str]:
    environment = dict(os.environ)
    environment["DO_NOT_TRACK"] = "1"
    completed = subprocess.run(
        (
            "openspec",
            "validate",
            verifier.CHANGE_ID,
            "--type",
            "change",
            "--strict",
            "--no-interactive",
        ),
        cwd=verifier.REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    if lines != [OPEN_SPEC_RESULT]:
        raise ValueError("strict OpenSpec validation output is not canonical")
    return {
        "status": "passed",
        "command": OPEN_SPEC_COMMAND,
        "result": OPEN_SPEC_RESULT,
    }


def _run_focused_validation(*, source_tree_digest: str) -> dict[str, Any]:
    environment = dict(os.environ)
    environment.update(verifier.FOCUSED_ENVIRONMENT)
    collection_argv = (
        verifier.FOCUSED_PYTHON,
        "-m",
        "pytest",
        "--collect-only",
        "-q",
        "-p",
        "no:cacheprovider",
        *verifier.FOCUSED_TEST_FILES,
    )
    collection = subprocess.run(
        collection_argv,
        cwd=verifier.REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if collection.returncode != 0:
        raise RuntimeError(
            "C2 focused test collection failed:\n"
            + collection.stdout
            + collection.stderr
        )
    node_ids = [
        line.strip()
        for line in collection.stdout.splitlines()
        if "::" in line and not line.startswith("ERROR ")
    ]
    if not node_ids or len(node_ids) != len(set(node_ids)):
        raise ValueError("C2 focused test collection is empty or duplicated")

    with tempfile.TemporaryDirectory(prefix="openzyme-c2-focused-") as temp_root:
        junit_path = Path(temp_root) / "focused-junit.xml"
        pytest_argv = (
            verifier.FOCUSED_PYTHON,
            "-m",
            "pytest",
            "-q",
            "-p",
            "no:cacheprovider",
            f"--junitxml={junit_path}",
            *verifier.FOCUSED_TEST_FILES,
        )
        pytest_result = subprocess.run(
            pytest_argv,
            cwd=verifier.REPOSITORY_ROOT,
            check=False,
            capture_output=True,
            text=True,
            env=environment,
        )
        if pytest_result.returncode != 0:
            raise RuntimeError(
                "C2 focused tests failed:\n"
                + pytest_result.stdout
                + pytest_result.stderr
            )
        junit_root = ElementTree.parse(junit_path).getroot()
        suites = list(junit_root)
        if junit_root.tag != "testsuites" or len(suites) != 1:
            raise ValueError("C2 focused JUnit schema is not one pytest suite")
        junit = suites[0]
        if junit.tag != "testsuite":
            raise ValueError("C2 focused JUnit suite is missing")
        tests = int(junit.attrib["tests"])
        failures = int(junit.attrib["failures"])
        errors = int(junit.attrib["errors"])
        skipped = int(junit.attrib["skipped"])
    if tests != len(node_ids) or failures != 0 or errors != 0 or skipped != 0:
        raise ValueError("C2 focused JUnit result does not match exact collection")

    ruff_argv = (
        verifier.FOCUSED_PYTHON,
        "-m",
        "ruff",
        "check",
        *verifier.FOCUSED_RUFF_PATHS,
    )
    ruff = subprocess.run(
        ruff_argv,
        cwd=verifier.REPOSITORY_ROOT,
        check=False,
        capture_output=True,
        text=True,
        env=environment,
    )
    if ruff.returncode != 0:
        raise RuntimeError("C2 Ruff validation failed:\n" + ruff.stdout + ruff.stderr)

    return {
        "status": "passed",
        "test_files": list(verifier.FOCUSED_TEST_FILES),
        "collection_command": list(collection_argv),
        "collection_exit_code": collection.returncode,
        "node_count": len(node_ids),
        "node_ids_digest": verifier.digest_value(node_ids),
        "collection_stdout_digest": verifier.digest_bytes(
            collection.stdout.encode("utf-8")
        ),
        "pytest_command": list(pytest_argv),
        "pytest_exit_code": pytest_result.returncode,
        "pytest_stdout_digest": verifier.digest_bytes(
            pytest_result.stdout.encode("utf-8")
        ),
        "passed": tests,
        "failed": failures,
        "errors": errors,
        "skipped": skipped,
        "ruff_command": list(ruff_argv),
        "ruff_exit_code": ruff.returncode,
        "ruff_stdout_digest": verifier.digest_bytes(ruff.stdout.encode("utf-8")),
        "ruff_status": "passed",
        "environment": verifier.FOCUSED_ENVIRONMENT,
        "source_tree_digest": source_tree_digest,
        "live_provider_hpc_opt_in": False,
    }


def build_final_evidence(
    *,
    mainline_root: Path,
    issued_at: str,
) -> dict[str, Any]:
    verifier.verify_all(require_acceptance=False, verify_sources=False)
    verifier.verify_tasks()
    if not issued_at:
        raise ValueError("C2 evidence issued_at is required")

    current_paths = verifier.working_tree_changed_paths()
    if verifier.ACCEPTANCE_REPOSITORY_PATH in current_paths:
        raise ValueError("final C2 acceptance already exists in the change scope")
    if current_paths != list(verifier.EXPECTED_IMPLEMENTATION_PATHS):
        raise ValueError("current C2 paths do not equal the reviewed implementation manifest")
    scope_paths = sorted([*current_paths, verifier.ACCEPTANCE_REPOSITORY_PATH])
    forbidden = [
        path
        for path in scope_paths
        if not verifier.is_allowed_scope_path(path)
    ]
    if forbidden:
        raise ValueError(f"C2 changed forbidden paths: {forbidden}")

    snapshot_entries = _snapshot_entries(current_paths)
    implementation_tree_digest = verifier.digest_value(snapshot_entries)
    deferred_boundary = verifier.verify_deferred_implementation_boundary(
        current_paths,
        revision=None,
    )
    evidence = {
        "schema_id": verifier.FINAL_EVIDENCE_SCHEMA,
        "source_revision": verifier.BASELINE_REVISION,
        "implementation_snapshot": {
            "file_count": len(snapshot_entries),
            "files": snapshot_entries,
            "tree_digest": implementation_tree_digest,
        },
        "schema": {
            "sqlite_schema_before": 38,
            "sqlite_schema_after": 39,
            "migration_id": "039_v3_agent_capability_leases",
            "migration_sha256": verifier.digest_bytes(
                (verifier.REPOSITORY_ROOT / verifier.MIGRATION_PATH).read_bytes()
            ),
            "lease_schema": "agent_capability_lease@1",
            "generation_reservation_schema": (
                "agent_workspace_generation_reservation@1"
            ),
            "retirement_request_schema": "agent_retirement_request@1",
            "retirement_cleanup_proof_schema": (
                "agent_retirement_cleanup_proof@1"
            ),
            "retirement_schema": "agent_retirement_record@1",
        },
        "focused_validation": _run_focused_validation(
            source_tree_digest=implementation_tree_digest
        ),
        "documentation": {
            "status": "passed",
            "paths": list(verifier.DOCUMENTATION_PATHS),
        },
        "openspec_validation": _openspec_validation(),
        "mainline_validation": _mainline_validation(mainline_root),
        "scope_audit": {
            "status": "passed",
            "changed_path_count": len(scope_paths),
            "changed_path_set_digest": verifier.digest_value(scope_paths),
            "implementation_manifest_digest": verifier.digest_value(
                list(verifier.EXPECTED_IMPLEMENTATION_PATHS)
            ),
            "forbidden_changed_paths": [],
            **deferred_boundary,
        },
        "issued_at": issued_at,
    }
    evidence["evidence_digest"] = verifier.digest_value(evidence)
    verifier.verify_final_evidence(evidence, verify_sources=True)
    return evidence


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mainline-root", required=True, type=Path)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    arguments = parse_args(argv)
    output_root = arguments.mainline_root.resolve(strict=True)
    if not output_root.is_dir():
        raise ValueError("C2 mainline evidence root is not a directory")
    evidence = build_final_evidence(
        mainline_root=output_root,
        issued_at=arguments.issued_at,
    )
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(evidence, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
    print(evidence["evidence_digest"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
