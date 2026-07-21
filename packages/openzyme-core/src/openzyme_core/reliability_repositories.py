from __future__ import annotations

from dataclasses import dataclass, replace
import hashlib
import sqlite3

from openzyme_domain import ControlledOperationDispatchRequest
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionEvent
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationExecutionPhase
from openzyme_domain import ControlledOperationExecutionTerminalOutcome
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationResultHandle
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import RetryEligibility

from .repositories import _commit
from .repositories import _json_dumps
from .repositories import _json_loads_object
from .repositories import _require_enum_member
from .repositories import _require_linked_session_id
from .repositories import _require_session_exists
from .result_artifacts import ControlledOperationResultArtifactRef
from .result_artifacts import controlled_operation_artifact_set_digest
from .result_artifacts import normalize_controlled_operation_result_artifacts


class ReliabilityRepositoryError(RuntimeError):
    """Base error for canonical reliability record mutations."""


class CanonicalRecordConflictError(ReliabilityRepositoryError):
    """Raised when a unique canonical identity is already owned by another record."""


class ImmutableIdentityConflictError(ReliabilityRepositoryError):
    """Raised when a caller attempts to rewrite a frozen record identity."""


class OptimisticStateConflictError(ReliabilityRepositoryError):
    """Raised when a state-version or execution-fence comparison fails."""


def is_transient_sqlite_contention(exc: BaseException) -> bool:
    """Classify local SQLite busy/locked failures without changing effect state."""

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, sqlite3.OperationalError):
            error_code = getattr(current, "sqlite_errorcode", None)
            if isinstance(error_code, int) and error_code & 0xFF in {
                sqlite3.SQLITE_BUSY,
                sqlite3.SQLITE_LOCKED,
            }:
                return True
            message = str(current).casefold()
            if any(
                marker in message
                for marker in (
                    "database is busy",
                    "database is locked",
                    "database table is locked",
                    "database schema is locked",
                )
            ):
                return True
        current = current.__cause__ or current.__context__
    return False


CONTROLLED_OPERATION_DISPATCH_REQUEST_MAX_BYTES = 4 * 1024 * 1024


def _canonical_request_bytes(value: dict[str, object]) -> bytes:
    return _json_dumps(value).encode("utf-8")


def _sha256_digest(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _require_execution_enums(record: ControlledOperationExecution) -> None:
    _require_enum_member(
        record.owner_mode,
        ControlledOperationOwnerMode,
        "ControlledOperationExecution.owner_mode",
    )
    _require_enum_member(
        record.lifecycle_state,
        ControlledOperationExecutionLifecycle,
        "ControlledOperationExecution.lifecycle_state",
    )
    _require_enum_member(
        record.effect_certainty,
        ExternalEffectCertainty,
        "ControlledOperationExecution.effect_certainty",
    )
    _require_enum_member(
        record.retry_eligibility,
        RetryEligibility,
        "ControlledOperationExecution.retry_eligibility",
    )
    if record.terminal_outcome is not None:
        _require_enum_member(
            record.terminal_outcome,
            ControlledOperationExecutionTerminalOutcome,
            "ControlledOperationExecution.terminal_outcome",
        )


def _execution_identity(record: ControlledOperationExecution) -> tuple[object, ...]:
    return (
        record.execution_id,
        record.operation_id,
        record.session_id,
        record.task_id,
        record.lane_id,
        record.approval_id,
        record.owner_mode,
        record.operation_digest,
        record.approval_digest,
        record.route_policy_id,
        record.selected_backend,
        record.adapter_policy_id,
        record.input_identity_digest,
        record.expected_output_contract_digest,
        record.runtime_identity_digest,
        record.created_at,
    )


@dataclass(slots=True)
class ControlledOperationExecutionRepository:
    connection: sqlite3.Connection

    def add(self, record: ControlledOperationExecution) -> ControlledOperationExecution:
        _require_execution_enums(record)
        if record.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1:
            raise ValueError(
                "ControlledOperationExecution.owner_mode must be durable_async_v1"
            )
        self._require_canonical_identity(record)
        try:
            self.connection.execute(
                """
                INSERT INTO controlled_operation_execution_records (
                    execution_id,
                    operation_id,
                    session_id,
                    task_id,
                    lane_id,
                    approval_id,
                    schema_version,
                    owner_mode,
                    operation_digest,
                    approval_digest,
                    route_policy_id,
                    selected_backend,
                    adapter_policy_id,
                    input_identity_digest,
                    expected_output_contract_digest,
                    runtime_identity_digest,
                    lifecycle_state,
                    terminal_outcome,
                    effect_certainty,
                    retry_eligibility,
                    dispatch_generation,
                    state_version,
                    lease_owner,
                    lease_token,
                    lease_expires_at,
                    fencing_token,
                    backend_handle_ref,
                    result_handle_ref,
                    result_digest,
                    artifact_set_digest,
                    error_code,
                    safe_error_summary,
                    created_at,
                    updated_at,
                    terminal_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._record_values(record),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_operation_id(record.operation_id)
            if existing == record:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "controlled operation already has a different execution owner"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, execution_id: str) -> ControlledOperationExecution | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_records
            WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_operation_id(
        self,
        operation_id: str,
    ) -> ControlledOperationExecution | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_records
            WHERE operation_id = ?
            """,
            (operation_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_session(self, session_id: str) -> list[ControlledOperationExecution]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_records
            WHERE session_id = ?
            ORDER BY created_at, execution_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_nonterminal(
        self,
        *,
        limit: int = 1_000,
    ) -> list[ControlledOperationExecution]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("controlled operation execution audit limit is invalid")
        rows = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_records
            WHERE lifecycle_state <> 'terminal'
            ORDER BY updated_at, execution_id
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def count_nonterminal(self) -> int:
        row = self.connection.execute(
            """
            SELECT COUNT(*) AS row_count
            FROM controlled_operation_execution_records
            WHERE lifecycle_state <> 'terminal'
            """
        ).fetchone()
        return 0 if row is None else int(row["row_count"])

    def list_claimable(
        self,
        *,
        now_iso: str,
        limit: int = 32,
    ) -> list[ControlledOperationExecution]:
        if limit <= 0 or limit > 1_000:
            raise ValueError("controlled operation execution claim limit is invalid")
        rows = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_records
            WHERE lifecycle_state IN (
                'ready',
                'claimed',
                'dispatching',
                'waiting_external',
                'result_staging',
                'result_ready',
                'reconcile_required'
            )
              AND (
                  lease_owner IS NULL
                  OR lease_expires_at IS NULL
                  OR lease_expires_at <= ?
              )
            ORDER BY updated_at, execution_id
            LIMIT ?
            """,
            (now_iso, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def replace_if_version(
        self,
        record: ControlledOperationExecution,
        *,
        expected_state_version: int,
        expected_lease_token: str | None = None,
        expected_fencing_token: int | None = None,
    ) -> ControlledOperationExecution:
        _require_execution_enums(record)
        if record.state_version != expected_state_version + 1:
            raise ValueError(
                "replacement state_version must increase exactly once from the "
                "expected state_version"
            )
        existing = self.get(record.execution_id)
        if existing is None:
            raise OptimisticStateConflictError("controlled operation execution is missing")
        if _execution_identity(existing) != _execution_identity(record):
            raise ImmutableIdentityConflictError(
                "controlled operation execution identity cannot change"
            )
        where = "execution_id = ? AND state_version = ?"
        where_values: list[object] = [record.execution_id, expected_state_version]
        if expected_lease_token is not None or expected_fencing_token is not None:
            if expected_lease_token is None or expected_fencing_token is None:
                raise ValueError(
                    "lease token and fencing token must be compared together"
                )
            where += " AND lease_token = ? AND fencing_token = ?"
            where_values.extend((expected_lease_token, expected_fencing_token))
        cursor = self.connection.execute(
            f"""
            UPDATE controlled_operation_execution_records
            SET
                lifecycle_state = ?,
                terminal_outcome = ?,
                effect_certainty = ?,
                retry_eligibility = ?,
                dispatch_generation = ?,
                state_version = ?,
                lease_owner = ?,
                lease_token = ?,
                lease_expires_at = ?,
                fencing_token = ?,
                backend_handle_ref = ?,
                result_handle_ref = ?,
                result_digest = ?,
                artifact_set_digest = ?,
                error_code = ?,
                safe_error_summary = ?,
                updated_at = ?,
                terminal_at = ?
            WHERE {where}
            """,
            (
                record.lifecycle_state.value,
                None
                if record.terminal_outcome is None
                else record.terminal_outcome.value,
                record.effect_certainty.value,
                record.retry_eligibility.value,
                record.dispatch_generation,
                record.state_version,
                record.lease_owner,
                record.lease_token,
                record.lease_expires_at,
                record.fencing_token,
                record.backend_handle_ref,
                record.result_handle_ref,
                record.result_digest,
                record.artifact_set_digest,
                record.error_code,
                record.safe_error_summary,
                record.updated_at,
                record.terminal_at,
                *where_values,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "controlled operation execution state or fence changed"
            )
        _commit(self.connection)
        return record

    def renew_lease(
        self,
        record: ControlledOperationExecution,
        *,
        expected_state_version: int,
        expected_lease_token: str,
        expected_fencing_token: int,
    ) -> ControlledOperationExecution:
        """Extend only lease time; heartbeat is not a lifecycle transition."""

        _require_execution_enums(record)
        if record.state_version != expected_state_version:
            raise ValueError("lease renewal must not change execution state_version")
        existing = self.get(record.execution_id)
        if existing is None:
            raise OptimisticStateConflictError(
                "controlled operation execution is missing"
            )
        if _execution_identity(existing) != _execution_identity(record):
            raise ImmutableIdentityConflictError(
                "controlled operation execution identity cannot change"
            )
        expected_record = replace(
            existing,
            lease_expires_at=record.lease_expires_at,
            updated_at=record.updated_at,
        )
        if record != expected_record:
            raise ImmutableIdentityConflictError(
                "lease renewal attempted to change execution state"
            )
        cursor = self.connection.execute(
            """
            UPDATE controlled_operation_execution_records
            SET lease_expires_at = ?, updated_at = ?
            WHERE execution_id = ?
              AND state_version = ?
              AND lease_token = ?
              AND fencing_token = ?
              AND lease_owner IS NOT NULL
            """,
            (
                record.lease_expires_at,
                record.updated_at,
                record.execution_id,
                expected_state_version,
                expected_lease_token,
                expected_fencing_token,
            ),
        )
        if cursor.rowcount != 1:
            _commit(self.connection)
            raise OptimisticStateConflictError(
                "controlled operation execution lease renewal was fenced"
            )
        _commit(self.connection)
        return record

    def _require_canonical_identity(
        self,
        record: ControlledOperationExecution,
    ) -> None:
        _require_session_exists(self.connection, record.session_id)
        _require_linked_session_id(
            self.connection,
            table_name="controlled_operation_records",
            id_column="operation_id",
            record_id=record.operation_id,
            expected_session_id=record.session_id,
        )
        if record.task_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="tasks",
                id_column="task_id",
                record_id=record.task_id,
                expected_session_id=record.session_id,
            )
        if record.lane_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="lanes",
                id_column="lane_id",
                record_id=record.lane_id,
                expected_session_id=record.session_id,
            )
        if record.approval_id is not None:
            _require_linked_session_id(
                self.connection,
                table_name="approval_requests",
                id_column="approval_id",
                record_id=record.approval_id,
                expected_session_id=record.session_id,
            )
        operation = self.connection.execute(
            """
            SELECT owner_mode, operation_digest
            FROM controlled_operation_records
            WHERE operation_id = ?
            """,
            (record.operation_id,),
        ).fetchone()
        if operation is None:
            raise CanonicalRecordConflictError("controlled operation is missing")
        if (
            operation["owner_mode"] != record.owner_mode.value
            or operation["operation_digest"] != record.operation_digest
        ):
            raise ImmutableIdentityConflictError(
                "controlled operation owner mode or digest does not match execution"
            )

    @staticmethod
    def _record_values(record: ControlledOperationExecution) -> tuple[object, ...]:
        return (
            record.execution_id,
            record.operation_id,
            record.session_id,
            record.task_id,
            record.lane_id,
            record.approval_id,
            record.SCHEMA_VERSION,
            record.owner_mode.value,
            record.operation_digest,
            record.approval_digest,
            record.route_policy_id,
            record.selected_backend,
            record.adapter_policy_id,
            record.input_identity_digest,
            record.expected_output_contract_digest,
            record.runtime_identity_digest,
            record.lifecycle_state.value,
            None if record.terminal_outcome is None else record.terminal_outcome.value,
            record.effect_certainty.value,
            record.retry_eligibility.value,
            record.dispatch_generation,
            record.state_version,
            record.lease_owner,
            record.lease_token,
            record.lease_expires_at,
            record.fencing_token,
            record.backend_handle_ref,
            record.result_handle_ref,
            record.result_digest,
            record.artifact_set_digest,
            record.error_code,
            record.safe_error_summary,
            record.created_at,
            record.updated_at,
            record.terminal_at,
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ControlledOperationExecution:
        return ControlledOperationExecution(
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            approval_id=row["approval_id"],
            owner_mode=ControlledOperationOwnerMode(row["owner_mode"]),
            operation_digest=row["operation_digest"],
            approval_digest=row["approval_digest"],
            route_policy_id=row["route_policy_id"],
            selected_backend=row["selected_backend"],
            adapter_policy_id=row["adapter_policy_id"],
            input_identity_digest=row["input_identity_digest"],
            expected_output_contract_digest=row["expected_output_contract_digest"],
            runtime_identity_digest=row["runtime_identity_digest"],
            lifecycle_state=ControlledOperationExecutionLifecycle(
                row["lifecycle_state"]
            ),
            terminal_outcome=None
            if row["terminal_outcome"] is None
            else ControlledOperationExecutionTerminalOutcome(
                row["terminal_outcome"]
            ),
            effect_certainty=ExternalEffectCertainty(row["effect_certainty"]),
            retry_eligibility=RetryEligibility(row["retry_eligibility"]),
            dispatch_generation=int(row["dispatch_generation"]),
            state_version=int(row["state_version"]),
            lease_owner=row["lease_owner"],
            lease_token=row["lease_token"],
            lease_expires_at=row["lease_expires_at"],
            fencing_token=int(row["fencing_token"]),
            backend_handle_ref=row["backend_handle_ref"],
            result_handle_ref=row["result_handle_ref"],
            result_digest=row["result_digest"],
            artifact_set_digest=row["artifact_set_digest"],
            error_code=row["error_code"],
            safe_error_summary=row["safe_error_summary"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            terminal_at=row["terminal_at"],
        )


@dataclass(slots=True)
class ControlledOperationDispatchRequestRepository:
    """Persistence boundary for restart-safe, Host-private dispatch inputs."""

    connection: sqlite3.Connection

    def save_once(
        self,
        record: ControlledOperationDispatchRequest,
    ) -> ControlledOperationDispatchRequest:
        encoded = _canonical_request_bytes(record.request_envelope)
        if not encoded or len(encoded) > CONTROLLED_OPERATION_DISPATCH_REQUEST_MAX_BYTES:
            raise ValueError(
                "controlled operation dispatch request exceeds its closed size bound"
            )
        if record.request_size_bytes != len(encoded):
            raise ValueError(
                "controlled operation dispatch request size does not match its envelope"
            )
        if record.request_digest != _sha256_digest(encoded):
            raise ValueError(
                "controlled operation dispatch request digest does not match its envelope"
            )
        execution = self.connection.execute(
            """
            SELECT operation_id, session_id
            FROM controlled_operation_execution_records
            WHERE execution_id = ?
            """,
            (record.execution_id,),
        ).fetchone()
        if execution is None:
            raise CanonicalRecordConflictError(
                "dispatch request has no controlled operation execution owner"
            )
        if (
            execution["operation_id"] != record.operation_id
            or execution["session_id"] != record.session_id
        ):
            raise ImmutableIdentityConflictError(
                "dispatch request identity does not match its execution owner"
            )
        try:
            self.connection.execute(
                """
                INSERT INTO controlled_operation_dispatch_requests (
                    request_id,
                    execution_id,
                    operation_id,
                    session_id,
                    schema_version,
                    request_digest,
                    request_envelope_json,
                    request_size_bytes,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.request_id,
                    record.execution_id,
                    record.operation_id,
                    record.session_id,
                    record.SCHEMA_VERSION,
                    record.request_digest,
                    encoded.decode("utf-8"),
                    record.request_size_bytes,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_execution_id(record.execution_id)
            if existing == record:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "controlled operation execution already has a different dispatch request"
            ) from exc
        _commit(self.connection)
        return record

    def get(
        self,
        request_id: str,
    ) -> ControlledOperationDispatchRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_dispatch_requests
            WHERE request_id = ?
            """,
            (request_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_execution_id(
        self,
        execution_id: str,
    ) -> ControlledOperationDispatchRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_dispatch_requests
            WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ControlledOperationDispatchRequest:
        return ControlledOperationDispatchRequest(
            request_id=row["request_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            request_digest=row["request_digest"],
            request_envelope=_json_loads_object(row["request_envelope_json"]) or {},
            request_size_bytes=int(row["request_size_bytes"]),
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ControlledOperationExecutionEventRepository:
    connection: sqlite3.Connection

    def append(
        self,
        event: ControlledOperationExecutionEvent,
    ) -> ControlledOperationExecutionEvent:
        _require_enum_member(
            event.phase,
            ControlledOperationExecutionPhase,
            "ControlledOperationExecutionEvent.phase",
        )
        _require_enum_member(
            event.lifecycle_state,
            ControlledOperationExecutionLifecycle,
            "ControlledOperationExecutionEvent.lifecycle_state",
        )
        _require_enum_member(
            event.effect_certainty,
            ExternalEffectCertainty,
            "ControlledOperationExecutionEvent.effect_certainty",
        )
        _require_enum_member(
            event.retry_eligibility,
            RetryEligibility,
            "ControlledOperationExecutionEvent.retry_eligibility",
        )
        execution = self.connection.execute(
            """
            SELECT operation_id, session_id, state_version
            FROM controlled_operation_execution_records
            WHERE execution_id = ?
            """,
            (event.execution_id,),
        ).fetchone()
        if execution is None:
            raise CanonicalRecordConflictError("execution event has no execution owner")
        if (
            execution["operation_id"] != event.operation_id
            or execution["session_id"] != event.session_id
            or int(execution["state_version"]) != event.state_version
        ):
            raise ImmutableIdentityConflictError(
                "execution event identity or state version does not match its owner"
            )
        try:
            self.connection.execute(
                """
                INSERT INTO controlled_operation_execution_events (
                    event_id,
                    execution_id,
                    operation_id,
                    session_id,
                    schema_version,
                    state_version,
                    dispatch_generation,
                    phase,
                    previous_lifecycle_state,
                    lifecycle_state,
                    terminal_outcome,
                    effect_certainty,
                    retry_eligibility,
                    fencing_token,
                    safe_receipt_digest,
                    safe_summary,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.execution_id,
                    event.operation_id,
                    event.session_id,
                    event.SCHEMA_VERSION,
                    event.state_version,
                    event.dispatch_generation,
                    event.phase.value,
                    None
                    if event.previous_lifecycle_state is None
                    else event.previous_lifecycle_state.value,
                    event.lifecycle_state.value,
                    None
                    if event.terminal_outcome is None
                    else event.terminal_outcome.value,
                    event.effect_certainty.value,
                    event.retry_eligibility.value,
                    event.fencing_token,
                    event.safe_receipt_digest,
                    event.safe_summary,
                    event.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get(event.event_id)
            if existing == event:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "execution event identity or state version already exists"
            ) from exc
        _commit(self.connection)
        return event

    def get(self, event_id: str) -> ControlledOperationExecutionEvent | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_events
            WHERE event_id = ?
            """,
            (event_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_execution(
        self,
        execution_id: str,
    ) -> list[ControlledOperationExecutionEvent]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_execution_events
            WHERE execution_id = ?
            ORDER BY state_version, event_id
            """,
            (execution_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ControlledOperationExecutionEvent:
        return ControlledOperationExecutionEvent(
            event_id=row["event_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            state_version=int(row["state_version"]),
            dispatch_generation=int(row["dispatch_generation"]),
            phase=ControlledOperationExecutionPhase(row["phase"]),
            previous_lifecycle_state=None
            if row["previous_lifecycle_state"] is None
            else ControlledOperationExecutionLifecycle(
                row["previous_lifecycle_state"]
            ),
            lifecycle_state=ControlledOperationExecutionLifecycle(
                row["lifecycle_state"]
            ),
            terminal_outcome=None
            if row["terminal_outcome"] is None
            else ControlledOperationExecutionTerminalOutcome(
                row["terminal_outcome"]
            ),
            effect_certainty=ExternalEffectCertainty(row["effect_certainty"]),
            retry_eligibility=RetryEligibility(row["retry_eligibility"]),
            fencing_token=int(row["fencing_token"]),
            safe_receipt_digest=row["safe_receipt_digest"],
            safe_summary=row["safe_summary"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ControlledOperationResultHandleRepository:
    connection: sqlite3.Connection

    def save_once(
        self,
        handle: ControlledOperationResultHandle,
    ) -> ControlledOperationResultHandle:
        _require_enum_member(
            handle.terminal_outcome,
            ControlledOperationExecutionTerminalOutcome,
            "ControlledOperationResultHandle.terminal_outcome",
        )
        execution = self.connection.execute(
            """
            SELECT operation_id, session_id, dispatch_generation
            FROM controlled_operation_execution_records
            WHERE execution_id = ?
            """,
            (handle.execution_id,),
        ).fetchone()
        if execution is None:
            raise CanonicalRecordConflictError("result handle has no execution owner")
        if (
            execution["operation_id"] != handle.operation_id
            or execution["session_id"] != handle.session_id
            or int(execution["dispatch_generation"]) != handle.dispatch_generation
        ):
            raise ImmutableIdentityConflictError(
                "result handle identity or dispatch generation does not match execution"
            )
        try:
            self.connection.execute(
                """
                INSERT INTO controlled_operation_result_handles (
                    result_handle_id,
                    execution_id,
                    operation_id,
                    session_id,
                    schema_version,
                    dispatch_generation,
                    terminal_outcome,
                    bounded_result_envelope_json,
                    result_digest,
                    artifact_set_digest,
                    origin,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handle.result_handle_id,
                    handle.execution_id,
                    handle.operation_id,
                    handle.session_id,
                    handle.SCHEMA_VERSION,
                    handle.dispatch_generation,
                    handle.terminal_outcome.value,
                    _json_dumps(handle.bounded_result_envelope),
                    handle.result_digest,
                    handle.artifact_set_digest,
                    handle.origin,
                    handle.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_execution_id(handle.execution_id)
            if existing == handle:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise CanonicalRecordConflictError(
                "controlled operation execution already has a different result handle"
            ) from exc
        _commit(self.connection)
        return handle

    def get(self, result_handle_id: str) -> ControlledOperationResultHandle | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_result_handles
            WHERE result_handle_id = ?
            """,
            (result_handle_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_execution_id(
        self,
        execution_id: str,
    ) -> ControlledOperationResultHandle | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM controlled_operation_result_handles
            WHERE execution_id = ?
            """,
            (execution_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> ControlledOperationResultHandle:
        return ControlledOperationResultHandle(
            result_handle_id=row["result_handle_id"],
            execution_id=row["execution_id"],
            operation_id=row["operation_id"],
            session_id=row["session_id"],
            dispatch_generation=int(row["dispatch_generation"]),
            terminal_outcome=ControlledOperationExecutionTerminalOutcome(
                row["terminal_outcome"]
            ),
            bounded_result_envelope=_json_loads_object(
                row["bounded_result_envelope_json"]
            )
            or {},
            result_digest=row["result_digest"],
            artifact_set_digest=row["artifact_set_digest"],
            origin=row["origin"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ControlledOperationResultArtifactRepository:
    connection: sqlite3.Connection

    def promote(
        self,
        handle: ControlledOperationResultHandle,
        refs: tuple[ControlledOperationResultArtifactRef, ...],
    ) -> tuple[ControlledOperationResultArtifactRef, ...]:
        ordered = normalize_controlled_operation_result_artifacts(refs)
        if controlled_operation_artifact_set_digest(ordered) != (
            handle.artifact_set_digest
        ):
            raise ImmutableIdentityConflictError(
                "result artifact set digest does not match immutable result"
            )
        existing = self.list_by_result_handle(handle.result_handle_id)
        if existing:
            if existing != ordered:
                raise CanonicalRecordConflictError(
                    "controlled operation result already owns another artifact set"
                )
            return existing
        for ordinal, ref in enumerate(ordered):
            row = self.connection.execute(
                """
                SELECT session_id, kind, relative_path, metadata_json
                FROM session_artifact_records
                WHERE artifact_id = ?
                """,
                (ref.artifact_id,),
            ).fetchone()
            if row is None or row["session_id"] != handle.session_id:
                raise ImmutableIdentityConflictError(
                    "result artifact is missing from its canonical session"
                )
            metadata = _json_loads_object(row["metadata_json"]) or {}
            catalog_digest = str(
                metadata.get("sealed_digest")
                or metadata.get("content_digest")
                or metadata.get("tree_digest")
                or metadata.get("source_tree_digest")
                or ""
            )
            if (
                row["kind"] != ref.kind.value
                or row["relative_path"] != ref.relative_path
                or catalog_digest != ref.artifact_digest
            ):
                raise ImmutableIdentityConflictError(
                    "result artifact identity or catalog digest drifted"
                )
            self.connection.execute(
                """
                INSERT INTO controlled_operation_result_artifacts (
                    result_handle_id,
                    ordinal,
                    artifact_id,
                    schema_version,
                    execution_id,
                    operation_id,
                    session_id,
                    artifact_kind,
                    relative_path,
                    artifact_digest
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    handle.result_handle_id,
                    ordinal,
                    ref.artifact_id,
                    "controlled_operation_result_artifact@1",
                    handle.execution_id,
                    handle.operation_id,
                    handle.session_id,
                    ref.kind.value,
                    ref.relative_path,
                    ref.artifact_digest,
                ),
            )
        _commit(self.connection)
        return ordered

    def assert_exact(self, handle: ControlledOperationResultHandle) -> None:
        refs = self.list_by_result_handle(handle.result_handle_id)
        if controlled_operation_artifact_set_digest(refs) != handle.artifact_set_digest:
            raise ImmutableIdentityConflictError(
                "immutable result artifact promotion is incomplete"
            )

    def list_by_result_handle(
        self,
        result_handle_id: str,
    ) -> tuple[ControlledOperationResultArtifactRef, ...]:
        rows = self.connection.execute(
            """
            SELECT artifact_id, artifact_kind, relative_path, artifact_digest
            FROM controlled_operation_result_artifacts
            WHERE result_handle_id = ?
            ORDER BY ordinal
            """,
            (result_handle_id,),
        ).fetchall()
        from openzyme_domain import ArtifactKind

        return tuple(
            ControlledOperationResultArtifactRef(
                artifact_id=row["artifact_id"],
                kind=ArtifactKind(row["artifact_kind"]),
                relative_path=row["relative_path"],
                artifact_digest=row["artifact_digest"],
            )
            for row in rows
        )

    def is_promoted(self, artifact_id: str) -> bool:
        row = self.connection.execute(
            """
            SELECT 1
            FROM controlled_operation_result_artifacts
            WHERE artifact_id = ?
            LIMIT 1
            """,
            (artifact_id,),
        ).fetchone()
        return row is not None
