"""Read-only validation for retired closure-stage diagnostic decisions."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import re
from typing import Any

from .aox_cutover_evidence import (
    DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID,
    CutoverEvidenceError,
    canonical_digest,
    canonical_json_bytes,
)
from .aox_live_run_class import AoxLiveRunClass, DIAGNOSTIC_RUN_POLICY


AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID = (
    "aox_diagnostic_attempt_authority_plan@1"
)
AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID = (
    "aox_diagnostic_attempt_authority_consumption@1"
)
AOX_DIAGNOSTIC_DECISION_SCHEMA_ID = "aox_blank_world_diagnostic_decision@2"
AOX_DIAGNOSTIC_DECISION_FILENAME = "diagnostic-decision.json"
_SCHEMAS = {AOX_DIAGNOSTIC_DECISION_SCHEMA_ID, "aox_blank_world_diagnostic_decision@1"}
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_]{0,127}")
_DIGEST = re.compile(r"sha256:[a-f0-9]{64}")
_FIELDS = {
    "schema_id", "run_class", "acceptance_eligible", "diagnostic_id",
    "attempt_id", "attempt_kind", "decided_at", "status", "blocker",
    "authority", "root", "micu_ledger", "observations", "decision_digest",
}
_AUTHORITY_FIELDS = {
    "plan_schema_id", "consumption_schema_id", "plan_digest",
    "consumption_digest", "envelope_id", "request_digest",
}
_ROOT_FIELDS = {
    "proof_schema_id", "root_namespace", "root_marker_digest", "root_identity"
}
_OBSERVATION_FIELDS = {
    "product_path_completed", "scientific_status", "report_status",
    "approval_count", "operation_count", "artifact_count", "evidence_digest",
    "scientific_attempt_control_digest",
}


def _reject(code: str, message: str) -> None:
    raise CutoverEvidenceError(code, message)


def _valid_micu(value: object) -> bool:
    if not isinstance(value, dict):
        return False
    if set(value) == {"status", "reason"}:
        return value == {
            "status": "not_claimed",
            "reason": "diagnostic_runner_failed_before_settled_snapshot",
        }
    return (
        set(value) == {"before", "after"}
        and isinstance(value.get("before"), dict)
        and isinstance(value.get("after"), dict)
    )


def validate_aox_diagnostic_decision(
    decision: Mapping[str, object],
) -> dict[str, Any]:
    value = dict(decision)
    schema, status = value.get("schema_id"), value.get("status")
    if not all((
        set(value) == _FIELDS,
        schema in _SCHEMAS,
        value.get("run_class") == AoxLiveRunClass.DIAGNOSTIC.value,
        value.get("acceptance_eligible") is False,
        value.get("attempt_kind") == "positive",
        status in {"completed_product_path", "blocked", "failed"},
    )):
        _reject("diagnostic_decision_schema_invalid", "unsupported diagnostic decision schema")
    diagnostic_id, attempt_id = value.get("diagnostic_id"), value.get("attempt_id")
    if not all((
        isinstance(diagnostic_id, str),
        isinstance(diagnostic_id, str)
        and DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(diagnostic_id),
        isinstance(attempt_id, str),
        isinstance(attempt_id, str)
        and DIAGNOSTIC_RUN_POLICY.attempt_id_pattern.fullmatch(attempt_id),
    )):
        _reject("diagnostic_decision_identity_invalid", "malformed diagnostic identities")
    authority, root, observations = (
        value.get(name) for name in ("authority", "root", "observations")
    )
    bound = (
        isinstance(authority, dict) and set(authority) == _AUTHORITY_FIELDS
        and authority.get("plan_schema_id") == AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
        and authority.get("consumption_schema_id")
        == AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID
        and isinstance(root, dict) and set(root) == _ROOT_FIELDS
        and root.get("root_namespace") == diagnostic_id.replace("_", "-")
        and root.get("proof_schema_id") in {None, DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID}
        and isinstance(observations, dict)
    )
    expected_observations = _OBSERVATION_FIELDS | (
        {"raw_facts"} if schema == AOX_DIAGNOSTIC_DECISION_SCHEMA_ID else set()
    )
    if not bound or set(observations) != expected_observations or (
        schema == AOX_DIAGNOSTIC_DECISION_SCHEMA_ID
        and not isinstance(observations.get("raw_facts"), dict)
    ):
        _reject("diagnostic_decision_binding_invalid", "diagnostic bindings do not reproduce")
    assert isinstance(authority, dict) and isinstance(root, dict)
    assert isinstance(observations, dict)
    digest_values = (
        authority.get("plan_digest"), authority.get("consumption_digest"),
        authority.get("request_digest"), root.get("root_marker_digest"),
        root.get("root_identity"), observations.get("evidence_digest"),
        observations.get("scientific_attempt_control_digest"),
    )
    if any(item is not None and (
        not isinstance(item, str) or _DIGEST.fullmatch(item) is None
    ) for item in digest_values):
        _reject("diagnostic_decision_digest_field_invalid", "malformed diagnostic digest")
    blocker = value.get("blocker")
    blocker_valid = blocker is None or (
        isinstance(blocker, dict) and set(blocker) == {"code", "identity"}
        and blocker.get("identity") == "diagnostic.runner"
        and isinstance(blocker.get("code"), str)
        and _ERROR_CODE.fullmatch(str(blocker["code"])) is not None
    )
    completed = status == "completed_product_path"
    semantics = all((
        type(observations.get("product_path_completed")) is bool,
        all(type(observations.get(key)) is int and observations[key] >= 0 for key in (
            "approval_count", "operation_count", "artifact_count"
        )),
        blocker_valid,
        not completed or (
            observations.get("product_path_completed") is True and blocker is None
        ),
        completed or blocker is not None,
        _valid_micu(value.get("micu_ledger")),
    ))
    if not semantics:
        _reject("diagnostic_decision_semantics_invalid", "invalid non-acceptance semantics")
    decided_at = value.get("decided_at")
    try:
        parsed = datetime.fromisoformat(str(decided_at))
    except ValueError as exc:
        raise CutoverEvidenceError(
            "diagnostic_decision_timestamp_invalid",
            "diagnostic decision timestamp is not ISO-8601",
        ) from exc
    if not isinstance(decided_at, str) or parsed.tzinfo is None:
        _reject("diagnostic_decision_timestamp_invalid", "timestamp must include a timezone")
    serialized = canonical_json_bytes(value)
    if any(marker in serialized for marker in (
        b"aox_blank_world_attempt_bundle@3",
        b"aox_blank_world_campaign_decision@1",
    )):
        _reject("diagnostic_decision_formal_evidence_forbidden", "formal evidence is forbidden")
    expected_digest = canonical_digest({
        key: item for key, item in value.items() if key != "decision_digest"
    })
    if value.get("decision_digest") != expected_digest:
        _reject("diagnostic_decision_digest_mismatch", "diagnostic digest does not reproduce")
    return value


__all__ = [
    "AOX_DIAGNOSTIC_DECISION_FILENAME", "AOX_DIAGNOSTIC_DECISION_SCHEMA_ID",
    "validate_aox_diagnostic_decision",
]
