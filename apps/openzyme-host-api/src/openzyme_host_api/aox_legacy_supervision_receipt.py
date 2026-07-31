"""Read-only validators for observer-era sealed supervision receipts."""

from __future__ import annotations

from collections.abc import Mapping
import math
import re

from openzyme_core import MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID

from .aox_cutover_evidence import CutoverEvidenceError, canonical_digest


SUPERVISION_SCHEMA_ID_V1 = "aox_live_attempt_supervision@1"
SUPERVISION_SCHEMA_ID_V2 = "aox_live_attempt_supervision@2"
SUPERVISION_SCHEMA_ID = "aox_live_attempt_supervision@3"
SUPERVISION_RECEIPT_SCHEMA_ID_V1 = "aox_live_attempt_supervision_receipt@1"
SUPERVISION_RECEIPT_SCHEMA_ID_V2 = "aox_live_attempt_supervision_receipt@2"
SUPERVISION_RECEIPT_SCHEMA_ID = "aox_live_attempt_supervision_receipt@3"
DEFAULT_TERM_GRACE_SECONDS = 15.0
DEFAULT_KILL_GRACE_SECONDS = 10.0
MAX_FRAME_BYTES = 64 * 1024
_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_EPOCH = re.compile(r"[0-9a-f]{32}")
_COMMON_FIELDS = {
    "schema_id", "mode", "attempt_id", "attempt_kind", "campaign_id",
    "process_epoch", "protocol_final_sequence", "protocol_final_digest",
    "child_exit_code", "descendant_retirement_proven", "sqlite_checkpoint",
    "sqlite_integrity", "declared_root_sync", "result_digest",
    "supervisor_contract_digest", "timeout_seconds", "term_grace_seconds",
    "kill_grace_seconds",
}
_AUTHORITY_FIELDS = {"attempt_authority_id", "attempt_authority_request_digest"}
_LEGACY_FIELDS = {
    "quiescent", "active_mutation_scope_count", "active_mutation_writer_count"
}
_CURRENT_FIELDS = {
    "local_state_settled", "parent_snapshot_revalidated",
    "mutation_authority_schema_id", "mutation_authority_snapshot_digest",
    "mutation_authority_observed_row_count", "nonterminal_mutation_scope_count",
    "active_mutation_writer_count",
}


def _contract(schema_id: str) -> dict[str, object]:
    current = schema_id == SUPERVISION_SCHEMA_ID
    if not current and schema_id not in {
        SUPERVISION_SCHEMA_ID_V1,
        SUPERVISION_SCHEMA_ID_V2,
    }:
        raise ValueError("historical attempt supervision schema is unsupported")
    return {
        "schema_id": schema_id,
        "frame_types": (
            ["child_started", "settling_local_state", "local_state_settled", "child_terminal"]
            if current
            else ["child_started", "quiescing", "quiescent", "child_terminal"]
        ),
        "serialization": "canonical_json_utf8",
        "frame_limit_bytes": MAX_FRAME_BYTES,
        "digest": "sha256",
        "start_method": "spawn",
        "session_boundary": "posix_setsid_process_group",
        "retirement_ladder": ["sigterm", "sigkill", "waitpid", "group_empty"],
        "normal_gate": (
            [
                "local_state_settled", "child_terminal_normal", "zero_exit",
                "group_empty", "parent_snapshot_revalidated", "result_digest_match",
            ]
            if current
            else [
                "quiescent", "child_terminal_normal", "zero_exit", "group_empty",
                "result_digest_match",
            ]
        ),
    }


def _nonnegative_int(value: object) -> bool:
    return type(value) is int and value >= 0


def _digest(value: object) -> bool:
    return isinstance(value, str) and _DIGEST.fullmatch(value) is not None


def derive_live_attempt_supervision_timeout_seconds(
    *,
    attempt_timeout_seconds: float,
    browser_approval_timeout_seconds: float,
    browser_completion_hold_seconds: float,
    browser_observation_submission_timeout_seconds: float,
) -> float:
    """Reproduce frozen @1-@3 receipts; never drive a current attempt."""

    values = (
        attempt_timeout_seconds,
        browser_approval_timeout_seconds,
        browser_completion_hold_seconds,
        browser_observation_submission_timeout_seconds,
    )
    if attempt_timeout_seconds <= 0 or any(
        not math.isfinite(value) or value < 0 for value in values
    ):
        raise ValueError("historical live supervision bounds are invalid")
    return sum((
        2 * attempt_timeout_seconds,
        browser_approval_timeout_seconds,
        browser_completion_hold_seconds,
        browser_observation_submission_timeout_seconds,
        120.0,
    ))


def supervision_contract_digest(
    *,
    timeout_seconds: float,
    term_grace_seconds: float,
    kill_grace_seconds: float,
    protocol_schema_id: str = SUPERVISION_SCHEMA_ID,
) -> str:
    return canonical_digest({
        **_contract(protocol_schema_id),
        "timeout_seconds": timeout_seconds,
        "term_grace_seconds": term_grace_seconds,
        "kill_grace_seconds": kill_grace_seconds,
    })


def _reject(code: str, message: str) -> None:
    raise CutoverEvidenceError(
        code, message, details={"identity": "product_path.attempt_supervision"}
    )


def validate_attempt_supervision_receipt(
    receipt: object,
    *,
    attempt_id: str,
    attempt_kind: str,
    attempt_authority_id: str | None = None,
    attempt_authority_request_digest: str | None = None,
    expected_contract_digest: str | None = None,
    allow_legacy: bool = False,
) -> dict[str, object]:
    """Validate sealed @1-@3 evidence without reviving its runtime."""

    if not isinstance(receipt, Mapping):
        _reject(
            "attempt_supervision_receipt_missing",
            "historical bundle lacks its sealed process supervision receipt",
        )
    value = dict(receipt)
    authority_expected = (
        attempt_authority_id is not None
        or attempt_authority_request_digest is not None
    )
    if authority_expected and not (
        isinstance(attempt_authority_id, str)
        and bool(attempt_authority_id)
        and _digest(attempt_authority_request_digest)
    ):
        _reject(
            "attempt_supervision_authority_invalid",
            "historical supervision validation requires exact authority identity",
        )
    bounds = tuple(value.get(name) for name in (
        "timeout_seconds", "term_grace_seconds", "kill_grace_seconds"
    ))
    valid_bounds = all(
        isinstance(item, (int, float))
        and not isinstance(item, bool)
        and math.isfinite(float(item))
        for item in bounds
    ) and float(bounds[0]) > 0 and float(bounds[1]) >= 0 and float(bounds[2]) >= 0
    common = all((
        value.get("mode") == "process_isolated_spawn",
        value.get("attempt_id") == attempt_id,
        value.get("attempt_kind") == attempt_kind,
        isinstance(value.get("process_epoch"), str)
        and _EPOCH.fullmatch(str(value["process_epoch"])) is not None,
        all(_digest(value.get(name)) for name in (
            "campaign_id", "protocol_final_digest", "result_digest",
            "supervisor_contract_digest",
        )),
        value.get("protocol_final_sequence") == 4,
        value.get("child_exit_code") == 0,
        value.get("descendant_retirement_proven") is True,
        value.get("sqlite_checkpoint") in {"passed", "not_present"},
        value.get("sqlite_integrity") in {"passed", "not_present"},
        value.get("declared_root_sync") is True,
        valid_bounds,
    ))
    schema = value.get("schema_id")
    if schema == SUPERVISION_RECEIPT_SCHEMA_ID:
        protocol = SUPERVISION_SCHEMA_ID
        valid = all((
            set(value) == _COMMON_FIELDS | _AUTHORITY_FIELDS | _CURRENT_FIELDS,
            authority_expected,
            common,
            value.get("attempt_authority_id") == attempt_authority_id,
            value.get("attempt_authority_request_digest")
            == attempt_authority_request_digest,
            value.get("local_state_settled") is True,
            value.get("parent_snapshot_revalidated") is True,
            value.get("mutation_authority_schema_id")
            == MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
            _digest(value.get("mutation_authority_snapshot_digest")),
            _nonnegative_int(value.get("mutation_authority_observed_row_count")),
            _nonnegative_int(value.get("nonterminal_mutation_scope_count")),
            value.get("active_mutation_writer_count") == 0,
        ))
    else:
        authority_bound = schema == SUPERVISION_RECEIPT_SCHEMA_ID_V2
        protocol = SUPERVISION_SCHEMA_ID_V2 if authority_bound else SUPERVISION_SCHEMA_ID_V1
        fields = _COMMON_FIELDS | _LEGACY_FIELDS | (
            _AUTHORITY_FIELDS if authority_bound else set()
        )
        valid = all((
            schema in {SUPERVISION_RECEIPT_SCHEMA_ID_V1, SUPERVISION_RECEIPT_SCHEMA_ID_V2},
            allow_legacy,
            set(value) == fields,
            common,
            authority_expected is authority_bound,
            not authority_bound or value.get("attempt_authority_id") == attempt_authority_id,
            not authority_bound or value.get("attempt_authority_request_digest")
            == attempt_authority_request_digest,
            value.get("quiescent") is True,
            value.get("active_mutation_scope_count") == 0,
            value.get("active_mutation_writer_count") == 0,
        ))
    expected = None if not valid_bounds else supervision_contract_digest(
        timeout_seconds=float(bounds[0]),
        term_grace_seconds=float(bounds[1]),
        kill_grace_seconds=float(bounds[2]),
        protocol_schema_id=protocol,
    )
    if not valid or value.get("supervisor_contract_digest") != expected or (
        expected_contract_digest is not None
        and value.get("supervisor_contract_digest") != expected_contract_digest
    ):
        _reject(
            "attempt_supervision_receipt_invalid",
            "historical process supervision receipt does not reproduce",
        )
    return value


__all__ = [
    "DEFAULT_KILL_GRACE_SECONDS", "DEFAULT_TERM_GRACE_SECONDS",
    "SUPERVISION_RECEIPT_SCHEMA_ID", "SUPERVISION_RECEIPT_SCHEMA_ID_V1",
    "SUPERVISION_RECEIPT_SCHEMA_ID_V2", "SUPERVISION_SCHEMA_ID",
    "SUPERVISION_SCHEMA_ID_V1", "SUPERVISION_SCHEMA_ID_V2",
    "derive_live_attempt_supervision_timeout_seconds", "supervision_contract_digest",
    "validate_attempt_supervision_receipt",
]
