from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from contextlib import nullcontext
from contextvars import copy_context
from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from datetime import timedelta
import hashlib
import json
import re
import threading
import time
from typing import Any
from typing import Protocol
from uuid import uuid4

from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType
from openzyme_domain import MutationWriterKind
from openzyme_domain.control_plane import utc_now_iso
from openzyme_runtime import sanitize_public_diagnostic_text

from .durable_coordination_repositories import MutationWriteAuthorityRejectedError
from .reliability_repositories import OptimisticStateConflictError
from .reliability_repositories import is_transient_sqlite_contention
from .repositories import CoreRepositories
from .repositories import DurableEventRecord
from .runtime_command_projection import sanitize_runtime_command_outcome
from .runtime_drain_receipts import (
    RUNTIME_COMMAND_OUTCOME_LEGACY_SCHEMA_VERSION,
)
from .runtime_drain_receipts import RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION
from .runtime_drain_receipts import runtime_command_pre_core_failure_summary
from .runtime_drain_receipts import validate_runtime_command_outcome_v2


RUNTIME_COMMAND_OUTCOME_MAX_BYTES = 32 * 1024
_SAFE_ERROR_CODE = re.compile(r"[a-z][a-z0-9_.-]{0,127}")
_HEARTBEAT_RETRY_DELAYS = (0.05, 0.1, 0.25)


@dataclass(frozen=True, slots=True)
class RuntimeCommandExecutionResult:
    status: RuntimeCommandStatus
    bounded_outcome_summary: dict[str, Any]
    error_code: str | None = None
    safe_error_summary: str | None = None
    safe_retry_hint: str | None = None


class RuntimeCommandExecutor(Protocol):
    def __call__(
        self,
        command: RuntimeCommandRecord,
    ) -> RuntimeCommandExecutionResult: ...


@dataclass(frozen=True, slots=True)
class RuntimeCommandWorkerOutcome:
    command_id: str | None
    action: str
    semantic_progress: bool
    status: str | None
    state_version: int | None


RuntimeCommandRepositoryScopeFactory = Callable[
    [], AbstractContextManager[CoreRepositories]
]
MutationWriterScopeFactory = Callable[..., AbstractContextManager[object]]


def runtime_command_request_digest(
    *,
    session_id: str,
    command_type: RuntimeCommandType,
    max_signals: int,
    max_steps_per_agent: int,
    auto_enqueue_ready_tasks: bool,
) -> str:
    payload = {
        "schema_version": "runtime_command_request@1",
        "session_id": session_id,
        "command_type": command_type.value,
        "max_signals": max_signals,
        "max_steps_per_agent": max_steps_per_agent,
        "auto_enqueue_ready_tasks": auto_enqueue_ready_tasks,
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(slots=True)
class RuntimeCommandWorker:
    """Advance one durable runtime command without holding a DB transaction.

    A reclaimed expired claim is failed closed instead of rerunning the scheduler:
    the previous worker may already have advanced one or more fenced signals.  Only
    an accepted, never-claimed command may begin a scheduler batch.
    """

    repository_scope_factory: RuntimeCommandRepositoryScopeFactory
    executor: RuntimeCommandExecutor
    worker_id: str
    lease_seconds: int = 30
    clock: Callable[[], str] = utc_now_iso
    mutation_writer_scope_factory: MutationWriterScopeFactory | None = None
    post_writer_finalizer: Callable[[str], None] | None = None

    def __post_init__(self) -> None:
        if not self.worker_id or self.worker_id != self.worker_id.strip():
            raise ValueError("runtime command worker_id is invalid")
        if self.lease_seconds <= 0 or self.lease_seconds > 3_600:
            raise ValueError("runtime command lease_seconds is invalid")

    def run_once(self) -> RuntimeCommandWorkerOutcome:
        now = self.clock()
        try:
            with self.repository_scope_factory() as repositories:
                candidates = repositories.runtime_commands.list_claimable(
                    now_iso=now,
                    limit=1,
                )
                if not candidates:
                    return self._idle_outcome()
                candidate = candidates[0]
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome()
            raise
        writer_scope = (
            nullcontext(None)
            if self.mutation_writer_scope_factory is None
            else self.mutation_writer_scope_factory(
                session_id=candidate.session_id,
                owner_kind=MutationWriterKind.RUNTIME_COMMAND,
                owner_ref=f"runtime-command:{candidate.command_id}",
            )
        )
        with writer_scope as initial_writer_authority:
            outcome = self._run_candidate(
                candidate,
                now_iso=now,
                late_settlement_writer_required=(
                    self.mutation_writer_scope_factory is not None
                    and initial_writer_authority is None
                ),
            )
        if self.post_writer_finalizer is not None:
            self.post_writer_finalizer(candidate.session_id)
        return outcome

    def _run_candidate(
        self,
        candidate: RuntimeCommandRecord,
        *,
        now_iso: str,
        late_settlement_writer_required: bool = False,
    ) -> RuntimeCommandWorkerOutcome:
        try:
            with self.repository_scope_factory() as repositories:
                claimed = repositories.runtime_commands.claim(
                    candidate.command_id,
                    expected_state_version=candidate.state_version,
                    claim_owner=self.worker_id,
                    lease_token=f"runtime-command-lease:{uuid4().hex}",
                    lease_expires_at=self._after_iso(now_iso, self.lease_seconds),
                    now_iso=now_iso,
                    started_at=now_iso,
                )
        except OptimisticStateConflictError:
            return RuntimeCommandWorkerOutcome(
                command_id=None,
                action="claim_raced",
                semantic_progress=False,
                status=None,
                state_version=None,
            )
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome()
            raise

        if candidate.status is RuntimeCommandStatus.CLAIMED:
            return self._finish_recovered_expired_claim(
                claimed,
                late_settlement_writer_required=late_settlement_writer_required,
            )

        try:
            result, captured = self._call_executor_with_heartbeat(
                claimed,
                late_writer_required=late_settlement_writer_required,
            )
        except OptimisticStateConflictError:
            return RuntimeCommandWorkerOutcome(
                command_id=claimed.command_id,
                action="claim_fenced",
                semantic_progress=False,
                status=RuntimeCommandStatus.CLAIMED.value,
                state_version=claimed.state_version,
            )
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome(claimed.command_id)
            failure = RuntimeCommandExecutionResult(
                status=RuntimeCommandStatus.FAILED,
                bounded_outcome_summary=(
                    runtime_command_pre_core_failure_summary()
                ),
                error_code="runtime_command_execution_failed",
                safe_error_summary=sanitize_public_diagnostic_text(str(exc)),
                safe_retry_hint=(
                    "Inspect the command status and submit a new command only "
                    "after the failure is understood."
                ),
            )
            try:
                return self._finish_with_settlement_writer(
                    claimed,
                    self._validated_result(failure),
                    late_settlement_writer_required=(
                        late_settlement_writer_required
                    ),
                )
            except OptimisticStateConflictError:
                return RuntimeCommandWorkerOutcome(
                    command_id=claimed.command_id,
                    action="failure_commit_fenced",
                    semantic_progress=False,
                    status=RuntimeCommandStatus.CLAIMED.value,
                    state_version=claimed.state_version,
                )
        try:
            return self._finish_with_settlement_writer(
                captured,
                self._validated_result(result),
                late_settlement_writer_required=late_settlement_writer_required,
            )
        except OptimisticStateConflictError:
            return RuntimeCommandWorkerOutcome(
                command_id=claimed.command_id,
                action="claim_fenced",
                semantic_progress=False,
                status=RuntimeCommandStatus.CLAIMED.value,
                state_version=claimed.state_version,
            )
        except Exception as exc:
            if is_transient_sqlite_contention(exc):
                return self._database_busy_outcome(claimed.command_id)
            raise

    def _finish_recovered_expired_claim(
        self,
        claimed: RuntimeCommandRecord,
        *,
        late_settlement_writer_required: bool = False,
    ) -> RuntimeCommandWorkerOutcome:
        result = RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.FAILED,
            bounded_outcome_summary=runtime_command_pre_core_failure_summary(
                recovery_required=True
            ),
            error_code="runtime_command_claim_expired",
            safe_error_summary=(
                "The previous command worker expired before recording a bounded "
                "outcome; the scheduler batch was not replayed."
            ),
            safe_retry_hint=(
                "Inspect current session facts before submitting a new drain command."
            ),
        )
        return self._finish_with_settlement_writer(
            claimed,
            result,
            action="recovered_without_replay",
            late_settlement_writer_required=late_settlement_writer_required,
        )

    def _finish_with_settlement_writer(
        self,
        claimed: RuntimeCommandRecord,
        result: RuntimeCommandExecutionResult,
        *,
        action: str | None = None,
        late_settlement_writer_required: bool,
    ) -> RuntimeCommandWorkerOutcome:
        """Settle a command under an authority that exists after execution.

        A command can begin before any mutation scope exists and create the
        session's first scientific-attempt scope during its scheduler batch.
        The pre-execution writer admission then correctly yields no authority,
        but the terminal command row and its public event are covered writes by
        the time the batch returns.  Acquire one exact, source-bound writer for
        that terminal settlement instead of leaving a completed batch claimed.
        """

        if (
            not late_settlement_writer_required
            or self.mutation_writer_scope_factory is None
        ):
            return self._finish(claimed, result, action=action)
        with self.mutation_writer_scope_factory(
            session_id=claimed.session_id,
            owner_kind=MutationWriterKind.RUNTIME_COMMAND,
            owner_ref=f"runtime-command:{claimed.command_id}:terminal-settlement",
        ):
            return self._finish(claimed, result, action=action)

    def _finish(
        self,
        claimed: RuntimeCommandRecord,
        result: RuntimeCommandExecutionResult,
        *,
        action: str | None = None,
    ) -> RuntimeCommandWorkerOutcome:
        completed_at = self.clock()
        terminal = replace(
            claimed,
            status=result.status,
            state_version=claimed.state_version + 1,
            bounded_outcome_summary=dict(result.bounded_outcome_summary),
            error_code=result.error_code,
            safe_error_summary=result.safe_error_summary,
            safe_retry_hint=result.safe_retry_hint,
            completed_at=completed_at,
        )
        with self.repository_scope_factory() as repositories:
            with repositories.atomic(prefix="runtime_command_finish"):
                stored = repositories.runtime_commands.finish_claim(
                    terminal,
                    expected_state_version=claimed.state_version,
                    expected_lease_token=str(claimed.lease_token),
                    expected_fencing_token=claimed.fencing_token,
                )
                repositories.durable_events.append(
                    DurableEventRecord(
                        event_id=f"runtime_command_event_{uuid4().hex}",
                        session_id=stored.session_id,
                        event_type="runtime.command.finished",
                        schema_version="openzyme.v3.event.v1",
                        visibility="public",
                        payload={
                            "command_id": stored.command_id,
                            "command_type": stored.command_type.value,
                            "status": stored.status.value,
                            "completed_at": stored.completed_at,
                            "bounded_outcome_summary": (stored.bounded_outcome_summary),
                            "error_code": stored.error_code,
                            "safe_error_summary": stored.safe_error_summary,
                            "safe_retry_hint": stored.safe_retry_hint,
                        },
                        command_id=stored.command_id,
                        correlation_id=None,
                        causation_id=None,
                        actor_ref="harness:runtime-command-worker",
                        created_at=completed_at,
                    )
                )
        return RuntimeCommandWorkerOutcome(
            command_id=stored.command_id,
            action=action or result.status.value,
            semantic_progress=True,
            status=stored.status.value,
            state_version=stored.state_version,
        )

    def _call_executor_with_heartbeat(
        self,
        command: RuntimeCommandRecord,
        *,
        late_writer_required: bool = False,
    ) -> tuple[RuntimeCommandExecutionResult, RuntimeCommandRecord]:
        stopped = threading.Event()
        state_lock = threading.Lock()
        latest = command
        heartbeat_error: list[Exception] = []
        heartbeat_interval = max(
            0.25,
            min(float(self.lease_seconds) / 3.0, 5.0),
        )

        def _heartbeat() -> None:
            nonlocal latest
            while not stopped.wait(heartbeat_interval):
                with state_lock:
                    captured = latest
                try:
                    renewed = self._renew_claim_lease(
                        captured,
                        stopped=stopped,
                        late_writer_required=late_writer_required,
                    )
                except Exception as exc:
                    heartbeat_error.append(exc)
                    stopped.set()
                    return
                if renewed is None:
                    return
                with state_lock:
                    latest = renewed

        heartbeat_context = copy_context()
        heartbeat = threading.Thread(
            target=lambda: heartbeat_context.run(_heartbeat),
            name=f"runtime-command-heartbeat:{command.command_id}",
            daemon=True,
        )
        heartbeat.start()
        try:
            result = self.executor(command)
        finally:
            stopped.set()
            heartbeat.join()
        with state_lock:
            captured = latest
        if heartbeat_error:
            raise OptimisticStateConflictError(
                "runtime command lost its lease during scheduler work"
            ) from heartbeat_error[0]
        return result, captured

    def _renew_claim_lease(
        self,
        captured: RuntimeCommandRecord,
        *,
        stopped: threading.Event,
        late_writer_required: bool,
    ) -> RuntimeCommandRecord | None:
        """Renew one exact claim without carrying a late writer across execution."""

        retry_deadline = time.monotonic() + self._lease_remaining_seconds(captured)
        retry_delays = iter(_HEARTBEAT_RETRY_DELAYS)
        while True:
            try:
                renewed_record = replace(
                    captured,
                    lease_expires_at=self._after_iso(
                        self.clock(),
                        self.lease_seconds,
                    ),
                )
                writer_scope = (
                    self.mutation_writer_scope_factory(
                        session_id=captured.session_id,
                        owner_kind=MutationWriterKind.RUNTIME_COMMAND,
                        owner_ref=(
                            f"runtime-command:{captured.command_id}:lease-heartbeat"
                        ),
                    )
                    if late_writer_required
                    and self.mutation_writer_scope_factory is not None
                    else nullcontext(None)
                )
                with writer_scope:
                    with self.repository_scope_factory() as repositories:
                        return repositories.runtime_commands.renew_lease(
                            renewed_record,
                            expected_state_version=captured.state_version,
                            expected_lease_token=str(captured.lease_token),
                            expected_fencing_token=captured.fencing_token,
                        )
            except Exception as exc:
                retryable = is_transient_sqlite_contention(exc) or (
                    late_writer_required
                    and isinstance(exc, MutationWriteAuthorityRejectedError)
                )
                if not retryable:
                    raise
                if stopped.is_set():
                    return None
                try:
                    delay = next(retry_delays)
                except StopIteration:
                    raise exc
                remaining = retry_deadline - time.monotonic()
                if remaining <= delay:
                    raise exc
                if stopped.wait(delay):
                    return None

    def _lease_remaining_seconds(self, command: RuntimeCommandRecord) -> float:
        if command.lease_expires_at is None:
            return 0.0
        lease_expires_at = datetime.fromisoformat(command.lease_expires_at)
        now = datetime.fromisoformat(self.clock())
        return max(0.0, (lease_expires_at - now).total_seconds())

    @staticmethod
    def _validated_result(
        result: RuntimeCommandExecutionResult,
    ) -> RuntimeCommandExecutionResult:
        if not isinstance(result, RuntimeCommandExecutionResult):
            raise TypeError("runtime command executor returned an invalid result")
        if result.status not in {
            RuntimeCommandStatus.COMPLETED,
            RuntimeCommandStatus.FAILED,
            RuntimeCommandStatus.LOCKED,
        }:
            raise ValueError("runtime command executor returned a nonterminal status")
        sanitized = sanitize_runtime_command_outcome(result.bounded_outcome_summary)
        if not isinstance(sanitized, dict):
            raise ValueError("runtime command outcome summary must be an object")
        validate_runtime_command_outcome_v2(sanitized)
        encoded = json.dumps(
            sanitized,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if len(encoded) > RUNTIME_COMMAND_OUTCOME_MAX_BYTES:
            raise ValueError("runtime command outcome summary exceeds the public bound")
        error_code = result.error_code
        if error_code is not None and _SAFE_ERROR_CODE.fullmatch(error_code) is None:
            raise ValueError("runtime command error_code is invalid")
        safe_error_summary = (
            None
            if result.safe_error_summary is None
            else sanitize_public_diagnostic_text(result.safe_error_summary)[:2_000]
        )
        safe_retry_hint = (
            None
            if result.safe_retry_hint is None
            else sanitize_public_diagnostic_text(result.safe_retry_hint)[:2_000]
        )
        return RuntimeCommandExecutionResult(
            status=result.status,
            bounded_outcome_summary=sanitized,
            error_code=error_code,
            safe_error_summary=safe_error_summary,
            safe_retry_hint=safe_retry_hint,
        )

    @staticmethod
    def _after_iso(now_iso: str, seconds: int) -> str:
        return (
            datetime.fromisoformat(now_iso) + timedelta(seconds=seconds)
        ).isoformat()

    @staticmethod
    def _idle_outcome() -> RuntimeCommandWorkerOutcome:
        return RuntimeCommandWorkerOutcome(
            command_id=None,
            action="idle",
            semantic_progress=False,
            status=None,
            state_version=None,
        )

    @staticmethod
    def _database_busy_outcome(
        command_id: str | None = None,
    ) -> RuntimeCommandWorkerOutcome:
        return RuntimeCommandWorkerOutcome(
            command_id=command_id,
            action="database_busy",
            semantic_progress=False,
            status=None,
            state_version=None,
        )


__all__ = [
    "RUNTIME_COMMAND_OUTCOME_MAX_BYTES",
    "RUNTIME_COMMAND_OUTCOME_LEGACY_SCHEMA_VERSION",
    "RUNTIME_COMMAND_OUTCOME_SCHEMA_VERSION",
    "RuntimeCommandExecutionResult",
    "RuntimeCommandExecutor",
    "RuntimeCommandRepositoryScopeFactory",
    "RuntimeCommandWorker",
    "RuntimeCommandWorkerOutcome",
    "runtime_command_request_digest",
]
