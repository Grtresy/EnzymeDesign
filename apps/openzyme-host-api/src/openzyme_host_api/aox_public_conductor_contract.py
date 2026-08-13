from __future__ import annotations

from collections.abc import Mapping, Sequence
import hashlib
from typing import Any

from .aox_cutover_evidence import CutoverEvidenceError


PUBLIC_CONDUCTOR_PROJECT_ID = "aox-blank-world-cutover"
PUBLIC_CONDUCTOR_OBJECTIVE = (
    "Run the canonical blank-world AOX/HMM product path and publish "
    "a source-linked scientific report."
)
PUBLIC_CONDUCTOR_TITLE = "AOX blank-world formal"
PUBLIC_CONDUCTOR_MESSAGE = (
    "Execute the pinned AOX/HMM workflow under the exact scientific-attempt "
    "authority. Use only public Host tools, resolve approvals explicitly, "
    "close the selected chain, and publish the source-linked report."
)

PUBLIC_DRAIN_MIN_SIGNALS = 1
PUBLIC_DRAIN_MAX_SIGNALS = 100
PUBLIC_DRAIN_MIN_STEPS = 1
PUBLIC_DRAIN_MAX_STEPS = 100


def _fail(code: str, message: str, *, identity: str) -> None:
    raise CutoverEvidenceError(code, message, details={"identity": identity})


def content_digest(content: bytes) -> str:
    return "sha256:" + hashlib.sha256(content).hexdigest()


def formal_mutation_idempotency_key(*parts: str) -> str:
    identity = "\x1f".join(parts).encode("utf-8")
    return "aox-formal-" + hashlib.sha256(identity).hexdigest()[:32]


def session_create_idempotency_key(session_id: str) -> str:
    return formal_mutation_idempotency_key("session-create", session_id)


def entry_message_idempotency_key(session_id: str, workflow_ref: str) -> str:
    return formal_mutation_idempotency_key(
        "entry-message",
        session_id,
        workflow_ref,
    )


def workflow_ref_from_preflight(preflight: Mapping[str, Any]) -> str:
    root_proof = preflight.get("root_proof")
    prerequisites = (
        root_proof.get("allowed_prerequisites")
        if isinstance(root_proof, Mapping)
        else None
    )
    workflow_ref = (
        prerequisites.get("workflow_ref")
        if isinstance(prerequisites, Mapping)
        else None
    )
    if not isinstance(workflow_ref, str) or not workflow_ref.startswith("workflow:"):
        _fail(
            "public_conductor_workflow_binding_invalid",
            "public conductor contract lacks one pinned workflow reference",
            identity="preflight.root_proof.allowed_prerequisites.workflow_ref",
        )
    return workflow_ref


def session_create_request(session_id: str) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "project_id": PUBLIC_CONDUCTOR_PROJECT_ID,
        "objective": PUBLIC_CONDUCTOR_OBJECTIVE,
        "title": PUBLIC_CONDUCTOR_TITLE,
    }


def entry_message_request(workflow_ref: str) -> dict[str, Any]:
    return {
        "message": PUBLIC_CONDUCTOR_MESSAGE,
        "skill_keys": [workflow_ref],
        "task_id": None,
        "lane_id": None,
    }


def entry_message_receipt_request(workflow_ref: str) -> dict[str, Any]:
    return {
        "message_digest": content_digest(PUBLIC_CONDUCTOR_MESSAGE.encode()),
        "skill_keys": [workflow_ref],
        "task_id": None,
        "lane_id": None,
    }


def runtime_drain_constraints() -> dict[str, Any]:
    return {
        "max_signals": {
            "minimum": PUBLIC_DRAIN_MIN_SIGNALS,
            "maximum": PUBLIC_DRAIN_MAX_SIGNALS,
        },
        "max_steps_per_agent": {
            "minimum": PUBLIC_DRAIN_MIN_STEPS,
            "maximum": PUBLIC_DRAIN_MAX_STEPS,
        },
        "auto_enqueue_ready_tasks": False,
    }


def validate_bounded_drain_request(
    request: object,
    *,
    code: str = "public_conductor_drain_request_invalid",
    identity: str = "runtime_drain",
) -> dict[str, Any]:
    value = dict(request) if isinstance(request, Mapping) else {}
    max_signals = value.get("max_signals")
    max_steps = value.get("max_steps_per_agent")
    valid = all(
        (
            set(value)
            == {
                "max_signals",
                "max_steps_per_agent",
                "auto_enqueue_ready_tasks",
            },
            type(max_signals) is int,
            type(max_steps) is int,
            type(max_signals) is int
            and PUBLIC_DRAIN_MIN_SIGNALS <= max_signals <= PUBLIC_DRAIN_MAX_SIGNALS,
            type(max_steps) is int
            and PUBLIC_DRAIN_MIN_STEPS <= max_steps <= PUBLIC_DRAIN_MAX_STEPS,
            value.get("auto_enqueue_ready_tasks") is False,
        )
    )
    if not valid:
        _fail(
            code,
            "formal runtime drain is not bounded or enables hidden task enqueue",
            identity=identity,
        )
    return value


def validate_bounded_drain_receipts(
    receipts: Sequence[Mapping[str, Any]],
    *,
    session_id: str,
    code: str = "public_conductor_drain_request_invalid",
) -> list[dict[str, Any]]:
    effective = effective_public_receipts(receipts)
    route = f"/v3/sessions/{session_id}/runtime/drain"
    drains = [
        dict(receipt)
        for receipt in effective
        if receipt.get("method") == "POST" and receipt.get("route") == route
    ]
    for receipt in drains:
        validate_bounded_drain_request(
            receipt.get("request"),
            code=code,
            identity=f"receipt_chain[{receipt.get('sequence')}]",
        )
    return drains


def effective_public_receipts(
    receipts: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Hide only an unproven mutation superseded by its exact terminal receipt."""

    records = [dict(receipt) for receipt in receipts]
    groups: dict[str, list[dict[str, Any]]] = {}
    for receipt in records:
        identity = receipt.get("request_identity_digest")
        if receipt.get("method") in {"POST", "PATCH"} and isinstance(identity, str):
            groups.setdefault(identity, []).append(receipt)
    superseded_sequences: set[int] = set()
    for identity, group in groups.items():
        terminals = [
            receipt
            for receipt in group
            if receipt.get("effect_certainty") == "terminal_known"
            and receipt.get("retry_eligibility") == "terminal"
            and receipt.get("reconciliation_required") is False
            and receipt.get("terminal_scope") == "host_mutation_occurrence"
        ]
        if len(terminals) > 1:
            _fail(
                "public_conductor_mutation_reconciliation_chain_invalid",
                "one mutation identity has multiple terminal receipt facts",
                identity=f"request_identity:{identity}",
            )
        if len(group) == 1 or not terminals:
            continue
        terminal = terminals[0]
        earlier = [
            receipt
            for receipt in group
            if int(receipt["sequence"]) < int(terminal["sequence"])
        ]
        exact_chain = all(
            (
                len(group) == 2,
                len(earlier) == 1,
                int(earlier[0]["sequence"]) + 1 == int(terminal["sequence"]),
                earlier[0].get("effect_certainty") == "unproven",
                earlier[0].get("retry_eligibility") == "reconcile_required",
                earlier[0].get("reconciliation_required") is True,
                earlier[0].get("terminal_scope") == "host_mutation_occurrence",
                earlier[0].get("method") == terminal.get("method"),
                earlier[0].get("route") == terminal.get("route"),
                earlier[0].get("request") == terminal.get("request"),
                earlier[0].get("request_digest") == terminal.get("request_digest"),
                earlier[0].get("idempotency_key")
                == terminal.get("idempotency_key"),
            )
        )
        if not exact_chain:
            _fail(
                "public_conductor_mutation_reconciliation_chain_invalid",
                "mutation reconciliation is not one adjacent exact convergence chain",
                identity=f"request_identity:{identity}",
            )
        superseded_sequences.add(int(earlier[0]["sequence"]))
    return [
        receipt
        for receipt in records
        if int(receipt["sequence"]) not in superseded_sequences
    ]


def public_receipt_occurrence_sequence(
    receipt: Mapping[str, Any],
    *,
    receipts: Sequence[Mapping[str, Any]],
) -> int:
    identity = receipt.get("request_identity_digest")
    if receipt.get("method") not in {"POST", "PATCH"} or not isinstance(
        identity, str
    ):
        return int(receipt["sequence"])
    return min(
        int(candidate["sequence"])
        for candidate in receipts
        if candidate.get("request_identity_digest") == identity
    )


def validate_canonical_entry_receipts(
    receipts: Sequence[Mapping[str, Any]],
    *,
    session_id: str,
    workflow_ref: str,
    code: str = "public_conductor_public_entry_invalid",
) -> tuple[dict[str, Any], dict[str, Any]]:
    effective = effective_public_receipts(receipts)
    session_receipts = [
        dict(receipt)
        for receipt in effective
        if receipt.get("method") == "POST" and receipt.get("route") == "/v3/sessions"
    ]
    message_route = f"/v3/sessions/{session_id}/messages"
    message_receipts = [
        dict(receipt)
        for receipt in effective
        if receipt.get("method") == "POST" and receipt.get("route") == message_route
    ]
    ordered = sorted(
        effective,
        key=lambda receipt: public_receipt_occurrence_sequence(
            receipt,
            receipts=receipts,
        ),
    )
    valid = all(
        (
            len(session_receipts) == 1,
            len(message_receipts) == 1,
            len(ordered) >= 2,
            len(session_receipts) == 1 and ordered[0] == session_receipts[0],
            len(message_receipts) == 1 and ordered[1] == message_receipts[0],
            len(session_receipts) == 1
            and session_receipts[0].get("request")
            == session_create_request(session_id),
            len(message_receipts) == 1
            and message_receipts[0].get("request")
            == entry_message_receipt_request(workflow_ref),
            len(session_receipts) == 1
            and type(session_receipts[0].get("status_code")) is int
            and 200 <= session_receipts[0]["status_code"] < 300,
            len(message_receipts) == 1
            and type(message_receipts[0].get("status_code")) is int
            and 200 <= message_receipts[0]["status_code"] < 300,
            len(session_receipts) == 1
            and (
                session_receipts[0].get("schema_id") == "openzyme_public_api_receipt@2"
                or session_receipts[0].get("idempotency_key")
                == session_create_idempotency_key(session_id)
            ),
            len(message_receipts) == 1
            and (
                message_receipts[0].get("schema_id") == "openzyme_public_api_receipt@2"
                or message_receipts[0].get("idempotency_key")
                == entry_message_idempotency_key(session_id, workflow_ref)
            ),
        )
    )
    if not valid:
        _fail(
            code,
            "formal public chain lacks one successful canonical session entry",
            identity="receipt_chain",
        )
    return session_receipts[0], message_receipts[0]


__all__ = [
    "PUBLIC_CONDUCTOR_MESSAGE",
    "PUBLIC_CONDUCTOR_OBJECTIVE",
    "PUBLIC_CONDUCTOR_PROJECT_ID",
    "PUBLIC_CONDUCTOR_TITLE",
    "PUBLIC_DRAIN_MAX_SIGNALS",
    "PUBLIC_DRAIN_MAX_STEPS",
    "PUBLIC_DRAIN_MIN_SIGNALS",
    "PUBLIC_DRAIN_MIN_STEPS",
    "content_digest",
    "entry_message_idempotency_key",
    "entry_message_receipt_request",
    "entry_message_request",
    "effective_public_receipts",
    "formal_mutation_idempotency_key",
    "public_receipt_occurrence_sequence",
    "runtime_drain_constraints",
    "session_create_request",
    "session_create_idempotency_key",
    "validate_bounded_drain_receipts",
    "validate_bounded_drain_request",
    "validate_canonical_entry_receipts",
    "workflow_ref_from_preflight",
]
