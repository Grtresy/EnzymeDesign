from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import sqlite3

from openzyme_domain import ContinuationDeliveryState
from openzyme_domain import ContinuationResumeStrategy
from openzyme_domain import ContinuationState
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import MutationScope
from openzyme_domain import MutationScopeKind
from openzyme_domain import MutationScopeState
from openzyme_domain import MutationWriter
from openzyme_domain import MutationWriterKind
from openzyme_domain import MutationWriterState
from openzyme_domain import QuiescenceReceipt
from openzyme_domain import QuiescenceSnapshot
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_domain import RuntimeCommandType

from .reliability_repositories import CanonicalRecordConflictError
from .reliability_repositories import ImmutableIdentityConflictError
from .reliability_repositories import OptimisticStateConflictError
from .repositories import CommandIdempotencyConflictError
from .repositories import ContinuationStateRepository
from .repositories import _commit
from .repositories import _json_dumps
from .repositories import _json_loads_object
from .repositories import _require_enum_member
from .repositories import _require_session_exists


def _runtime_command_identity(record: RuntimeCommandRecord) -> tuple[object, ...]:
    return (
        record.command_id,
        record.session_id,
        record.command_type,
        record.request_digest,
        record.idempotency_key,
        record.max_signals,
        record.max_steps_per_agent,
        record.auto_enqueue_ready_tasks,
        record.accepted_at,
    )


def _runtime_command_request_identity(
    record: RuntimeCommandRecord,
) -> tuple[object, ...]:
    """Identity of an admitted request, excluding server-assigned row metadata."""

    return (
        record.session_id,
        record.command_type,
        record.request_digest,
        record.idempotency_key,
        record.max_signals,
        record.max_steps_per_agent,
        record.auto_enqueue_ready_tasks,
    )


@dataclass(slots=True)
class RuntimeCommandRepository:
    connection: sqlite3.Connection

    def add(self, record: RuntimeCommandRecord) -> RuntimeCommandRecord:
        self._require_record(record)
        _require_session_exists(self.connection, record.session_id)
        existing = self.find_by_idempotency_key(
            session_id=record.session_id,
            command_type=record.command_type,
            idempotency_key=record.idempotency_key,
        )
        if existing is not None:
            if _runtime_command_request_identity(
                existing
            ) == _runtime_command_request_identity(record):
                return existing
            raise CommandIdempotencyConflictError(
                "runtime command idempotency key was reused with a different request"
            )
        try:
            self.connection.execute(
                """
                INSERT INTO runtime_command_records (
                    command_id,
                    session_id,
                    schema_version,
                    command_type,
                    request_digest,
                    idempotency_key,
                    status,
                    max_signals,
                    max_steps_per_agent,
                    auto_enqueue_ready_tasks,
                    claim_owner,
                    lease_token,
                    lease_expires_at,
                    fencing_token,
                    state_version,
                    bounded_outcome_summary_json,
                    error_code,
                    safe_error_summary,
                    safe_retry_hint,
                    accepted_at,
                    started_at,
                    completed_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._record_values(record),
            )
        except sqlite3.IntegrityError as exc:
            raced = self.find_by_idempotency_key(
                session_id=record.session_id,
                command_type=record.command_type,
                idempotency_key=record.idempotency_key,
            )
            if raced is not None and _runtime_command_request_identity(
                raced
            ) == _runtime_command_request_identity(record):
                _commit(self.connection)
                return raced
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "runtime command identity already exists"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, command_id: str) -> RuntimeCommandRecord | None:
        row = self.connection.execute(
            "SELECT * FROM runtime_command_records WHERE command_id = ?",
            (command_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_for_session(
        self,
        *,
        session_id: str,
        command_id: str,
    ) -> RuntimeCommandRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM runtime_command_records
            WHERE session_id = ? AND command_id = ?
            """,
            (session_id, command_id),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def find_by_idempotency_key(
        self,
        *,
        session_id: str,
        command_type: RuntimeCommandType,
        idempotency_key: str,
    ) -> RuntimeCommandRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM runtime_command_records
            WHERE session_id = ? AND command_type = ? AND idempotency_key = ?
            """,
            (session_id, command_type.value, idempotency_key),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_accepted(self, *, limit: int) -> list[RuntimeCommandRecord]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        rows = self.connection.execute(
            """
            SELECT *
            FROM runtime_command_records
            WHERE status = 'accepted'
            ORDER BY accepted_at, command_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_active(self) -> list[RuntimeCommandRecord]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM runtime_command_records
            WHERE status IN ('accepted', 'claimed')
            ORDER BY accepted_at, command_id
            """
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_active(self) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS active_count
            FROM runtime_command_records
            WHERE status IN ('accepted', 'claimed')
            """
        ).fetchone()
        return 0 if row is None else int(row["active_count"])

    def list_claimable(
        self,
        *,
        now_iso: str,
        limit: int,
    ) -> list[RuntimeCommandRecord]:
        if limit <= 0 or limit > 1_000:
            raise ValueError("runtime command claim limit is invalid")
        rows = self.connection.execute(
            """
            SELECT *
            FROM runtime_command_records
            WHERE status = 'accepted'
               OR (
                    status = 'claimed'
                    AND lease_expires_at IS NOT NULL
                    AND lease_expires_at <= ?
               )
            ORDER BY accepted_at, command_id
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def claim(
        self,
        command_id: str,
        *,
        expected_state_version: int,
        claim_owner: str,
        lease_token: str,
        lease_expires_at: str,
        now_iso: str,
        started_at: str,
    ) -> RuntimeCommandRecord:
        cursor = self.connection.execute(
            """
            UPDATE runtime_command_records
            SET
                status = 'claimed',
                claim_owner = ?,
                lease_token = ?,
                lease_expires_at = ?,
                fencing_token = fencing_token + 1,
                state_version = state_version + 1,
                started_at = COALESCE(started_at, ?)
            WHERE command_id = ?
              AND state_version = ?
              AND (
                    status = 'accepted'
                    OR (
                        status = 'claimed'
                        AND lease_expires_at IS NOT NULL
                        AND lease_expires_at <= ?
                    )
              )
            """,
            (
                claim_owner,
                lease_token,
                lease_expires_at,
                started_at,
                command_id,
                expected_state_version,
                now_iso,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "runtime command is no longer accepted at the expected version"
            )
        _commit(self.connection)
        claimed = self.get(command_id)
        if claimed is None:
            raise OptimisticStateConflictError("claimed runtime command disappeared")
        return claimed

    def renew_lease(
        self,
        record: RuntimeCommandRecord,
        *,
        expected_state_version: int,
        expected_lease_token: str,
        expected_fencing_token: int,
    ) -> RuntimeCommandRecord:
        self._require_record(record)
        if record.status is not RuntimeCommandStatus.CLAIMED:
            raise ValueError("runtime command lease renewal requires claimed state")
        if record.state_version != expected_state_version:
            raise ValueError(
                "runtime command lease renewal cannot change state_version"
            )
        existing = self.get(record.command_id)
        if existing is None:
            raise OptimisticStateConflictError("runtime command is missing")
        if _runtime_command_identity(existing) != _runtime_command_identity(record):
            raise ImmutableIdentityConflictError(
                "runtime command identity cannot change"
            )
        expected_record = replace(
            existing,
            lease_expires_at=record.lease_expires_at,
        )
        if record != expected_record:
            raise ImmutableIdentityConflictError(
                "runtime command lease renewal attempted to change command state"
            )
        cursor = self.connection.execute(
            """
            UPDATE runtime_command_records
            SET lease_expires_at = ?
            WHERE command_id = ?
              AND status = 'claimed'
              AND state_version = ?
              AND lease_token = ?
              AND fencing_token = ?
            """,
            (
                record.lease_expires_at,
                record.command_id,
                expected_state_version,
                expected_lease_token,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "runtime command lease renewal was fenced"
            )
        _commit(self.connection)
        return record

    def finish_claim(
        self,
        record: RuntimeCommandRecord,
        *,
        expected_state_version: int,
        expected_lease_token: str,
        expected_fencing_token: int,
    ) -> RuntimeCommandRecord:
        self._require_record(record)
        if record.status not in {
            RuntimeCommandStatus.COMPLETED,
            RuntimeCommandStatus.FAILED,
            RuntimeCommandStatus.LOCKED,
            RuntimeCommandStatus.CANCELLED,
        }:
            raise ValueError(
                "runtime command claim can only finish in a terminal status"
            )
        if record.state_version != expected_state_version + 1:
            raise ValueError("runtime command state_version must increase exactly once")
        existing = self.get(record.command_id)
        if existing is None:
            raise OptimisticStateConflictError("runtime command is missing")
        if _runtime_command_identity(existing) != _runtime_command_identity(record):
            raise ImmutableIdentityConflictError(
                "runtime command identity cannot change"
            )
        cursor = self.connection.execute(
            """
            UPDATE runtime_command_records
            SET
                status = ?,
                state_version = ?,
                bounded_outcome_summary_json = ?,
                error_code = ?,
                safe_error_summary = ?,
                safe_retry_hint = ?,
                completed_at = ?
            WHERE command_id = ?
              AND status = 'claimed'
              AND state_version = ?
              AND lease_token = ?
              AND fencing_token = ?
            """,
            (
                record.status.value,
                record.state_version,
                None
                if record.bounded_outcome_summary is None
                else _json_dumps(record.bounded_outcome_summary),
                record.error_code,
                record.safe_error_summary,
                record.safe_retry_hint,
                record.completed_at,
                record.command_id,
                expected_state_version,
                expected_lease_token,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "runtime command claim state or fence changed"
            )
        _commit(self.connection)
        return record

    @staticmethod
    def _require_record(record: RuntimeCommandRecord) -> None:
        _require_enum_member(
            record.command_type,
            RuntimeCommandType,
            "RuntimeCommandRecord.command_type",
        )
        _require_enum_member(
            record.status,
            RuntimeCommandStatus,
            "RuntimeCommandRecord.status",
        )

    @staticmethod
    def _record_values(record: RuntimeCommandRecord) -> tuple[object, ...]:
        return (
            record.command_id,
            record.session_id,
            record.SCHEMA_VERSION,
            record.command_type.value,
            record.request_digest,
            record.idempotency_key,
            record.status.value,
            record.max_signals,
            record.max_steps_per_agent,
            int(record.auto_enqueue_ready_tasks),
            record.claim_owner,
            record.lease_token,
            record.lease_expires_at,
            record.fencing_token,
            record.state_version,
            None
            if record.bounded_outcome_summary is None
            else _json_dumps(record.bounded_outcome_summary),
            record.error_code,
            record.safe_error_summary,
            record.safe_retry_hint,
            record.accepted_at,
            record.started_at,
            record.completed_at,
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> RuntimeCommandRecord:
        return RuntimeCommandRecord(
            command_id=row["command_id"],
            session_id=row["session_id"],
            command_type=RuntimeCommandType(row["command_type"]),
            request_digest=row["request_digest"],
            idempotency_key=row["idempotency_key"],
            status=RuntimeCommandStatus(row["status"]),
            max_signals=int(row["max_signals"]),
            max_steps_per_agent=int(row["max_steps_per_agent"]),
            auto_enqueue_ready_tasks=bool(row["auto_enqueue_ready_tasks"]),
            state_version=int(row["state_version"]),
            fencing_token=int(row["fencing_token"]),
            accepted_at=row["accepted_at"],
            claim_owner=row["claim_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            bounded_outcome_summary=_json_loads_object(
                row["bounded_outcome_summary_json"]
            ),
            error_code=row["error_code"],
            safe_error_summary=row["safe_error_summary"],
            safe_retry_hint=row["safe_retry_hint"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
        )


@dataclass(slots=True)
class ContinuationDeliveryRepository:
    connection: sqlite3.Connection

    @property
    def _states(self) -> ContinuationStateRepository:
        return ContinuationStateRepository(self.connection)

    def get(self, continuation_id: str) -> ContinuationState | None:
        return self._states.get(continuation_id)

    def list_claimable(
        self,
        *,
        now_iso: str,
        limit: int = 1,
    ) -> list[ContinuationState]:
        if limit <= 0:
            return []
        rows = self.connection.execute(
            """
            SELECT *
            FROM continuation_state_records
            WHERE delivery_state = 'ready'
               OR (
                    delivery_state = 'claimed'
                    AND delivery_lease_expires_at IS NOT NULL
                    AND delivery_lease_expires_at <= ?
               )
            ORDER BY updated_at, continuation_id
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [self._states._row_to_record(row) for row in rows]

    def list_recovery_candidates(self) -> list[ContinuationState]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM continuation_state_records
            WHERE (
                    resume_strategy IN (
                        'attached_process',
                        'journaled_sdk_call_boundary'
                    )
                    AND delivery_state IN (
                        'awaiting_result',
                        'ready',
                        'claimed'
                    )
                  )
               OR (
                    resume_strategy = 'legacy_non_resumable'
                    AND status IN (
                        'waiting_approval',
                        'approved',
                        'claimed'
                    )
                  )
            ORDER BY created_at, continuation_id
            """
        ).fetchall()
        return [self._states._row_to_record(row) for row in rows]

    def count_active(self) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM continuation_state_records
            WHERE delivery_state IN ('awaiting_result', 'ready', 'claimed')
            """
        ).fetchone()
        return 0 if row is None else int(row["count"])

    def mark_ready(
        self,
        continuation_id: str,
        *,
        expected_state_version: int,
        result_digest: str,
        updated_at: str,
    ) -> ContinuationState:
        existing = self.get(continuation_id)
        if existing is None:
            raise OptimisticStateConflictError("continuation is missing")
        if existing.resume_strategy is ContinuationResumeStrategy.LEGACY_NON_RESUMABLE:
            raise ImmutableIdentityConflictError(
                "legacy continuation cannot become resumable"
            )
        cursor = self.connection.execute(
            """
            UPDATE continuation_state_records
            SET
                delivery_state = 'ready',
                delivery_result_digest = ?,
                state_version = state_version + 1,
                updated_at = ?
            WHERE continuation_id = ?
              AND delivery_state = 'awaiting_result'
              AND delivery_generation >= 1
              AND state_version = ?
            """,
            (result_digest, updated_at, continuation_id, expected_state_version),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "continuation delivery is not awaiting this result version"
            )
        _commit(self.connection)
        ready = self.get(continuation_id)
        if ready is None:
            raise OptimisticStateConflictError("ready continuation disappeared")
        return ready

    def claim(
        self,
        continuation_id: str,
        *,
        expected_state_version: int,
        delivery_generation: int,
        claim_owner: str,
        lease_token: str,
        lease_expires_at: str,
        now_iso: str,
        updated_at: str,
    ) -> ContinuationState:
        cursor = self.connection.execute(
            """
            UPDATE continuation_state_records
            SET
                delivery_state = 'claimed',
                delivery_claim_owner = ?,
                delivery_lease_token = ?,
                delivery_lease_expires_at = ?,
                delivery_fencing_token = delivery_fencing_token + 1,
                state_version = state_version + 1,
                updated_at = ?
            WHERE continuation_id = ?
              AND delivery_generation = ?
              AND state_version = ?
              AND (
                    delivery_state = 'ready'
                    OR (
                        delivery_state = 'claimed'
                        AND delivery_lease_expires_at IS NOT NULL
                        AND delivery_lease_expires_at <= ?
                    )
              )
            """,
            (
                claim_owner,
                lease_token,
                lease_expires_at,
                updated_at,
                continuation_id,
                delivery_generation,
                expected_state_version,
                now_iso,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "continuation delivery is no longer ready at this generation"
            )
        _commit(self.connection)
        claimed = self.get(continuation_id)
        if claimed is None:
            raise OptimisticStateConflictError("claimed continuation disappeared")
        return claimed

    def renew_lease(
        self,
        continuation_id: str,
        *,
        expected_state_version: int,
        delivery_generation: int,
        expected_lease_token: str,
        expected_fencing_token: int,
        lease_expires_at: str,
    ) -> ContinuationState:
        cursor = self.connection.execute(
            """
            UPDATE continuation_state_records
            SET delivery_lease_expires_at = ?
            WHERE continuation_id = ?
              AND delivery_state = 'claimed'
              AND delivery_generation = ?
              AND state_version = ?
              AND delivery_lease_token = ?
              AND delivery_fencing_token = ?
            """,
            (
                lease_expires_at,
                continuation_id,
                delivery_generation,
                expected_state_version,
                expected_lease_token,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "continuation delivery lease renewal was fenced"
            )
        _commit(self.connection)
        renewed = self.get(continuation_id)
        if renewed is None:
            raise OptimisticStateConflictError(
                "renewed continuation delivery disappeared"
            )
        return renewed

    def finish_claim(
        self,
        continuation_id: str,
        *,
        expected_state_version: int,
        delivery_generation: int,
        expected_lease_token: str,
        expected_fencing_token: int,
        delivery_state: ContinuationDeliveryState,
        completed_at: str,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> ContinuationState:
        if delivery_state not in {
            ContinuationDeliveryState.DELIVERED,
            ContinuationDeliveryState.FAILED,
            ContinuationDeliveryState.RECOVERY_FAILED,
            ContinuationDeliveryState.CANCELLED,
        }:
            raise ValueError("continuation delivery claim must finish terminally")
        compatibility_status = {
            ContinuationDeliveryState.DELIVERED: ContinuationStateStatus.COMPLETED,
            ContinuationDeliveryState.FAILED: ContinuationStateStatus.FAILED,
            ContinuationDeliveryState.RECOVERY_FAILED: (
                ContinuationStateStatus.RECOVERY_FAILED
            ),
            ContinuationDeliveryState.CANCELLED: ContinuationStateStatus.FAILED,
        }[delivery_state]
        cursor = self.connection.execute(
            """
            UPDATE continuation_state_records
            SET
                status = ?,
                delivery_state = ?,
                delivery_claim_owner = NULL,
                delivery_lease_token = NULL,
                delivery_lease_expires_at = NULL,
                state_version = state_version + 1,
                completed_at = ?,
                error_code = ?,
                error_message = ?,
                updated_at = ?
            WHERE continuation_id = ?
              AND delivery_state = 'claimed'
              AND delivery_generation = ?
              AND state_version = ?
              AND delivery_lease_token = ?
              AND delivery_fencing_token = ?
            """,
            (
                compatibility_status.value,
                delivery_state.value,
                completed_at,
                error_code,
                error_message,
                completed_at,
                continuation_id,
                delivery_generation,
                expected_state_version,
                expected_lease_token,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "continuation delivery claim state or fence changed"
            )
        _commit(self.connection)
        finished = self.get(continuation_id)
        if finished is None:
            raise OptimisticStateConflictError("finished continuation disappeared")
        return finished

    def mark_recovery_failed(
        self,
        continuation_id: str,
        *,
        expected_state_version: int,
        completed_at: str,
        error_code: str,
        error_message: str,
    ) -> ContinuationState:
        cursor = self.connection.execute(
            """
            UPDATE continuation_state_records
            SET
                status = 'recovery_failed',
                delivery_state = 'recovery_failed',
                delivery_claim_owner = NULL,
                delivery_lease_token = NULL,
                delivery_lease_expires_at = NULL,
                delivery_fencing_token = delivery_fencing_token + 1,
                state_version = state_version + 1,
                completed_at = ?,
                error_code = ?,
                error_message = ?,
                updated_at = ?
            WHERE continuation_id = ?
              AND state_version = ?
              AND (
                    delivery_state IN ('awaiting_result', 'ready', 'claimed')
                    OR (
                        resume_strategy = 'legacy_non_resumable'
                        AND status IN ('waiting_approval', 'approved', 'claimed')
                    )
              )
            """,
            (
                completed_at,
                error_code,
                error_message,
                completed_at,
                continuation_id,
                expected_state_version,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "continuation recovery state changed before failure was recorded"
            )
        _commit(self.connection)
        failed = self.get(continuation_id)
        if failed is None:
            raise OptimisticStateConflictError(
                "recovery-failed continuation disappeared"
            )
        return failed


_SCOPE_TRANSITIONS: dict[MutationScopeState, frozenset[MutationScopeState]] = {
    MutationScopeState.OPEN: frozenset(
        {MutationScopeState.FREEZING, MutationScopeState.FAILED}
    ),
    MutationScopeState.FREEZING: frozenset(
        {MutationScopeState.QUIESCENT, MutationScopeState.FAILED}
    ),
    MutationScopeState.QUIESCENT: frozenset(
        {MutationScopeState.SEALED, MutationScopeState.FAILED}
    ),
    MutationScopeState.SEALED: frozenset(),
    MutationScopeState.FAILED: frozenset(),
}


def _mutation_scope_identity(record: MutationScope) -> tuple[object, ...]:
    return (
        record.scope_id,
        record.scope_kind,
        record.scope_ref,
        record.session_id,
        record.parent_scope_id,
        record.generation,
        record.policy_id,
        record.writer_coverage_manifest_digest,
        record.opened_at,
    )


@dataclass(slots=True)
class MutationScopeRepository:
    connection: sqlite3.Connection

    def add(self, record: MutationScope) -> MutationScope:
        self._require_record(record)
        try:
            self.connection.execute(
                """
                INSERT INTO mutation_scope_records (
                    scope_id,
                    schema_version,
                    scope_kind,
                    scope_ref,
                    parent_scope_id,
                    session_id,
                    state,
                    generation,
                    mutation_fencing_token,
                    state_version,
                    policy_id,
                    writer_coverage_manifest_digest,
                    opened_at,
                    freeze_requested_at,
                    quiescent_at,
                    sealed_at,
                    failed_at,
                    safe_error_summary,
                    sealed_receipt_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.scope_id,
                    record.SCHEMA_VERSION,
                    record.scope_kind.value,
                    record.scope_ref,
                    record.parent_scope_id,
                    record.session_id,
                    record.state.value,
                    record.generation,
                    record.mutation_fencing_token,
                    record.state_version,
                    record.policy_id,
                    record.writer_coverage_manifest_digest,
                    record.opened_at,
                    record.freeze_requested_at,
                    record.quiescent_at,
                    record.sealed_at,
                    record.failed_at,
                    record.safe_error_summary,
                    record.sealed_receipt_digest,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get(record.scope_id)
            if existing == record:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "mutation scope identity or generation already exists"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, scope_id: str) -> MutationScope | None:
        row = self.connection.execute(
            "SELECT * FROM mutation_scope_records WHERE scope_id = ?",
            (scope_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_ref(
        self,
        *,
        scope_kind: MutationScopeKind,
        scope_ref: str,
    ) -> list[MutationScope]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM mutation_scope_records
            WHERE scope_kind = ? AND scope_ref = ?
            ORDER BY generation, scope_id
            """,
            (scope_kind.value, scope_ref),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def latest_by_ref(
        self,
        *,
        scope_kind: MutationScopeKind,
        scope_ref: str,
    ) -> MutationScope | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM mutation_scope_records
            WHERE scope_kind = ? AND scope_ref = ?
            ORDER BY generation DESC, scope_id DESC
            LIMIT 1
            """,
            (scope_kind.value, scope_ref),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_session(self, session_id: str) -> list[MutationScope]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM mutation_scope_records
            WHERE session_id = ?
            ORDER BY opened_at, scope_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def replace_if_version(
        self,
        record: MutationScope,
        *,
        expected_state_version: int,
        expected_fencing_token: int,
    ) -> MutationScope:
        self._require_record(record)
        if record.state_version != expected_state_version + 1:
            raise ValueError("mutation scope state_version must increase exactly once")
        existing = self.get(record.scope_id)
        if existing is None:
            raise OptimisticStateConflictError("mutation scope is missing")
        if _mutation_scope_identity(existing) != _mutation_scope_identity(record):
            raise ImmutableIdentityConflictError(
                "mutation scope identity cannot change"
            )
        if record.state not in _SCOPE_TRANSITIONS[existing.state]:
            raise ValueError(
                f"invalid mutation scope transition {existing.state.value} -> "
                f"{record.state.value}"
            )
        cursor = self.connection.execute(
            """
            UPDATE mutation_scope_records
            SET
                state = ?,
                mutation_fencing_token = ?,
                state_version = ?,
                freeze_requested_at = ?,
                quiescent_at = ?,
                sealed_at = ?,
                failed_at = ?,
                safe_error_summary = ?
                , sealed_receipt_digest = ?
            WHERE scope_id = ?
              AND state_version = ?
              AND mutation_fencing_token = ?
            """,
            (
                record.state.value,
                record.mutation_fencing_token,
                record.state_version,
                record.freeze_requested_at,
                record.quiescent_at,
                record.sealed_at,
                record.failed_at,
                record.safe_error_summary,
                record.sealed_receipt_digest,
                record.scope_id,
                expected_state_version,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError("mutation scope state or fence changed")
        _commit(self.connection)
        return record

    @staticmethod
    def _require_record(record: MutationScope) -> None:
        _require_enum_member(
            record.scope_kind,
            MutationScopeKind,
            "MutationScope.scope_kind",
        )
        _require_enum_member(record.state, MutationScopeState, "MutationScope.state")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MutationScope:
        return MutationScope(
            scope_id=row["scope_id"],
            scope_kind=MutationScopeKind(row["scope_kind"]),
            scope_ref=row["scope_ref"],
            session_id=row["session_id"],
            parent_scope_id=row["parent_scope_id"],
            state=MutationScopeState(row["state"]),
            generation=int(row["generation"]),
            mutation_fencing_token=int(row["mutation_fencing_token"]),
            state_version=int(row["state_version"]),
            policy_id=row["policy_id"],
            writer_coverage_manifest_digest=row["writer_coverage_manifest_digest"],
            opened_at=row["opened_at"],
            freeze_requested_at=row["freeze_requested_at"],
            quiescent_at=row["quiescent_at"],
            sealed_at=row["sealed_at"],
            failed_at=row["failed_at"],
            safe_error_summary=row["safe_error_summary"],
            sealed_receipt_digest=row["sealed_receipt_digest"],
        )


_WRITER_TRANSITIONS: dict[MutationWriterState, frozenset[MutationWriterState]] = {
    MutationWriterState.REGISTERED: frozenset(
        {
            MutationWriterState.RETIRING,
            MutationWriterState.RETIRED,
            MutationWriterState.REJECTED,
        }
    ),
    MutationWriterState.RETIRING: frozenset(
        {MutationWriterState.RETIRED, MutationWriterState.REJECTED}
    ),
    MutationWriterState.RETIRED: frozenset(),
    MutationWriterState.REJECTED: frozenset(),
}


def _mutation_writer_identity(record: MutationWriter) -> tuple[object, ...]:
    return (
        record.writer_id,
        record.scope_id,
        record.scope_generation,
        record.owner_kind,
        record.owner_ref,
        record.process_epoch,
        record.parent_writer_id,
        record.registered_at,
    )


@dataclass(slots=True)
class MutationWriterRepository:
    connection: sqlite3.Connection

    def add(self, record: MutationWriter) -> MutationWriter:
        self._require_record(record)
        try:
            self.connection.execute(
                """
                INSERT INTO mutation_writer_records (
                    writer_id,
                    schema_version,
                    scope_id,
                    scope_generation,
                    owner_kind,
                    owner_ref,
                    process_epoch,
                    state,
                    parent_writer_id,
                    fencing_token,
                    state_version,
                    registered_at,
                    retired_at,
                    terminal_proof_digest,
                    safe_error_summary
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.writer_id,
                    record.SCHEMA_VERSION,
                    record.scope_id,
                    record.scope_generation,
                    record.owner_kind.value,
                    record.owner_ref,
                    record.process_epoch,
                    record.state.value,
                    record.parent_writer_id,
                    record.fencing_token,
                    record.state_version,
                    record.registered_at,
                    record.retired_at,
                    record.terminal_proof_digest,
                    record.safe_error_summary,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get(record.writer_id)
            if existing == record:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "mutation writer registration conflicts with canonical scope authority"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, writer_id: str) -> MutationWriter | None:
        row = self.connection.execute(
            "SELECT * FROM mutation_writer_records WHERE writer_id = ?",
            (writer_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_active(self, scope_id: str) -> list[MutationWriter]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM mutation_writer_records
            WHERE scope_id = ? AND state IN ('registered', 'retiring')
            ORDER BY registered_at, writer_id
            """,
            (scope_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_all(self, scope_id: str) -> list[MutationWriter]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM mutation_writer_records
            WHERE scope_id = ?
            ORDER BY registered_at, writer_id
            """,
            (scope_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_children(self, writer_id: str) -> list[MutationWriter]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM mutation_writer_records
            WHERE parent_writer_id = ?
            ORDER BY registered_at, writer_id
            """,
            (writer_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def replace_if_version(
        self,
        record: MutationWriter,
        *,
        expected_state_version: int,
        expected_fencing_token: int,
    ) -> MutationWriter:
        self._require_record(record)
        if record.state_version != expected_state_version + 1:
            raise ValueError("mutation writer state_version must increase exactly once")
        existing = self.get(record.writer_id)
        if existing is None:
            raise OptimisticStateConflictError("mutation writer is missing")
        if _mutation_writer_identity(existing) != _mutation_writer_identity(record):
            raise ImmutableIdentityConflictError(
                "mutation writer identity cannot change"
            )
        if record.state not in _WRITER_TRANSITIONS[existing.state]:
            raise ValueError(
                f"invalid mutation writer transition {existing.state.value} -> "
                f"{record.state.value}"
            )
        cursor = self.connection.execute(
            """
            UPDATE mutation_writer_records
            SET
                state = ?,
                fencing_token = ?,
                state_version = ?,
                retired_at = ?,
                terminal_proof_digest = ?,
                safe_error_summary = ?
            WHERE writer_id = ?
              AND state_version = ?
              AND fencing_token = ?
            """,
            (
                record.state.value,
                record.fencing_token,
                record.state_version,
                record.retired_at,
                record.terminal_proof_digest,
                record.safe_error_summary,
                record.writer_id,
                expected_state_version,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError("mutation writer state or fence changed")
        _commit(self.connection)
        return record

    @staticmethod
    def _require_record(record: MutationWriter) -> None:
        _require_enum_member(
            record.owner_kind,
            MutationWriterKind,
            "MutationWriter.owner_kind",
        )
        _require_enum_member(record.state, MutationWriterState, "MutationWriter.state")

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> MutationWriter:
        return MutationWriter(
            writer_id=row["writer_id"],
            scope_id=row["scope_id"],
            scope_generation=int(row["scope_generation"]),
            owner_kind=MutationWriterKind(row["owner_kind"]),
            owner_ref=row["owner_ref"],
            process_epoch=row["process_epoch"],
            state=MutationWriterState(row["state"]),
            parent_writer_id=row["parent_writer_id"],
            fencing_token=int(row["fencing_token"]),
            state_version=int(row["state_version"]),
            registered_at=row["registered_at"],
            retired_at=row["retired_at"],
            terminal_proof_digest=row["terminal_proof_digest"],
            safe_error_summary=row["safe_error_summary"],
        )


@dataclass(slots=True)
class QuiescenceReceiptRepository:
    connection: sqlite3.Connection

    def save_once(self, receipt: QuiescenceReceipt) -> QuiescenceReceipt:
        try:
            self.connection.execute(
                """
                INSERT INTO quiescence_receipt_records (
                    receipt_id,
                    schema_version,
                    scope_id,
                    seal_generation,
                    policy_digest,
                    coverage_digest,
                    writer_set_digest,
                    terminal_proof_digest,
                    sqlite_high_watermark,
                    event_high_watermark,
                    artifact_high_watermark,
                    snapshot_digest,
                    receipt_digest,
                    issued_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    receipt.receipt_id,
                    receipt.SCHEMA_VERSION,
                    receipt.scope_id,
                    receipt.seal_generation,
                    receipt.policy_digest,
                    receipt.coverage_digest,
                    receipt.writer_set_digest,
                    receipt.terminal_proof_digest,
                    receipt.sqlite_high_watermark,
                    receipt.event_high_watermark,
                    receipt.artifact_high_watermark,
                    receipt.snapshot_digest,
                    receipt.receipt_digest,
                    receipt.issued_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_scope(
                scope_id=receipt.scope_id,
                seal_generation=receipt.seal_generation,
            )
            if existing == receipt:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "quiescence receipt identity or generation already exists"
            ) from exc
        _commit(self.connection)
        return receipt

    def get(self, receipt_id: str) -> QuiescenceReceipt | None:
        row = self.connection.execute(
            "SELECT * FROM quiescence_receipt_records WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_scope(
        self,
        *,
        scope_id: str,
        seal_generation: int,
    ) -> QuiescenceReceipt | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM quiescence_receipt_records
            WHERE scope_id = ? AND seal_generation = ?
            """,
            (scope_id, seal_generation),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> QuiescenceReceipt:
        return QuiescenceReceipt(
            receipt_id=row["receipt_id"],
            scope_id=row["scope_id"],
            seal_generation=int(row["seal_generation"]),
            policy_digest=row["policy_digest"],
            coverage_digest=row["coverage_digest"],
            writer_set_digest=row["writer_set_digest"],
            terminal_proof_digest=row["terminal_proof_digest"],
            sqlite_high_watermark=row["sqlite_high_watermark"],
            event_high_watermark=row["event_high_watermark"],
            artifact_high_watermark=row["artifact_high_watermark"],
            snapshot_digest=row["snapshot_digest"],
            receipt_digest=row["receipt_digest"],
            issued_at=row["issued_at"],
        )


@dataclass(slots=True)
class QuiescenceSnapshotRepository:
    connection: sqlite3.Connection

    def save_once(self, snapshot: QuiescenceSnapshot) -> QuiescenceSnapshot:
        evidence_json = _json_dumps(snapshot.evidence)
        try:
            self.connection.execute(
                """
                INSERT INTO quiescence_snapshot_records (
                    snapshot_id,
                    schema_version,
                    receipt_id,
                    scope_id,
                    seal_generation,
                    evidence_json,
                    evidence_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot.snapshot_id,
                    snapshot.SCHEMA_VERSION,
                    snapshot.receipt_id,
                    snapshot.scope_id,
                    snapshot.seal_generation,
                    evidence_json,
                    snapshot.evidence_digest,
                    snapshot.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_scope(
                scope_id=snapshot.scope_id,
                seal_generation=snapshot.seal_generation,
            )
            if existing == snapshot:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "quiescence snapshot identity or generation already exists"
            ) from exc
        _commit(self.connection)
        return snapshot

    def get(self, snapshot_id: str) -> QuiescenceSnapshot | None:
        row = self.connection.execute(
            "SELECT * FROM quiescence_snapshot_records WHERE snapshot_id = ?",
            (snapshot_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_receipt(self, receipt_id: str) -> QuiescenceSnapshot | None:
        row = self.connection.execute(
            "SELECT * FROM quiescence_snapshot_records WHERE receipt_id = ?",
            (receipt_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_scope(
        self,
        *,
        scope_id: str,
        seal_generation: int,
    ) -> QuiescenceSnapshot | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM quiescence_snapshot_records
            WHERE scope_id = ? AND seal_generation = ?
            """,
            (scope_id, seal_generation),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> QuiescenceSnapshot:
        return QuiescenceSnapshot(
            snapshot_id=row["snapshot_id"],
            receipt_id=row["receipt_id"],
            scope_id=row["scope_id"],
            seal_generation=int(row["seal_generation"]),
            evidence=_json_loads_object(row["evidence_json"]),
            evidence_digest=row["evidence_digest"],
            created_at=row["created_at"],
        )
