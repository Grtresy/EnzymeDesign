#!/usr/bin/env python3
"""Read-only verifier for the C0 AOX artifact-cutover supersession decision."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
import subprocess
from pathlib import Path
from typing import Any


OPERATOR_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = OPERATOR_DIR.parents[3]
LEGACY_CHANGE_PATH = "openspec/changes/aox-hmm-blank-world-cutover"
LEGACY_TASKS_PATH = f"{LEGACY_CHANGE_PATH}/tasks.md"
LEGACY_TASK_IDS = ("8.3", "8.4", "8.5", "8.6", "8.7", "8.8")
LEGACY_C001_ROOT = Path(
    "/tmp/openzyme-rseries-c001-campaign/"
    "formal-slot-be41f223f1ebea0d8389a3fa"
)
SQLITE_SIDECARS = frozenset(
    {"control-plane.sqlite3-shm", "control-plane.sqlite3-wal"}
)

DOCUMENTS = {
    "scope_gate": ("scope-gate.json", "gate_digest"),
    "inventory": ("frozen-inventory.json", "inventory_digest"),
    "manifest": ("supersession-manifest.json", "manifest_digest"),
    "operator_index": ("operator-index.json", "index_digest"),
    "negative_checklist": ("negative-checklist.json", "checklist_digest"),
    "governance_receipt": (
        "c0-governance-gate-receipt.json",
        "receipt_digest",
    ),
    "acceptance_receipt": ("acceptance-receipt.json", "receipt_digest"),
}

SCHEMAS = {
    "scope_gate": "c0_scope_gate@1",
    "inventory": "aox_artifact_cutover_frozen_inventory@1",
    "manifest": "aox_artifact_cutover_supersession@1",
    "operator_index": "aox_artifact_cutover_operator_index@1",
    "negative_checklist": "aox_artifact_cutover_negative_checklist@1",
    "governance_receipt": "c0_governance_gate_receipt@1",
    "acceptance_receipt": "aox_artifact_cutover_supersession_acceptance@1",
}

EXPECTED_FIELDS = {
    "scope_gate": {
        "schema_id",
        "change_id",
        "baseline_revision",
        "allowed_path_prefixes",
        "forbidden_path_prefixes",
        "forbidden_actions",
        "live_authorized",
        "external_effects_authorized",
        "issued_by",
        "issued_at",
        "gate_digest",
    },
    "inventory": {
        "schema_id",
        "legacy_change",
        "legacy_tasks",
        "c001",
        "source_snapshots",
        "identity_sets",
        "completeness_proof",
        "current_state",
        "inventory_digest",
    },
    "manifest": {
        "schema_id",
        "decision_id",
        "legacy_change",
        "c001_identity",
        "legacy_task_ids",
        "frozen_inventory",
        "decision",
        "live_authorized",
        "adoptable",
        "merge_to_main_specs",
        "legacy_identity_disposition",
        "historical_migration",
        "fresh_successor_admission",
        "decided_by",
        "decided_at",
        "manifest_digest",
    },
    "operator_index": {
        "schema_id",
        "entries",
        "closed_admission_decision",
        "index_digest",
    },
    "negative_checklist": {
        "schema_id",
        "manifest_digest",
        "checks",
        "effect_summary",
        "checklist_digest",
    },
    "governance_receipt": {
        "schema_id",
        "change_id",
        "source_revision",
        "scope_gate_digest",
        "inventory_digest",
        "manifest_digest",
        "operator_index_digest",
        "negative_checklist_digest",
        "legacy_decision",
        "live_effect_summary",
        "eligible_changes",
        "status",
        "issued_at",
        "receipt_digest",
    },
    "acceptance_receipt": {
        "schema_id",
        "change_id",
        "source_revision",
        "governance_gate_receipt_digest",
        "manifest_digest",
        "inventory_digest",
        "scope_audit",
        "focused_tests",
        "documentation",
        "openspec_validation",
        "mainline_validation",
        "eligible_successors",
        "legacy_decision",
        "status",
        "issued_at",
        "receipt_digest",
    },
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def digest_value(value: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_bytes(value)).hexdigest()


def digest_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def load_document(name: str, *, required: bool = True) -> dict[str, Any] | None:
    filename, _ = DOCUMENTS[name]
    path = OPERATOR_DIR / filename
    if not path.exists():
        if required:
            raise ValueError(f"required operator document is missing: {filename}")
        return None
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"operator document must be a JSON object: {filename}")
    return value


def verify_document(name: str, value: dict[str, Any]) -> str:
    actual_fields = set(value)
    if actual_fields != EXPECTED_FIELDS[name]:
        raise ValueError(
            f"{name} fields are not closed: "
            f"missing={sorted(EXPECTED_FIELDS[name] - actual_fields)}, "
            f"extra={sorted(actual_fields - EXPECTED_FIELDS[name])}"
        )
    if value["schema_id"] != SCHEMAS[name]:
        raise ValueError(f"{name} schema_id is invalid")
    _, digest_field = DOCUMENTS[name]
    preimage = {key: item for key, item in value.items() if key != digest_field}
    actual_digest = digest_value(preimage)
    if value[digest_field] != actual_digest:
        raise ValueError(f"{name} canonical digest does not match")
    return actual_digest


def _git_output(*arguments: str) -> bytes:
    return subprocess.run(
        ("git", *arguments),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
    ).stdout


def git_tree_snapshot(revision: str, prefix: str) -> dict[str, Any]:
    paths = _git_output("ls-tree", "-r", "--name-only", revision, "--", prefix)
    entries = []
    for path_bytes in paths.splitlines():
        path = path_bytes.decode("utf-8")
        content = _git_output("show", f"{revision}:{path}")
        entries.append(
            {"path": path, "sha256": digest_bytes(content), "size": len(content)}
        )
    return {
        "file_count": len(entries),
        "total_bytes": sum(entry["size"] for entry in entries),
        "tree_digest": digest_value(entries),
    }


def working_tree_changed_paths() -> list[str]:
    tracked = subprocess.run(
        ("git", "-c", "core.quotePath=false", "diff", "--name-only"),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    untracked = subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "ls-files",
            "--others",
            "--exclude-standard",
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    return sorted(set(tracked + untracked))


def scope_audit_paths(receipt: dict[str, Any]) -> list[str]:
    acceptance_path = OPERATOR_DIR / DOCUMENTS["acceptance_receipt"][0]
    repository_path = acceptance_path.relative_to(REPOSITORY_ROOT).as_posix()
    publication_commits = subprocess.run(
        (
            "git",
            "log",
            "--format=%H",
            "--diff-filter=A",
            "--",
            repository_path,
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    if not publication_commits:
        return working_tree_changed_paths()
    if len(publication_commits) != 1:
        raise ValueError("acceptance receipt has multiple publication commits")
    publication_commit = publication_commits[0]
    published_bytes = _git_output("show", f"{publication_commit}:{repository_path}")
    if published_bytes != acceptance_path.read_bytes():
        raise ValueError("published acceptance receipt was modified after publication")
    return subprocess.run(
        (
            "git",
            "-c",
            "core.quotePath=false",
            "diff",
            "--name-only",
            receipt["source_revision"],
            publication_commit,
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()


def filesystem_tree_snapshot(root: Path) -> dict[str, Any]:
    entries = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.name in SQLITE_SIDECARS:
            continue
        content = path.read_bytes()
        entries.append(
            {
                "path": path.relative_to(root).as_posix(),
                "sha256": digest_bytes(content),
                "size": len(content),
            }
        )
    return {
        "file_count": len(entries),
        "total_bytes": sum(entry["size"] for entry in entries),
        "tree_digest": digest_value(entries),
    }


def _sqlite_rows(
    connection: sqlite3.Connection,
    query: str,
) -> list[dict[str, Any]]:
    connection.row_factory = sqlite3.Row
    return [dict(row) for row in connection.execute(query)]


def sqlite_projection_digests(database_path: Path) -> dict[str, dict[str, Any]]:
    connection = sqlite3.connect(f"file:{database_path}?mode=ro", uri=True)
    projections: dict[str, list[dict[str, Any]]] = {
        "command_receipts": _sqlite_rows(
            connection,
            """
            SELECT command_receipt_id, scope_ref, session_id, command_type,
                   idempotency_key, request_digest, status, created_at, completed_at
            FROM command_receipt_records ORDER BY command_receipt_id
            """,
        ),
        "mutation_authority": _sqlite_rows(
            connection,
            """
            SELECT scope_id, scope_kind, scope_ref, state, state_version, policy_id,
                   writer_coverage_manifest_digest, sealed_receipt_digest
            FROM mutation_scope_records ORDER BY scope_id
            """,
        ),
        "approvals": _sqlite_rows(
            connection,
            """
            SELECT approval_id, request_ref, status, kind, created_at
            FROM approval_requests ORDER BY approval_id
            """,
        ),
        "result_artifacts": _sqlite_rows(
            connection,
            """
            SELECT result_handle_id, ordinal, artifact_id, schema_version,
                   execution_id, operation_id, artifact_kind, relative_path,
                   artifact_digest
            FROM controlled_operation_result_artifacts
            ORDER BY result_handle_id, ordinal
            """,
        ),
        "result_handles": _sqlite_rows(
            connection,
            """
            SELECT result_handle_id, execution_id, operation_id, session_id,
                   schema_version, dispatch_generation, terminal_outcome,
                   result_digest, artifact_set_digest, origin, created_at
            FROM controlled_operation_result_handles ORDER BY result_handle_id
            """,
        ),
        "execution_events": _sqlite_rows(
            connection,
            """
            SELECT event_id, execution_id, operation_id, schema_version,
                   state_version, phase, lifecycle_state, terminal_outcome,
                   effect_certainty, retry_eligibility, safe_receipt_digest,
                   created_at
            FROM controlled_operation_execution_events
            ORDER BY execution_id, state_version
            """,
        ),
        "attempt_authority": _sqlite_rows(
            connection,
            """
            SELECT envelope_id, schema_version, session_id, task_id, campaign_id,
                   workflow_id, root_ref, status, state_version, policy_digest,
                   request_digest, created_at, updated_at
            FROM scientific_attempt_authorization_records ORDER BY envelope_id
            """,
        ),
        "failures": _sqlite_rows(
            connection,
            """
            SELECT failure_id, schema_version, session_id, task_id, lane_id,
                   source_kind, source_ref, error_code, effect_certainty,
                   retry_eligibility, private_diagnostic_digest, created_at
            FROM failure_observation_records ORDER BY failure_id
            """,
        ),
    }
    artifact_rows = _sqlite_rows(
        connection,
        """
        SELECT artifact_id, kind, relative_path, metadata_json, created_at
        FROM session_artifact_records ORDER BY artifact_id
        """,
    )
    for row in artifact_rows:
        metadata = json.loads(row.pop("metadata_json"))
        row["content_digest"] = metadata.get("content_digest") or metadata.get(
            "source_tree_digest"
        )
        row["metadata_identity_digest"] = digest_value(metadata)
    projections["artifact_manifests"] = artifact_rows
    connection.close()
    return {
        name: {"count": len(rows), "digest": digest_value(rows)}
        for name, rows in projections.items()
    }


def public_receipt_projection(path: Path) -> dict[str, Any]:
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]
    projection_fields = (
        "sequence",
        "schema_id",
        "method",
        "route",
        "idempotency_key",
        "request_digest",
        "request_identity_digest",
        "response_digest",
        "response_semantic_digest",
        "status_code",
        "effect_certainty",
        "retry_eligibility",
        "terminal_scope",
    )
    projection = [
        {field: row.get(field) for field in projection_fields} for row in rows
    ]
    return {
        "count": len(rows),
        "sequences": [row["sequence"] for row in rows],
        "schema_ids": sorted({row["schema_id"] for row in rows}),
        "projection_digest": digest_value(projection),
        "file_digest": digest_bytes(path.read_bytes()),
    }


def sealed_byte_projections(root: Path) -> dict[str, dict[str, Any]]:
    sealed_files = []
    for path in sorted((root / "blobs/sealed/files").iterdir()):
        content = path.read_bytes()
        digest = digest_bytes(content)
        sealed_files.append(
            {
                "path": path.relative_to(root).as_posix(),
                "size": len(content),
                "digest": digest,
                "name_matches_digest": path.name == digest.removeprefix("sha256:"),
            }
        )
    source_trees = []
    for directory in sorted((root / "blobs/sealed/source").iterdir()):
        files = []
        for path in sorted(item for item in directory.rglob("*") if item.is_file()):
            content = path.read_bytes()
            files.append(
                {
                    "path": path.relative_to(directory).as_posix(),
                    "size": len(content),
                    "digest": digest_bytes(content),
                }
            )
        source_trees.append(
            {
                "source_tree_digest": f"sha256:{directory.name}",
                "file_count": len(files),
                "files_digest": digest_value(files),
            }
        )
    return {
        "sealed_files": {
            "count": len(sealed_files),
            "digest": digest_value(sealed_files),
        },
        "source_trees": {
            "count": len(source_trees),
            "digest": digest_value(source_trees),
        },
    }


def verify_scope_gate(scope_gate: dict[str, Any]) -> None:
    if scope_gate["live_authorized"] or scope_gate["external_effects_authorized"]:
        raise ValueError("C0 scope gate must authorize zero live or external effects")
    expected_allowed = [
        "openspec/changes/supersede-aox-hmm-artifact-cutover/",
        "docs/OpenZyme架构设计.md",
        "docs/v3/",
    ]
    if scope_gate["allowed_path_prefixes"] != expected_allowed:
        raise ValueError("C0 allowed path prefixes do not match the closed scope")
    if LEGACY_CHANGE_PATH + "/" not in scope_gate["forbidden_path_prefixes"]:
        raise ValueError("legacy AOX change is not explicitly write-forbidden")


def verify_inventory(inventory: dict[str, Any]) -> None:
    tasks = inventory["legacy_tasks"]
    if [task["task_id"] for task in tasks] != list(LEGACY_TASK_IDS):
        raise ValueError("legacy task inventory is incomplete, duplicated, or reordered")
    if any(task["status"] != "pending_unexecuted" for task in tasks):
        raise ValueError("a legacy live task was incorrectly marked executed")
    expected_task_fields = {
        "task_id",
        "source_path",
        "schema_or_id",
        "digest",
        "status",
    }
    if any(set(task) != expected_task_fields for task in tasks):
        raise ValueError("legacy task inventory fields are not closed")
    c001 = inventory["c001"]
    expected_c001 = {
        "campaign_id": "aox_campaign_9b88525edafde6cb643da624",
        "launch_id": "formal-slot-be41f223f1ebea0d8389a3fa",
        "session_id": "sess_aox_formal_ffcec8565dd7abe16b88dbe1c68e12ea",
        "attempt_id": "attempt_8f5b8e0430c5bfb036abea08",
        "selection_id": "selection_8430d343987b39ca03687857",
        "earliest_failure_id": "failure_c9bfd006a706eedb3878",
    }
    for field, expected in expected_c001.items():
        if c001[field] != expected:
            raise ValueError(f"c001 {field} does not match the frozen incident")
    proof = inventory["completeness_proof"]
    if proof["legacy_task_ids_exactly_once"] is not True:
        raise ValueError("legacy task uniqueness proof is absent")
    if proof["c001_identity_unique"] is not True:
        raise ValueError("c001 identity uniqueness proof is absent")
    if proof["omitted_related_identity_count"] != 0:
        raise ValueError("frozen inventory reports omitted related identities")
    if inventory["current_state"]["canonical_go_no_go_created"] is not False:
        raise ValueError("c001 must remain noncanonical")
    identity_sets = inventory["identity_sets"]
    expected_identity_counts = {
        "authorities": 6,
        "roots": 5,
        "receipts": 11,
        "byte_manifests": 4,
        "entities": 4,
    }
    if set(identity_sets) != set(expected_identity_counts):
        raise ValueError("frozen identity-set categories are not closed")
    identity_fields = {"source_path", "schema_or_id", "identity", "digest", "status"}
    for category, expected_count in expected_identity_counts.items():
        entries = identity_sets[category]
        if len(entries) != expected_count:
            raise ValueError(f"frozen {category} inventory count does not match")
        if any(set(entry) != identity_fields for entry in entries):
            raise ValueError(f"frozen {category} inventory fields are not closed")
        identities = [entry["identity"] for entry in entries]
        if len(identities) != len(set(identities)):
            raise ValueError(f"frozen {category} inventory contains duplicate identities")
    expected_sqlite_projections = {
        "command_receipts",
        "mutation_authority",
        "approvals",
        "result_artifacts",
        "result_handles",
        "execution_events",
        "attempt_authority",
        "failures",
        "artifact_manifests",
    }
    if set(proof["sqlite_projections"]) != expected_sqlite_projections:
        raise ValueError("SQLite completeness projection set is not closed")
    if proof["public_api_receipt_projection"]["sequences"] != list(range(1, 57)):
        raise ValueError("public API receipt chain is incomplete or reordered")
    if proof["sealed_byte_projections"]["sealed_files"]["count"] != 9:
        raise ValueError("sealed legacy byte inventory is incomplete")
    if proof["sealed_byte_projections"]["source_trees"]["count"] != 10:
        raise ValueError("sealed source-tree inventory is incomplete")


def verify_manifest(
    manifest: dict[str, Any],
    inventory: dict[str, Any],
) -> None:
    if manifest["frozen_inventory"]["digest"] != inventory["inventory_digest"]:
        raise ValueError("manifest does not bind the frozen inventory digest")
    if manifest["legacy_task_ids"] != list(LEGACY_TASK_IDS):
        raise ValueError("manifest does not bind the exact six legacy live tasks")
    if manifest["decision"] != "legacy_no_go":
        raise ValueError("legacy decision must remain legacy_no_go")
    if manifest["live_authorized"] is not False:
        raise ValueError("legacy live work must remain unauthorized")
    if manifest["adoptable"] is not False:
        raise ValueError("legacy evidence must remain non-adoptable")
    if manifest["merge_to_main_specs"] is not False:
        raise ValueError("legacy artifact deltas must not enter main specs")
    disposition = manifest["legacy_identity_disposition"]
    expected_disposition_fields = {
        "authority",
        "roots",
        "receipts",
        "bytes",
        "tasks",
    }
    if set(disposition) != expected_disposition_fields:
        raise ValueError("legacy identity disposition is not closed")
    for name, value in disposition.items():
        if value != {
            "recoverable": False,
            "replayable": False,
            "replacement_allowed": False,
            "successor_admission_input": False,
        }:
            raise ValueError(f"legacy {name} disposition permits forbidden reuse")
    historical = manifest["historical_migration"]
    if historical != {
        "classification": "historical_import_non_adoptable",
        "may_create_published_revision": False,
        "may_create_fresh_scientific_evidence": False,
        "may_satisfy_go": False,
        "must_retain_supersession_identity": True,
    }:
        raise ValueError("historical byte migration could create current truth")


def verify_index(index: dict[str, Any], manifest: dict[str, Any]) -> None:
    if len(index["entries"]) != 1:
        raise ValueError("operator index must contain exactly one legacy entry")
    entry = index["entries"][0]
    if entry["change_id"] != "aox-hmm-blank-world-cutover":
        raise ValueError("operator index points to the wrong legacy change")
    if entry["decision"] != "superseded":
        raise ValueError("operator index does not mark the legacy change superseded")
    if entry["supersession_manifest_digest"] != manifest["manifest_digest"]:
        raise ValueError("operator index manifest binding does not match")
    decision = index["closed_admission_decision"]
    if decision["code"] != "legacy_aox_artifact_cutover_superseded":
        raise ValueError("operator admission decision code drifted")
    if decision["external_effect"] != "no_effect":
        raise ValueError("operator rejection must precede every external effect")


def verify_negative_checklist(
    checklist: dict[str, Any],
    manifest: dict[str, Any],
) -> None:
    if checklist["manifest_digest"] != manifest["manifest_digest"]:
        raise ValueError("negative checklist manifest binding does not match")
    expected_checks = {
        "c001_resume",
        "legacy_tasks_8_3_through_8_8",
        "legacy_authority_reuse",
        "legacy_byte_adoption",
        "legacy_main_spec_sync",
    }
    if {check["check_id"] for check in checklist["checks"]} != expected_checks:
        raise ValueError("negative checklist is incomplete")
    if any(check["decision"] != "rejected_superseded" for check in checklist["checks"]):
        raise ValueError("a negative checklist entry is not rejected")
    if any(check["external_effect"] != "no_effect" for check in checklist["checks"]):
        raise ValueError("a negative checklist entry permits an external effect")
    if any(value != 0 for value in checklist["effect_summary"].values()):
        raise ValueError("C0 effect summary is not zero")


def verify_governance_receipt(
    receipt: dict[str, Any],
    documents: dict[str, dict[str, Any]],
) -> None:
    expected_bindings = {
        "scope_gate_digest": documents["scope_gate"]["gate_digest"],
        "inventory_digest": documents["inventory"]["inventory_digest"],
        "manifest_digest": documents["manifest"]["manifest_digest"],
        "operator_index_digest": documents["operator_index"]["index_digest"],
        "negative_checklist_digest": documents["negative_checklist"][
            "checklist_digest"
        ],
    }
    for field, expected in expected_bindings.items():
        if receipt[field] != expected:
            raise ValueError(f"governance receipt {field} binding does not match")
    if receipt["status"] != "passed":
        raise ValueError("C0 governance receipt is not passed")
    if receipt["legacy_decision"] != "legacy_no_go":
        raise ValueError("C0 governance receipt lost legacy NO-GO")
    if any(value != 0 for value in receipt["live_effect_summary"].values()):
        raise ValueError("C0 governance receipt reports a live effect")
    if receipt["eligible_changes"] != [
        "establish-project-repository-bindings",
        "establish-agent-capability-leases",
    ]:
        raise ValueError("C0 governance receipt successor set drifted")


def verify_acceptance_receipt(
    receipt: dict[str, Any],
    documents: dict[str, dict[str, Any]],
) -> None:
    if (
        receipt["governance_gate_receipt_digest"]
        != documents["governance_receipt"]["receipt_digest"]
    ):
        raise ValueError("acceptance receipt governance binding does not match")
    if receipt["manifest_digest"] != documents["manifest"]["manifest_digest"]:
        raise ValueError("acceptance receipt manifest binding does not match")
    if receipt["inventory_digest"] != documents["inventory"]["inventory_digest"]:
        raise ValueError("acceptance receipt inventory binding does not match")
    if receipt["status"] != "passed":
        raise ValueError("C0 acceptance receipt is not passed")
    if receipt["legacy_decision"] != "legacy_no_go":
        raise ValueError("C0 acceptance receipt lost legacy NO-GO")
    if receipt["eligible_successors"] != ["C1", "C2"]:
        raise ValueError("C0 acceptance successor set drifted")
    for evidence_field in (
        "scope_audit",
        "focused_tests",
        "documentation",
        "openspec_validation",
        "mainline_validation",
    ):
        if receipt[evidence_field]["status"] != "passed":
            raise ValueError(f"acceptance evidence did not pass: {evidence_field}")


def verify_working_scope(
    receipt: dict[str, Any],
    scope_gate: dict[str, Any],
) -> None:
    paths = scope_audit_paths(receipt)
    audit = receipt["scope_audit"]
    if audit["changed_path_count"] != len(paths):
        raise ValueError("acceptance scope-audit path count does not match")
    if audit["changed_path_set_digest"] != digest_value(paths):
        raise ValueError("acceptance scope-audit path digest does not match")
    forbidden = [
        path
        for path in paths
        if not any(
            path == prefix or path.startswith(prefix)
            for prefix in scope_gate["allowed_path_prefixes"]
        )
    ]
    if forbidden:
        raise ValueError(f"C0 working tree contains forbidden paths: {forbidden}")
    if audit["forbidden_changed_paths"] != []:
        raise ValueError("acceptance scope audit reports forbidden paths")


def verify_legacy_sources(inventory: dict[str, Any]) -> None:
    legacy = inventory["legacy_change"]
    frozen_snapshot = git_tree_snapshot(
        legacy["frozen_source_revision"], LEGACY_CHANGE_PATH
    )
    if frozen_snapshot != legacy["frozen_change_tree"]:
        raise ValueError("frozen legacy OpenSpec tree does not match")
    governance_snapshot = git_tree_snapshot(
        legacy["governance_snapshot_revision"], LEGACY_CHANGE_PATH
    )
    if governance_snapshot != legacy["governance_change_tree"]:
        raise ValueError("governance legacy OpenSpec tree does not match")
    tasks_text = _git_output(
        "show", f"{legacy['governance_snapshot_revision']}:{LEGACY_TASKS_PATH}"
    ).decode("utf-8")
    for task_id in LEGACY_TASK_IDS:
        matches = re.findall(
            rf"^- \[ \] {re.escape(task_id)} .+$",
            tasks_text,
            flags=re.MULTILINE,
        )
        if len(matches) != 1:
            raise ValueError(f"legacy task {task_id} is not pending exactly once")
        task_entry = next(
            item for item in inventory["legacy_tasks"] if item["task_id"] == task_id
        )
        if digest_bytes(matches[0].encode("utf-8")) != task_entry["digest"]:
            raise ValueError(f"legacy task {task_id} source digest does not match")
    root_snapshot = filesystem_tree_snapshot(LEGACY_C001_ROOT)
    expected_root_snapshot = inventory["source_snapshots"]["c001_root"]
    comparable_expected = {
        key: expected_root_snapshot[key]
        for key in ("file_count", "total_bytes", "tree_digest")
    }
    if root_snapshot != comparable_expected:
        raise ValueError("c001 frozen filesystem snapshot does not match")
    database_path = LEGACY_C001_ROOT / "control-plane.sqlite3"
    if digest_bytes(database_path.read_bytes()) != inventory["source_snapshots"][
        "control_plane_database"
    ]["file_digest"]:
        raise ValueError("c001 control-plane database bytes do not match")
    expected_sqlite = inventory["completeness_proof"]["sqlite_projections"]
    if sqlite_projection_digests(database_path) != expected_sqlite:
        raise ValueError("c001 SQLite identity projection does not match")
    public_receipts = LEGACY_C001_ROOT / "evidence/public-api-receipts.jsonl"
    if public_receipt_projection(public_receipts) != inventory[
        "completeness_proof"
    ]["public_api_receipt_projection"]:
        raise ValueError("c001 public API receipt projection does not match")
    if sealed_byte_projections(LEGACY_C001_ROOT) != inventory[
        "completeness_proof"
    ]["sealed_byte_projections"]:
        raise ValueError("c001 sealed byte projection does not match")
    for document in inventory["source_snapshots"]["external_documents"]:
        path = Path(document["source_path"])
        if digest_bytes(path.read_bytes()) != document["file_digest"]:
            raise ValueError(f"external frozen document bytes do not match: {path}")
    raw_file_entries = [
        *inventory["identity_sets"]["authorities"][:3],
        *inventory["identity_sets"]["receipts"][:8],
    ]
    for entry in raw_file_entries:
        path = Path(entry["source_path"].split("#", maxsplit=1)[0])
        if digest_bytes(path.read_bytes()) != entry["digest"]:
            raise ValueError(f"frozen identity source bytes do not match: {path}")


def verify_all(
    *,
    require_acceptance: bool,
    verify_sources: bool,
) -> dict[str, Any]:
    names = [
        "scope_gate",
        "inventory",
        "manifest",
        "operator_index",
        "negative_checklist",
        "governance_receipt",
    ]
    if require_acceptance:
        names.append("acceptance_receipt")
    documents = {name: load_document(name) for name in names}
    typed_documents = {
        name: value for name, value in documents.items() if value is not None
    }
    digests = {
        name: verify_document(name, value)
        for name, value in typed_documents.items()
    }
    verify_scope_gate(typed_documents["scope_gate"])
    verify_inventory(typed_documents["inventory"])
    verify_manifest(typed_documents["manifest"], typed_documents["inventory"])
    verify_index(typed_documents["operator_index"], typed_documents["manifest"])
    verify_negative_checklist(
        typed_documents["negative_checklist"], typed_documents["manifest"]
    )
    verify_governance_receipt(
        typed_documents["governance_receipt"], typed_documents
    )
    if require_acceptance:
        verify_acceptance_receipt(
            typed_documents["acceptance_receipt"], typed_documents
        )
    if verify_sources:
        verify_legacy_sources(typed_documents["inventory"])
        if require_acceptance:
            verify_working_scope(
                typed_documents["acceptance_receipt"],
                typed_documents["scope_gate"],
            )
    return {
        "schema_id": "aox_artifact_cutover_supersession_verification@1",
        "status": "passed",
        "acceptance_required": require_acceptance,
        "legacy_sources_verified": verify_sources,
        "document_digests": digests,
        "external_effects": 0,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--require-acceptance",
        action="store_true",
        help="also require and verify the final C0 acceptance receipt",
    )
    parser.add_argument(
        "--verify-legacy-sources",
        action="store_true",
        help="re-read local frozen Git/c001 sources and compare every projection",
    )
    return parser.parse_args()


def main() -> None:
    arguments = parse_args()
    result = verify_all(
        require_acceptance=arguments.require_acceptance,
        verify_sources=arguments.verify_legacy_sources,
    )
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))


if __name__ == "__main__":
    main()
