from __future__ import annotations

from typing import Any

from openzyme_core import canonical_digest
from openzyme_core import CommandIdempotencyConflictError
from openzyme_core import project_runtime_command
from openzyme_core import runtime_command_request_digest
from openzyme_core import scientific_attempt_authorization_identity
from openzyme_domain import RuntimeCommandType

from .aox_fault_injection import aox_fault_injection_request_digest
from .aox_fault_injection import observe_authority_bound_aox_reference_byte_flip


HOST_MUTATION_OBSERVATION_SCHEMA_ID = "host_mutation_operation_observation@1"
HOST_MUTATION_OBSERVATION_COMMAND_TYPES = frozenset(
    {
        "aox.reference-fault.inject",
        "approval.resolve",
        "conversation.message.post",
        "lane.claim",
        "lane.create",
        "lane.keep",
        "lane.remove",
        "runtime.drain",
        "scientific.authorization.grant",
        "session.create",
        "task.create",
        "task.update",
    }
)
HOST_MUTATION_ORIGINAL_STATUS_CODES = {
    command_type: (202 if command_type == "runtime.drain" else 200)
    for command_type in HOST_MUTATION_OBSERVATION_COMMAND_TYPES
}


def host_command_request_digest(
    *, command_type: str, scope_ref: str, request_payload: object
) -> str:
    return canonical_digest(
        {
            "command_type": command_type,
            "scope_ref": scope_ref,
            "request": request_payload,
        }
    )


def host_mutation_request_digest(
    *,
    principal_id: str,
    session_id: str,
    command_type: str,
    scope_ref: str,
    idempotency_key: str,
    request_payload: dict[str, Any],
) -> str:
    """Derive the request digest used by the existing durable owner."""

    if command_type == "runtime.drain":
        if set(request_payload) != {
            "max_signals",
            "max_steps_per_agent",
            "auto_enqueue_ready_tasks",
        }:
            raise ValueError("runtime.drain observation request is not exact")
        return runtime_command_request_digest(
            session_id=session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            max_signals=request_payload["max_signals"],
            max_steps_per_agent=request_payload["max_steps_per_agent"],
            auto_enqueue_ready_tasks=request_payload["auto_enqueue_ready_tasks"],
        )
    if command_type == "scientific.authorization.grant":
        _, request_digest, _ = scientific_attempt_authorization_identity(
            session_id=session_id,
            grantor_ref=principal_id,
            idempotency_key=idempotency_key,
            **request_payload,
        )
        return request_digest
    if command_type == "aox.reference-fault.inject":
        if set(request_payload) != {"attempt_id", "artifact_id"}:
            raise ValueError("AOX fault observation request is not exact")
        return aox_fault_injection_request_digest(
            session_id=session_id,
            attempt_id=str(request_payload["attempt_id"]),
            artifact_id=str(request_payload["artifact_id"]),
            idempotency_key=idempotency_key,
        )
    return host_command_request_digest(
        command_type=command_type,
        scope_ref=scope_ref,
        request_payload=request_payload,
    )


def observe_host_mutation_operation(
    service: Any,
    *,
    principal_id: str,
    session_id: str,
    command_type: str,
    scope_ref: str,
    idempotency_key: str,
    expected_request_digest: str,
    attempt_id: str | None = None,
    artifact_id: str | None = None,
) -> dict[str, Any]:
    """Read one existing durable mutation owner without replaying its effect."""

    normalized_key = idempotency_key.strip()
    if not normalized_key or len(normalized_key) > 256:
        raise ValueError("idempotency_key must contain 1 to 256 characters")
    if command_type not in HOST_MUTATION_OBSERVATION_COMMAND_TYPES:
        raise ValueError("command_type has no public durable observation owner")
    if not scope_ref or len(scope_ref) > 1_000:
        raise ValueError("scope_ref must contain 1 to 1000 characters")
    if not (
        len(expected_request_digest) == 71
        and expected_request_digest.startswith("sha256:")
        and all(character in "0123456789abcdef" for character in expected_request_digest[7:])
    ):
        raise ValueError("request_digest must be one sha256 digest")
    status = "unproven"
    response: dict[str, Any] | None = None
    request_digest: str | None = None

    if command_type == "runtime.drain":
        _require_no_fault_identity(attempt_id=attempt_id, artifact_id=artifact_id)
        record = service.repositories.runtime_commands.find_by_idempotency_key(
            session_id=session_id,
            command_type=RuntimeCommandType.RUNTIME_DRAIN,
            idempotency_key=normalized_key,
        )
        if record is not None:
            request_digest = record.request_digest
            _require_request_digest(request_digest, expected_request_digest)
            response = project_runtime_command(record)
            status = "terminal" if record.status.is_terminal else "in_progress"
    elif command_type == "scientific.authorization.grant":
        _require_no_fault_identity(attempt_id=attempt_id, artifact_id=artifact_id)
        record = (
            service.repositories.scientific_attempt_authorizations.get_by_idempotency(
                session_id=session_id,
                grantor_ref=principal_id,
                idempotency_key=normalized_key,
            )
        )
        if record is not None:
            request_digest = record.request_digest
            _require_request_digest(request_digest, expected_request_digest)
            response = {
                "session_id": session_id,
                "record": record.to_dict(),
                "scientific_attempts": service.scientific_attempt_control().project_session(
                    session_id
                ),
            }
            status = "terminal"
    elif command_type == "aox.reference-fault.inject":
        if not attempt_id or not artifact_id:
            raise ValueError(
                "AOX fault observation requires attempt_id and artifact_id"
            )
        request_digest = aox_fault_injection_request_digest(
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            idempotency_key=normalized_key,
        )
        _require_request_digest(request_digest, expected_request_digest)
        owner_status, response = observe_authority_bound_aox_reference_byte_flip(
            service.repositories,
            session_id=session_id,
            attempt_id=attempt_id,
            artifact_id=artifact_id,
            actor_ref=principal_id,
            idempotency_key=normalized_key,
        )
        status = {"terminal": "terminal", "claimed": "in_progress"}.get(
            owner_status, "unproven"
        )
    else:
        _require_no_fault_identity(attempt_id=attempt_id, artifact_id=artifact_id)
        receipt = service.repositories.command_receipts.find(
            scope_ref=scope_ref,
            command_type=command_type,
            idempotency_key=normalized_key,
        )
        if receipt is not None:
            if receipt.session_id != session_id:
                raise ValueError(
                    "durable Host mutation owner has a different session identity"
                )
            request_digest = receipt.request_digest
            _require_request_digest(request_digest, expected_request_digest)
            response = dict(receipt.response)
            status = "terminal"

    terminal = status == "terminal"
    return {
        "schema_id": HOST_MUTATION_OBSERVATION_SCHEMA_ID,
        "session_id": session_id,
        "command_type": command_type,
        "scope_ref": scope_ref,
        "idempotency_key": normalized_key,
        "request_digest": expected_request_digest,
        "status": status,
        "response": response,
        "effect_certainty": "terminal_known" if terminal else "unproven",
        "retry_eligibility": "terminal" if terminal else "reconcile_required",
        "reconciliation_required": not terminal,
        "terminal_scope": "host_mutation_occurrence",
        "query_read_only": True,
        "resume_applicable": False,
    }


def _require_request_digest(actual: str, expected: str) -> None:
    if actual != expected:
        raise CommandIdempotencyConflictError(
            "Host mutation operation has different request facts"
        )


def _require_no_fault_identity(
    *, attempt_id: str | None, artifact_id: str | None
) -> None:
    if attempt_id is not None or artifact_id is not None:
        raise ValueError(
            "attempt_id and artifact_id apply only to AOX fault observation"
        )


__all__ = [
    "HOST_MUTATION_OBSERVATION_COMMAND_TYPES",
    "HOST_MUTATION_ORIGINAL_STATUS_CODES",
    "HOST_MUTATION_OBSERVATION_SCHEMA_ID",
    "host_command_request_digest",
    "host_mutation_request_digest",
    "observe_host_mutation_operation",
]
