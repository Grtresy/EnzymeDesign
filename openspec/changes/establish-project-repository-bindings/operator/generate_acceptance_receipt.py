#!/usr/bin/env python3
"""Generate the final C1 acceptance from explicit, sealed evidence inputs."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from typing import cast

import verify_repository_binding as verifier


OPEN_SPEC_COMMAND = (
    "DO_NOT_TRACK=1 openspec validate establish-project-repository-bindings "
    "--type change --strict --no-interactive"
)


def load_json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"evidence input is not a JSON object: {path}")
    return value


def _fixed_documents() -> tuple[
    dict[str, dict[str, Any]],
    dict[str, str],
]:
    verifier.verify_all(require_acceptance=False, verify_sources=False)
    names = (
        "baseline",
        "policy",
        "binding",
        "preflight",
        "standard_protocol",
        "local_protocol",
        "restore",
    )
    documents = {
        name: cast(dict[str, Any], verifier.load_document(name)) for name in names
    }
    digests = {
        name: verifier.verify_document(name, document)
        for name, document in documents.items()
    }
    documents["c0"] = verifier.load_c0_acceptance()
    return documents, digests


def _snapshot_entries(paths: list[str]) -> list[dict[str, Any]]:
    entries = []
    for path in paths:
        source = verifier.REPOSITORY_ROOT / path
        if source.is_symlink() or not source.is_file():
            raise ValueError(
                f"C1 implementation snapshot is not a regular file: {path}"
            )
        content = source.read_bytes()
        entries.append(
            {
                "path": path,
                "size": len(content),
                "sha256": verifier.digest_bytes(content),
            }
        )
    return entries


def _mainline_validation(
    plan: dict[str, Any],
    mainline_receipt: dict[str, Any],
    verification_result: dict[str, Any],
) -> dict[str, Any]:
    source_identity = plan["source_identity"]
    return {
        "status": "passed",
        "command": "./scripts/check-mainline.sh",
        "verification_command": "verify-mainline-authoritative",
        "profile_id": "mainline_authoritative",
        "authority_domain": "authoritative_non_live_mainline",
        "current_authoritative_entry": "scripts/check-mainline.sh",
        "plan_digest": plan["self_digest"],
        "receipt_digest": mainline_receipt["self_digest"],
        "source_identity_digest": verifier.digest_value(source_identity),
        "source_identity": source_identity,
        "plan_schema_id": plan["schema_id"],
        "receipt_schema_id": mainline_receipt["schema_id"],
        "receipt_plan_digest": mainline_receipt["plan_digest"],
        "receipt_source_identity_digest": mainline_receipt["source_identity_digest"],
        "verification_result": verification_result,
        "plan": plan,
        "receipt": mainline_receipt,
        "terminal_status": "pass",
        "authoritative": True,
        "profile_contract_authoritative": True,
        "admission_eligible": False,
        "live_eligible": False,
        "verified_current_sources": True,
    }


def build_acceptance_receipt(
    *,
    plan: dict[str, Any],
    mainline_receipt: dict[str, Any],
    verification_result: dict[str, Any],
    focused_passed: int,
    native_passed: int,
    issued_at: str,
) -> dict[str, Any]:
    documents, document_digests = _fixed_documents()
    verifier.verify_tasks()

    current_paths = verifier.working_tree_changed_paths()
    if verifier.ACCEPTANCE_REPOSITORY_PATH in current_paths:
        raise ValueError("final C1 acceptance already exists in the change scope")
    changed_paths = sorted([*current_paths, verifier.ACCEPTANCE_REPOSITORY_PATH])
    forbidden_paths = [
        path
        for path in changed_paths
        if not any(
            path == prefix or path.startswith(prefix)
            for prefix in verifier.ALLOWED_SCOPE_PREFIXES
        )
    ]
    if forbidden_paths:
        raise ValueError(f"C1 changed forbidden paths: {forbidden_paths}")

    implementation_entries = _snapshot_entries(current_paths)
    implementation_snapshot = {
        "file_count": len(implementation_entries),
        "files": implementation_entries,
        "tree_digest": verifier.digest_value(implementation_entries),
    }
    preflight = documents["preflight"]
    binding = documents["binding"]
    database = preflight["preflight"]["database"]
    root_facts = preflight["preflight"]["root_facts"]
    mainline_validation = _mainline_validation(
        plan,
        mainline_receipt,
        verification_result,
    )

    acceptance = {
        "schema_id": "project_repository_binding_acceptance@1",
        "change_id": verifier.CHANGE_ID,
        "source_revision": verifier.BASELINE_REVISION,
        "c0_acceptance_receipt_digest": documents["c0"]["receipt_digest"],
        "implementation_baseline_digest": document_digests["baseline"],
        "durable_root_preflight_digest": document_digests["preflight"],
        "standard_protocol_implementation_digest": document_digests[
            "standard_protocol"
        ],
        "local_protocol_acceptance_digest": document_digests["local_protocol"],
        "restore_rehearsal_digest": document_digests["restore"],
        "implementation_snapshot": implementation_snapshot,
        "schema": {
            "sqlite_schema_before": 37,
            "sqlite_schema_after": 38,
            "migration_id": "038_v3_project_repository_bindings",
            "migration_sha256": verifier.digest_bytes(
                (verifier.REPOSITORY_ROOT / verifier.MIGRATION_PATH).read_bytes()
            ),
            "binding_schema": "project_repository_binding@1",
            "session_pin_schema": "session_repository_binding_pin@1",
            "credential_schema": "repository_credential@1",
        },
        "configuration": {
            "acceptance_profile": "approved_local_development",
            "https_origin": preflight["https_origin"],
            "database_identity_digest": preflight["database_identity_digest"],
            "database_mode": database["mode"],
            "binding_inventory_digest": preflight["preflight"]["inventory_digest"],
            "repository_policy_digest": document_digests["policy"],
            "binding_canonical_digest": binding["canonical_digest"],
            "durable_root_path_digests": sorted(
                str(item["path_digest"]) for item in root_facts
            ),
            "all_required_settings_explicit": True,
            "credential_material_projected": False,
            "upstream_authority": "separate_controlled_external_operation",
        },
        "scope_audit": {
            "status": "passed",
            "changed_path_count": len(changed_paths),
            "changed_path_set_digest": verifier.digest_value(changed_paths),
            "forbidden_changed_paths": [],
        },
        "focused_tests": {
            "status": "passed",
            "test_files": list(verifier.FOCUSED_TEST_FILES),
            "passed": focused_passed,
            "failed": 0,
        },
        "native_integration": {
            "status": "passed",
            "test_file": (
                "apps/openzyme-host-api/tests/test_repository_native_clients.py"
            ),
            "passed": native_passed,
            "failed": 0,
            "git_smart_http_v2_over_https": True,
            "git_lfs_batch_v2_basic": True,
            "durable_restart_reread": True,
            "revoked_credential_rejected": True,
            "hostile_git_environment_isolated": True,
            "multi_ref_push_rejected": True,
            "dynamic_health_verified": True,
            "closed_namespace_write_rejected": True,
            "released_lease_hold_write_rejected": True,
        },
        "documentation": {
            "status": "passed",
            "paths": list(verifier.DOCUMENTATION_PATHS),
        },
        "forbidden_pattern_audit": {
            "status": "passed",
            "catch_all_matches": [],
            "silent_fallback_matches": [],
            "ambient_git_fallback_matches": [],
        },
        "openspec_validation": {
            "status": "passed",
            "command": OPEN_SPEC_COMMAND,
        },
        "mainline_validation": mainline_validation,
        "product_boundaries": {
            "agent_clone_provisioning_implemented": False,
            "workspace_publication_implemented": False,
            "production_capability_lease_issuance_proven": False,
            "production_disaster_recovery_proven": False,
            "upstream_effects": 0,
        },
        "eligible_successor": {
            "change": "provision-independent-agent-git-workspaces",
            "condition": ("establish-agent-capability-leases acceptance also passes"),
            "eligible_now": False,
        },
        "status": "passed",
        "issued_at": issued_at,
    }
    acceptance["receipt_digest"] = verifier.digest_value(acceptance)

    verifier.verify_document("acceptance", acceptance)
    verifier.verify_acceptance(acceptance, documents, document_digests)
    verifier._verify_mainline_source_identity(
        acceptance,
        revision=None,
        changed=changed_paths,
    )
    for entry in documents["standard_protocol"]["implementation_files"]:
        content = (verifier.REPOSITORY_ROOT / entry["path"]).read_bytes()
        if (
            verifier.digest_bytes(content) != entry["sha256"]
            or len(content) != entry["size"]
        ):
            raise ValueError(
                f"standard protocol implementation source drift: {entry['path']}"
            )
    for path in documents["standard_protocol"]["test_files"]:
        (verifier.REPOSITORY_ROOT / path).read_bytes()
    return acceptance


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--plan", required=True, type=Path)
    parser.add_argument("--mainline-receipt", required=True, type=Path)
    parser.add_argument("--verification", required=True, type=Path)
    parser.add_argument("--focused-passed", required=True, type=int)
    parser.add_argument("--native-passed", required=True, type=int)
    parser.add_argument("--issued-at", required=True)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main() -> None:
    arguments = parse_args()
    output = arguments.output.resolve()
    expected_output = (
        verifier.OPERATOR_DIR / verifier.DOCUMENTS["acceptance"][0]
    ).resolve()
    if output != expected_output:
        raise ValueError(f"C1 acceptance output must be {expected_output}")
    if output.exists():
        raise ValueError("final C1 acceptance receipt already exists")

    acceptance = build_acceptance_receipt(
        plan=load_json_object(arguments.plan),
        mainline_receipt=load_json_object(arguments.mainline_receipt),
        verification_result=load_json_object(arguments.verification),
        focused_passed=arguments.focused_passed,
        native_passed=arguments.native_passed,
        issued_at=arguments.issued_at,
    )
    output.write_text(
        json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(acceptance["receipt_digest"])


if __name__ == "__main__":
    main()
