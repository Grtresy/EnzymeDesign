from __future__ import annotations

import hashlib
import json
from typing import Any

from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import RetryEligibility
from openzyme_domain import likely_causes_for_error_code
from openzyme_domain import utc_now_iso

from .public_diagnostics import sanitize_public_diagnostic_payload
from .public_diagnostics import sanitize_public_diagnostic_text
from .public_diagnostics import safe_public_machine_identifier


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
    safe_evidence_refs = tuple(
        sanitize_public_diagnostic_text(str(value))
        for value in evidence_refs
        if str(value).strip()
    )
    observation = FailureObservation(
        failure_id=_failure_identity(
            session_id=session_id,
            source_kind=safe_source_kind,
            source_ref=source_ref,
            source_version=source_version,
            phase=safe_phase,
            error_code=safe_error_code,
        ),
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
        private_diagnostic_digest=None
        if private_diagnostic is None
        else _canonical_digest(private_diagnostic),
        created_at=utc_now_iso(),
    )
    add = getattr(observation_repository, "add", None)
    if callable(add):
        return add(observation)
    return observation


__all__ = ["record_failure_observation"]
