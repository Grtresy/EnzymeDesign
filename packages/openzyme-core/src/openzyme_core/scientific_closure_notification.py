from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptClosure
from openzyme_domain import ScientificAttemptClosureRequest
from openzyme_domain import ScientificAttemptClosureResponse
from openzyme_domain import ScientificAttemptLifecyclePhase
from openzyme_domain import Task

from .repositories import CoreRepositories
from .scientific_attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .scientific_attempt_lifecycle import ScientificAttemptLifecycleResolver
from .scientific_attempts import ScientificAttemptError
from .scientific_attempts import ScientificAttemptService


class ScientificClosureNotificationReason(StrEnum):
    SOURCE_MISSING = "source_missing"
    SIGNAL_NOT_CLAIMED = "signal_not_claimed"
    ATTEMPT_MISSING = "attempt_missing"
    CLOSURE_REQUEST_MISSING = "closure_request_missing"
    CONTROL_BINDING_INVALID = "control_binding_invalid"
    LIFECYCLE_INVALID = "lifecycle_invalid"
    TASK_MISSING = "task_missing"
    RESPONSE_INVALID = "response_invalid"


class ScientificClosureNotificationSettlementError(RuntimeError):
    error_code = "scientific_closure_notification_invalid"
    retryable = False

    def __init__(self, reason: ScientificClosureNotificationReason) -> None:
        super().__init__(
            "scientific closure notification bindings are inconsistent"
        )
        self.reason = reason
        self.details: dict[str, Any] = {
            "boundary": "scientific_closure_notification",
            "disposition": "fail_closed",
            "settlement_reason": reason.value,
            "mutation_applied": False,
        }


@dataclass(frozen=True, slots=True)
class ScientificClosureNotificationProof:
    signal: AgentRuntimeSignal
    task: Task
    attempt: ScientificAttempt
    closure_request: ScientificAttemptClosureRequest
    closure: ScientificAttemptClosure
    response: ScientificAttemptClosureResponse


@dataclass(frozen=True, slots=True)
class ScientificClosureNotificationVerifier:
    repositories: CoreRepositories

    def verify(
        self,
        signal: AgentRuntimeSignal,
    ) -> ScientificClosureNotificationProof | None:
        if signal.reason is not AgentRuntimeSignalReason.MANUAL_RESUME:
            return None
        source_ref = str(signal.source_ref or "").strip()
        if not source_ref:
            return None
        closure = self.repositories.scientific_attempt_closures.get(source_ref)
        if closure is None:
            if source_ref.startswith("attempt_closure_"):
                raise ScientificClosureNotificationSettlementError(
                    ScientificClosureNotificationReason.SOURCE_MISSING
                )
            return None
        if signal.status is not AgentRuntimeSignalStatus.CLAIMED:
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.SIGNAL_NOT_CLAIMED
            )
        attempt = self.repositories.scientific_attempts.get(closure.attempt_id)
        if attempt is None:
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.ATTEMPT_MISSING
            )
        request = self.repositories.scientific_attempt_closure_requests.get(
            closure.closure_request_id
        )
        if request is None:
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.CLOSURE_REQUEST_MISSING
            )
        if (
            signal.source_ref != closure.closure_id
            or signal.correlation_id != closure.closure_id
            or signal.session_id != attempt.session_id
            or signal.task_id != attempt.task_id
            or signal.lane_id != attempt.lane_id
            or signal.agent_id != request.actor_ref
            or closure.actor_ref != request.actor_ref
            or closure.attempt_id != request.attempt_id
            or closure.selection_id != request.selection_id
            or closure.closure_request_id != request.closure_request_id
        ):
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.CONTROL_BINDING_INVALID
            )
        try:
            lifecycle = ScientificAttemptLifecycleResolver(
                self.repositories
            ).resolve(attempt)
        except ScientificAttemptLifecycleIntegrityError as exc:
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.LIFECYCLE_INVALID
            ) from exc
        if (
            lifecycle.phase is not ScientificAttemptLifecyclePhase.CLOSED
            or lifecycle.closure != closure
            or lifecycle.closure_request != request
        ):
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.LIFECYCLE_INVALID
            )
        task = self.repositories.tasks.get(attempt.task_id)
        if task is None or task.session_id != attempt.session_id:
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.TASK_MISSING
            )
        try:
            response = ScientificAttemptService(
                self.repositories
            ).require_closure_response(request)
        except ScientificAttemptError as exc:
            raise ScientificClosureNotificationSettlementError(
                ScientificClosureNotificationReason.RESPONSE_INVALID
            ) from exc
        if not task.status.is_terminal:
            return None
        return ScientificClosureNotificationProof(
            signal=signal,
            task=task,
            attempt=attempt,
            closure_request=request,
            closure=closure,
            response=response,
        )


__all__ = [
    "ScientificClosureNotificationProof",
    "ScientificClosureNotificationReason",
    "ScientificClosureNotificationSettlementError",
    "ScientificClosureNotificationVerifier",
]
