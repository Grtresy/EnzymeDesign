#!/usr/bin/env python3
"""Compile and independently verify the final file-workspace acceptance chain."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
from typing import Any, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.test_gate.source import collect_source_identity  # noqa: E402

CORE_SOURCE = REPOSITORY_ROOT / "packages/openzyme-core/src"
sys.path.insert(0, str(CORE_SOURCE))

from openzyme_core.device_fresh_reset import (  # noqa: E402
    DeviceFreshResetError,
    build_reset_receipt,
    canonical_digest,
    load_occurrences,
    load_permission_adjustments,
    verify_inventory,
    verify_reset_receipt,
)


MANIFEST_PATH = Path(__file__).with_name("final-evidence-manifest.json")
CHANGE_ROOT = REPOSITORY_ROOT / "openspec/changes"
EVIDENCE_MAP_SCHEMA = "file_workspace_final_evidence_map@1"
CHANGE_RECEIPT_SCHEMA = "openspec_change_acceptance_receipt@2"
BUNDLE_SCHEMA = "file_workspace_cutover_release_bundle@2"
VERIFICATION_SCHEMA = "file_workspace_cutover_receipt_verification@1"
DIGEST_PATTERN = re.compile(r"sha256:[0-9a-f]{64}")
TASK_PATTERN = re.compile(r"^- \[([ x])] (\d+\.\d+) (.+)$", re.MULTILINE)
REQUIREMENT_PATTERN = re.compile(r"^### Requirement: (.+)$", re.MULTILINE)


class FinalEvidenceError(RuntimeError):
    """Fail-closed evidence error with actionable, stable context."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        phase: str,
        identity: str | None,
        expected: object,
        observed: object,
        action: str,
    ) -> None:
        self.code = code
        self.phase = phase
        self.identity = identity
        self.expected = expected
        self.observed = observed
        self.action = action
        detail = {
            "error_code": code,
            "phase": phase,
            "identity": identity,
            "expected": expected,
            "observed": observed,
            "operator_action": action,
            "mutation_applied": False,
            "fallback_performed": False,
        }
        self.diagnostic_id = canonical_digest(detail)
        super().__init__(
            f"{code}: {message}; phase={phase}; identity={identity!r}; "
            f"expected={expected!r}; observed={observed!r}; "
            f"operator_action={action}; mutation_applied=false; "
            f"fallback_performed=false; diagnostic_id={self.diagnostic_id}"
        )


def _fail(
    code: str,
    message: str,
    *,
    phase: str,
    identity: str | None,
    expected: object,
    observed: object,
    action: str,
) -> FinalEvidenceError:
    return FinalEvidenceError(
        code,
        message,
        phase=phase,
        identity=identity,
        expected=expected,
        observed=observed,
        action=action,
    )


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise _fail(
            "evidence_json_unreadable",
            "evidence is not a readable strict JSON document",
            phase="evidence_loading",
            identity=str(path),
            expected="one UTF-8 JSON object",
            observed={"exception_type": type(exc).__name__, "message": str(exc)},
            action="restore_or_regenerate_the_exact_evidence",
        ) from exc
    if not isinstance(value, dict):
        raise _fail(
            "evidence_json_not_object",
            "evidence root is not an object",
            phase="evidence_loading",
            identity=str(path),
            expected="JSON object",
            observed=type(value).__name__,
            action="regenerate_the_evidence_with_the_supported_schema",
        )
    return value


def _file_digest(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def _require_digest(value: object, *, field: str, identity: str) -> str:
    if not isinstance(value, str) or DIGEST_PATTERN.fullmatch(value) is None:
        raise _fail(
            "evidence_digest_invalid",
            "identity is not a canonical SHA-256 digest",
            phase="identity_validation",
            identity=identity,
            expected=f"canonical digest in {field}",
            observed=value,
            action="regenerate_from_the_exact_canonical_payload",
        )
    return value


def _canonical_entry(relative: str) -> dict[str, object]:
    path = REPOSITORY_ROOT / relative
    try:
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise _fail(
            "manifest_path_unavailable",
            "manifest evidence path is unavailable",
            phase="evidence_map_compilation",
            identity=relative,
            expected="existing in-repository regular file",
            observed={"exception_type": type(exc).__name__, "message": str(exc)},
            action="correct_the_manifest_or_restore_the_direct_evidence",
        ) from exc
    if resolved != path or not path.is_file() or path.is_symlink():
        raise _fail(
            "manifest_path_identity_mismatch",
            "manifest path is not an exact regular repository file",
            phase="evidence_map_compilation",
            identity=relative,
            expected=str(path),
            observed=str(resolved),
            action="replace_the_entry_with_an_exact_non_symlink_file",
        )
    return {"path": relative, "size": path.stat().st_size, "digest": _file_digest(path)}


def _change_contract(
    change_id: str,
) -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[str],
    list[str],
]:
    root = CHANGE_ROOT / change_id
    tasks_path = root / "tasks.md"
    task_text = tasks_path.read_text(encoding="utf-8")
    tasks = TASK_PATTERN.findall(task_text)
    pending = [task_id for marker, task_id, _ in tasks if marker != "x"]
    if not tasks or pending:
        raise _fail(
            "change_tasks_incomplete",
            "change checklist is empty or contains pending tasks",
            phase="change_contract_validation",
            identity=change_id,
            expected="all task checkboxes complete",
            observed={"task_count": len(tasks), "pending": pending},
            action="leave_the_change_active_and_restore_direct_evidence",
        )
    contract_paths = [root / name for name in ("proposal.md", "design.md", "tasks.md")]
    delta_specs = sorted((root / "specs").rglob("spec.md"))
    contract_paths.extend(delta_specs)
    entries = [
        _canonical_entry(str(path.relative_to(REPOSITORY_ROOT)))
        for path in contract_paths
        if path.is_file()
    ]
    requirements: list[str] = []
    main_spec_entries: list[dict[str, object]] = []
    for spec in delta_specs:
        requirements.extend(REQUIREMENT_PATTERN.findall(spec.read_text(encoding="utf-8")))
        capability = spec.parent.name
        main_spec_entries.append(
            _canonical_entry(f"openspec/specs/{capability}/spec.md")
        )
    if not requirements:
        raise _fail(
            "change_requirements_missing",
            "change has no machine-discovered requirements",
            phase="change_contract_validation",
            identity=change_id,
            expected="one or more Requirement headings",
            observed=[],
            action="correct_the_delta_spec_before_acceptance",
        )
    return (
        entries,
        main_spec_entries,
        [task_id for _, task_id, _ in tasks],
        requirements,
    )


def _run_json(command: Sequence[str], *, phase: str, identity: str) -> dict[str, Any]:
    environment = dict(os.environ)
    environment["DO_NOT_TRACK"] = "1"
    try:
        completed = subprocess.run(
            tuple(command),
            cwd=REPOSITORY_ROOT,
            env=environment,
            check=False,
            capture_output=True,
            text=True,
        )
    except OSError as exc:
        raise _fail(
            "evidence_command_unavailable",
            "evidence verifier could not start",
            phase=phase,
            identity=identity,
            expected={"exit_code": 0, "command": list(command)},
            observed={"exception_type": type(exc).__name__, "message": str(exc)},
            action="restore_the_exact_toolchain_and_rerun_the_gate",
        ) from exc
    if completed.returncode != 0:
        raise _fail(
            "evidence_command_failed",
            "evidence verifier returned a nonzero exit code",
            phase=phase,
            identity=identity,
            expected={"exit_code": 0, "command": list(command)},
            observed={
                "exit_code": completed.returncode,
                "stdout": completed.stdout[-4000:],
                "stderr": completed.stderr[-4000:],
            },
            action="inspect_the_earliest_cause_and_do_not_issue_receipts",
        )
    output = completed.stdout.strip()
    if not output:
        raise _fail(
            "evidence_command_output_missing",
            "evidence verifier returned no JSON summary",
            phase=phase,
            identity=identity,
            expected="terminal JSON object",
            observed=completed.stdout,
            action="repair_the_verifier_output_contract",
        )
    try:
        result = json.loads(output)
    except json.JSONDecodeError as whole_output_error:
        lines = [line for line in output.splitlines() if line.strip()]
        try:
            result = json.loads(lines[-1])
        except json.JSONDecodeError as terminal_line_error:
            raise _fail(
                "evidence_command_output_invalid",
                "verifier output is neither one JSON document nor a terminal JSON summary",
                phase=phase,
                identity=identity,
                expected="JSON object",
                observed={
                    "stdout_tail": output[-4000:],
                    "whole_output_error": str(whole_output_error),
                    "terminal_line_error": str(terminal_line_error),
                },
                action="repair_the_verifier_output_contract",
            ) from terminal_line_error
    if not isinstance(result, dict):
        raise _fail(
            "evidence_command_output_not_object",
            "terminal verifier output is not an object",
            phase=phase,
            identity=identity,
            expected="JSON object",
            observed=type(result).__name__,
            action="repair_the_verifier_output_contract",
        )
    return result


def _verify_mainline(root: Path, source: Mapping[str, object]) -> dict[str, object]:
    result = _run_json(
        (
            str(REPOSITORY_ROOT / ".venv/bin/python3"),
            "scripts/run-test-gate.py",
            "verify-mainline-authoritative",
            str(root.resolve(strict=True)),
        ),
        phase="mainline_verification",
        identity=str(root),
    )
    if result.get("terminal_status") != "pass":
        raise _fail(
            "mainline_not_terminal_pass",
            "authoritative mainline verifier did not return terminal pass",
            phase="mainline_verification",
            identity=str(root),
            expected="pass",
            observed=result,
            action="rerun_the_full_authoritative_mainline",
        )
    plan = _load_object(root / "mainline-authoritative-plan.json")
    receipt = _load_object(root / "mainline-authoritative-receipt.json")
    if plan.get("source_identity") != source:
        raise _fail(
            "mainline_source_drift",
            "mainline plan is bound to a different source",
            phase="mainline_verification",
            identity=str(root),
            expected=source,
            observed=plan.get("source_identity"),
            action="rerun_mainline_on_the_final_frozen_source",
        )
    if receipt.get("terminal_status") != "pass" or receipt.get("plan_digest") != plan.get("self_digest"):
        raise _fail(
            "mainline_receipt_binding_invalid",
            "mainline receipt is not a pass bound to the exact plan",
            phase="mainline_verification",
            identity=str(root),
            expected={"terminal_status": "pass", "plan_digest": plan.get("self_digest")},
            observed={"terminal_status": receipt.get("terminal_status"), "plan_digest": receipt.get("plan_digest")},
            action="regenerate_authoritative_mainline_evidence",
        )
    return {
        "verification": result,
        "plan_digest": _require_digest(plan.get("self_digest"), field="self_digest", identity=str(root)),
        "receipt_digest": _require_digest(receipt.get("self_digest"), field="self_digest", identity=str(root)),
    }


def _verify_qualification(path: Path) -> dict[str, object]:
    result = _run_json(
        (
            "uv",
            "run",
            "python",
            "scripts/verify-v3-architecture-qualification.py",
            str(path.resolve(strict=True)),
        ),
        phase="architecture_qualification_verification",
        identity=str(path),
    )
    if result.get("valid") is not True:
        raise _fail(
            "architecture_qualification_invalid",
            "architecture qualification pure verification failed",
            phase="architecture_qualification_verification",
            identity=str(path),
            expected={"valid": True},
            observed=result,
            action="rerun_the_complete_current_qualification_profile",
        )
    return {
        **result,
        "report_file_digest": _file_digest(path),
        "payload_digest": _require_digest(result.get("payload_digest"), field="payload_digest", identity=str(path)),
    }


def _verify_audits() -> dict[str, object]:
    retired = _run_json(
        ("uv", "run", "python", "scripts/audit-v3-compat-callers.py", "--summary"),
        phase="retired_surface_audit",
        identity="scripts/audit-v3-compat-callers.py",
    )
    exceptions = _run_json(
        ("uv", "run", "python", "scripts/audit-production-exceptions.py", "--summary"),
        phase="production_exception_audit",
        identity="scripts/audit-production-exceptions.py",
    )
    for name, summary in (("retired_surface", retired), ("production_exception", exceptions)):
        if summary.get("scan_error_count") != 0 or summary.get("violation_count") != 0:
            raise _fail(
                "static_audit_not_clean",
                "static audit contains errors or violations",
                phase="static_audit_verification",
                identity=name,
                expected={"scan_error_count": 0, "violation_count": 0},
                observed=summary,
                action="resolve_every_reported_item_before_receipt_issuance",
            )
        _require_digest(summary.get("report_digest"), field="report_digest", identity=name)
    return {"retired_surface": retired, "production_exception": exceptions}


def _verify_strict(change_ids: Sequence[str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for change_id in change_ids:
        completed = subprocess.run(
            ("openspec", "validate", change_id, "--type", "change", "--strict", "--no-interactive"),
            cwd=REPOSITORY_ROOT,
            env={**os.environ, "DO_NOT_TRACK": "1"},
            check=False,
            capture_output=True,
            text=True,
        )
        expected = f"Change '{change_id}' is valid"
        lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
        if completed.returncode != 0 or lines != [expected]:
            raise _fail(
                "openspec_strict_invalid",
                "strict OpenSpec validation failed or returned an unexpected result",
                phase="openspec_strict_validation",
                identity=change_id,
                expected={"exit_code": 0, "stdout": expected},
                observed={"exit_code": completed.returncode, "stdout": lines, "stderr": completed.stderr[-2000:]},
                action="repair_the_change_contract_and_rerun_strict_validation",
            )
        result[change_id] = expected
    return result


def _verify_reset(reset_root: Path, source_digest: str) -> dict[str, object]:
    root = reset_root.resolve(strict=True)
    inventory = _load_object(root / "inventory.json")
    occurrences = load_occurrences(root / "deletion-occurrences.jsonl")
    permissions = load_permission_adjustments(root / "permission-adjustments.jsonl")
    quiescence = _load_object(root / "quiescence.json")
    zero = _load_object(root / "zero-scan.json")
    fresh = _load_object(root / "fresh-proof.json")
    for document, field in ((quiescence, "quiescence_digest"), (zero, "zero_scan_digest")):
        stored = document.get(field)
        observed = canonical_digest({key: value for key, value in document.items() if key != field})
        if stored != observed:
            raise _fail(
                "device_evidence_digest_drift",
                "device evidence digest differs from its canonical payload",
                phase="device_reset_verification",
                identity=field,
                expected=stored,
                observed=observed,
                action="stop_and_inspect_the_private_device_evidence",
            )
    replacement = zero.get("fresh_replacement")
    if not isinstance(replacement, dict) or not isinstance(replacement.get("path"), str):
        raise _fail(
            "fresh_replacement_missing",
            "zero scan lacks an exact fresh database replacement",
            phase="device_reset_verification",
            identity=str(root),
            expected="fresh_replacement object",
            observed=replacement,
            action="repeat_the_post_reset_zero_scan",
        )
    verify_inventory(
        inventory,
        occurrences=occurrences,
        permission_adjustments=permissions,
        allowed_replacements={str(replacement["path"]): replacement},
    )
    database_path = Path(str(replacement["path"]))
    current_database_digest = _file_digest(database_path)
    fresh_receipt = fresh.get("recomputed_fresh_receipt_digest")
    if (
        fresh.get("query_only") is not True
        or fresh.get("integrity_check") != ["ok"]
        or fresh.get("foreign_key_check") != []
        or fresh.get("legacy_item_rows") != 0
        or fresh.get("legacy_ledger_rows") != 0
        or fresh.get("product_row_total") != 0
        or fresh_receipt != fresh.get("expected_fresh_receipt")
        or fresh_receipt != fresh.get("removal_receipt_digest")
        or current_database_digest != fresh.get("database_sha256")
        or current_database_digest != replacement.get("content_digest")
    ):
        raise _fail(
            "fresh_database_proof_invalid",
            "fresh database proof is incomplete or drifted",
            phase="device_reset_verification",
            identity=str(database_path),
            expected={"query_only": True, "integrity_check": ["ok"], "foreign_key_check": [], "legacy_rows": 0, "product_rows": 0, "database_sha256": replacement.get("content_digest")},
            observed={"fresh": fresh, "current_database_digest": current_database_digest},
            action="stop_the_writer_and_reverify_the_fresh_database",
        )
    receipt = build_reset_receipt(
        inventory=inventory,
        occurrences=tuple(occurrences.values()),
        permission_adjustments=tuple(permissions.values()),
        source_identity=source_digest,
        quiescence_digest=str(quiescence["quiescence_digest"]),
        zero_scan_digest=str(zero["zero_scan_digest"]),
        fresh_bootstrap_receipt_digest=str(fresh_receipt),
        fresh_database_identity_digest=str(fresh["fresh_database_identity_digest"]),
    )
    verify_reset_receipt(receipt)
    return {
        "receipt": receipt,
        "inventory_item_count": inventory.get("item_count"),
        "deleted_byte_total": inventory.get("deletion_byte_total"),
        "preserved_git_file_set_digest": zero.get("preserved_git_file_set_digest"),
        "preserved_lfs_file_set_digest": zero.get("preserved_lfs_file_set_digest"),
        "fresh_database_path": str(database_path),
        "fresh_database_content_digest": current_database_digest,
        "fresh_startup_status": fresh.get("current_client_startup_http_status"),
        "fresh_startup_error_code": fresh.get("current_client_startup_response", {}).get("error", {}).get("code"),
    }


def _manifest_entries() -> tuple[dict[str, Any], list[dict[str, Any]]]:
    manifest = _load_object(MANIFEST_PATH)
    raw_changes = manifest.get("changes")
    if manifest.get("schema_id") != "file_workspace_final_evidence_manifest@1" or not isinstance(raw_changes, list):
        raise _fail(
            "evidence_manifest_schema_invalid",
            "final evidence manifest schema is unsupported",
            phase="evidence_map_compilation",
            identity=str(MANIFEST_PATH),
            expected="file_workspace_final_evidence_manifest@1 with changes array",
            observed={"schema_id": manifest.get("schema_id"), "changes_type": type(raw_changes).__name__},
            action="restore_the_supported_manifest",
        )
    change_ids = [entry.get("change_id") for entry in raw_changes if isinstance(entry, dict)]
    if len(change_ids) != 15 or len(set(change_ids)) != 15 or manifest.get("closure_change") != change_ids[-1]:
        raise _fail(
            "evidence_manifest_change_set_invalid",
            "manifest must name exactly fourteen targets followed by the closure change",
            phase="evidence_map_compilation",
            identity=str(MANIFEST_PATH),
            expected={"count": 15, "closure_last": manifest.get("closure_change")},
            observed=change_ids,
            action="restore_the_authorized_target_set_and_order",
        )
    return manifest, [dict(entry) for entry in raw_changes]


def _compile_map(
    manifest: Mapping[str, object],
    entries: Sequence[Mapping[str, Any]],
    source: Mapping[str, object],
    *,
    mainline: Mapping[str, object],
    qualification: Mapping[str, object],
    audits: Mapping[str, object],
    strict: Mapping[str, str],
    reset: Mapping[str, object],
) -> dict[str, object]:
    common_docs = [_canonical_entry(path) for path in manifest["common_documentation"]]  # type: ignore[index]
    changes: list[dict[str, object]] = []
    for entry in entries:
        change_id = str(entry["change_id"])
        contracts, main_specs, tasks, requirements = _change_contract(change_id)
        direct: dict[str, list[dict[str, object]]] = {}
        for category in ("code", "tests", "documentation"):
            values = entry.get(category)
            if not isinstance(values, list) or not values:
                raise _fail(
                    "change_evidence_category_empty",
                    "change evidence category is empty",
                    phase="evidence_map_compilation",
                    identity=f"{change_id}:{category}",
                    expected="non-empty path array",
                    observed=values,
                    action="add_current_direct_evidence_or_leave_the_change_incomplete",
                )
            direct[category] = [_canonical_entry(str(path)) for path in values]
        change_payload = {
            "change_id": change_id,
            "receipt_schema_id": entry["receipt_schema_id"],
            "contract_entries": contracts,
            "contract_digest": canonical_digest(contracts),
            "main_spec_entries": main_specs,
            "main_spec_digest": canonical_digest(main_specs),
            "task_ids": tasks,
            "task_count": len(tasks),
            "all_tasks_complete": True,
            "requirements": requirements,
            "requirement_count": len(requirements),
            "direct_evidence": direct,
            "direct_evidence_digest": canonical_digest(direct),
            "strict_result": strict[change_id],
            "common_gate_binding": "release_bundle",
            "deployment_proof_binding": "device_reset_receipt",
        }
        changes.append(change_payload)
    payload: dict[str, object] = {
        "schema_id": EVIDENCE_MAP_SCHEMA,
        "source_identity": source,
        "source_identity_digest": canonical_digest(source),
        "manifest_digest": _file_digest(MANIFEST_PATH),
        "common_documentation": common_docs,
        "common_documentation_digest": canonical_digest(common_docs),
        "changes": changes,
        "mainline": mainline,
        "architecture_qualification": qualification,
        "static_audits": audits,
        "strict_openspec": strict,
        "device_reset_receipt_digest": reset["receipt"]["receipt_digest"],  # type: ignore[index]
        "authority_limits": manifest["authority_limits"],
        "excluded_active_changes": manifest["excluded_active_changes"],
        "superseded_history_policy": {
            "old_local_receipts_deleted_by_exact_device_inventory": True,
            "old_receipts_reused": False,
            "old_receipts_overwritten": False,
            "historical_openspec_preserved": True,
        },
    }
    payload["evidence_map_digest"] = canonical_digest(payload)
    return payload


def _write_exclusive(path: Path, value: Mapping[str, object]) -> None:
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")
    try:
        descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as exc:
        raise _fail(
            "receipt_no_replace_violation",
            "receipt output already exists or cannot be created exclusively",
            phase="receipt_publication",
            identity=str(path),
            expected="absent path in an existing private parent",
            observed={"exception_type": type(exc).__name__, "message": str(exc)},
            action="choose_a_new_empty_output_root_without_overwriting_history",
        ) from exc
    with os.fdopen(descriptor, "wb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def _issue(
    output_root: Path,
    *,
    evidence_map: Mapping[str, object],
    reset: Mapping[str, object],
) -> dict[str, object]:
    output = output_root.resolve()
    if output.exists() or not output.parent.resolve(strict=True).is_dir():
        raise _fail(
            "receipt_output_scope_invalid",
            "receipt output must be a new child of an existing parent",
            phase="receipt_publication",
            identity=str(output),
            expected="absent output root",
            observed={"exists": output.exists(), "parent": str(output.parent)},
            action="choose_a_new_exact_output_root",
        )
    output.mkdir(mode=0o700)
    _write_exclusive(output / "final-evidence-map.json", evidence_map)
    _write_exclusive(output / "device-reset-receipt.json", reset["receipt"])  # type: ignore[arg-type]
    evidence_digest = str(evidence_map["evidence_map_digest"])
    source_digest = str(evidence_map["source_identity_digest"])
    mainline = evidence_map["mainline"]
    qualification = evidence_map["architecture_qualification"]
    assert isinstance(mainline, Mapping) and isinstance(qualification, Mapping)
    transitive = canonical_digest({
        "source_identity_digest": source_digest,
        "mainline_receipt_digest": mainline["receipt_digest"],
        "qualification_payload_digest": qualification["payload_digest"],
        "device_reset_receipt_digest": reset["receipt"]["receipt_digest"],  # type: ignore[index]
        "evidence_map_digest": evidence_digest,
    })
    receipt_digests: dict[str, str] = {}
    changes = evidence_map["changes"]
    assert isinstance(changes, list)
    for sequence, change in enumerate(changes[:-1], start=1):
        assert isinstance(change, Mapping)
        payload: dict[str, object] = {
            "schema_id": CHANGE_RECEIPT_SCHEMA,
            "change_id": change["change_id"],
            "change_receipt_schema_id": change["receipt_schema_id"],
            "sequence": sequence,
            "accepted": True,
            "source_identity_digest": source_digest,
            "contract_digest": change["contract_digest"],
            "main_spec_digest": change["main_spec_digest"],
            "direct_evidence_digest": change["direct_evidence_digest"],
            "evidence_map_digest": evidence_digest,
            "previous_transitive_digest": transitive,
            "live_authority_granted": False,
            "external_effect_authority_granted": False,
        }
        payload["receipt_digest"] = canonical_digest(payload)
        change_id = str(change["change_id"])
        _write_exclusive(output / f"{sequence:02d}-{change_id}.json", payload)
        receipt_digests[change_id] = str(payload["receipt_digest"])
        transitive = canonical_digest({"previous_transitive_digest": transitive, "receipt_digest": payload["receipt_digest"]})
    bundle_payload: dict[str, object] = {
        "schema_id": BUNDLE_SCHEMA,
        "source_identity_digest": source_digest,
        "evidence_map_digest": evidence_digest,
        "device_reset_receipt_digest": reset["receipt"]["receipt_digest"],  # type: ignore[index]
        "mainline_plan_digest": mainline["plan_digest"],
        "mainline_receipt_digest": mainline["receipt_digest"],
        "qualification_payload_digest": qualification["payload_digest"],
        "per_change_receipt_digests": receipt_digests,
        "final_transitive_digest": transitive,
        "target_change_count": 14,
        "authority_limits": evidence_map["authority_limits"],
    }
    bundle_payload["bundle_digest"] = canonical_digest(bundle_payload)
    _write_exclusive(output / "release-bundle.json", bundle_payload)
    closure = changes[-1]
    assert isinstance(closure, Mapping)
    closure_payload: dict[str, object] = {
        "schema_id": CHANGE_RECEIPT_SCHEMA,
        "change_id": closure["change_id"],
        "change_receipt_schema_id": closure["receipt_schema_id"],
        "sequence": 15,
        "accepted": True,
        "source_identity_digest": source_digest,
        "contract_digest": closure["contract_digest"],
        "main_spec_digest": closure["main_spec_digest"],
        "direct_evidence_digest": closure["direct_evidence_digest"],
        "evidence_map_digest": evidence_digest,
        "release_bundle_digest": bundle_payload["bundle_digest"],
        "previous_transitive_digest": transitive,
        "live_authority_granted": False,
        "external_effect_authority_granted": False,
    }
    closure_payload["receipt_digest"] = canonical_digest(closure_payload)
    _write_exclusive(output / "15-close-file-workspace-cutover-verification-gaps.json", closure_payload)
    return {
        "output_root": str(output),
        "source_identity_digest": source_digest,
        "evidence_map_digest": evidence_digest,
        "device_reset_receipt_digest": reset["receipt"]["receipt_digest"],  # type: ignore[index]
        "release_bundle_digest": bundle_payload["bundle_digest"],
        "closure_receipt_digest": closure_payload["receipt_digest"],
    }


def _verify_output(output_root: Path) -> dict[str, object]:
    root = output_root.resolve(strict=True)
    evidence = _load_object(root / "final-evidence-map.json")
    reset = _load_object(root / "device-reset-receipt.json")
    bundle = _load_object(root / "release-bundle.json")
    closure = _load_object(root / "15-close-file-workspace-cutover-verification-gaps.json")
    current = collect_source_identity(REPOSITORY_ROOT).as_dict()
    current_digest = canonical_digest(current)
    if evidence.get("schema_id") != EVIDENCE_MAP_SCHEMA or evidence.get("source_identity") != current:
        raise _fail(
            "receipt_source_drift",
            "receipt evidence does not bind the current source",
            phase="receipt_chain_verification",
            identity=str(root),
            expected=current_digest,
            observed=evidence.get("source_identity_digest"),
            action="invalidate_the_chain_and_return_to_final_source_gates",
        )
    evidence_payload = {key: value for key, value in evidence.items() if key != "evidence_map_digest"}
    if evidence.get("evidence_map_digest") != canonical_digest(evidence_payload):
        raise _fail(
            "evidence_map_digest_drift",
            "final evidence map digest differs",
            phase="receipt_chain_verification",
            identity=str(root / "final-evidence-map.json"),
            expected=evidence.get("evidence_map_digest"),
            observed=canonical_digest(evidence_payload),
            action="discard_the_invalid_chain_and_recompile",
        )
    verify_reset_receipt(reset)
    if reset.get("source_identity") != current_digest:
        raise _fail(
            "reset_receipt_source_drift",
            "device reset receipt does not bind the current source",
            phase="receipt_chain_verification",
            identity=str(root / "device-reset-receipt.json"),
            expected=current_digest,
            observed=reset.get("source_identity"),
            action="rebuild_the_reset_receipt_from_frozen_device_evidence",
        )
    changes = evidence.get("changes")
    if not isinstance(changes, list) or len(changes) != 15:
        raise _fail(
            "receipt_change_set_invalid",
            "evidence map does not contain the authorized change set",
            phase="receipt_chain_verification",
            identity=str(root),
            expected=15,
            observed=0 if not isinstance(changes, list) else len(changes),
            action="discard_the_invalid_chain_and_recompile",
        )
    previous = canonical_digest({
        "source_identity_digest": current_digest,
        "mainline_receipt_digest": evidence["mainline"]["receipt_digest"],
        "qualification_payload_digest": evidence["architecture_qualification"]["payload_digest"],
        "device_reset_receipt_digest": reset["receipt_digest"],
        "evidence_map_digest": evidence["evidence_map_digest"],
    })
    observed_receipts: dict[str, str] = {}
    for sequence, change in enumerate(changes[:-1], start=1):
        change_id = str(change["change_id"])
        receipt = _load_object(root / f"{sequence:02d}-{change_id}.json")
        stored = receipt.get("receipt_digest")
        payload = {key: value for key, value in receipt.items() if key != "receipt_digest"}
        if (
            receipt.get("schema_id") != CHANGE_RECEIPT_SCHEMA
            or receipt.get("sequence") != sequence
            or receipt.get("change_id") != change_id
            or receipt.get("previous_transitive_digest") != previous
            or receipt.get("accepted") is not True
            or receipt.get("source_identity_digest") != current_digest
            or receipt.get("contract_digest") != change["contract_digest"]
            or receipt.get("main_spec_digest") != change["main_spec_digest"]
            or receipt.get("direct_evidence_digest")
            != change["direct_evidence_digest"]
            or receipt.get("evidence_map_digest")
            != evidence["evidence_map_digest"]
            or receipt.get("live_authority_granted") is not False
            or receipt.get("external_effect_authority_granted") is not False
            or stored != canonical_digest(payload)
        ):
            raise _fail(
                "change_receipt_invalid",
                "per-change receipt schema, order, authority, or digest differs",
                phase="receipt_chain_verification",
                identity=change_id,
                expected={"sequence": sequence, "previous_transitive_digest": previous, "accepted": True, "authority": False},
                observed=receipt,
                action="discard_the_invalid_chain_and_recompile",
            )
        observed_receipts[change_id] = str(stored)
        previous = canonical_digest({"previous_transitive_digest": previous, "receipt_digest": stored})
    bundle_stored = bundle.get("bundle_digest")
    bundle_payload = {key: value for key, value in bundle.items() if key != "bundle_digest"}
    closure_stored = closure.get("receipt_digest")
    closure_payload = {key: value for key, value in closure.items() if key != "receipt_digest"}
    if (
        bundle.get("schema_id") != BUNDLE_SCHEMA
        or bundle.get("per_change_receipt_digests") != observed_receipts
        or bundle.get("final_transitive_digest") != previous
        or bundle_stored != canonical_digest(bundle_payload)
        or closure.get("previous_transitive_digest") != previous
        or closure.get("release_bundle_digest") != bundle_stored
        or closure.get("change_id") != "close-file-workspace-cutover-verification-gaps"
        or closure.get("source_identity_digest") != current_digest
        or closure.get("contract_digest") != changes[-1]["contract_digest"]
        or closure.get("main_spec_digest") != changes[-1]["main_spec_digest"]
        or closure.get("direct_evidence_digest")
        != changes[-1]["direct_evidence_digest"]
        or closure.get("evidence_map_digest") != evidence["evidence_map_digest"]
        or closure_stored != canonical_digest(closure_payload)
    ):
        raise _fail(
            "release_receipt_chain_invalid",
            "release bundle or closure receipt is not exactly linked",
            phase="receipt_chain_verification",
            identity=str(root),
            expected={"per_change_receipts": observed_receipts, "final_transitive_digest": previous, "closure_change": "close-file-workspace-cutover-verification-gaps"},
            observed={"bundle": bundle, "closure": closure},
            action="discard_the_invalid_chain_and_recompile",
        )
    payload = {
        "schema_id": VERIFICATION_SCHEMA,
        "valid": True,
        "source_identity_digest": current_digest,
        "evidence_map_digest": evidence["evidence_map_digest"],
        "device_reset_receipt_digest": reset["receipt_digest"],
        "release_bundle_digest": bundle_stored,
        "closure_receipt_digest": closure_stored,
        "verified_change_count": 15,
        "live_authority_granted": False,
        "external_effect_authority_granted": False,
    }
    payload["verification_digest"] = canonical_digest(payload)
    return payload


def compile_chain(*, mainline_root: Path, qualification_report: Path, reset_root: Path, output_root: Path) -> dict[str, object]:
    source = collect_source_identity(REPOSITORY_ROOT).as_dict()
    source_digest = canonical_digest(source)
    manifest, entries = _manifest_entries()
    change_ids = [str(entry["change_id"]) for entry in entries]
    strict = _verify_strict(change_ids)
    mainline = _verify_mainline(mainline_root.resolve(strict=True), source)
    qualification = _verify_qualification(qualification_report)
    audits = _verify_audits()
    reset = _verify_reset(reset_root, source_digest)
    evidence_map = _compile_map(
        manifest,
        entries,
        source,
        mainline=mainline,
        qualification=qualification,
        audits=audits,
        strict=strict,
        reset=reset,
    )
    issued = _issue(output_root, evidence_map=evidence_map, reset=reset)
    verification = _verify_output(output_root)
    _write_exclusive(output_root.resolve() / "verification.json", verification)
    return {**issued, "verification_digest": verification["verification_digest"], "valid": True}


def _absolute(value: str) -> Path:
    path = Path(value)
    if not path.is_absolute():
        raise argparse.ArgumentTypeError("path must be absolute")
    return path


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    compile_parser = sub.add_parser("compile")
    compile_parser.add_argument("--mainline-root", required=True, type=_absolute)
    compile_parser.add_argument("--qualification-report", required=True, type=_absolute)
    compile_parser.add_argument("--reset-root", required=True, type=_absolute)
    compile_parser.add_argument("--output-root", required=True, type=_absolute)
    verify_parser = sub.add_parser("verify")
    verify_parser.add_argument("--output-root", required=True, type=_absolute)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        if arguments.command == "compile":
            result = compile_chain(
                mainline_root=arguments.mainline_root,
                qualification_report=arguments.qualification_report,
                reset_root=arguments.reset_root,
                output_root=arguments.output_root,
            )
        else:
            result = _verify_output(arguments.output_root)
    except FinalEvidenceError as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error_code": exc.code,
                    "message": str(exc),
                    "phase": exc.phase,
                    "identity": exc.identity,
                    "diagnostic_id": exc.diagnostic_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    except DeviceFreshResetError as exc:
        print(
            json.dumps(
                {
                    "valid": False,
                    "error_code": exc.error_code,
                    "message": str(exc),
                    "phase": exc.phase,
                    "identity": exc.identity,
                    "diagnostic_id": exc.diagnostic_id,
                    "expected": exc.expected,
                    "observed": exc.observed,
                    "operator_action": exc.operator_action,
                    "mutation_applied": exc.mutation_applied,
                    "fallback_performed": exc.fallback_performed,
                },
                ensure_ascii=False,
                sort_keys=True,
            ),
            file=sys.stderr,
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
