from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import os
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID
from .aox_diagnostic_authority import (
    AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID,
)
from .aox_diagnostic_authority import (
    AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID,
)
from .aox_live_run_class import AoxLiveRunClass
from .aox_live_run_class import DIAGNOSTIC_RUN_POLICY


AOX_DIAGNOSTIC_DECISION_SCHEMA_ID = "aox_blank_world_diagnostic_decision@2"
_LEGACY_DIAGNOSTIC_DECISION_SCHEMA_IDS = frozenset(
    {"aox_blank_world_diagnostic_decision@1"}
)
AOX_DIAGNOSTIC_DECISION_FILENAME = "diagnostic-decision.json"
_ERROR_CODE_PATTERN = re.compile(r"^[a-z][a-z0-9_]{0,127}$")
_DECISION_FIELDS = frozenset(
    {
        "schema_id",
        "run_class",
        "acceptance_eligible",
        "diagnostic_id",
        "attempt_id",
        "attempt_kind",
        "decided_at",
        "status",
        "blocker",
        "authority",
        "root",
        "micu_ledger",
        "observations",
        "decision_digest",
    }
)


def validate_aox_diagnostic_decision(
    decision: Mapping[str, object],
) -> dict[str, Any]:
    normalized = dict(decision)
    schema_id = normalized.get("schema_id")
    if (
        set(normalized) != _DECISION_FIELDS
        or schema_id
        not in {
            AOX_DIAGNOSTIC_DECISION_SCHEMA_ID,
            *_LEGACY_DIAGNOSTIC_DECISION_SCHEMA_IDS,
        }
        or normalized.get("run_class") != AoxLiveRunClass.DIAGNOSTIC.value
        or normalized.get("acceptance_eligible") is not False
        or normalized.get("attempt_kind") != "positive"
        or normalized.get("status")
        not in {"completed_product_path", "blocked", "failed"}
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_schema_invalid",
            "diagnostic decision has an unsupported closed schema",
        )
    diagnostic_id = normalized.get("diagnostic_id")
    attempt_id = normalized.get("attempt_id")
    if (
        not isinstance(diagnostic_id, str)
        or DIAGNOSTIC_RUN_POLICY.campaign_id_pattern.fullmatch(diagnostic_id) is None
        or not isinstance(attempt_id, str)
        or DIAGNOSTIC_RUN_POLICY.attempt_id_pattern.fullmatch(attempt_id) is None
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_identity_invalid",
            "diagnostic decision identities are malformed",
        )
    authority = normalized.get("authority")
    root = normalized.get("root")
    observations = normalized.get("observations")
    blocker = normalized.get("blocker")
    micu_ledger = normalized.get("micu_ledger")
    if (
        not isinstance(authority, dict)
        or set(authority)
        != {
            "plan_schema_id",
            "consumption_schema_id",
            "plan_digest",
            "consumption_digest",
            "envelope_id",
            "request_digest",
        }
        or authority.get("plan_schema_id") != AOX_DIAGNOSTIC_AUTHORITY_PLAN_SCHEMA_ID
        or authority.get("consumption_schema_id")
        != AOX_DIAGNOSTIC_AUTHORITY_CONSUMPTION_SCHEMA_ID
        or not isinstance(root, dict)
        or set(root)
        != {
            "proof_schema_id",
            "root_namespace",
            "root_marker_digest",
            "root_identity",
        }
        or root.get("root_namespace") != diagnostic_id.replace("_", "-")
        or root.get("proof_schema_id") not in {None, DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID}
        or not isinstance(observations, dict)
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_binding_invalid",
            "diagnostic decision does not bind its disjoint authority and root",
        )
    expected_observation_fields = {
        "product_path_completed",
        "scientific_status",
        "report_status",
        "approval_count",
        "operation_count",
        "artifact_count",
        "evidence_digest",
        "scientific_attempt_control_digest",
    }
    if schema_id == AOX_DIAGNOSTIC_DECISION_SCHEMA_ID:
        expected_observation_fields.add("raw_facts")
    if set(observations) != expected_observation_fields or (
        schema_id == AOX_DIAGNOSTIC_DECISION_SCHEMA_ID
        and not isinstance(observations.get("raw_facts"), dict)
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_binding_invalid",
            "diagnostic decision does not bind its disjoint authority and root",
        )
    digest_values = (
        authority.get("plan_digest"),
        authority.get("consumption_digest"),
        authority.get("request_digest"),
        root.get("root_marker_digest"),
        root.get("root_identity"),
        observations.get("evidence_digest"),
        observations.get("scientific_attempt_control_digest"),
    )
    if any(
        value is not None
        and (
            not isinstance(value, str)
            or re.fullmatch(r"sha256:[a-f0-9]{64}", value) is None
        )
        for value in digest_values
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_digest_field_invalid",
            "diagnostic decision contains a malformed digest binding",
        )
    if (
        type(observations.get("product_path_completed")) is not bool
        or any(
            type(observations.get(key)) is not int or int(observations[key]) < 0
            for key in (
                "approval_count",
                "operation_count",
                "artifact_count",
            )
        )
        or (
            blocker is not None
            and (
                not isinstance(blocker, dict)
                or set(blocker) != {"code", "identity"}
                or blocker.get("identity") != "diagnostic.runner"
                or not isinstance(blocker.get("code"), str)
                or _ERROR_CODE_PATTERN.fullmatch(str(blocker["code"])) is None
            )
        )
        or (
            normalized.get("status") == "completed_product_path"
            and (
                observations.get("product_path_completed") is not True
                or blocker is not None
            )
        )
        or (normalized.get("status") != "completed_product_path" and blocker is None)
        or not isinstance(micu_ledger, dict)
        or (
            set(micu_ledger) == {"status", "reason"}
            and (
                micu_ledger.get("status") != "not_claimed"
                or micu_ledger.get("reason")
                != "diagnostic_runner_failed_before_settled_snapshot"
            )
        )
        or (
            set(micu_ledger) != {"status", "reason"}
            and (
                set(micu_ledger) != {"before", "after"}
                or not isinstance(micu_ledger.get("before"), dict)
                or not isinstance(micu_ledger.get("after"), dict)
            )
        )
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_semantics_invalid",
            "diagnostic decision violates its non-acceptance semantics",
        )
    decided_at = normalized.get("decided_at")
    try:
        parsed_decided_at = datetime.fromisoformat(str(decided_at))
    except ValueError as exc:
        raise CutoverEvidenceError(
            "diagnostic_decision_timestamp_invalid",
            "diagnostic decision timestamp is not ISO-8601",
        ) from exc
    if not isinstance(decided_at, str) or parsed_decided_at.tzinfo is None:
        raise CutoverEvidenceError(
            "diagnostic_decision_timestamp_invalid",
            "diagnostic decision timestamp must include a timezone",
        )
    serialized = canonical_json_bytes(normalized)
    if (
        b"aox_blank_world_attempt_bundle@3" in serialized
        or b"aox_blank_world_campaign_decision@1" in serialized
    ):
        raise CutoverEvidenceError(
            "diagnostic_decision_formal_evidence_forbidden",
            "diagnostic decisions cannot contain formal acceptance evidence",
        )
    expected_digest = canonical_digest(
        {key: value for key, value in normalized.items() if key != "decision_digest"}
    )
    if normalized.get("decision_digest") != expected_digest:
        raise CutoverEvidenceError(
            "diagnostic_decision_digest_mismatch",
            "diagnostic decision digest does not match its canonical payload",
        )
    return normalized


def seal_aox_diagnostic_decision(
    decision: Mapping[str, object],
    destination: Path,
) -> str:
    normalized = validate_aox_diagnostic_decision(decision)
    content = canonical_json_bytes(normalized) + b"\n"
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid4().hex}.tmp")
    try:
        with temporary.open("xb") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.chmod(0o444)
        try:
            os.link(temporary, destination)
        except FileExistsError as exc:
            raise CutoverEvidenceError(
                "diagnostic_decision_append_only",
                "diagnostic decision already exists and cannot be overwritten",
            ) from exc
        directory_fd = os.open(
            destination.parent,
            os.O_RDONLY | getattr(os, "O_DIRECTORY", 0),
        )
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        temporary.unlink(missing_ok=True)
    return str(normalized["decision_digest"])


__all__ = [
    "AOX_DIAGNOSTIC_DECISION_FILENAME",
    "AOX_DIAGNOSTIC_DECISION_SCHEMA_ID",
    "seal_aox_diagnostic_decision",
    "validate_aox_diagnostic_decision",
]
