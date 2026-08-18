from __future__ import annotations

import hashlib
import json
import traceback
from dataclasses import dataclass
from typing import Any

from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import PrivateDiagnosticRecord
from openzyme_domain import RetryEligibility
from openzyme_domain import likely_causes_for_error_code
from openzyme_domain import utc_now_iso

from .public_diagnostics import sanitize_public_diagnostic_payload
from .public_diagnostics import sanitize_public_diagnostic_text
from .public_diagnostics import safe_public_machine_identifier


@dataclass(frozen=True, slots=True)
class FailureDiagnosticPair:
    observation: FailureObservation
    private_record: PrivateDiagnosticRecord | None


class DiagnosticBoundaryError(RuntimeError):
    """Typed public boundary error that identifies its durable diagnostic pair."""

    def __init__(self, observation: FailureObservation) -> None:
        self.error_code = observation.error_code
        self.diagnostic_id = observation.diagnostic_id
        self.failure_id = observation.failure_id
        self.observation = observation
        super().__init__(
            f"{observation.error_code}: {observation.safe_summary} "
            f"diagnostic_id={observation.diagnostic_id}"
        )


def _canonical_digest(value: object) -> str:
    payload = json.dumps(
        value,
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(payload).hexdigest()


def _failure_identity(
    *,
    session_id: str,
    source_kind: str,
    source_ref: str,
    source_version: str,
    phase: str,
    error_code: str,
) -> str:
    digest = _canonical_digest(
        {
            "session_id": session_id,
            "source_kind": source_kind,
            "source_ref": source_ref,
            "source_version": source_version,
            "phase": phase,
            "error_code": error_code,
        }
    )
    return "failure_" + digest.removeprefix("sha256:")[:20]


def _diagnostic_identity(failure_id: str) -> str:
    return "diagnostic_" + _canonical_digest(
        {"failure_id": failure_id, "schema_version": "private_diagnostic_record@1"}
    ).removeprefix("sha256:")[:20]


def _exception_chain(error: BaseException) -> tuple[BaseException, ...]:
    chain: list[BaseException] = []
    seen: set[int] = set()
    current: BaseException | None = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        chain.append(current)
        if current.__cause__ is not None:
            current = current.__cause__
        elif current.__context__ is not None and not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
    return tuple(chain)


def _safe_cause_chain(error: BaseException | None) -> tuple[dict[str, str], ...]:
    if error is None:
        return ()
    return tuple(
        {
            "type": safe_public_machine_identifier(
                item.__class__.__name__, fallback="Exception"
            )
            or "Exception",
            "code": safe_public_machine_identifier(
                getattr(item, "error_code", None), fallback="unclassified_error"
            )
            or "unclassified_error",
            "message_digest": _canonical_digest(str(item)),
        }
        for item in _exception_chain(error)
    )


def _bounded_private_text(value: object | None) -> str | None:
    if value is None:
        return None
    encoded = str(value).encode("utf-8", errors="replace")
    if len(encoded) <= 65_536:
        return encoded.decode("utf-8", errors="replace")
    return encoded[:65_515].decode("utf-8", errors="ignore") + "[private-truncated]"


def build_private_diagnostic_record(
    *,
    diagnostic_id: str,
    failure_id: str,
    session_id: str,
    component: str,
    operation: str,
    phase: str,
    source_kind: str,
    source_ref: str,
    source_version: str,
    private_diagnostic: object,
    created_at: str,
    correlation_id: str | None = None,
) -> PrivateDiagnosticRecord:
    """Capture complete operator evidence without exposing it to public projections."""

    error = private_diagnostic if isinstance(private_diagnostic, BaseException) else None
    if error is not None:
        chain = _exception_chain(error)
        exception_type = error.__class__.__qualname__
        exception_message = str(error)
        traceback_text = "".join(
            traceback.format_exception(type(error), error, error.__traceback__)
        )
        diagnostic_context = getattr(error, "diagnostic_context", None)
        private_context = (
            dict(diagnostic_context)
            if isinstance(diagnostic_context, dict)
            else {}
        )
    else:
        chain = ()
        exception_type = type(private_diagnostic).__qualname__
        exception_message = str(private_diagnostic)
        traceback_text = ""
        private_context = (
            dict(private_diagnostic)
            if isinstance(private_diagnostic, dict)
            else {"value_repr": repr(private_diagnostic)}
        )
    return PrivateDiagnosticRecord.create(
        diagnostic_id=diagnostic_id,
        failure_id=failure_id,
        session_id=session_id,
        component=component,
        operation=operation,
        phase=phase,
        exception_type=exception_type,
        exception_message=exception_message,
        traceback_text=traceback_text,
        cause_chain=tuple(
            {
                "type": item.__class__.__qualname__,
                "module": item.__class__.__module__,
                "message": str(item),
                "error_code": getattr(item, "error_code", None),
            }
            for item in chain
        ),
        errno=getattr(error, "errno", None),
        return_code=getattr(error, "returncode", None),
        bounded_stdout=_bounded_private_text(getattr(error, "stdout", None)),
        bounded_stderr=_bounded_private_text(getattr(error, "stderr", None)),
        private_context=private_context,
        source_kind=source_kind,
        source_ref=source_ref,
        source_version=source_version,
        correlation_id=correlation_id,
        created_at=created_at,
    )


def record_failure_observation(
    repositories: Any,
    *,
    session_id: str,
    source_kind: str,
    source_ref: str,
    source_version: str,
    phase: str,
    failure_class: FailureClass,
    recoverability: FailureRecoverability,
    effect_certainty: ExternalEffectCertainty,
    retry_eligibility: RetryEligibility,
    actor_kind: FailureActorKind,
    error_code: str,
    safe_summary: str,
    task_id: str | None = None,
    lane_id: str | None = None,
    agent_id: str | None = None,
    safe_hint: str | None = None,
    facts: dict[str, Any] | None = None,
    evidence_refs: tuple[str, ...] = (),
    private_diagnostic: object | None = None,
    component: str | None = None,
    operation: str | None = None,
    identities: dict[str, str] | None = None,
    mutation_applied: bool = False,
    fallback_performed: bool = False,
    next_action: str | None = None,
    correlation_id: str | None = None,
) -> FailureObservation:
    """Build and, when available, persist one public-safe failure observation."""

    safe_error_code = safe_public_machine_identifier(
        error_code,
        fallback="runtime_error",
    )
    assert safe_error_code is not None
    safe_source_kind = safe_public_machine_identifier(
        source_kind,
        fallback="runtime",
    )
    assert safe_source_kind is not None
    safe_phase = safe_public_machine_identifier(phase, fallback="runtime")
    assert safe_phase is not None
    safe_component = safe_public_machine_identifier(
        component or safe_source_kind,
        fallback="runtime",
    )
    assert safe_component is not None
    safe_operation = safe_public_machine_identifier(
        operation or safe_phase,
        fallback="observe_failure",
    )
    assert safe_operation is not None
    safe_next_action = safe_public_machine_identifier(
        next_action
        or (
            "reconcile_exact_effect"
            if retry_eligibility is RetryEligibility.RECONCILE_REQUIRED
            else "inspect_diagnostic"
        ),
        fallback="inspect_diagnostic",
    )
    assert safe_next_action is not None
    observation_repository = getattr(repositories, "failure_observations", None)
    get_by_source = getattr(observation_repository, "get_by_source", None)
    if callable(get_by_source):
        existing = get_by_source(
            session_id=session_id,
            source_kind=safe_source_kind,
            source_ref=source_ref,
            source_version=source_version,
            phase=safe_phase,
            error_code=safe_error_code,
        )
        if existing is not None:
            return existing
    sanitized_facts = sanitize_public_diagnostic_payload(facts or {})
    if not isinstance(sanitized_facts, dict):
        sanitized_facts = {}
    sanitized_identities = sanitize_public_diagnostic_payload(identities or {})
    if not isinstance(sanitized_identities, dict) or any(
        not isinstance(key, str) or not isinstance(value, str)
        for key, value in sanitized_identities.items()
    ):
        sanitized_identities = {}
    safe_evidence_refs = tuple(
        sanitize_public_diagnostic_text(str(value))
        for value in evidence_refs
        if str(value).strip()
    )
    failure_id = _failure_identity(
            session_id=session_id,
            source_kind=safe_source_kind,
            source_ref=source_ref,
            source_version=source_version,
            phase=safe_phase,
            error_code=safe_error_code,
        )
    diagnostic_id = _diagnostic_identity(failure_id)
    created_at = utc_now_iso()
    private_record = (
        None
        if private_diagnostic is None
        else build_private_diagnostic_record(
            diagnostic_id=diagnostic_id,
            failure_id=failure_id,
            session_id=session_id,
            component=safe_component,
            operation=safe_operation,
            phase=safe_phase,
            source_kind=safe_source_kind,
            source_ref=source_ref,
            source_version=source_version,
            private_diagnostic=private_diagnostic,
            created_at=created_at,
            correlation_id=correlation_id,
        )
    )
    observation = FailureObservation(
        failure_id=failure_id,
        session_id=session_id,
        task_id=task_id,
        lane_id=lane_id,
        agent_id=agent_id,
        source_kind=safe_source_kind,
        source_ref=source_ref,
        source_version=source_version,
        phase=safe_phase,
        failure_class=failure_class,
        recoverability=recoverability,
        effect_certainty=effect_certainty,
        retry_eligibility=retry_eligibility,
        actor_kind=actor_kind,
        error_code=safe_error_code,
        safe_summary=sanitize_public_diagnostic_text(safe_summary),
        safe_hint=None
        if safe_hint is None
        else sanitize_public_diagnostic_text(safe_hint),
        facts=dict(sanitized_facts),
        likely_causes=likely_causes_for_error_code(safe_error_code),
        evidence_refs=safe_evidence_refs,
        private_diagnostic_digest=(
            None if private_record is None else private_record.record_digest
        ),
        component=safe_component,
        operation=safe_operation,
        identities=dict(sanitized_identities),
        mutation_applied=mutation_applied,
        fallback_performed=fallback_performed,
        cause_chain=_safe_cause_chain(
            private_diagnostic if isinstance(private_diagnostic, BaseException) else None
        ),
        diagnostic_id=diagnostic_id,
        next_action=safe_next_action,
        created_at=created_at,
    )
    add = getattr(observation_repository, "add", None)
    if callable(add):
        private_repository = getattr(repositories, "private_diagnostics", None)
        add_private = getattr(private_repository, "add", None)
        atomic = getattr(repositories, "atomic", None)
        if private_record is not None and callable(add_private) and callable(atomic):
            with atomic(prefix="failure_diagnostic_pair"):
                persisted = add(observation)
                add_private(private_record)
                return persisted
        if private_record is not None and callable(add_private):
            persisted = add(observation)
            add_private(private_record)
            return persisted
        return add(observation)
    return observation


__all__ = [
    "DiagnosticBoundaryError",
    "FailureDiagnosticPair",
    "build_private_diagnostic_record",
    "record_failure_observation",
]
