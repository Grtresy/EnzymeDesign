#!/usr/bin/env python3
"""Compile the exact prerequisite receipt chain for offline subsystem removal."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.source import collect_source_identity  # noqa: E402


CHANGE_ROOT = REPOSITORY_ROOT / "openspec" / "changes"
FINAL_SCHEMA = (
    REPOSITORY_ROOT
    / "packages/openzyme-core/src/openzyme_core/migrations/001_file_workspace_final.sql"
)
ACTIVATION_SCHEMA_ID = "file_workspace_release_activation@1"
RELEASE_BUNDLE_SCHEMA_ID = "file_workspace_release_receipt_bundle@1"
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
CHANGE_IDS = (
    "supersede-aox-hmm-artifact-cutover",
    "establish-project-repository-bindings",
    "establish-agent-capability-leases",
    "provision-independent-agent-git-workspaces",
    "publish-and-sync-workspace-revisions",
    "support-git-lfs-work-products",
    "migrate-research-report-and-task-handoffs-to-files",
    "provision-isolated-executor-hpc-workspaces",
    "execute-hpc-jobs-from-workspace-revisions",
    "migrate-scientific-deliverables-to-files",
    "replace-sandbox-artifact-boundaries-with-files",
    "cut-over-workspace-public-interfaces",
    "migrate-historical-artifacts-to-git-lfs",
)
RECEIPT_SCHEMA_IDS = {
    "supersede-aox-hmm-artifact-cutover": (
        "aox_artifact_cutover_supersession_acceptance@1"
    ),
    "establish-project-repository-bindings": (
        "project_repository_binding_acceptance@1"
    ),
    "establish-agent-capability-leases": "agent_capability_lease_acceptance@1",
    "provision-independent-agent-git-workspaces": "agent_git_workspace_acceptance@1",
    "publish-and-sync-workspace-revisions": "workspace_publication_acceptance@1",
    "support-git-lfs-work-products": "git_lfs_work_product_acceptance@1",
    "migrate-research-report-and-task-handoffs-to-files": (
        "revision_path_handoff_acceptance@1"
    ),
    "provision-isolated-executor-hpc-workspaces": (
        "executor_hpc_workspace_acceptance@1"
    ),
    "execute-hpc-jobs-from-workspace-revisions": (
        "workspace_revision_execution_acceptance@1"
    ),
    "migrate-scientific-deliverables-to-files": (
        "scientific_deliverable_file_acceptance@1"
    ),
    "replace-sandbox-artifact-boundaries-with-files": (
        "file_workspace_internal_acceptance@1"
    ),
    "cut-over-workspace-public-interfaces": "file_workspace_public_acceptance@1",
    "migrate-historical-artifacts-to-git-lfs": (
        "historical_artifact_migration_change_completion@1"
    ),
}


def canonical_digest(value: object) -> str:
    content = json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return "sha256:" + hashlib.sha256(content).hexdigest()


def file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def load_object(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"JSON document is not an object: {path}")
    return value


def require_digest(value: object, name: str) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{name} is not a canonical SHA-256 digest")
    return value


def verify_mainline(evidence_root: Path) -> tuple[dict[str, object], dict[str, object]]:
    root = evidence_root.resolve(strict=True)
    completed = subprocess.run(
        (
            str(REPOSITORY_ROOT / ".venv/bin/python3"),
            "scripts/run-test-gate.py",
            "verify-mainline-authoritative",
            str(root),
        ),
        cwd=REPOSITORY_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )
    verification = json.loads(completed.stdout.strip().splitlines()[-1])
    if verification.get("terminal_status") != "pass":
        raise ValueError("authoritative mainline verification did not pass")
    plan = load_object(root / "mainline-authoritative-plan.json")
    receipt = load_object(root / "mainline-authoritative-receipt.json")
    plan_digest = require_digest(plan.get("self_digest"), "mainline plan digest")
    if receipt.get("plan_digest") != plan_digest:
        raise ValueError("mainline receipt does not bind the exact plan")
    require_digest(receipt.get("self_digest"), "mainline receipt digest")
    if receipt.get("terminal_status") != "pass":
        raise ValueError("mainline receipt is not terminal pass")
    current_source_identity = collect_source_identity(REPOSITORY_ROOT).as_dict()
    if plan.get("source_identity") != current_source_identity:
        raise ValueError("authoritative mainline source identity is not current")
    return plan, receipt


def verify_task_checklists(change_ids: tuple[str, ...]) -> None:
    for change_id in change_ids:
        tasks = CHANGE_ROOT / change_id / "tasks.md"
        text = tasks.read_text(encoding="utf-8")
        pending = re.findall(r"^- \[ \] (\d+\.\d+) ", text, flags=re.MULTILINE)
        if pending:
            raise ValueError(f"{change_id} tasks remain incomplete: {pending}")
        if not re.search(r"^- \[x\] \d+\.\d+ ", text, flags=re.MULTILINE):
            raise ValueError(f"{change_id} has no completed task entries")


def verify_strict_openspec(change_ids: tuple[str, ...]) -> dict[str, str]:
    results: dict[str, str] = {}
    environment = dict(os.environ)
    environment["DO_NOT_TRACK"] = "1"
    for change_id in change_ids:
        completed = subprocess.run(
            (
                "openspec",
                "validate",
                change_id,
                "--type",
                "change",
                "--strict",
                "--no-interactive",
            ),
            cwd=REPOSITORY_ROOT,
            check=True,
            capture_output=True,
            text=True,
            env=environment,
        )
        output = "\n".join(
            line.strip() for line in completed.stdout.splitlines() if line.strip()
        )
        expected = f"Change '{change_id}' is valid"
        if output != expected:
            raise ValueError(f"strict OpenSpec output differs for {change_id}")
        results[change_id] = expected
    return results


def verify_activation(path: Path) -> tuple[dict[str, object], str]:
    activation = load_object(path.resolve(strict=True))
    if activation.get("schema_id") != ACTIVATION_SCHEMA_ID:
        raise ValueError("release activation evidence schema is unsupported")
    required_true = (
        "maintenance_mode",
        "host_stopped",
        "runtime_consumers_stopped",
        "continuations_stopped",
        "execution_workers_stopped",
        "runner_callbacks_stopped",
        "ui_writes_stopped",
        "zero_legacy_public_surface",
        "scientific_file_contract_active",
        "file_workspace_internal_contract_active",
        "file_workspace_public_contract_active",
        "historical_sessions_closed_or_unsupported",
        "hpc_target_activation_is_per_target_and_fail_closed",
        "live_authority_granted",
    )
    for field in required_true[:-1]:
        if activation.get(field) is not True:
            raise ValueError(f"release activation evidence is incomplete: {field}")
    if activation.get("live_authority_granted") is not False:
        raise ValueError("release activation must not grant live authority")
    for field in (
        "active_writer_count",
        "unsettled_external_effect_count",
        "active_artifact_era_session_count",
        "activated_hpc_target_count_without_native_proof",
    ):
        if activation.get(field) != 0:
            raise ValueError(f"release activation count is not closed: {field}")
    for field in (
        "database_snapshot_digest",
        "storage_snapshot_digest",
        "quiescence_receipt_digest",
        "database_backup_digest",
        "storage_backup_digest",
        "catalog_identity_digest",
        "public_schema_identity_digest",
        "build_identity_digest",
    ):
        require_digest(activation.get(field), field)
    payload = {key: value for key, value in activation.items() if key != "evidence_digest"}
    evidence_digest = canonical_digest(payload)
    if activation.get("evidence_digest") != evidence_digest:
        raise ValueError("release activation evidence digest differs")
    return activation, evidence_digest


def verify_historical_migration(
    receipt_path: Path,
    verification_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    receipt = load_object(receipt_path.resolve(strict=True))
    if receipt.get("schema") != "historical_artifact_migration_receipt@1":
        raise ValueError("historical migration receipt schema is unsupported")
    receipt_payload = {
        key: value for key, value in receipt.items() if key != "receipt_digest"
    }
    receipt_digest = require_digest(
        receipt.get("receipt_digest"),
        "historical migration receipt digest",
    )
    if canonical_digest(receipt_payload) != receipt_digest:
        raise ValueError("historical migration receipt digest differs")
    exact_pairs = (
        ("expected_identity_set_digest", "migrated_identity_set_digest"),
        ("expected_reference_set_digest", "migrated_reference_set_digest"),
        ("expected_byte_total", "migrated_byte_total"),
    )
    if any(receipt.get(expected) != receipt.get(actual) for expected, actual in exact_pairs):
        raise ValueError("historical migration exact identity set differs")
    if any(
        receipt.get(field) != 0
        for field in (
            "unresolved_reference_count",
            "post_freeze_write_count",
            "negative_item_count",
        )
    ):
        raise ValueError("historical migration negative closure is incomplete")
    if (
        receipt.get("aox_non_adoption_proven") is not True
        or receipt.get("source_preserved") is not True
    ):
        raise ValueError("historical migration preservation or non-adoption differs")
    verification = load_object(verification_path.resolve(strict=True))
    if verification.get("schema") != "historical_artifact_standalone_verification@1":
        raise ValueError("historical standalone verification schema is unsupported")
    verification_payload = {
        key: value for key, value in verification.items() if key != "verification_digest"
    }
    if verification.get("receipt_digest") != receipt_digest:
        raise ValueError("historical verification binds a different receipt")
    if (
        verification.get("historical_only") is not True
        or verification.get("current_adoption_authorized") is not False
    ):
        raise ValueError("historical verification adoption boundary differs")
    verification_digest = require_digest(
        verification.get("verification_digest"),
        "historical standalone verification digest",
    )
    if canonical_digest(verification_payload) != verification_digest:
        raise ValueError("historical standalone verification digest differs")
    return receipt, verification


def change_contract_digest(change_id: str) -> tuple[str, list[dict[str, object]]]:
    root = CHANGE_ROOT / change_id
    paths = [root / "proposal.md", root / "design.md", root / "tasks.md"]
    paths.extend(sorted((root / "specs").rglob("*.md")))
    entries = []
    for path in paths:
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"change contract file is unavailable: {path}")
        entries.append(
            {
                "path": str(path.relative_to(REPOSITORY_ROOT)),
                "size": path.stat().st_size,
                "digest": file_digest(path),
            }
        )
    return canonical_digest(entries), entries


def documentation_digest() -> tuple[str, list[dict[str, object]]]:
    paths = [REPOSITORY_ROOT / "docs/OpenZyme架构设计.md"]
    paths.extend(sorted((REPOSITORY_ROOT / "docs/v3").rglob("*.md")))
    entries = [
        {
            "path": str(path.relative_to(REPOSITORY_ROOT)),
            "size": path.stat().st_size,
            "digest": file_digest(path),
        }
        for path in paths
        if path.is_file() and not path.is_symlink()
    ]
    return canonical_digest(entries), entries


def compile_receipts(
    *,
    evidence_root: Path,
    activation_path: Path,
    output_root: Path,
    bundle_path: Path,
    through_change: str,
    historical_migration_receipt_path: Path | None,
    historical_verification_path: Path | None,
) -> None:
    output = output_root.resolve()
    bundle = bundle_path.resolve()
    if output.exists() or bundle.exists():
        raise ValueError("release receipt output already exists")
    if output.parent.resolve(strict=True) != output.parent:
        raise ValueError("release receipt parent identity differs")
    if bundle.parent.resolve(strict=True) != bundle.parent:
        raise ValueError("release bundle parent identity differs")
    through_index = CHANGE_IDS.index(through_change)
    change_ids = CHANGE_IDS[: through_index + 1]
    verify_task_checklists(change_ids)
    strict_results = verify_strict_openspec(change_ids)
    plan, mainline_receipt = verify_mainline(evidence_root)
    activation, activation_digest = verify_activation(activation_path)
    includes_historical_migration = (
        through_index >= CHANGE_IDS.index("migrate-historical-artifacts-to-git-lfs")
    )
    if includes_historical_migration:
        if (
            historical_migration_receipt_path is None
            or historical_verification_path is None
        ):
            raise ValueError("historical completion requires migration and verification")
        historical_receipt, historical_verification = verify_historical_migration(
            historical_migration_receipt_path,
            historical_verification_path,
        )
    else:
        if (
            historical_migration_receipt_path is not None
            or historical_verification_path is not None
        ):
            raise ValueError("historical evidence was supplied before the historical change")
        historical_receipt = None
        historical_verification = None
    source_identity = plan.get("source_identity")
    if not isinstance(source_identity, dict):
        raise ValueError("mainline source identity is unavailable")
    source_revision = str(source_identity.get("commit", ""))
    if re.fullmatch(r"[0-9a-f]{40}", source_revision) is None:
        raise ValueError("mainline source revision is not an exact commit")
    source_identity_digest = canonical_digest(source_identity)
    schema_identity_digest = file_digest(FINAL_SCHEMA)
    docs_digest, docs_entries = documentation_digest()
    receipts: list[dict[str, object]] = []
    contract_entries: dict[str, list[dict[str, object]]] = {}
    transitive = canonical_digest(
        {
            "mainline_receipt_digest": mainline_receipt["self_digest"],
            "activation_evidence_digest": activation_digest,
        }
    )
    for activation_epoch, change_id in enumerate(change_ids, start=1):
        contract_digest, entries = change_contract_digest(change_id)
        contract_entries[change_id] = entries
        if change_id == "migrate-historical-artifacts-to-git-lfs":
            if historical_receipt is None or historical_verification is None:
                raise ValueError("historical completion evidence is unavailable")
            transitive = canonical_digest(
                {
                    "previous_transitive_receipt_digest": transitive,
                    "historical_migration_receipt_digest": historical_receipt[
                        "receipt_digest"
                    ],
                    "historical_standalone_verification_digest": (
                        historical_verification["verification_digest"]
                    ),
                }
            )
        payload = {
            "change_id": change_id,
            "receipt_schema_id": RECEIPT_SCHEMA_IDS[change_id],
            "source_revision": source_revision,
            "schema_identity_digest": schema_identity_digest,
            "contract_identity_digest": contract_digest,
            "activation_epoch": activation_epoch,
            "accepted": True,
            "superseded": False,
            "transitive_receipt_digest": transitive,
        }
        receipt = {**payload, "receipt_digest": canonical_digest(payload)}
        receipts.append(receipt)
        transitive = canonical_digest(
            {
                "previous_transitive_receipt_digest": transitive,
                "change_receipt_digest": receipt["receipt_digest"],
            }
        )
    bundle_payload = {
        "schema_id": RELEASE_BUNDLE_SCHEMA_ID,
        "through_change": through_change,
        "source_revision": source_revision,
        "source_identity_digest": source_identity_digest,
        "mainline_plan_digest": plan["self_digest"],
        "mainline_receipt_digest": mainline_receipt["self_digest"],
        "activation_evidence_digest": activation_digest,
        "final_schema_identity_digest": schema_identity_digest,
        "documentation_digest": docs_digest,
        "strict_openspec_results": strict_results,
        "receipt_digests": {
            str(item["change_id"]): item["receipt_digest"] for item in receipts
        },
        "final_transitive_receipt_digest": transitive,
        "live_authority_granted": False,
        "external_effect_authority_granted": False,
        "source_contract_entries": contract_entries,
        "documentation_entries": docs_entries,
        "activation_evidence": activation,
    }
    if historical_receipt is not None and historical_verification is not None:
        bundle_payload["historical_migration_evidence"] = {
            "receipt_digest": historical_receipt["receipt_digest"],
            "inventory_digest": historical_receipt["inventory_digest"],
            "standalone_verification_digest": historical_verification[
                "verification_digest"
            ],
            "expected_identity_set_digest": historical_receipt[
                "expected_identity_set_digest"
            ],
            "migrated_identity_set_digest": historical_receipt[
                "migrated_identity_set_digest"
            ],
            "expected_byte_total": historical_receipt["expected_byte_total"],
            "migrated_byte_total": historical_receipt["migrated_byte_total"],
            "source_preserved": historical_receipt["source_preserved"],
            "current_adoption_authorized": historical_verification[
                "current_adoption_authorized"
            ],
        }
    release_bundle = {
        **bundle_payload,
        "bundle_digest": canonical_digest(bundle_payload),
    }
    output.mkdir(mode=0o700)
    for receipt in receipts:
        path = output / f"{receipt['change_id']}.json"
        path.write_text(
            json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    bundle.write_text(
        json.dumps(release_bundle, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser(description=__doc__)
    value.add_argument("--mainline-root", required=True, type=Path)
    value.add_argument("--activation-evidence", required=True, type=Path)
    value.add_argument("--output-root", required=True, type=Path)
    value.add_argument("--bundle", required=True, type=Path)
    value.add_argument("--through-change", choices=CHANGE_IDS, required=True)
    value.add_argument("--historical-migration-receipt", type=Path)
    value.add_argument("--historical-verification", type=Path)
    return value


if __name__ == "__main__":
    arguments = parser().parse_args()
    compile_receipts(
        evidence_root=arguments.mainline_root,
        activation_path=arguments.activation_evidence,
        output_root=arguments.output_root,
        bundle_path=arguments.bundle,
        through_change=arguments.through_change,
        historical_migration_receipt_path=arguments.historical_migration_receipt,
        historical_verification_path=arguments.historical_verification,
    )
