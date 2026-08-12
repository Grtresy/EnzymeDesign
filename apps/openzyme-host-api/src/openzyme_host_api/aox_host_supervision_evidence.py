from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime
import math
import re
from typing import Any

from openzyme_core import MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID
from openzyme_engines import PODMAN_SANDBOX_PREFLIGHT_FAILURE_CODES

from .aox_attempt_start import ATTEMPT_START_CLAIM_FILENAME
from .aox_cutover_evidence import (
    CutoverEvidenceError,
    canonical_digest,
)
from .aox_launch_profile import AOX_CUTOVER_LAUNCH_PROFILE_FILENAME
from .aox_attempt_preflight import (
    ATTEMPT_CONDUCTOR_CONTRACT_FILENAME,
    ATTEMPT_PREFLIGHT_FILENAME,
    ATTEMPT_SLOT_CLAIM_FILENAME,
)


HOST_STARTUP_SCHEMA_ID = "aox_supervised_host_startup@5"
HOST_SUPERVISION_RECEIPT_SCHEMA_ID = "aox_supervised_host_receipt@4"
HOST_SUPERVISION_FATAL_SCHEMA_ID = "aox_supervised_host_fatal@2"
HOST_PRE_READY_FAILURE_SCHEMA_ID = "aox_supervised_host_pre_ready_failure@2"
HOST_SANDBOX_BOOTSTRAP_SCHEMA_ID = "aox_supervised_host_sandbox_bootstrap@1"
HOST_STARTUP_FILENAME = "aox-host-startup.json"
HOST_SUPERVISION_FILENAME = "aox-host-supervision.json"
HOST_SUPERVISION_FATAL_FILENAME = "aox-host-supervision-fatal.json"
HOST_PRE_READY_FAILURE_FILENAME = "aox-host-pre-ready-failure.json"
HOST_SPAWN_OUTCOME_SCHEMA_ID = "aox_host_spawn_outcome@1"
HOST_SPAWN_OUTCOME_FILENAME = "aox-host-spawn-outcome.json"

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_PRE_READY_FAILURE_CODES = frozenset(
    {
        "host_sandbox_runtime_identity_drift",
        "host_sandbox_runtime_identity_invalid",
        "host_sandbox_runtime_identity_mismatch",
        "host_sandbox_runtime_identity_missing",
    }
)
_PRE_READY_INITIAL_EVIDENCE_FILES = sorted(
    {
        AOX_CUTOVER_LAUNCH_PROFILE_FILENAME,
        ATTEMPT_CONDUCTOR_CONTRACT_FILENAME,
        ATTEMPT_PREFLIGHT_FILENAME,
        ATTEMPT_SLOT_CLAIM_FILENAME,
        ATTEMPT_START_CLAIM_FILENAME,
    }
)
_CONTRACT = {
    "schema_id": "aox_supervised_host_contract@1",
    "child_target": "configured_host_api",
    "network_boundary": "loopback_only",
    "runtime_policy": "public_commands_only",
    "automatic_runtime_drain": False,
    "automatic_approval": False,
    "automatic_rollover": False,
    "process_boundary": "spawn_posix_session",
    "retirement_ladder": ["cooperative", "sigterm", "sigkill", "group_empty"],
    "settlement": [
        "host_lifespan_retired",
        "mutation_writers_zero",
        "sqlite_checkpoint",
        "sqlite_integrity",
        "declared_roots_fsynced",
        "parent_snapshot_revalidated",
    ],
}
_RECEIPT_FIELDS = set(
    "schema_id mode launch_id attempt_kind session_id root_ref authority_policy_digest "
    "campaign_id preflight_receipt_digest attempt_start_claim_digest "
    "host_startup_receipt_digest process_epoch shutdown_reason child_exit_code "
    "local_state_settled descendant_retirement_proven parent_snapshot_revalidated "
    "mutation_authority_schema_id mutation_authority_snapshot_digest "
    "mutation_authority_observed_row_count nonterminal_mutation_scope_count "
    "active_mutation_writer_count sqlite_checkpoint sqlite_integrity declared_root_sync "
    "terminal_frame_digest timeout_seconds startup_timeout_seconds term_grace_seconds "
    "kill_grace_seconds supervisor_contract_digest retired_at receipt_digest".split()
)
_PRE_READY_RECEIPT_FIELDS = set(
    "schema_id mode launch_id attempt_kind session_id root_ref authority_policy_digest "
    "campaign_id preflight_receipt_digest attempt_start_claim_digest process_epoch "
    "failure_stage failure_code sandbox_preflight_failure_code child_pid child_pgid "
    "child_start_time_ticks child_exit_code local_state_settled "
    "descendant_retirement_proven parent_snapshot_revalidated "
    "mutation_authority_schema_id mutation_authority_snapshot_digest "
    "mutation_authority_observed_row_count nonterminal_mutation_scope_count "
    "active_mutation_writer_count sqlite_checkpoint sqlite_integrity control_plane_row_count "
    "effect_root_entry_counts evidence_files_before_receipt host_startup_created "
    "host_supervision_created public_receipt_chain_created declared_root_sync "
    "terminal_frame_digest timeout_seconds startup_timeout_seconds term_grace_seconds "
    "kill_grace_seconds supervisor_contract_digest retired_at receipt_digest".split()
)


def host_supervision_contract_digest(
    *, timeout_seconds: float, startup_timeout_seconds: float,
    term_grace_seconds: float, kill_grace_seconds: float,
) -> str:
    bounds = (timeout_seconds, startup_timeout_seconds, term_grace_seconds, kill_grace_seconds)
    if (not all(math.isfinite(value) for value in bounds) or timeout_seconds <= 0
            or startup_timeout_seconds <= 0 or term_grace_seconds < 0
            or kill_grace_seconds < 0):
        raise ValueError("supervised Host bounds are invalid")
    return canonical_digest({
        **_CONTRACT, "timeout_seconds": timeout_seconds,
        "startup_timeout_seconds": startup_timeout_seconds,
        "term_grace_seconds": term_grace_seconds,
        "kill_grace_seconds": kill_grace_seconds,
    })


def _receipt_contract(value: Mapping[str, Any]) -> str | None:
    try:
        return host_supervision_contract_digest(
            timeout_seconds=float(value["timeout_seconds"]),
            startup_timeout_seconds=float(value["startup_timeout_seconds"]),
            term_grace_seconds=float(value["term_grace_seconds"]),
            kill_grace_seconds=float(value["kill_grace_seconds"]),
        )
    except (KeyError, TypeError, ValueError):
        return None


def _has_digests(value: Mapping[str, Any], names: tuple[str, ...]) -> bool:
    return all(_DIGEST.fullmatch(str(value.get(name) or "")) for name in names)


def validate_supervised_host_receipt(
    receipt: object, *, launch_id: str, attempt_kind: str,
    session_id: str, root_ref: str, campaign_id: str,
    authority_policy_digest: str, attempt_start_claim_digest: str | None = None,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise CutoverEvidenceError(
            "host_supervision_receipt_missing",
            "eligible AOX evidence requires supervised Host retirement",
        )
    value = dict(receipt)
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    valid = all((
        set(value) == (_RECEIPT_FIELDS if attempt_start_claim_digest else
                       _RECEIPT_FIELDS - {"attempt_start_claim_digest"}),
        value.get("schema_id") == (HOST_SUPERVISION_RECEIPT_SCHEMA_ID if
                                    attempt_start_claim_digest else "aox_supervised_host_receipt@3"),
        value.get("mode") == "policy_free_public_host",
        value.get("launch_id") == launch_id,
        value.get("attempt_kind") == attempt_kind,
        value.get("session_id") == session_id, value.get("root_ref") == root_ref,
        value.get("campaign_id") == campaign_id,
        value.get("authority_policy_digest") == authority_policy_digest,
        attempt_start_claim_digest is None or
        value.get("attempt_start_claim_digest") == attempt_start_claim_digest,
        bool(value.get("process_epoch")),
        _has_digests(value, (
            "authority_policy_digest", "preflight_receipt_digest",
            "host_startup_receipt_digest",
            "mutation_authority_snapshot_digest", "terminal_frame_digest",
            "supervisor_contract_digest", "receipt_digest",
        ) + (() if attempt_start_claim_digest is None else ("attempt_start_claim_digest",))),
        value.get("shutdown_reason") in {"operator_stop", "authority_deadline"},
        value.get("child_exit_code") == 0, value.get("local_state_settled") is True,
        value.get("descendant_retirement_proven") is True,
        value.get("parent_snapshot_revalidated") is True,
        value.get("mutation_authority_schema_id") == MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
        all(type(value.get(name)) is int and value[name] >= 0 for name in (
            "mutation_authority_observed_row_count", "nonterminal_mutation_scope_count",
            "active_mutation_writer_count",
        )),
        value.get("nonterminal_mutation_scope_count") == 0,
        value.get("active_mutation_writer_count") == 0,
        value.get("sqlite_checkpoint") in {"passed", "not_present"},
        value.get("sqlite_integrity") in {"passed", "not_present"},
        value.get("declared_root_sync") is True, bool(value.get("retired_at")),
        value.get("supervisor_contract_digest") == _receipt_contract(value),
        value.get("receipt_digest") == canonical_digest(payload),
    ))
    if not valid:
        raise CutoverEvidenceError(
            "host_supervision_receipt_invalid",
            "supervised Host receipt does not prove exact local retirement",
            details={"identity": "product_path.attempt_supervision"},
        )
    return value


def validate_supervised_host_pre_ready_failure(
    receipt: object,
    *,
    preflight: Mapping[str, Any],
    attempt_start_claim_digest: str | None = None,
) -> dict[str, Any]:
    if not isinstance(receipt, dict):
        raise CutoverEvidenceError(
            "host_pre_ready_failure_receipt_missing",
            "pre-child-ready formal failure requires a supervision receipt",
            details={"identity": "host_pre_ready_failure"},
        )
    value = dict(receipt)
    payload = {key: item for key, item in value.items() if key != "receipt_digest"}
    slot = dict(preflight.get("slot") or {})
    slot_claim = dict(preflight.get("slot_claim") or {})
    try:
        retired_at = datetime.fromisoformat(str(value.get("retired_at") or ""))
    except ValueError:
        retired_at = None
    sandbox_failure_code = value.get("sandbox_preflight_failure_code")
    failure_code = value.get("failure_code")
    terminal_payload = {
        "schema_id": ("aox_supervised_host_child_pre_ready_failure@2" if
                      attempt_start_claim_digest else
                      "aox_supervised_host_child_pre_ready_failure@1"),
        "process_epoch": value.get("process_epoch"),
        "outcome": "failed",
        "failure_code": failure_code,
        "failure_type": "HostSupervisionError",
        "failure_stage": value.get("failure_stage"),
        "sandbox_preflight_failure_code": sandbox_failure_code,
        "child_pid": value.get("child_pid"),
        "child_pgid": value.get("child_pgid"),
        "child_start_time_ticks": value.get("child_start_time_ticks"),
    }
    if attempt_start_claim_digest:
        terminal_payload["attempt_start_claim_digest"] = value.get("attempt_start_claim_digest")
    valid = all((
            set(value) == (_PRE_READY_RECEIPT_FIELDS if attempt_start_claim_digest else
                           _PRE_READY_RECEIPT_FIELDS - {"attempt_start_claim_digest"}),
            value.get("schema_id") == (HOST_PRE_READY_FAILURE_SCHEMA_ID if
                                        attempt_start_claim_digest else
                                        "aox_supervised_host_pre_ready_failure@1"),
            value.get("mode") == "pre_child_ready",
            value.get("launch_id") == slot_claim.get("launch_id"),
            value.get("attempt_kind") == slot.get("attempt_kind"),
            value.get("session_id") == slot.get("session_id"),
            value.get("root_ref") == slot.get("root_ref"),
            value.get("authority_policy_digest") == slot.get("authority_policy_digest"),
            value.get("campaign_id") == preflight.get("campaign_id"),
            value.get("preflight_receipt_digest") == preflight.get("receipt_digest"),
            attempt_start_claim_digest is None or
            value.get("attempt_start_claim_digest") == attempt_start_claim_digest,
            isinstance(value.get("process_epoch"), str),
            bool(value.get("process_epoch")),
            value.get("failure_stage") == "sandbox_bootstrap_pre_registry",
            failure_code in _PRE_READY_FAILURE_CODES,
            sandbox_failure_code is None
            or sandbox_failure_code in PODMAN_SANDBOX_PREFLIGHT_FAILURE_CODES,
            failure_code
            not in {
                "host_sandbox_runtime_identity_missing",
                "host_sandbox_runtime_identity_drift",
            }
            or sandbox_failure_code in PODMAN_SANDBOX_PREFLIGHT_FAILURE_CODES,
            type(value.get("child_pid")) is int,
            value.get("child_pid", 0) > 0,
            value.get("child_pgid") == value.get("child_pid"),
            type(value.get("child_start_time_ticks")) is int,
            value.get("child_start_time_ticks", 0) > 0,
            type(value.get("child_exit_code")) is int,
            value.get("child_exit_code") != 0,
            value.get("local_state_settled") is True,
            value.get("descendant_retirement_proven") is True,
            value.get("parent_snapshot_revalidated") is True,
            value.get("mutation_authority_schema_id") == MUTATION_LOCAL_SETTLEMENT_SCHEMA_ID,
            all(type(value.get(name)) is int and value[name] == 0 for name in (
                "mutation_authority_observed_row_count", "nonterminal_mutation_scope_count",
                "active_mutation_writer_count", "control_plane_row_count",
            )),
            value.get("sqlite_checkpoint") == "parent_read_only",
            value.get("sqlite_integrity") == "passed",
            value.get("effect_root_entry_counts")
            == {"artifacts": 0, "blobs": 0, "hpc-workspace": 0, "sandboxes": 0},
            value.get("evidence_files_before_receipt")
            == _PRE_READY_INITIAL_EVIDENCE_FILES,
            value.get("host_startup_created") is False,
            value.get("host_supervision_created") is False,
            value.get("public_receipt_chain_created") is False,
            value.get("declared_root_sync") is True,
            value.get("terminal_frame_digest") == canonical_digest(terminal_payload),
            _has_digests(value, (
                "authority_policy_digest", "preflight_receipt_digest",
                "mutation_authority_snapshot_digest",
                "terminal_frame_digest", "supervisor_contract_digest", "receipt_digest",
            ) + (() if attempt_start_claim_digest is None else ("attempt_start_claim_digest",))),
            value.get("supervisor_contract_digest") == _receipt_contract(value),
            retired_at is not None and retired_at.tzinfo is not None,
            value.get("receipt_digest") == canonical_digest(payload),
        ))
    if not valid:
        raise CutoverEvidenceError(
            "host_pre_ready_failure_receipt_invalid",
            "pre-child-ready supervision receipt is not fail-closed",
            details={"identity": "host_pre_ready_failure"},
        )
    return value
