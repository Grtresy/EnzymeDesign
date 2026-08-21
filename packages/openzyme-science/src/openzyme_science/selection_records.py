from __future__ import annotations

from dataclasses import dataclass

from .attempts import ScientificChainSelection


class ScientificAttemptRepositoryError(RuntimeError):
    """Stable Science state conflict base independent of a storage mechanism."""


class ScientificAttemptIdentityConflictError(ScientificAttemptRepositoryError):
    """An idempotency or canonical identity was reused for different facts."""


class ScientificAttemptVersionConflictError(ScientificAttemptRepositoryError):
    """A compare-and-swap update lost its expected state version."""


class ScientificSelectionIntegrityError(ScientificAttemptRepositoryError):
    """A selection head does not resolve to one canonical selection."""

    error_code = "scientific_selection_head_invalid"
    _REASONS = frozenset(
        {
            "selection_missing",
            "attempt_mismatch",
            "revision_mismatch",
        }
    )

    def __init__(self, reason_code: str) -> None:
        if reason_code not in self._REASONS:
            raise ValueError("unsupported scientific selection integrity reason")
        super().__init__("scientific selection head is invalid")
        self.reason_code = reason_code


@dataclass(frozen=True, slots=True)
class ScientificOccurrenceSnapshot:
    selection_id: str
    attempt_id: str
    operation_id: str
    sandbox_run_id: str
    occurrence_digest: str
    created_at: str

    def to_dict(self) -> dict[str, str]:
        return {
            "selection_id": self.selection_id,
            "attempt_id": self.attempt_id,
            "operation_id": self.operation_id,
            "sandbox_run_id": self.sandbox_run_id,
            "occurrence_digest": self.occurrence_digest,
            "created_at": self.created_at,
        }


@dataclass(frozen=True, slots=True)
class ScientificSelectionHead:
    attempt_id: str
    selection_id: str
    revision: int
    state_version: int
    updated_at: str


@dataclass(frozen=True, slots=True)
class ResolvedScientificSelectionHead:
    head: ScientificSelectionHead
    selection: ScientificChainSelection


__all__ = [
    "ResolvedScientificSelectionHead",
    "ScientificAttemptIdentityConflictError",
    "ScientificAttemptRepositoryError",
    "ScientificAttemptVersionConflictError",
    "ScientificOccurrenceSnapshot",
    "ScientificSelectionHead",
    "ScientificSelectionIntegrityError",
]
