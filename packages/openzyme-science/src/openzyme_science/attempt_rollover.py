from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol

from openzyme_contracts import MutationScope
from openzyme_contracts import MutationScopeKind
from openzyme_contracts import MutationScopeState
from .attempts import ScientificAttempt
from .attempts import ScientificAttemptLifecyclePhase
from .attempts import ScientificAttemptScope

from .attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .attempt_lifecycle import ScientificAttemptClosureReader
from .attempt_lifecycle import ScientificAttemptClosureRequestReader
from .attempt_lifecycle import ScientificAttemptLifecycleResolver


class ScientificAttemptReader(Protocol):
    def list_by_session(self, session_id: str) -> list[ScientificAttempt]: ...


class MutationScopeReader(Protocol):
    def list_by_session(self, session_id: str) -> list[MutationScope]: ...


class ScientificAttemptRolloverRepositoryView(Protocol):
    scientific_attempts: ScientificAttemptReader
    scientific_attempt_closure_requests: ScientificAttemptClosureRequestReader
    scientific_attempt_closures: ScientificAttemptClosureReader
    mutation_scopes: MutationScopeReader


class ScientificAttemptScopeRolloverPhase(StrEnum):
    ROLLOVER_PENDING = "rollover_pending"
    POST_CLOSURE_SCOPE_OPEN = "post_closure_scope_open"


class ScientificAttemptScopeRolloverReason(StrEnum):
    ENVELOPE_INVALID = "envelope_invalid"
    ATTEMPT_MISSING = "attempt_missing"
    ATTEMPT_AMBIGUOUS = "attempt_ambiguous"
    ATTEMPT_BINDING_INVALID = "attempt_binding_invalid"
    ATTEMPT_SCOPE_MISSING = "attempt_scope_missing"
    ATTEMPT_SCOPE_IDENTITY_INVALID = "attempt_scope_identity_invalid"
    ATTEMPT_SCOPE_STATE_INVALID = "attempt_scope_state_invalid"
    LIFECYCLE_INVALID = "lifecycle_invalid"
    LIFECYCLE_SCOPE_MISMATCH = "lifecycle_scope_mismatch"
    POST_SCOPE_MISSING = "post_scope_missing"
    POST_SCOPE_PREMATURE = "post_scope_premature"
    POST_SCOPE_IDENTITY_INVALID = "post_scope_identity_invalid"
    SCOPE_TOPOLOGY_AMBIGUOUS = "scope_topology_ambiguous"


class ScientificAttemptScopeRolloverIntegrityError(RuntimeError):
    """Canonical lifecycle and mutation scopes do not form one legal rollover."""

    error_code = "scientific_attempt_scope_rollover_invalid"
    retryable = False

    def __init__(
        self,
        reason: ScientificAttemptScopeRolloverReason,
        *,
        scope_state: MutationScopeState | None = None,
        open_scope_count: int | None = None,
    ) -> None:
        super().__init__("scientific attempt terminal scope rollover is invalid")
        self.reason = reason
        self.details: dict[str, Any] = {
            "boundary": "scientific_attempt_scope_rollover",
            "disposition": "fail_closed",
            "scope_rollover_reason": reason.value,
            "mutation_applied": False,
        }
        if scope_state is not None:
            self.details["scope_state"] = scope_state.value
        if open_scope_count is not None:
            self.details["open_scope_count"] = open_scope_count


@dataclass(frozen=True, slots=True)
class ScientificAttemptScopeRolloverEnvelope:
    session_id: str
    envelope_id: str
    task_id: str
    lane_id: str
    campaign_id: str
    workflow_id: str
    scope: ScientificAttemptScope
    root_ref: str


@dataclass(frozen=True, slots=True)
class ScientificAttemptScopeRolloverProjection:
    phase: ScientificAttemptScopeRolloverPhase
    attempt_id: str
    attempt_scope_id: str
    attempt_scope_state: MutationScopeState
    post_scope_id: str | None
    open_scope_count: int

    def safe_details(self) -> dict[str, object]:
        return {
            "scope_rollover_phase": self.phase.value,
            "scope_state": self.attempt_scope_state.value,
            "open_scope_count": self.open_scope_count,
        }


def scientific_attempt_post_scope_id(attempt_id: str) -> str:
    return f"mutation_scope_post_{attempt_id}"


def scientific_attempt_post_scope_ref(attempt_id: str) -> str:
    return f"post-scientific-attempt:{attempt_id}"


@dataclass(frozen=True, slots=True)
class ScientificAttemptScopeRolloverProjector:
    repositories: ScientificAttemptRolloverRepositoryView

    def project(
        self,
        envelope: ScientificAttemptScopeRolloverEnvelope,
    ) -> ScientificAttemptScopeRolloverProjection:
        self._validate_envelope(envelope)
        attempt = self._resolve_attempt(envelope)
        scopes = tuple(
            self.repositories.mutation_scopes.list_by_session(envelope.session_id)
        )
        attempt_scope = self._require_attempt_scope(
            attempt=attempt,
            scopes=scopes,
        )
        open_scopes = tuple(
            scope for scope in scopes if scope.state is MutationScopeState.OPEN
        )
        active_scopes = tuple(
            scope
            for scope in scopes
            if scope.state
            in {
                MutationScopeState.OPEN,
                MutationScopeState.FREEZING,
                MutationScopeState.QUIESCENT,
            }
        )
        children = tuple(
            scope
            for scope in scopes
            if scope.parent_scope_id == attempt_scope.scope_id
        )
        try:
            lifecycle = ScientificAttemptLifecycleResolver(
                self.repositories
            ).resolve(attempt)
        except ScientificAttemptLifecycleIntegrityError as exc:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.LIFECYCLE_INVALID,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            ) from exc

        if (
            lifecycle.phase
            is ScientificAttemptLifecyclePhase.CLOSURE_REQUESTED
        ):
            return self._project_pending(
                attempt=attempt,
                attempt_scope=attempt_scope,
                open_scopes=open_scopes,
                active_scopes=active_scopes,
                children=children,
            )
        if lifecycle.phase is ScientificAttemptLifecyclePhase.CLOSED:
            return self._project_post_scope(
                attempt=attempt,
                attempt_scope=attempt_scope,
                scopes=scopes,
                open_scopes=open_scopes,
                active_scopes=active_scopes,
                children=children,
            )
        raise ScientificAttemptScopeRolloverIntegrityError(
            ScientificAttemptScopeRolloverReason.LIFECYCLE_SCOPE_MISMATCH,
            scope_state=attempt_scope.state,
            open_scope_count=len(open_scopes),
        )

    @staticmethod
    def _validate_envelope(
        envelope: ScientificAttemptScopeRolloverEnvelope,
    ) -> None:
        values = (
            envelope.session_id,
            envelope.envelope_id,
            envelope.task_id,
            envelope.lane_id,
            envelope.campaign_id,
            envelope.workflow_id,
            envelope.root_ref,
        )
        if (
            not isinstance(envelope.scope, ScientificAttemptScope)
            or any(not value.strip() for value in values)
        ):
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ENVELOPE_INVALID
            )

    def _resolve_attempt(
        self,
        envelope: ScientificAttemptScopeRolloverEnvelope,
    ) -> ScientificAttempt:
        matching_envelope = tuple(
            attempt
            for attempt in self.repositories.scientific_attempts.list_by_session(
                envelope.session_id
            )
            if attempt.envelope_id == envelope.envelope_id
        )
        if not matching_envelope:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ATTEMPT_MISSING
            )
        if len(matching_envelope) != 1:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ATTEMPT_AMBIGUOUS
            )
        attempt = matching_envelope[0]
        if (
            attempt.session_id != envelope.session_id
            or attempt.task_id != envelope.task_id
            or attempt.lane_id != envelope.lane_id
            or attempt.campaign_id != envelope.campaign_id
            or attempt.workflow_id != envelope.workflow_id
            or attempt.scope is not envelope.scope
            or attempt.root_ref != envelope.root_ref
        ):
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ATTEMPT_BINDING_INVALID
            )
        return attempt

    def _require_attempt_scope(
        self,
        *,
        attempt: ScientificAttempt,
        scopes: tuple[MutationScope, ...],
    ) -> MutationScope:
        matching = tuple(
            scope for scope in scopes if scope.scope_id == attempt.mutation_scope_id
        )
        if len(matching) != 1:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ATTEMPT_SCOPE_MISSING
            )
        scope = matching[0]
        if (
            scope.session_id != attempt.session_id
            or scope.scope_kind is not MutationScopeKind.ATTEMPT
            or scope.scope_id != f"mutation_scope_{attempt.attempt_id}"
            or scope.scope_ref != attempt.attempt_id
        ):
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ATTEMPT_SCOPE_IDENTITY_INVALID,
                scope_state=scope.state,
            )
        if scope.parent_scope_id is not None:
            parents = tuple(
                parent
                for parent in scopes
                if parent.scope_id == scope.parent_scope_id
            )
            if (
                len(parents) != 1
                or parents[0].session_id != attempt.session_id
                or parents[0].state is not MutationScopeState.SEALED
            ):
                raise ScientificAttemptScopeRolloverIntegrityError(
                    ScientificAttemptScopeRolloverReason
                    .ATTEMPT_SCOPE_IDENTITY_INVALID,
                    scope_state=scope.state,
                )
        return scope

    @staticmethod
    def _project_pending(
        *,
        attempt: ScientificAttempt,
        attempt_scope: MutationScope,
        open_scopes: tuple[MutationScope, ...],
        active_scopes: tuple[MutationScope, ...],
        children: tuple[MutationScope, ...],
    ) -> ScientificAttemptScopeRolloverProjection:
        if attempt_scope.state not in {
            MutationScopeState.FREEZING,
            MutationScopeState.QUIESCENT,
            MutationScopeState.SEALED,
        }:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.ATTEMPT_SCOPE_STATE_INVALID,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        if children:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.POST_SCOPE_PREMATURE,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        expected_active = (
            ()
            if attempt_scope.state is MutationScopeState.SEALED
            else (attempt_scope.scope_id,)
        )
        if (
            open_scopes
            or tuple(scope.scope_id for scope in active_scopes)
            != expected_active
        ):
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.SCOPE_TOPOLOGY_AMBIGUOUS,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        return ScientificAttemptScopeRolloverProjection(
            phase=ScientificAttemptScopeRolloverPhase.ROLLOVER_PENDING,
            attempt_id=attempt.attempt_id,
            attempt_scope_id=attempt_scope.scope_id,
            attempt_scope_state=attempt_scope.state,
            post_scope_id=None,
            open_scope_count=0,
        )

    @staticmethod
    def _project_post_scope(
        *,
        attempt: ScientificAttempt,
        attempt_scope: MutationScope,
        scopes: tuple[MutationScope, ...],
        open_scopes: tuple[MutationScope, ...],
        active_scopes: tuple[MutationScope, ...],
        children: tuple[MutationScope, ...],
    ) -> ScientificAttemptScopeRolloverProjection:
        if attempt_scope.state is not MutationScopeState.SEALED:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.LIFECYCLE_SCOPE_MISMATCH,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        if not children:
            expected_identity = tuple(
                scope
                for scope in scopes
                if scope.scope_id
                == scientific_attempt_post_scope_id(attempt.attempt_id)
                or scope.scope_ref
                == scientific_attempt_post_scope_ref(attempt.attempt_id)
            )
            if expected_identity:
                raise ScientificAttemptScopeRolloverIntegrityError(
                    ScientificAttemptScopeRolloverReason
                    .POST_SCOPE_IDENTITY_INVALID,
                    scope_state=attempt_scope.state,
                    open_scope_count=len(open_scopes),
                )
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.POST_SCOPE_MISSING,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        if len(children) != 1:
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.SCOPE_TOPOLOGY_AMBIGUOUS,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        post_scope = children[0]
        if (
            post_scope.scope_id
            != scientific_attempt_post_scope_id(attempt.attempt_id)
            or post_scope.scope_ref
            != scientific_attempt_post_scope_ref(attempt.attempt_id)
            or post_scope.session_id != attempt.session_id
            or post_scope.scope_kind is not MutationScopeKind.SESSION
            or post_scope.parent_scope_id != attempt_scope.scope_id
            or post_scope.state is not MutationScopeState.OPEN
        ):
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.POST_SCOPE_IDENTITY_INVALID,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        if (
            tuple(scope.scope_id for scope in open_scopes)
            != (post_scope.scope_id,)
            or tuple(scope.scope_id for scope in active_scopes)
            != (post_scope.scope_id,)
        ):
            raise ScientificAttemptScopeRolloverIntegrityError(
                ScientificAttemptScopeRolloverReason.SCOPE_TOPOLOGY_AMBIGUOUS,
                scope_state=attempt_scope.state,
                open_scope_count=len(open_scopes),
            )
        return ScientificAttemptScopeRolloverProjection(
            phase=(
                ScientificAttemptScopeRolloverPhase.POST_CLOSURE_SCOPE_OPEN
            ),
            attempt_id=attempt.attempt_id,
            attempt_scope_id=attempt_scope.scope_id,
            attempt_scope_state=attempt_scope.state,
            post_scope_id=post_scope.scope_id,
            open_scope_count=1,
        )


__all__ = [
    "ScientificAttemptScopeRolloverEnvelope",
    "ScientificAttemptScopeRolloverIntegrityError",
    "ScientificAttemptRolloverRepositoryView",
    "ScientificAttemptScopeRolloverPhase",
    "ScientificAttemptScopeRolloverProjection",
    "ScientificAttemptScopeRolloverProjector",
    "ScientificAttemptScopeRolloverReason",
    "scientific_attempt_post_scope_id",
    "scientific_attempt_post_scope_ref",
]
