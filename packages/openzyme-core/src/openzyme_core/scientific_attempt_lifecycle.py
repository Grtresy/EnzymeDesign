from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptClosure
from openzyme_domain import ScientificAttemptClosureRequest
from openzyme_domain import ScientificAttemptLifecyclePhase
from openzyme_domain import ScientificAttemptStatus

from .repositories import CoreRepositories


class ScientificAttemptLifecycleIntegrityError(RuntimeError):
    """Canonical attempt/request/closure records do not form one lifecycle."""

    error_code = "scientific_attempt_lifecycle_invalid"
    _REASONS = frozenset(
        {
            "closure_attempt_mismatch",
            "closure_record_status_conflict",
            "closure_request_attempt_mismatch",
            "closure_request_identity_mismatch",
            "closure_request_missing",
            "closure_request_record_status_conflict",
            "closure_selection_mismatch",
            "terminal_record_evidence_missing",
        }
    )

    def __init__(
        self,
        *,
        attempt_id: str,
        reason_code: str,
        closure_request_id: str | None = None,
        closure_id: str | None = None,
    ) -> None:
        if reason_code not in self._REASONS:
            raise ValueError("unsupported scientific attempt lifecycle reason")
        super().__init__("scientific attempt lifecycle records are inconsistent")
        self.reason_code = reason_code
        self.details: dict[str, Any] = {
            "attempt_id": attempt_id,
            "integrity_reason": reason_code,
            "mutation_applied": False,
        }
        if closure_request_id is not None:
            self.details["closure_request_id"] = closure_request_id
        if closure_id is not None:
            self.details["closure_id"] = closure_id


@dataclass(frozen=True, slots=True)
class ResolvedScientificAttemptLifecycle:
    """One derived lifecycle view over immutable canonical records."""

    attempt: ScientificAttempt
    phase: ScientificAttemptLifecyclePhase
    closure_request: ScientificAttemptClosureRequest | None = None
    closure: ScientificAttemptClosure | None = None

    @property
    def record_status(self) -> ScientificAttemptStatus:
        return self.attempt.status

    @property
    def effective_status(self) -> ScientificAttemptStatus:
        if self.phase is ScientificAttemptLifecyclePhase.CLOSED:
            return ScientificAttemptStatus.CLOSED
        if self.phase is ScientificAttemptLifecyclePhase.CLOSURE_REQUESTED:
            return ScientificAttemptStatus.CLOSING
        if self.phase is ScientificAttemptLifecyclePhase.BLOCKED:
            return ScientificAttemptStatus.BLOCKED
        return ScientificAttemptStatus.ACTIVE

    @property
    def projected_status(self) -> ScientificAttemptStatus:
        """Compatibility status for existing request-only @1 projections."""

        if self.phase is ScientificAttemptLifecyclePhase.CLOSED:
            return ScientificAttemptStatus.CLOSED
        return self.record_status

    @property
    def closure_requested(self) -> bool:
        return self.closure_request is not None

    @property
    def is_closed(self) -> bool:
        return self.phase is ScientificAttemptLifecyclePhase.CLOSED

    @property
    def accepts_scientific_mutation(self) -> bool:
        return self.phase.accepts_scientific_mutation

    @property
    def closure_request_id(self) -> str | None:
        if self.closure_request is None:
            return None
        return self.closure_request.closure_request_id

    @property
    def closure_id(self) -> str | None:
        if self.closure is None:
            return None
        return self.closure.closure_id


def resolve_scientific_attempt_lifecycle(
    *,
    attempt: ScientificAttempt,
    closure_request: ScientificAttemptClosureRequest | None,
    closure: ScientificAttemptClosure | None,
) -> ResolvedScientificAttemptLifecycle:
    request_id = (
        None if closure_request is None else closure_request.closure_request_id
    )
    closure_id = None if closure is None else closure.closure_id

    def invalid(reason_code: str) -> None:
        raise ScientificAttemptLifecycleIntegrityError(
            attempt_id=attempt.attempt_id,
            reason_code=reason_code,
            closure_request_id=request_id,
            closure_id=closure_id,
        )

    if closure_request is not None and closure_request.attempt_id != attempt.attempt_id:
        invalid("closure_request_attempt_mismatch")
    if closure is not None and closure.attempt_id != attempt.attempt_id:
        invalid("closure_attempt_mismatch")

    if closure is not None:
        if closure_request is None:
            invalid("closure_request_missing")
        assert closure_request is not None
        if closure.closure_request_id != closure_request.closure_request_id:
            invalid("closure_request_identity_mismatch")
        if closure.selection_id != closure_request.selection_id:
            invalid("closure_selection_mismatch")
        if attempt.status is ScientificAttemptStatus.BLOCKED:
            invalid("closure_record_status_conflict")
        return ResolvedScientificAttemptLifecycle(
            attempt=attempt,
            phase=ScientificAttemptLifecyclePhase.CLOSED,
            closure_request=closure_request,
            closure=closure,
        )

    if closure_request is not None:
        if attempt.status not in {
            ScientificAttemptStatus.ACTIVE,
            ScientificAttemptStatus.CLOSING,
        }:
            invalid("closure_request_record_status_conflict")
        return ResolvedScientificAttemptLifecycle(
            attempt=attempt,
            phase=ScientificAttemptLifecyclePhase.CLOSURE_REQUESTED,
            closure_request=closure_request,
        )

    if attempt.status is ScientificAttemptStatus.ACTIVE:
        phase = ScientificAttemptLifecyclePhase.OPEN
    elif attempt.status is ScientificAttemptStatus.BLOCKED:
        phase = ScientificAttemptLifecyclePhase.BLOCKED
    else:
        invalid("terminal_record_evidence_missing")
        raise AssertionError("unreachable")
    return ResolvedScientificAttemptLifecycle(
        attempt=attempt,
        phase=phase,
    )


@dataclass(frozen=True, slots=True)
class ScientificAttemptLifecycleResolver:
    repositories: CoreRepositories

    def resolve(
        self,
        attempt: ScientificAttempt,
    ) -> ResolvedScientificAttemptLifecycle:
        return resolve_scientific_attempt_lifecycle(
            attempt=attempt,
            closure_request=(
                self.repositories.scientific_attempt_closure_requests.get_by_attempt(
                    attempt.attempt_id
                )
            ),
            closure=self.repositories.scientific_attempt_closures.get_by_attempt(
                attempt.attempt_id
            ),
        )


__all__ = [
    "ResolvedScientificAttemptLifecycle",
    "ScientificAttemptLifecycleIntegrityError",
    "ScientificAttemptLifecycleResolver",
    "resolve_scientific_attempt_lifecycle",
]
