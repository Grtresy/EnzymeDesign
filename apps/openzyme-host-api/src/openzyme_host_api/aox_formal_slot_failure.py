from __future__ import annotations

# AOX-DEBT-EVIDENCE-MODULE-SPLIT: before adding another closure mode or evidence
# reconstruction responsibility, follow the extraction trigger recorded in
# docs/v3/harness-complexity-audit.md.

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePath
import re
import stat
from typing import Any

from .aox_attempt_preflight import ATTEMPT_PREFLIGHT_FILENAME
from .aox_attempt_preflight import ATTEMPT_SLOT_CLAIM_FILENAME
from .aox_attempt_preflight import load_attempt_preflight_receipt
from .aox_attempt_start import ATTEMPT_START_CLAIM_FILENAME
from .aox_attempt_start import load_bound_attempt_start_claim
from .aox_cutover_evidence import CutoverEvidenceError
from .aox_cutover_evidence import VerificationIssue
from .aox_cutover_evidence import _normalize_identity
from .aox_cutover_evidence import _validate_ledger_transition
from .aox_cutover_evidence import _write_append_only_bytes
from .aox_cutover_evidence import canonical_digest
from .aox_cutover_evidence import canonical_json_bytes
from .aox_host_supervision import HOST_STARTUP_FILENAME
from .aox_host_supervision import HOST_PRE_READY_FAILURE_FILENAME
from .aox_host_supervision import HOST_PRE_READY_FAILURE_SCHEMA_ID
from .aox_host_supervision import HOST_SUPERVISION_FILENAME
from .aox_host_supervision import validate_supervised_host_pre_ready_failure
from .aox_host_supervision import validate_supervised_host_receipt
from .aox_public_conductor_bundle import PUBLIC_CONDUCTOR_BUNDLE_FILENAME
from .aox_public_conductor_bundle import _content_digest
from .aox_public_conductor_bundle import _load_canonical_object
from .aox_public_conductor_bundle import _load_receipt_chain
from .aox_public_conductor_bundle import _load_response_envelope
from .aox_public_conductor_bundle import _validate_events
from .aox_public_conductor_bundle import _validate_runtime_command_handoffs
from .aox_public_conductor_bundle import _validate_startup
from .aox_public_conductor_contract import validate_bounded_drain_receipts
from .aox_public_conductor_contract import validate_canonical_entry_receipts


FORMAL_SLOT_FAILURE_SCHEMA_ID = "aox_formal_slot_failure@3"
LEGACY_FORMAL_SLOT_FAILURE_SCHEMA_IDS = {
    "aox_formal_slot_failure@1", "aox_formal_slot_failure@2",
}
FORMAL_SLOT_FAILURE_FILENAME = "formal-slot-failure.json"
FORMAL_SLOT_FAILURE_DECISION_SCHEMA_ID = (
    "aox_blank_world_campaign_failure_decision@1"
)

_DIGEST = re.compile(r"sha256:[0-9a-f]{64}")
_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_TERMINAL_COMMAND_STATUSES = {"completed", "failed", "locked", "cancelled"}
_LEGACY_PAYLOAD_FIELDS = {
    "schema_id",
    "sealed_at",
    "run_class",
    "acceptance_eligible",
    "state_reusable",
    "identity",
    "campaign_id",
    "plan_digest",
    "consumption_digest",
    "launch_id",
    "attempt_kind",
    "slot_ordinal",
    "session_id",
    "root_ref",
    "authority_policy_digest",
    "preflight_receipt_digest",
    "slot_claim_digest",
    "host_startup_receipt_digest",
    "host_supervision_receipt_digest",
    "public_api_receipt_chain_digest",
    "final_workspace_response_digest",
    "final_event_response_digest",
    "terminal_handoff_response_digests",
    "scientific_attempt_state",
    "terminal_command",
    "earliest_typed_cause",
    "cause_observation",
    "micu_ledger",
    "sources",
}
_V2_PUBLIC_HOST_PAYLOAD_FIELDS = _LEGACY_PAYLOAD_FIELDS | {"closure_mode"}
_PUBLIC_HOST_PAYLOAD_FIELDS = _V2_PUBLIC_HOST_PAYLOAD_FIELDS | {
    "attempt_start_claim_digest"
}
_V2_PRE_READY_PAYLOAD_FIELDS = {
    "schema_id",
    "closure_mode",
    "sealed_at",
    "run_class",
    "acceptance_eligible",
    "state_reusable",
    "identity",
    "campaign_id",
    "plan_digest",
    "consumption_digest",
    "launch_id",
    "attempt_kind",
    "slot_ordinal",
    "session_id",
    "root_ref",
    "authority_policy_digest",
    "preflight_receipt_digest",
    "slot_claim_digest",
    "host_pre_ready_failure_receipt_digest",
    "scientific_attempt_state",
    "earliest_typed_cause",
    "micu_ledger",
    "sources",
}
_PRE_READY_PAYLOAD_FIELDS = _V2_PRE_READY_PAYLOAD_FIELDS | {
    "attempt_start_claim_digest"
}
_CAUSE_FIELDS = {
    "code",
    "identity",
    "source_kind",
    "source_ref",
    "source_version",
    "effect_certainty",
    "recoverability",
    "retry_eligibility",
}
_CAUSE_OBSERVATION_FIELDS = {
    "failure_id",
    "source_kind",
    "source_ref",
    "source_version",
    "error_code",
    "effect_certainty",
    "recoverability",
    "retry_eligibility",
}
_EFFECT_CERTAINTIES = {
    "dispatch_in_doubt",
    "effect_known",
    "no_effect",
    "terminal_known",
    "unproven",
}
_RECOVERABILITIES = {
    "agent_can_replan",
    "agent_can_retry",
    "authorization_required",
    "reconciliation_required",
    "runtime_retry",
    "terminal",
}
_RETRY_ELIGIBILITIES = {
    "reconcile_required",
    "same_phase_safe",
    "terminal",
    "verify_then_retry",
}
_TERMINAL_COMMAND_FIELDS = {
    "command_id",
    "status",
    "error_code",
    "completed_at",
    "bounded_outcome_summary",
}
_ATTEMPT_STATE_FIELDS = {
    "attempt_count",
    "attempt_ids",
    "cutover_eligible",
}
_SOURCE_KEYS = {
    "preflight",
    "slot_claim",
    "host_startup",
    "host_supervision",
    "receipt_chain",
    "workspace",
    "events",
    "ledger_before",
    "ledger_after",
    "handoffs",
}
_CURRENT_SOURCE_KEYS = (_SOURCE_KEYS - {"ledger_before"}) | {"attempt_start_claim"}
_PRE_READY_SOURCE_KEYS = {
    "preflight",
    "slot_claim",
    "host_pre_ready_failure",
    "ledger_before",
    "ledger_after",
}
_CURRENT_PRE_READY_SOURCE_KEYS = (
    _PRE_READY_SOURCE_KEYS - {"ledger_before"}
) | {"attempt_start_claim"}
_DECISION_FIELDS = {
    "schema_id",
    "decided_at",
    "decision",
    "campaign_id",
    "plan_digest",
    "slot_ordinal",
    "launch_id",
    "attempt_kind",
    "formal_slot_failure_digest",
    "attempt_digests",
    "attempt_ids",
    "blocker",
    "decision_digest",
}
_DECISION_BLOCKER_FIELDS = {"code", "identity", "message"}


@dataclass(frozen=True, slots=True)
class FormalSlotFailureVerification:
    passed: bool
    failure_digest: str | None
    campaign_id: str | None
    plan_digest: str | None
    launch_id: str | None
    attempt_kind: str | None
    slot_ordinal: int | None
    issue: VerificationIssue | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_id": "aox_formal_slot_failure_verification@1",
            "passed": self.passed,
            "failure_digest": self.failure_digest,
            "campaign_id": self.campaign_id,
            "plan_digest": self.plan_digest,
            "launch_id": self.launch_id,
            "attempt_kind": self.attempt_kind,
            "slot_ordinal": self.slot_ordinal,
            "issue": None if self.issue is None else self.issue.to_dict(),
        }


def _fail(code: str, message: str, *, identity: str) -> None:
    raise CutoverEvidenceError(code, message, details={"identity": identity})


def _is_aware_timestamp(value: object) -> bool:
    if not isinstance(value, str) or not value:
        return False
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return False
    return parsed.tzinfo is not None


def _real_source_path(path: Path, *, identity: str) -> Path:
    candidate = path.expanduser().absolute()
    try:
        metadata = candidate.lstat()
        resolved = candidate.resolve(strict=True)
    except OSError as exc:
        raise CutoverEvidenceError(
            "formal_slot_failure_source_unreadable",
            "formal slot failure source is unreadable",
            details={"identity": identity},
        ) from exc
    if (
        not stat.S_ISREG(metadata.st_mode)
        or stat.S_ISLNK(metadata.st_mode)
        or resolved != candidate
    ):
        _fail(
            "formal_slot_failure_source_invalid",
            "formal slot failure source must be one real regular file",
            identity=identity,
        )
    return candidate


def _safe_source_name(path: Path, *, evidence_root: Path) -> str:
    if path.parent != evidence_root or path.name != PurePath(path.name).name:
        _fail(
            "formal_slot_failure_source_path_invalid",
            "formal slot failure sources must stay in the exact evidence root",
            identity="sources",
        )
    if not path.name or path.name in {".", "..", FORMAL_SLOT_FAILURE_FILENAME}:
        _fail(
            "formal_slot_failure_source_path_invalid",
            "formal slot failure source name is unsafe",
            identity="sources",
        )
    return path.name


def _source_descriptor(path: Path, *, evidence_root: Path) -> dict[str, str]:
    name = _safe_source_name(path, evidence_root=evidence_root)
    try:
        metadata = path.lstat()
        content = path.read_bytes()
    except OSError as exc:
        raise CutoverEvidenceError(
            "formal_slot_failure_source_unreadable",
            "formal slot failure source is unreadable",
            details={"identity": name},
        ) from exc
    if not (
        stat.S_ISREG(metadata.st_mode)
        and not stat.S_ISLNK(metadata.st_mode)
        and stat.S_IMODE(metadata.st_mode) & 0o077 == 0
    ):
        _fail(
            "formal_slot_failure_source_invalid",
            "formal slot failure source must be one private regular file",
            identity=name,
        )
    return {"name": name, "content_digest": _content_digest(content)}


def _source_path(
    sources: Mapping[str, Any],
    key: str,
    *,
    evidence_root: Path,
) -> Path:
    descriptor = sources.get(key)
    if not isinstance(descriptor, dict) or set(descriptor) != {
        "name",
        "content_digest",
    }:
        _fail(
            "formal_slot_failure_source_binding_invalid",
            "formal slot failure source descriptor is malformed",
            identity=f"sources.{key}",
        )
    name = descriptor.get("name")
    digest = descriptor.get("content_digest")
    if (
        not isinstance(name, str)
        or not name
        or name != PurePath(name).name
        or name in {".", "..", FORMAL_SLOT_FAILURE_FILENAME}
        or not isinstance(digest, str)
        or _DIGEST.fullmatch(digest) is None
    ):
        _fail(
            "formal_slot_failure_source_binding_invalid",
            "formal slot failure source descriptor is unsafe",
            identity=f"sources.{key}",
        )
    path = evidence_root / name
    actual = _source_descriptor(path, evidence_root=evidence_root)
    if actual != descriptor:
        _fail(
            "formal_slot_failure_source_digest_mismatch",
            "formal slot failure source bytes drifted",
            identity=f"sources.{key}",
        )
    return path


def _terminal_command_facts(
    command_handoffs: Sequence[Mapping[str, Any]],
) -> dict[str, Any] | None:
    if not command_handoffs:
        return None
    response = dict(command_handoffs[-1].get("terminal_response") or {})
    facts = {
        key: response.get(key)
        for key in (
            "command_id",
            "status",
            "error_code",
            "completed_at",
            "bounded_outcome_summary",
        )
    }
    if (
        set(facts) != _TERMINAL_COMMAND_FIELDS
        or facts["status"] not in _TERMINAL_COMMAND_STATUSES
        or not facts["command_id"]
        or not facts["completed_at"]
    ):
        _fail(
            "formal_slot_failure_terminal_command_invalid",
            "formal slot failure lacks one closed terminal command",
            identity="terminal_command",
        )
    return facts


def _derive_failure_facts(
    *,
    workspace: Mapping[str, Any],
    events: Sequence[Mapping[str, Any]],
    command_handoffs: Sequence[Mapping[str, Any]],
    launch_id: str,
) -> tuple[dict[str, Any], dict[str, Any] | None, dict[str, Any] | None]:
    terminal_command = _terminal_command_facts(command_handoffs)
    failed_signal_events = [
        dict(event)
        for event in events
        if event.get("event_type") == "agent.runtime_signal.updated"
        and dict(event.get("payload") or {}).get("status") == "failed"
    ]
    failed_signal = (
        dict(failed_signal_events[-1].get("payload") or {})
        if failed_signal_events
        else {}
    )
    signal_id = str(failed_signal.get("signal_id") or "")
    causal_events = [
        dict(event)
        for event in events
        if event.get("event_type") == "runtime.budget_handoff_incomplete"
        and dict(event.get("payload") or {}).get("signal_id") == signal_id
        and _ERROR_CODE.fullmatch(
            str(dict(event.get("payload") or {}).get("error_code") or "")
        )
    ]
    observations = workspace.get("failure_observations")
    projected_observations = (
        [dict(item) for item in observations if isinstance(item, dict)]
        if isinstance(observations, list)
        else []
    )
    matching_observations = [
        observation
        for observation in projected_observations
        if observation.get("source_kind") == "runtime_signal"
        and observation.get("source_ref") == signal_id
        and observation.get("error_code") == failed_signal.get("error_message")
    ]
    cause_observation = matching_observations[0] if matching_observations else None
    if causal_events:
        event = causal_events[0]
        event_payload = dict(event.get("payload") or {})
        code = str(event_payload["error_code"])
        identity = f"event_cursor:{event['cursor']}"
        source_kind = "runtime_event"
        source_ref = signal_id
        source_version = f"cursor:{event['cursor']}"
    elif cause_observation is not None:
        code = str(cause_observation.get("error_code") or "")
        identity = str(cause_observation.get("failure_id") or "")
        source_kind = str(cause_observation.get("source_kind") or "")
        source_ref = str(cause_observation.get("source_ref") or "")
        source_version = str(cause_observation.get("source_version") or "")
    elif terminal_command is not None and terminal_command.get("error_code"):
        code = str(terminal_command["error_code"])
        identity = str(terminal_command["command_id"])
        source_kind = "runtime_command"
        source_ref = identity
        source_version = str(terminal_command["completed_at"])
    else:
        _fail(
            "formal_slot_failure_cause_unproven",
            "formal slot failure lacks a source-bound typed cause",
            identity=launch_id,
        )
    if _ERROR_CODE.fullmatch(code) is None or not all(
        (identity, source_kind, source_ref, source_version)
    ):
        _fail(
            "formal_slot_failure_cause_invalid",
            "formal slot failure cause is not a safe typed identity",
            identity="earliest_typed_cause",
        )
    cause = {
        "code": code,
        "identity": identity,
        "source_kind": source_kind,
        "source_ref": source_ref,
        "source_version": source_version,
        "effect_certainty": (
            "unproven"
            if cause_observation is None
            else cause_observation.get("effect_certainty")
        ),
        "recoverability": (
            "terminal"
            if cause_observation is None
            else cause_observation.get("recoverability")
        ),
        "retry_eligibility": (
            "terminal"
            if cause_observation is None
            else cause_observation.get("retry_eligibility")
        ),
    }
    if (
        set(cause) != _CAUSE_FIELDS
        or any(value is None for value in cause.values())
        or cause["effect_certainty"] not in _EFFECT_CERTAINTIES
        or cause["recoverability"] not in _RECOVERABILITIES
        or cause["retry_eligibility"] not in _RETRY_ELIGIBILITIES
    ):
        _fail(
            "formal_slot_failure_cause_invalid",
            "formal slot failure cause is incomplete",
            identity="earliest_typed_cause",
        )
    projected_observation = (
        None
        if cause_observation is None
        else {
            key: cause_observation.get(key)
            for key in _CAUSE_OBSERVATION_FIELDS
        }
    )
    return cause, projected_observation, terminal_command


def _load_handoff_envelopes(
    paths: Sequence[Path],
    *,
    receipts: Sequence[Mapping[str, Any]],
    evidence_root: Path,
) -> tuple[list[dict[str, Any]], list[dict[str, str]]]:
    envelopes: list[dict[str, Any]] = []
    descriptors: list[dict[str, str]] = []
    for path in paths:
        resolved = _real_source_path(
            path,
            identity="formal_slot_failure.handoff",
        )
        _safe_source_name(resolved, evidence_root=evidence_root)
        envelope, _ = _load_response_envelope(
            resolved,
            identity="formal_slot_failure.handoff",
            receipts=receipts,
        )
        envelopes.append(envelope)
        descriptors.append(_source_descriptor(resolved, evidence_root=evidence_root))
    return envelopes, descriptors


def _load_common_failure_sources(
    *, identity_path: Path | None, identity_value: Mapping[str, Any] | None,
    preflight_path: Path, sealed_at: str, schema_id: str,
) -> tuple[
    Path, Path, dict[str, Any], dict[str, Any], bool, dict[str, Any] | None,
    str | None, dict[str, Any], dict[str, Any], Path,
]:
    if not _is_aware_timestamp(sealed_at):
        _fail("formal_slot_failure_sealed_at_invalid",
              "formal slot failure requires an aware sealing timestamp",
              identity="sealed_at")
    preflight_path = _real_source_path(
        preflight_path, identity="formal_slot_failure.preflight")
    evidence_root = preflight_path.parent
    if preflight_path.name != ATTEMPT_PREFLIGHT_FILENAME:
        _fail("formal_slot_failure_preflight_invalid",
              "formal slot failure requires the canonical preflight source",
              identity="preflight")
    if (identity_path is None) == (identity_value is None):
        _fail("formal_slot_failure_identity_source_invalid",
              "formal slot failure requires exactly one identity source",
              identity="identity")
    if identity_path is not None:
        loaded_identity, _ = _load_canonical_object(
            _real_source_path(identity_path, identity="formal_slot_failure.identity"),
            identity="formal_slot_failure.identity")
    else:
        assert identity_value is not None
        loaded_identity = dict(identity_value)
    identity = _normalize_identity(loaded_identity)
    preflight = load_attempt_preflight_receipt(preflight_path)
    current = schema_id == FORMAL_SLOT_FAILURE_SCHEMA_ID
    start_claim = load_bound_attempt_start_claim(preflight_path)[1] if current else None
    start_digest = str(start_claim["claim_digest"]) if start_claim else None
    if preflight.get("identity_digest") != canonical_digest(identity):
        _fail("formal_slot_failure_identity_mismatch",
              "formal slot failure identity differs from preflight",
              identity="identity")
    slot, slot_claim = dict(preflight["slot"]), dict(preflight["slot_claim"])
    slot_claim_path = evidence_root / ATTEMPT_SLOT_CLAIM_FILENAME
    slot_claim_value, _ = _load_canonical_object(
        slot_claim_path, identity="formal_slot_failure.slot_claim")
    if slot_claim_value != slot_claim:
        _fail("formal_slot_failure_slot_claim_mismatch",
              "formal slot failure slot claim differs from preflight",
              identity="slot_claim")
    return (preflight_path, evidence_root, identity, preflight, current,
            start_claim, start_digest, slot, slot_claim, slot_claim_path)


def _load_micu_sources(
    *, evidence_root: Path, current: bool,
    start_claim: Mapping[str, Any] | None, ledger_before_path: Path | None,
    ledger_after_path: Path, require_unchanged: bool,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Path]]:
    if current:
        assert start_claim is not None
        before = dict(start_claim["micu_before"])
        before_key = "attempt_start_claim"
        before_path = evidence_root / ATTEMPT_START_CLAIM_FILENAME
    else:
        assert ledger_before_path is not None
        before_key = "ledger_before"
        before_path = _real_source_path(
            ledger_before_path, identity="formal_slot_failure.micu_before")
        before, _ = _load_canonical_object(
            before_path, identity="formal_slot_failure.micu_before")
    after_path = _real_source_path(
        ledger_after_path, identity="formal_slot_failure.micu_after")
    if after_path.parent != evidence_root or (
        require_unchanged and before_path == after_path
    ):
        _fail("formal_slot_failure_source_path_invalid",
              "formal slot failure sources must share one evidence root",
              identity="micu_ledger")
    after, _ = _load_canonical_object(
        after_path, identity="formal_slot_failure.micu_after")
    _validate_ledger_transition(before, after)
    if require_unchanged and before != after:
        _fail("formal_slot_failure_pre_ready_micu_changed",
              "pre-ready failure requires an unchanged cumulative MICU ledger",
              identity="micu_ledger")
    return before, after, {before_key: before_path, "ledger_after": after_path}


def _build_payload(
    *,
    identity_path: Path | None = None,
    identity_value: Mapping[str, Any] | None = None,
    preflight_path: Path,
    receipt_chain_path: Path,
    workspace_response_path: Path,
    event_response_path: Path,
    handoff_response_paths: Sequence[Path],
    ledger_after_path: Path,
    ledger_before_path: Path | None = None,
    sealed_at: str,
    schema_id: str = FORMAL_SLOT_FAILURE_SCHEMA_ID,
) -> dict[str, Any]:
    (preflight_path, evidence_root, identity, preflight, current, start_claim,
     start_digest, slot, slot_claim, slot_claim_path) = _load_common_failure_sources(
        identity_path=identity_path, identity_value=identity_value,
        preflight_path=preflight_path, sealed_at=sealed_at, schema_id=schema_id)
    startup_path = evidence_root / HOST_STARTUP_FILENAME
    startup_value, _ = _load_canonical_object(
        startup_path,
        identity="formal_slot_failure.host_startup",
    )
    startup = _validate_startup(
        startup_value, preflight=preflight,
        attempt_start_claim_digest=start_digest,
    )
    supervision_path = evidence_root / HOST_SUPERVISION_FILENAME
    supervision_value, _ = _load_canonical_object(
        supervision_path,
        identity="formal_slot_failure.host_supervision",
    )
    supervision = validate_supervised_host_receipt(
        supervision_value,
        launch_id=str(slot_claim["launch_id"]),
        attempt_kind=str(slot["attempt_kind"]),
        session_id=str(slot["session_id"]),
        root_ref=str(slot["root_ref"]),
        campaign_id=str(preflight["campaign_id"]),
        authority_policy_digest=str(slot["authority_policy_digest"]),
        attempt_start_claim_digest=start_digest,
    )
    if any(
        supervision.get(key) != expected
        for key, expected in {
            "preflight_receipt_digest": preflight.get("receipt_digest"),
            "host_startup_receipt_digest": startup.get("receipt_digest"),
            "process_epoch": startup.get("process_epoch"),
            "session_id": slot.get("session_id"),
            "campaign_id": preflight.get("campaign_id"),
        }.items()
    ):
        _fail(
            "formal_slot_failure_supervision_mismatch",
            "formal slot failure Host supervision identity drifted",
            identity="host_supervision",
        )

    receipt_chain_path = _real_source_path(
        receipt_chain_path,
        identity="formal_slot_failure.receipt_chain",
    )
    receipts, receipt_bytes = _load_receipt_chain(
        receipt_chain_path,
        allow_failure_responses=True,
    )
    session_id = str(slot["session_id"])
    validate_canonical_entry_receipts(
        receipts,
        session_id=session_id,
        workflow_ref=identity["workflow_ref"],
        code="formal_slot_failure_public_entry_invalid",
    )
    forbidden_fragments = {
        "scientific-attempt-commands",
        "scientific-attempt-admissions/finalize",
        "scientific-attempt-closures/finalize",
    }
    if any(
        any(fragment in str(receipt.get("route") or "") for fragment in forbidden_fragments)
        for receipt in receipts
    ):
        _fail(
            "formal_slot_failure_actor_boundary_invalid",
            "formal slot failure receipt chain contains a private conductor mutation",
            identity="receipt_chain",
        )

    workspace_response_path = _real_source_path(
        workspace_response_path,
        identity="formal_slot_failure.workspace",
    )
    event_response_path = _real_source_path(
        event_response_path,
        identity="formal_slot_failure.events",
    )
    workspace_envelope, _ = _load_response_envelope(
        workspace_response_path,
        identity="formal_slot_failure.workspace",
        receipts=receipts,
    )
    event_envelope, _ = _load_response_envelope(
        event_response_path,
        identity="formal_slot_failure.events",
        receipts=receipts,
    )
    workspace = workspace_envelope.get("response")
    events = _validate_events(event_envelope.get("response"), session_id=session_id)
    if (
        not isinstance(workspace, dict)
        or dict(workspace.get("session") or {}).get("session_id") != session_id
        or dict(workspace_envelope["receipt"]).get("route")
        != f"/v3/sessions/{session_id}/workspace"
        or not str(dict(event_envelope["receipt"]).get("route") or "").startswith(
            f"/v3/sessions/{session_id}/events?replay=1&after_cursor="
        )
    ):
        _fail(
            "formal_slot_failure_public_state_invalid",
            "formal slot failure final public state has the wrong identity",
            identity="workspace_or_events",
        )
    final_workspace_sequence = int(dict(workspace_envelope["receipt"])["sequence"])
    final_event_sequence = int(dict(event_envelope["receipt"])["sequence"])
    if any(
        receipt.get("method") == "GET"
        and receipt.get("route") == f"/v3/sessions/{session_id}/workspace"
        and int(receipt["sequence"]) > final_workspace_sequence
        for receipt in receipts
    ) or any(
        receipt.get("method") == "GET"
        and str(receipt.get("route") or "").startswith(
            f"/v3/sessions/{session_id}/events?replay=1&after_cursor="
        )
        and int(receipt["sequence"]) > final_event_sequence
        for receipt in receipts
    ):
        _fail(
            "formal_slot_failure_final_read_not_latest",
            "formal slot failure did not seal the final public reads",
            identity="workspace_or_events",
        )
    mutation_sequences = [
        int(receipt["sequence"])
        for receipt in receipts
        if receipt.get("method") in {"DELETE", "PATCH", "POST", "PUT"}
    ]
    if mutation_sequences and min(
        final_workspace_sequence,
        final_event_sequence,
    ) <= max(mutation_sequences):
        _fail(
            "formal_slot_failure_final_read_not_latest",
            "formal slot failure final reads precede a public state change",
            identity="workspace_or_events",
        )
    handoff_envelopes, handoff_descriptors = _load_handoff_envelopes(
        handoff_response_paths,
        receipts=receipts,
        evidence_root=evidence_root,
    )
    drains = validate_bounded_drain_receipts(
        receipts,
        session_id=session_id,
        code="formal_slot_failure_drain_request_invalid",
    )
    statuses = [
        receipt
        for receipt in receipts
        if receipt.get("method") == "GET"
        and re.fullmatch(
            rf"/v3/sessions/{re.escape(session_id)}/runtime/commands/[^/]+",
            str(receipt.get("route") or ""),
        )
    ]
    if bool(drains) != bool(handoff_envelopes):
        _fail(
            "formal_slot_failure_handoff_cardinality_invalid",
            "formal slot failure drains and sealed handoffs disagree",
            identity="handoffs",
        )
    command_handoffs: list[dict[str, Any]] = []
    if drains:
        command_handoffs, _, used = _validate_runtime_command_handoffs(
            records=receipts,
            drains=drains,
            statuses=statuses,
            handoff_envelopes=handoff_envelopes,
            events=events,
            session_id=session_id,
            final_sequence=min(final_workspace_sequence, final_event_sequence),
        )
        if used != {
            int(dict(envelope["receipt"])["sequence"])
            for envelope in handoff_envelopes
        }:
            _fail(
                "formal_slot_failure_handoff_cardinality_invalid",
                "formal slot failure contains unrelated handoff responses",
                identity="handoffs",
            )
    attempt_state = workspace.get("scientific_attempts")
    if not (
        isinstance(attempt_state, dict)
        and attempt_state.get("attempt_count") == 0
        and attempt_state.get("attempts") == []
    ):
        _fail(
            "formal_slot_failure_attempt_exists",
            "formal slot failure cannot replace a real scientific attempt bundle",
            identity="workspace.scientific_attempts",
        )
    cause, cause_observation, terminal_command = _derive_failure_facts(
        workspace=workspace,
        events=events,
        command_handoffs=command_handoffs,
        launch_id=str(slot_claim["launch_id"]),
    )
    before, after, ledger_paths = _load_micu_sources(
        evidence_root=evidence_root, current=current, start_claim=start_claim,
        ledger_before_path=ledger_before_path, ledger_after_path=ledger_after_path,
        require_unchanged=False)
    fixed_paths = {
        "preflight": preflight_path,
        "slot_claim": slot_claim_path,
        "host_startup": startup_path,
        "host_supervision": supervision_path,
        "receipt_chain": receipt_chain_path,
        "workspace": workspace_response_path,
        "events": event_response_path,
        **ledger_paths,
    }
    if any(path.parent != evidence_root for path in fixed_paths.values()):
        _fail(
            "formal_slot_failure_source_path_invalid",
            "formal slot failure sources must share one evidence root",
            identity="sources",
        )
    sources: dict[str, Any] = {
        key: _source_descriptor(path, evidence_root=evidence_root)
        for key, path in fixed_paths.items()
    }
    sources["handoffs"] = sorted(
        handoff_descriptors,
        key=lambda item: item["name"],
    )
    if schema_id not in {FORMAL_SLOT_FAILURE_SCHEMA_ID, *LEGACY_FORMAL_SLOT_FAILURE_SCHEMA_IDS}:
        _fail(
            "formal_slot_failure_schema_invalid",
            "formal slot failure schema is not supported",
            identity="schema_id",
        )
    payload = {
        "schema_id": schema_id,
        "sealed_at": sealed_at,
        "run_class": "formal_acceptance",
        "acceptance_eligible": False,
        "state_reusable": False,
        "identity": {**identity, "identity_digest": canonical_digest(identity)},
        "campaign_id": preflight["campaign_id"],
        "plan_digest": preflight["plan_digest"],
        "consumption_digest": preflight["consumption_digest"],
        "launch_id": slot_claim["launch_id"],
        "attempt_kind": slot["attempt_kind"],
        "slot_ordinal": slot["ordinal"],
        "session_id": session_id,
        "root_ref": slot["root_ref"],
        "authority_policy_digest": slot["authority_policy_digest"],
        "preflight_receipt_digest": preflight["receipt_digest"],
        "slot_claim_digest": slot_claim["claim_digest"],
        "host_startup_receipt_digest": startup["receipt_digest"],
        "host_supervision_receipt_digest": supervision["receipt_digest"],
        "public_api_receipt_chain_digest": _content_digest(receipt_bytes),
        "final_workspace_response_digest": workspace_envelope["envelope_digest"],
        "final_event_response_digest": event_envelope["envelope_digest"],
        "terminal_handoff_response_digests": [
            envelope["envelope_digest"]
            for envelope in sorted(
                handoff_envelopes,
                key=lambda item: int(dict(item["receipt"])["sequence"]),
            )
        ],
        "scientific_attempt_state": {
            "attempt_count": 0,
            "attempt_ids": [],
            "cutover_eligible": False,
        },
        "terminal_command": terminal_command,
        "earliest_typed_cause": cause,
        "cause_observation": cause_observation,
        "micu_ledger": {"before": before, "after": after},
        "sources": sources,
    }
    if schema_id != "aox_formal_slot_failure@1":
        payload["closure_mode"] = "public_host"
    if current:
        payload["attempt_start_claim_digest"] = start_digest
    return payload


def finalize_and_seal_formal_slot_failure(
    *,
    identity_path: Path,
    preflight_path: Path,
    receipt_chain_path: Path,
    workspace_response_path: Path,
    event_response_path: Path,
    handoff_response_paths: Sequence[Path],
    ledger_after_path: Path,
    sealed_at: str | None = None,
) -> tuple[Path, str]:
    preflight_path = _real_source_path(
        preflight_path,
        identity="formal_slot_failure.preflight",
    )
    destination = preflight_path.parent / FORMAL_SLOT_FAILURE_FILENAME
    payload = _build_payload(
        identity_path=identity_path,
        preflight_path=preflight_path,
        receipt_chain_path=receipt_chain_path,
        workspace_response_path=workspace_response_path,
        event_response_path=event_response_path,
        handoff_response_paths=handoff_response_paths,
        ledger_after_path=ledger_after_path,
        sealed_at=sealed_at or datetime.now(UTC).isoformat(),
    )
    failure_digest = canonical_digest(payload)
    _write_append_only_bytes(
        destination,
        canonical_json_bytes(
            {"payload": payload, "failure_digest": failure_digest}
        )
        + b"\n",
        error_code="formal_slot_failure_append_only",
        error_message="formal slot failure receipt already exists",
    )
    return destination, failure_digest


def _verify_payload_sources(
    payload: Mapping[str, Any],
    *,
    failure_path: Path,
) -> None:
    evidence_root = failure_path.parent
    sources = payload.get("sources")
    source_keys = (_CURRENT_SOURCE_KEYS if payload.get("schema_id") ==
                   FORMAL_SLOT_FAILURE_SCHEMA_ID else _SOURCE_KEYS)
    if not isinstance(sources, dict) or set(sources) != source_keys:
        _fail(
            "formal_slot_failure_source_binding_invalid",
            "formal slot failure source map is incomplete",
            identity="sources",
        )
    paths = {
        key: _source_path(sources, key, evidence_root=evidence_root)
        for key in source_keys - {"handoffs"}
    }
    raw_handoffs = sources.get("handoffs")
    if not isinstance(raw_handoffs, list):
        _fail(
            "formal_slot_failure_source_binding_invalid",
            "formal slot failure handoff sources are malformed",
            identity="sources.handoffs",
        )
    handoff_paths: list[Path] = []
    names: set[str] = set()
    for index, descriptor in enumerate(raw_handoffs):
        probe = {"handoff": descriptor}
        path = _source_path(
            probe,
            "handoff",
            evidence_root=evidence_root,
        )
        if path.name in names:
            _fail(
                "formal_slot_failure_source_binding_invalid",
                "formal slot failure handoff source is duplicated",
                identity=f"sources.handoffs[{index}]",
            )
        names.add(path.name)
        handoff_paths.append(path)
    identity = dict(payload.get("identity") or {})
    declared_identity_digest = identity.pop("identity_digest", None)
    if declared_identity_digest != canonical_digest(identity):
        _fail(
            "formal_slot_failure_identity_mismatch",
            "formal slot failure identity digest does not reproduce",
            identity="identity.identity_digest",
        )
    rebuilt = _build_payload(
        identity_value=identity,
        preflight_path=paths["preflight"],
        receipt_chain_path=paths["receipt_chain"],
        workspace_response_path=paths["workspace"],
        event_response_path=paths["events"],
        handoff_response_paths=handoff_paths,
        ledger_before_path=paths.get("ledger_before"),
        ledger_after_path=paths["ledger_after"],
        sealed_at=str(payload.get("sealed_at") or ""),
        schema_id=str(payload.get("schema_id") or ""),
    )
    if rebuilt != dict(payload):
        _fail(
            "formal_slot_failure_semantic_mismatch",
            "formal slot failure facts do not reproduce from sealed public sources",
            identity="payload",
        )


def _build_pre_ready_payload(
    *,
    identity_path: Path | None = None,
    identity_value: Mapping[str, Any] | None = None,
    preflight_path: Path,
    pre_ready_failure_path: Path,
    ledger_after_path: Path,
    ledger_before_path: Path | None = None,
    sealed_at: str,
    schema_id: str = FORMAL_SLOT_FAILURE_SCHEMA_ID,
) -> dict[str, Any]:
    (preflight_path, evidence_root, identity, preflight, current, start_claim,
     start_digest, slot, slot_claim, slot_claim_path) = _load_common_failure_sources(
        identity_path=identity_path, identity_value=identity_value,
        preflight_path=preflight_path, sealed_at=sealed_at, schema_id=schema_id)
    pre_ready_failure_path = _real_source_path(
        pre_ready_failure_path,
        identity="formal_slot_failure.host_pre_ready_failure",
    )
    if (
        pre_ready_failure_path.parent != evidence_root
        or pre_ready_failure_path.name != HOST_PRE_READY_FAILURE_FILENAME
    ):
        _fail(
            "formal_slot_failure_source_path_invalid",
            "pre-ready failure must use the canonical evidence source",
            identity="host_pre_ready_failure",
        )
    pre_ready_value, _ = _load_canonical_object(
        pre_ready_failure_path,
        identity="formal_slot_failure.host_pre_ready_failure",
    )
    pre_ready = validate_supervised_host_pre_ready_failure(
        pre_ready_value,
        preflight=preflight,
        attempt_start_claim_digest=start_digest,
    )
    for forbidden in (
        HOST_STARTUP_FILENAME,
        HOST_SUPERVISION_FILENAME,
        "aox-host-supervision-fatal.json",
        "aox-public-conductor-retirement-readiness.json",
        "public-api-receipts.jsonl",
        PUBLIC_CONDUCTOR_BUNDLE_FILENAME,
    ):
        if (evidence_root / forbidden).exists():
            _fail(
                "formal_slot_failure_pre_ready_source_conflict",
                "pre-ready failure cannot coexist with later Host or public evidence",
                identity=forbidden,
            )
    before, after, ledger_paths = _load_micu_sources(
        evidence_root=evidence_root, current=current, start_claim=start_claim,
        ledger_before_path=ledger_before_path, ledger_after_path=ledger_after_path,
        require_unchanged=True)
    source_paths = {
        "preflight": preflight_path, "slot_claim": slot_claim_path,
        "host_pre_ready_failure": pre_ready_failure_path, **ledger_paths,
    }
    sources = {
        key: _source_descriptor(path, evidence_root=evidence_root)
        for key, path in source_paths.items()
    }
    sandbox_failure_code = pre_ready.get("sandbox_preflight_failure_code")
    cause_code = str(sandbox_failure_code or pre_ready["failure_code"])
    payload = {
        "schema_id": schema_id,
        "closure_mode": "pre_child_ready",
        "sealed_at": sealed_at,
        "run_class": "formal_acceptance",
        "acceptance_eligible": False,
        "state_reusable": False,
        "identity": {**identity, "identity_digest": canonical_digest(identity)},
        "campaign_id": preflight["campaign_id"],
        "plan_digest": preflight["plan_digest"],
        "consumption_digest": preflight["consumption_digest"],
        "launch_id": slot_claim["launch_id"],
        "attempt_kind": slot["attempt_kind"],
        "slot_ordinal": slot["ordinal"],
        "session_id": slot["session_id"],
        "root_ref": slot["root_ref"],
        "authority_policy_digest": slot["authority_policy_digest"],
        "preflight_receipt_digest": preflight["receipt_digest"],
        "slot_claim_digest": slot_claim["claim_digest"],
        "host_pre_ready_failure_receipt_digest": pre_ready["receipt_digest"],
        "scientific_attempt_state": {
            "attempt_count": 0,
            "attempt_ids": [],
            "cutover_eligible": False,
        },
        "earliest_typed_cause": {
            "code": cause_code,
            "identity": f"sandbox_runtime.{cause_code}",
            "source_kind": "host_supervision",
            "source_ref": HOST_PRE_READY_FAILURE_FILENAME,
            "source_version": (HOST_PRE_READY_FAILURE_SCHEMA_ID if current else
                               "aox_supervised_host_pre_ready_failure@1"),
            "effect_certainty": "no_effect",
            "recoverability": "authorization_required",
            "retry_eligibility": "terminal",
        },
        "micu_ledger": {"before": before, "after": after},
        "sources": sources,
    }
    if current:
        payload["attempt_start_claim_digest"] = start_digest
    return payload


def finalize_and_seal_pre_ready_formal_slot_failure(
    *,
    identity_path: Path,
    preflight_path: Path,
    pre_ready_failure_path: Path,
    ledger_after_path: Path,
    sealed_at: str | None = None,
) -> tuple[Path, str]:
    preflight_path = _real_source_path(
        preflight_path,
        identity="formal_slot_failure.preflight",
    )
    destination = preflight_path.parent / FORMAL_SLOT_FAILURE_FILENAME
    payload = _build_pre_ready_payload(
        identity_path=identity_path,
        preflight_path=preflight_path,
        pre_ready_failure_path=pre_ready_failure_path,
        ledger_after_path=ledger_after_path,
        sealed_at=sealed_at or datetime.now(UTC).isoformat(),
    )
    failure_digest = canonical_digest(payload)
    _write_append_only_bytes(
        destination,
        canonical_json_bytes(
            {"payload": payload, "failure_digest": failure_digest}
        )
        + b"\n",
        error_code="formal_slot_failure_append_only",
        error_message="formal slot failure receipt already exists",
    )
    return destination, failure_digest


def _verify_pre_ready_payload_sources(
    payload: Mapping[str, Any],
    *,
    failure_path: Path,
) -> None:
    evidence_root = failure_path.parent
    sources = payload.get("sources")
    source_keys = (_CURRENT_PRE_READY_SOURCE_KEYS if payload.get("schema_id") ==
                   FORMAL_SLOT_FAILURE_SCHEMA_ID else _PRE_READY_SOURCE_KEYS)
    if not isinstance(sources, dict) or set(sources) != source_keys:
        _fail(
            "formal_slot_failure_source_binding_invalid",
            "pre-ready formal slot failure source map is incomplete",
            identity="sources",
        )
    paths = {
        key: _source_path(sources, key, evidence_root=evidence_root)
        for key in source_keys
    }
    identity = dict(payload.get("identity") or {})
    declared_identity_digest = identity.pop("identity_digest", None)
    if declared_identity_digest != canonical_digest(identity):
        _fail(
            "formal_slot_failure_identity_mismatch",
            "formal slot failure identity digest does not reproduce",
            identity="identity.identity_digest",
        )
    rebuilt = _build_pre_ready_payload(
        identity_value=identity,
        preflight_path=paths["preflight"],
        pre_ready_failure_path=paths["host_pre_ready_failure"],
        ledger_before_path=paths.get("ledger_before"),
        ledger_after_path=paths["ledger_after"],
        sealed_at=str(payload.get("sealed_at") or ""),
        schema_id=str(payload.get("schema_id") or ""),
    )
    if rebuilt != dict(payload):
        _fail(
            "formal_slot_failure_semantic_mismatch",
            "pre-ready formal slot failure does not reproduce from exact sources",
            identity="payload",
        )

def verify_formal_slot_failure(path: Path) -> FormalSlotFailureVerification:
    try:
        resolved = _real_source_path(
            path,
            identity="formal_slot_failure",
        )
        envelope, _ = _load_canonical_object(
            resolved,
            identity="formal_slot_failure",
        )
        if set(envelope) != {"payload", "failure_digest"}:
            _fail(
                "formal_slot_failure_envelope_invalid",
                "formal slot failure envelope is malformed",
                identity="formal_slot_failure",
            )
        payload = envelope.get("payload")
        if not isinstance(payload, dict):
            _fail(
                "formal_slot_failure_schema_invalid",
                "formal slot failure payload is not the current closed schema",
                identity="payload",
            )
        schema_id = payload.get("schema_id")
        current = schema_id == FORMAL_SLOT_FAILURE_SCHEMA_ID
        is_pre_ready = (
            schema_id in {FORMAL_SLOT_FAILURE_SCHEMA_ID, "aox_formal_slot_failure@2"}
            and payload.get("closure_mode") == "pre_child_ready"
        )
        if is_pre_ready:
            cause = payload.get("earliest_typed_cause")
            attempt_state = payload.get("scientific_attempt_state")
            if not all(
                (
                    set(payload) == (_PRE_READY_PAYLOAD_FIELDS if current else
                                     _V2_PRE_READY_PAYLOAD_FIELDS),
                    payload.get("run_class") == "formal_acceptance",
                    payload.get("acceptance_eligible") is False,
                    payload.get("state_reusable") is False,
                    _is_aware_timestamp(payload.get("sealed_at")),
                    payload.get("attempt_kind") in {"positive", "fault"},
                    type(payload.get("slot_ordinal")) is int,
                    payload.get("slot_ordinal") in {1, 2, 3},
                    all(
                        isinstance(payload.get(field), str)
                        and bool(payload.get(field))
                        for field in (
                            "campaign_id",
                            "launch_id",
                            "session_id",
                            "root_ref",
                        )
                    ),
                    all(
                        _DIGEST.fullmatch(str(payload.get(field) or ""))
                        is not None
                        for field in (
                            "plan_digest",
                            "consumption_digest",
                            "authority_policy_digest",
                            "preflight_receipt_digest",
                            "slot_claim_digest",
                            "host_pre_ready_failure_receipt_digest",
                        ) + (("attempt_start_claim_digest",) if current else ())
                    ),
                    isinstance(cause, dict) and set(cause) == _CAUSE_FIELDS,
                    isinstance(cause, dict)
                    and _ERROR_CODE.fullmatch(str(cause.get("code") or ""))
                    is not None,
                    isinstance(cause, dict)
                    and cause.get("effect_certainty") == "no_effect",
                    isinstance(cause, dict)
                    and cause.get("recoverability") == "authorization_required",
                    isinstance(cause, dict)
                    and cause.get("retry_eligibility") == "terminal",
                    isinstance(attempt_state, dict)
                    and attempt_state
                    == {
                        "attempt_count": 0,
                        "attempt_ids": [],
                        "cutover_eligible": False,
                    },
                    envelope.get("failure_digest") == canonical_digest(payload),
                )
            ):
                _fail(
                    "formal_slot_failure_semantics_invalid",
                    "pre-ready formal slot failure payload is not fail-closed",
                    identity="payload",
                )
            _verify_pre_ready_payload_sources(payload, failure_path=resolved)
            return FormalSlotFailureVerification(
                passed=True,
                failure_digest=str(envelope["failure_digest"]),
                campaign_id=str(payload["campaign_id"]),
                plan_digest=str(payload["plan_digest"]),
                launch_id=str(payload["launch_id"]),
                attempt_kind=str(payload["attempt_kind"]),
                slot_ordinal=int(payload["slot_ordinal"]),
            )
        is_legacy_public = (
            schema_id == "aox_formal_slot_failure@1"
            and set(payload) == _LEGACY_PAYLOAD_FIELDS
        ) or (
            schema_id == "aox_formal_slot_failure@2"
            and payload.get("closure_mode") == "public_host"
            and set(payload) == _V2_PUBLIC_HOST_PAYLOAD_FIELDS
        )
        is_current_public = (
            payload.get("schema_id") == FORMAL_SLOT_FAILURE_SCHEMA_ID
            and payload.get("closure_mode") == "public_host"
            and set(payload) == _PUBLIC_HOST_PAYLOAD_FIELDS
        )
        if not (is_legacy_public or is_current_public):
            _fail(
                "formal_slot_failure_schema_invalid",
                "formal slot failure payload is not a supported closed schema",
                identity="payload",
            )
        cause = payload.get("earliest_typed_cause")
        attempt_state = payload.get("scientific_attempt_state")
        terminal_command = payload.get("terminal_command")
        if not all(
            (
                is_legacy_public or is_current_public,
                payload.get("run_class") == "formal_acceptance",
                payload.get("acceptance_eligible") is False,
                payload.get("state_reusable") is False,
                _is_aware_timestamp(payload.get("sealed_at")),
                payload.get("attempt_kind") in {"positive", "fault"},
                all(
                    isinstance(payload.get(field), str)
                    and bool(payload.get(field))
                    for field in (
                        "campaign_id",
                        "launch_id",
                        "session_id",
                        "root_ref",
                    )
                ),
                isinstance(cause, dict) and set(cause) == _CAUSE_FIELDS,
                isinstance(cause, dict)
                and _ERROR_CODE.fullmatch(str(cause.get("code") or ""))
                is not None,
                isinstance(cause, dict)
                and all(
                    isinstance(cause.get(field), str)
                    and bool(cause.get(field))
                    for field in (
                        "identity",
                        "source_kind",
                        "source_ref",
                        "source_version",
                    )
                ),
                isinstance(cause, dict)
                and cause.get("effect_certainty") in _EFFECT_CERTAINTIES,
                isinstance(cause, dict)
                and cause.get("recoverability") in _RECOVERABILITIES,
                isinstance(cause, dict)
                and cause.get("retry_eligibility") in _RETRY_ELIGIBILITIES,
                payload.get("cause_observation") is None
                or (
                    isinstance(payload.get("cause_observation"), dict)
                    and set(payload["cause_observation"])
                    == _CAUSE_OBSERVATION_FIELDS
                ),
                isinstance(attempt_state, dict)
                and set(attempt_state) == _ATTEMPT_STATE_FIELDS,
                attempt_state
                == {
                    "attempt_count": 0,
                    "attempt_ids": [],
                    "cutover_eligible": False,
                },
                terminal_command is None
                or (
                    isinstance(terminal_command, dict)
                    and set(terminal_command) == _TERMINAL_COMMAND_FIELDS
                    and terminal_command.get("status")
                    in _TERMINAL_COMMAND_STATUSES
                ),
                type(payload.get("slot_ordinal")) is int,
                payload.get("slot_ordinal") in {1, 2, 3},
                all(
                    _DIGEST.fullmatch(str(payload.get(field) or ""))
                    for field in (
                        "plan_digest",
                        "consumption_digest",
                        "authority_policy_digest",
                        "preflight_receipt_digest",
                        "slot_claim_digest",
                        "host_startup_receipt_digest",
                        "host_supervision_receipt_digest",
                        "public_api_receipt_chain_digest",
                        "final_workspace_response_digest",
                        "final_event_response_digest",
                    )
                ),
                envelope.get("failure_digest") == canonical_digest(payload),
            )
        ):
            _fail(
                "formal_slot_failure_semantics_invalid",
                "formal slot failure payload is not fail-closed",
                identity="payload",
            )
        _verify_payload_sources(payload, failure_path=resolved)
        return FormalSlotFailureVerification(
            passed=True,
            failure_digest=str(envelope["failure_digest"]),
            campaign_id=str(payload["campaign_id"]),
            plan_digest=str(payload["plan_digest"]),
            launch_id=str(payload["launch_id"]),
            attempt_kind=str(payload["attempt_kind"]),
            slot_ordinal=int(payload["slot_ordinal"]),
        )
    except (
        CutoverEvidenceError,
        KeyError,
        OSError,
        TypeError,
        ValueError,
    ) as exc:
        code = (
            exc.code
            if isinstance(exc, CutoverEvidenceError)
            else "formal_slot_failure_unreadable"
        )
        identity = (
            str(exc.details.get("identity") or "formal_slot_failure")
            if isinstance(exc, CutoverEvidenceError)
            else "formal_slot_failure"
        )
        return FormalSlotFailureVerification(
            passed=False,
            failure_digest=None,
            campaign_id=None,
            plan_digest=None,
            launch_id=None,
            attempt_kind=None,
            slot_ordinal=None,
            issue=VerificationIssue(
                code=code,
                identity=identity,
                message="formal slot failure verification failed",
            ),
        )


def evaluate_formal_slot_failure(
    path: Path,
    *,
    decided_at: str | None = None,
) -> dict[str, Any]:
    verification = verify_formal_slot_failure(path)
    if not verification.passed:
        issue = verification.issue
        raise CutoverEvidenceError(
            "formal_slot_failure_verification_failed",
            "formal slot failure must verify before campaign reduction",
            details={
                "identity": "formal_slot_failure"
                if issue is None
                else issue.identity
            },
        )
    envelope, _ = _load_canonical_object(path, identity="formal_slot_failure")
    payload = dict(envelope["payload"])
    cause = dict(payload["earliest_typed_cause"])
    decision = {
        "schema_id": FORMAL_SLOT_FAILURE_DECISION_SCHEMA_ID,
        "decided_at": decided_at or datetime.now(UTC).isoformat(),
        "decision": "NO-GO",
        "campaign_id": payload["campaign_id"],
        "plan_digest": payload["plan_digest"],
        "slot_ordinal": payload["slot_ordinal"],
        "launch_id": payload["launch_id"],
        "attempt_kind": payload["attempt_kind"],
        "formal_slot_failure_digest": envelope["failure_digest"],
        "attempt_digests": [],
        "attempt_ids": [],
        "blocker": {
            "code": cause["code"],
            "identity": cause["identity"],
            "message": (
                "the consumed formal slot retired before a scientific attempt "
                "could produce an acceptance bundle"
            ),
        },
    }
    return {**decision, "decision_digest": canonical_digest(decision)}


def seal_formal_slot_failure_decision(
    decision: Mapping[str, Any],
    destination: Path,
) -> str:
    value = dict(decision)
    blocker = value.get("blocker")
    try:
        decided_at = datetime.fromisoformat(str(value.get("decided_at") or ""))
    except ValueError:
        decided_at = None
    if not all(
        (
            set(value) == _DECISION_FIELDS,
            value.get("schema_id")
            == FORMAL_SLOT_FAILURE_DECISION_SCHEMA_ID,
            value.get("decision") == "NO-GO",
            decided_at is not None and decided_at.tzinfo is not None,
            isinstance(value.get("campaign_id"), str)
            and bool(value.get("campaign_id")),
            _DIGEST.fullmatch(str(value.get("plan_digest") or ""))
            is not None,
            type(value.get("slot_ordinal")) is int,
            value.get("slot_ordinal") in {1, 2, 3},
            isinstance(value.get("launch_id"), str)
            and bool(value.get("launch_id")),
            value.get("attempt_kind") in {"positive", "fault"},
            _DIGEST.fullmatch(
                str(value.get("formal_slot_failure_digest") or "")
            )
            is not None,
            value.get("attempt_digests") == [],
            value.get("attempt_ids") == [],
            isinstance(blocker, dict)
            and set(blocker) == _DECISION_BLOCKER_FIELDS,
            isinstance(blocker, dict)
            and _ERROR_CODE.fullmatch(str(blocker.get("code") or ""))
            is not None,
            isinstance(blocker, dict)
            and isinstance(blocker.get("identity"), str)
            and bool(blocker.get("identity")),
            isinstance(blocker, dict)
            and isinstance(blocker.get("message"), str)
            and bool(blocker.get("message")),
        )
    ):
        _fail(
            "formal_slot_failure_decision_semantics_invalid",
            "formal slot failure decision is not the current closed NO-GO schema",
            identity="decision",
        )
    expected = canonical_digest(
        {key: item for key, item in value.items() if key != "decision_digest"}
    )
    if value.get("decision_digest") != expected:
        _fail(
            "formal_slot_failure_decision_digest_mismatch",
            "formal slot failure decision digest does not reproduce",
            identity="decision.decision_digest",
        )
    _write_append_only_bytes(
        destination,
        canonical_json_bytes(value) + b"\n",
        error_code="campaign_decision_append_only",
        error_message="campaign decision already exists and cannot be overwritten",
    )
    return expected


__all__ = [
    "FORMAL_SLOT_FAILURE_DECISION_SCHEMA_ID",
    "FORMAL_SLOT_FAILURE_FILENAME",
    "FORMAL_SLOT_FAILURE_SCHEMA_ID",
    "FormalSlotFailureVerification",
    "evaluate_formal_slot_failure",
    "finalize_and_seal_pre_ready_formal_slot_failure",
    "finalize_and_seal_formal_slot_failure",
    "seal_formal_slot_failure_decision",
    "verify_formal_slot_failure",
]
