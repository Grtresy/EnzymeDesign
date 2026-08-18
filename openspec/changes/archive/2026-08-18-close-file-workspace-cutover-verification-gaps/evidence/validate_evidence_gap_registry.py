from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parent
DIGEST_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
GAP_ID_RE = re.compile(r"^GAP-[A-Z0-9-]+$")
TASK_ID_RE = re.compile(r"^[0-9]+(?:\.[0-9]+)+$")


def _load(name: str) -> dict[str, Any]:
    value = json.loads((ROOT / name).read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{name} must contain one JSON object")
    return value


def _require_exact_keys(value: dict[str, Any], expected: set[str], label: str) -> None:
    observed = set(value)
    if observed != expected:
        raise ValueError(
            f"{label} fields differ: missing={sorted(expected - observed)!r}, "
            f"extra={sorted(observed - expected)!r}"
        )


def validate() -> None:
    schema = _load("evidence-gap-registry.schema.json")
    registry = _load("evidence-gap-registry.json")
    baseline_bytes = (ROOT / "remediation-baseline.json").read_bytes()
    baseline_digest = f"sha256:{hashlib.sha256(baseline_bytes).hexdigest()}"

    if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
        raise ValueError("registry schema must use JSON Schema draft 2020-12")
    _require_exact_keys(
        registry,
        {
            "schema_id",
            "generated_at",
            "baseline_digest",
            "target_changes",
            "excluded_active_changes",
            "change_audits",
            "gaps",
        },
        "registry",
    )
    if registry["schema_id"] != "file_workspace_evidence_gap_registry@1":
        raise ValueError("unexpected registry schema_id")
    if registry["baseline_digest"] != baseline_digest:
        raise ValueError(
            "baseline digest mismatch: "
            f"expected={baseline_digest}, observed={registry['baseline_digest']}"
        )

    targets = registry["target_changes"]
    excluded = registry["excluded_active_changes"]
    audits = registry["change_audits"]
    gaps = registry["gaps"]
    if len(targets) != 14 or len(set(targets)) != 14:
        raise ValueError("target_changes must contain exactly 14 unique changes")
    if len(excluded) != 2 or len(set(excluded)) != 2 or set(targets) & set(excluded):
        raise ValueError("excluded_active_changes must be two unique non-target changes")
    if len(audits) != 14 or {item["change_id"] for item in audits} != set(targets):
        raise ValueError("change_audits must cover the exact target set")

    gap_ids = [item["gap_id"] for item in gaps]
    if len(gap_ids) != len(set(gap_ids)) or not all(GAP_ID_RE.fullmatch(item) for item in gap_ids):
        raise ValueError("gap identities must be unique and canonical")
    gap_id_set = set(gap_ids)
    for audit in audits:
        _require_exact_keys(
            audit,
            {
                "change_id",
                "initial_tasks_digest",
                "initial_completed_tasks",
                "total_tasks",
                "audit_disposition",
                "gap_ids",
            },
            f"change audit {audit['change_id']}",
        )
        if not DIGEST_RE.fullmatch(audit["initial_tasks_digest"]):
            raise ValueError(f"invalid tasks digest for {audit['change_id']}")
        if not set(audit["gap_ids"]) <= gap_id_set:
            raise ValueError(f"unknown gap reference for {audit['change_id']}")

    for gap in gaps:
        _require_exact_keys(
            gap,
            {
                "gap_id",
                "category",
                "severity",
                "owning_change",
                "owning_tasks",
                "counterevidence",
                "repair_tasks",
                "required_evidence",
                "disposition",
                "final_evidence_digest",
            },
            f"gap {gap['gap_id']}",
        )
        if not gap["counterevidence"] or not gap["required_evidence"]:
            raise ValueError(f"gap {gap['gap_id']} lacks counterevidence or required evidence")
        if not all(TASK_ID_RE.fullmatch(item) for item in gap["owning_tasks"]):
            raise ValueError(f"gap {gap['gap_id']} has a non-canonical owning task")
        if gap["disposition"] == "open" and gap["final_evidence_digest"] is not None:
            raise ValueError(f"open gap {gap['gap_id']} cannot carry final evidence")
        if gap["disposition"] == "resolved" and not DIGEST_RE.fullmatch(
            gap["final_evidence_digest"] or ""
        ):
            raise ValueError(f"resolved gap {gap['gap_id']} requires final evidence")


if __name__ == "__main__":
    try:
        validate()
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        print(f"evidence-gap-registry-invalid: {exc}", file=sys.stderr)
        raise SystemExit(1) from exc
    print("evidence-gap-registry-valid")
