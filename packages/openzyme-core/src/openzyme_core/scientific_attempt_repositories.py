from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import sqlite3

from openzyme_domain import (
    SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION,
)
from openzyme_domain import SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION
from openzyme_domain import (
    SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION,
)
from openzyme_domain import SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION
from openzyme_domain import SCIENTIFIC_ATTEMPT_SCHEMA_VERSION
from openzyme_domain import SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION
from openzyme_domain import SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION
from openzyme_domain import SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION
from openzyme_domain import ScientificAttempt
from openzyme_domain import ScientificAttemptAdmissionRequest
from openzyme_domain import ScientificAttemptAuthorization
from openzyme_domain import ScientificAttemptAuthorityStatus
from openzyme_domain import ScientificAttemptClosure
from openzyme_domain import ScientificAttemptClosureRequest
from openzyme_domain import ScientificAttemptScope
from openzyme_domain import ScientificAttemptStatus
from openzyme_domain import ScientificChainSelection
from openzyme_domain import ScientificEffectAdoption
from openzyme_domain import ScientificOperationDisposition
from openzyme_domain import ScientificOperationDispositionKind
from openzyme_domain import ScientificSelectionState

from .repositories import _commit
from .repositories import _json_dumps
from .repositories import _json_loads_list


class ScientificAttemptRepositoryError(RuntimeError):
    """Base error for scientific-attempt canonical state."""


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


@dataclass(slots=True)
class ScientificAttemptAuthorizationRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: ScientificAttemptAuthorization,
    ) -> ScientificAttemptAuthorization:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_authorization_records (
                    envelope_id,
                    schema_version,
                    session_id,
                    task_id,
                    campaign_id,
                    workflow_id,
                    root_ref,
                    grantor_kind,
                    grantor_ref,
                    allowed_scopes_json,
                    allowed_effect_classes_json,
                    allowed_providers_json,
                    allowed_hpc_targets_json,
                    max_attempts,
                    max_micu,
                    max_cost_microunits,
                    max_wall_time_seconds,
                    consumed_attempts,
                    reserved_micu,
                    reserved_cost_microunits,
                    reserved_wall_time_seconds,
                    expires_at,
                    policy_digest,
                    idempotency_key,
                    request_digest,
                    status,
                    state_version,
                    created_at,
                    updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._values(record),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                session_id=record.session_id,
                grantor_ref=record.grantor_ref,
                idempotency_key=record.idempotency_key,
            )
            if (
                existing is not None
                and replace(
                    record,
                    envelope_id=existing.envelope_id,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific attempt authorization identity already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, envelope_id: str) -> ScientificAttemptAuthorization | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_authorization_records
            WHERE envelope_id = ?
            """,
            (envelope_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency(
        self,
        *,
        session_id: str,
        grantor_ref: str,
        idempotency_key: str,
    ) -> ScientificAttemptAuthorization | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_authorization_records
            WHERE session_id = ? AND grantor_ref = ? AND idempotency_key = ?
            """,
            (session_id, grantor_ref, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_session(
        self,
        session_id: str,
    ) -> list[ScientificAttemptAuthorization]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_authorization_records
            WHERE session_id = ?
            ORDER BY created_at, envelope_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def replace_consumption(
        self,
        record: ScientificAttemptAuthorization,
        *,
        expected_state_version: int,
    ) -> ScientificAttemptAuthorization:
        if record.state_version != expected_state_version + 1:
            raise ValueError("authority state_version must increase exactly once")
        cursor = self.connection.execute(
            """
            UPDATE scientific_attempt_authorization_records
            SET consumed_attempts = ?,
                reserved_micu = ?,
                reserved_cost_microunits = ?,
                reserved_wall_time_seconds = ?,
                status = ?,
                state_version = ?,
                updated_at = ?
            WHERE envelope_id = ? AND state_version = ?
            """,
            (
                record.consumed_attempts,
                record.reserved_micu,
                record.reserved_cost_microunits,
                record.reserved_wall_time_seconds,
                record.status.value,
                record.state_version,
                record.updated_at,
                record.envelope_id,
                expected_state_version,
            ),
        )
        if cursor.rowcount != 1:
            raise ScientificAttemptVersionConflictError(
                "scientific attempt authorization version changed"
            )
        _commit(self.connection)
        return record

    @staticmethod
    def _values(record: ScientificAttemptAuthorization) -> tuple[object, ...]:
        return (
            record.envelope_id,
            SCIENTIFIC_ATTEMPT_AUTHORIZATION_SCHEMA_VERSION,
            record.session_id,
            record.task_id,
            record.campaign_id,
            record.workflow_id,
            record.root_ref,
            record.grantor_kind,
            record.grantor_ref,
            _json_dumps([scope.value for scope in record.allowed_scopes]),
            _json_dumps(list(record.allowed_effect_classes)),
            _json_dumps(list(record.allowed_providers)),
            _json_dumps(list(record.allowed_hpc_targets)),
            record.max_attempts,
            record.max_micu,
            record.max_cost_microunits,
            record.max_wall_time_seconds,
            record.consumed_attempts,
            record.reserved_micu,
            record.reserved_cost_microunits,
            record.reserved_wall_time_seconds,
            record.expires_at,
            record.policy_digest,
            record.idempotency_key,
            record.request_digest,
            record.status.value,
            record.state_version,
            record.created_at,
            record.updated_at,
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificAttemptAuthorization:
        return ScientificAttemptAuthorization(
            envelope_id=row["envelope_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            campaign_id=row["campaign_id"],
            workflow_id=row["workflow_id"],
            root_ref=row["root_ref"],
            grantor_kind=row["grantor_kind"],
            grantor_ref=row["grantor_ref"],
            allowed_scopes=tuple(
                ScientificAttemptScope(item)
                for item in _json_loads_list(row["allowed_scopes_json"])
            ),
            allowed_effect_classes=_json_loads_list(row["allowed_effect_classes_json"]),
            allowed_providers=_json_loads_list(row["allowed_providers_json"]),
            allowed_hpc_targets=_json_loads_list(row["allowed_hpc_targets_json"]),
            max_attempts=int(row["max_attempts"]),
            max_micu=int(row["max_micu"]),
            max_cost_microunits=int(row["max_cost_microunits"]),
            max_wall_time_seconds=int(row["max_wall_time_seconds"]),
            consumed_attempts=int(row["consumed_attempts"]),
            reserved_micu=int(row["reserved_micu"]),
            reserved_cost_microunits=int(row["reserved_cost_microunits"]),
            reserved_wall_time_seconds=int(row["reserved_wall_time_seconds"]),
            expires_at=row["expires_at"],
            policy_digest=row["policy_digest"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            status=ScientificAttemptAuthorityStatus(row["status"]),
            state_version=int(row["state_version"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class ScientificAttemptAdmissionRequestRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: ScientificAttemptAdmissionRequest,
    ) -> ScientificAttemptAdmissionRequest:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_admission_request_records (
                    admission_request_id,
                    schema_version,
                    envelope_id,
                    session_id,
                    task_id,
                    lane_id,
                    campaign_id,
                    workflow_id,
                    scope,
                    workflow_contract_digest,
                    requested_effect_classes_json,
                    provider,
                    hpc_target,
                    reserved_micu,
                    reserved_cost_microunits,
                    reserved_wall_time_seconds,
                    actor_ref,
                    idempotency_key,
                    request_digest,
                    created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._values(record),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                envelope_id=record.envelope_id,
                idempotency_key=record.idempotency_key,
            )
            if existing == record:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific attempt admission request identity already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(
        self,
        admission_request_id: str,
    ) -> ScientificAttemptAdmissionRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_admission_request_records
            WHERE admission_request_id = ?
            """,
            (admission_request_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency(
        self,
        *,
        envelope_id: str,
        idempotency_key: str,
    ) -> ScientificAttemptAdmissionRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_admission_request_records
            WHERE envelope_id = ? AND idempotency_key = ?
            """,
            (envelope_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_session(
        self,
        session_id: str,
    ) -> list[ScientificAttemptAdmissionRequest]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_admission_request_records
            WHERE session_id = ?
            ORDER BY created_at, admission_request_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _values(
        record: ScientificAttemptAdmissionRequest,
    ) -> tuple[object, ...]:
        return (
            record.admission_request_id,
            SCIENTIFIC_ATTEMPT_ADMISSION_REQUEST_SCHEMA_VERSION,
            record.envelope_id,
            record.session_id,
            record.task_id,
            record.lane_id,
            record.campaign_id,
            record.workflow_id,
            record.scope.value,
            record.workflow_contract_digest,
            _json_dumps(list(record.requested_effect_classes)),
            record.provider,
            record.hpc_target,
            record.reserved_micu,
            record.reserved_cost_microunits,
            record.reserved_wall_time_seconds,
            record.actor_ref,
            record.idempotency_key,
            record.request_digest,
            record.created_at,
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificAttemptAdmissionRequest:
        return ScientificAttemptAdmissionRequest(
            admission_request_id=row["admission_request_id"],
            envelope_id=row["envelope_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            campaign_id=row["campaign_id"],
            workflow_id=row["workflow_id"],
            scope=ScientificAttemptScope(row["scope"]),
            workflow_contract_digest=row["workflow_contract_digest"],
            requested_effect_classes=_json_loads_list(
                row["requested_effect_classes_json"]
            ),
            provider=row["provider"],
            hpc_target=row["hpc_target"],
            reserved_micu=int(row["reserved_micu"]),
            reserved_cost_microunits=int(row["reserved_cost_microunits"]),
            reserved_wall_time_seconds=int(row["reserved_wall_time_seconds"]),
            actor_ref=row["actor_ref"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ScientificAttemptRepository:
    connection: sqlite3.Connection

    def add(self, record: ScientificAttempt) -> ScientificAttempt:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_records (
                    attempt_id,
                    schema_version,
                    admission_request_id,
                    envelope_id,
                    session_id,
                    task_id,
                    lane_id,
                    campaign_id,
                    workflow_id,
                    scope,
                    root_ref,
                    mutation_scope_id,
                    ordinal,
                    request_digest,
                    idempotency_key,
                    workflow_contract_digest,
                    requested_effect_classes_json,
                    provider,
                    hpc_target,
                    reserved_micu,
                    reserved_cost_microunits,
                    reserved_wall_time_seconds,
                    status,
                    state_version,
                    created_by,
                    created_at,
                    updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._values(record),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                envelope_id=record.envelope_id,
                idempotency_key=record.idempotency_key,
            )
            if (
                existing is not None
                and replace(
                    record,
                    attempt_id=existing.attempt_id,
                    root_ref=existing.root_ref,
                    mutation_scope_id=existing.mutation_scope_id,
                    ordinal=existing.ordinal,
                    created_at=existing.created_at,
                    updated_at=existing.updated_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific attempt identity already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, attempt_id: str) -> ScientificAttempt | None:
        row = self.connection.execute(
            "SELECT * FROM scientific_attempt_records WHERE attempt_id = ?",
            (attempt_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency(
        self,
        *,
        envelope_id: str,
        idempotency_key: str,
    ) -> ScientificAttempt | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_records
            WHERE envelope_id = ? AND idempotency_key = ?
            """,
            (envelope_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_admission_request(
        self,
        admission_request_id: str,
    ) -> ScientificAttempt | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_records
            WHERE admission_request_id = ?
            """,
            (admission_request_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_session(self, session_id: str) -> list[ScientificAttempt]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_records
            WHERE session_id = ?
            ORDER BY created_at, attempt_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def list_by_campaign(
        self,
        *,
        session_id: str,
        task_id: str,
        campaign_id: str,
    ) -> list[ScientificAttempt]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_records
            WHERE session_id = ? AND task_id = ? AND campaign_id = ?
            ORDER BY ordinal, attempt_id
            """,
            (session_id, task_id, campaign_id),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _values(record: ScientificAttempt) -> tuple[object, ...]:
        return (
            record.attempt_id,
            SCIENTIFIC_ATTEMPT_SCHEMA_VERSION,
            record.admission_request_id,
            record.envelope_id,
            record.session_id,
            record.task_id,
            record.lane_id,
            record.campaign_id,
            record.workflow_id,
            record.scope.value,
            record.root_ref,
            record.mutation_scope_id,
            record.ordinal,
            record.request_digest,
            record.idempotency_key,
            record.workflow_contract_digest,
            _json_dumps(list(record.requested_effect_classes)),
            record.provider,
            record.hpc_target,
            record.reserved_micu,
            record.reserved_cost_microunits,
            record.reserved_wall_time_seconds,
            record.status.value,
            record.state_version,
            record.created_by,
            record.created_at,
            record.updated_at,
        )

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificAttempt:
        return ScientificAttempt(
            attempt_id=row["attempt_id"],
            admission_request_id=row["admission_request_id"],
            envelope_id=row["envelope_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            campaign_id=row["campaign_id"],
            workflow_id=row["workflow_id"],
            scope=ScientificAttemptScope(row["scope"]),
            root_ref=row["root_ref"],
            mutation_scope_id=row["mutation_scope_id"],
            ordinal=int(row["ordinal"]),
            request_digest=row["request_digest"],
            idempotency_key=row["idempotency_key"],
            workflow_contract_digest=row["workflow_contract_digest"],
            requested_effect_classes=_json_loads_list(
                row["requested_effect_classes_json"]
            ),
            provider=row["provider"],
            hpc_target=row["hpc_target"],
            reserved_micu=int(row["reserved_micu"]),
            reserved_cost_microunits=int(row["reserved_cost_microunits"]),
            reserved_wall_time_seconds=int(row["reserved_wall_time_seconds"]),
            status=ScientificAttemptStatus(row["status"]),
            state_version=int(row["state_version"]),
            created_by=row["created_by"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )


@dataclass(slots=True)
class ScientificAttemptBindingRepository:
    connection: sqlite3.Connection

    def bind_run(
        self,
        *,
        attempt_id: str,
        sandbox_run_id: str,
        session_id: str,
        bound_by: str,
        created_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_run_bindings (
                    attempt_id,
                    sandbox_run_id,
                    session_id,
                    bound_by,
                    created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (attempt_id, sandbox_run_id, session_id, bound_by, created_at),
            )
        except sqlite3.IntegrityError as exc:
            row = self.connection.execute(
                """
                SELECT *
                FROM scientific_attempt_run_bindings
                WHERE sandbox_run_id = ?
                """,
                (sandbox_run_id,),
            ).fetchone()
            if row is not None and (
                row["attempt_id"],
                row["session_id"],
            ) == (attempt_id, session_id):
                _commit(self.connection)
                return
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "sandbox run is already bound to a different scientific attempt"
            ) from exc
        _commit(self.connection)

    def bind_operation(
        self,
        *,
        attempt_id: str,
        operation_id: str,
        sandbox_run_id: str,
        session_id: str,
        bound_by: str,
        created_at: str,
    ) -> None:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_operation_bindings (
                    attempt_id,
                    operation_id,
                    sandbox_run_id,
                    session_id,
                    bound_by,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    attempt_id,
                    operation_id,
                    sandbox_run_id,
                    session_id,
                    bound_by,
                    created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            row = self.connection.execute(
                """
                SELECT *
                FROM scientific_attempt_operation_bindings
                WHERE operation_id = ?
                """,
                (operation_id,),
            ).fetchone()
            if row is not None and (
                row["attempt_id"],
                row["sandbox_run_id"],
                row["session_id"],
            ) == (attempt_id, sandbox_run_id, session_id):
                _commit(self.connection)
                return
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "controlled operation is already bound to a different scientific attempt"
            ) from exc
        _commit(self.connection)

    def list_runs(self, attempt_id: str) -> tuple[str, ...]:
        rows = self.connection.execute(
            """
            SELECT sandbox_run_id
            FROM scientific_attempt_run_bindings
            WHERE attempt_id = ?
            ORDER BY created_at, sandbox_run_id
            """,
            (attempt_id,),
        ).fetchall()
        return tuple(row["sandbox_run_id"] for row in rows)

    def list_operations(self, attempt_id: str) -> tuple[dict[str, str], ...]:
        rows = self.connection.execute(
            """
            SELECT operation_id, sandbox_run_id, created_at
            FROM scientific_attempt_operation_bindings
            WHERE attempt_id = ?
            ORDER BY created_at, operation_id
            """,
            (attempt_id,),
        ).fetchall()
        return tuple(dict(row) for row in rows)

    def attempt_for_operation(self, operation_id: str) -> str | None:
        row = self.connection.execute(
            """
            SELECT attempt_id
            FROM scientific_attempt_operation_bindings
            WHERE operation_id = ?
            """,
            (operation_id,),
        ).fetchone()
        return None if row is None else str(row["attempt_id"])

    def attempt_for_run(self, sandbox_run_id: str) -> str | None:
        row = self.connection.execute(
            """
            SELECT attempt_id
            FROM scientific_attempt_run_bindings
            WHERE sandbox_run_id = ?
            """,
            (sandbox_run_id,),
        ).fetchone()
        return None if row is None else str(row["attempt_id"])


@dataclass(slots=True)
class ScientificSelectionRepository:
    connection: sqlite3.Connection

    def add(
        self,
        selection: ScientificChainSelection,
        occurrences: tuple[ScientificOccurrenceSnapshot, ...],
        *,
        expected_head_state_version: int | None,
    ) -> ScientificChainSelection:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_chain_selection_records (
                    selection_id,
                    schema_version,
                    attempt_id,
                    revision,
                    parent_selection_id,
                    state,
                    operation_universe_digest,
                    operation_count,
                    disposition_digest,
                    adoption_digest,
                    workflow_contract_digest,
                    actor_ref,
                    idempotency_key,
                    request_digest,
                    created_at,
                    sealed_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    selection.selection_id,
                    SCIENTIFIC_CHAIN_SELECTION_SCHEMA_VERSION,
                    selection.attempt_id,
                    selection.revision,
                    selection.parent_selection_id,
                    selection.state.value,
                    selection.operation_universe_digest,
                    selection.operation_count,
                    selection.disposition_digest,
                    selection.adoption_digest,
                    selection.workflow_contract_digest,
                    selection.actor_ref,
                    selection.idempotency_key,
                    selection.request_digest,
                    selection.created_at,
                    selection.sealed_at,
                ),
            )
            for occurrence in occurrences:
                self.connection.execute(
                    """
                    INSERT INTO scientific_selection_occurrence_records (
                        selection_id,
                        attempt_id,
                        operation_id,
                        sandbox_run_id,
                        occurrence_digest,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        occurrence.selection_id,
                        occurrence.attempt_id,
                        occurrence.operation_id,
                        occurrence.sandbox_run_id,
                        occurrence.occurrence_digest,
                        occurrence.created_at,
                    ),
                )
            if expected_head_state_version is None:
                self.connection.execute(
                    """
                    INSERT INTO scientific_selection_head_records (
                        attempt_id,
                        selection_id,
                        revision,
                        state_version,
                        updated_at
                    ) VALUES (?, ?, ?, 1, ?)
                    """,
                    (
                        selection.attempt_id,
                        selection.selection_id,
                        selection.revision,
                        selection.created_at,
                    ),
                )
            else:
                cursor = self.connection.execute(
                    """
                    UPDATE scientific_selection_head_records
                    SET selection_id = ?,
                        revision = ?,
                        state_version = state_version + 1,
                        updated_at = ?
                    WHERE attempt_id = ? AND state_version = ?
                    """,
                    (
                        selection.selection_id,
                        selection.revision,
                        selection.created_at,
                        selection.attempt_id,
                        expected_head_state_version,
                    ),
                )
                if cursor.rowcount != 1:
                    raise ScientificAttemptVersionConflictError(
                        "scientific selection head version changed"
                    )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                attempt_id=selection.attempt_id,
                actor_ref=selection.actor_ref,
                idempotency_key=selection.idempotency_key,
            )
            if (
                existing is not None
                and replace(
                    selection,
                    selection_id=existing.selection_id,
                    revision=existing.revision,
                    parent_selection_id=existing.parent_selection_id,
                    created_at=existing.created_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific selection identity already has different facts"
            ) from exc
        _commit(self.connection)
        return selection

    def get(self, selection_id: str) -> ScientificChainSelection | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_chain_selection_records
            WHERE selection_id = ?
            """,
            (selection_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency(
        self,
        *,
        attempt_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificChainSelection | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_chain_selection_records
            WHERE attempt_id = ? AND actor_ref = ? AND idempotency_key = ?
            """,
            (attempt_id, actor_ref, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_attempt(
        self,
        attempt_id: str,
    ) -> list[ScientificChainSelection]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_chain_selection_records
            WHERE attempt_id = ?
            ORDER BY revision, selection_id
            """,
            (attempt_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def resolve_head(
        self,
        attempt_id: str,
    ) -> ResolvedScientificSelectionHead | None:
        row = self.connection.execute(
            """
            SELECT
                head.attempt_id AS head_attempt_id,
                head.selection_id AS head_selection_id,
                head.revision AS head_revision,
                head.state_version AS head_state_version,
                head.updated_at AS head_updated_at,
                selection.selection_id AS selection_selection_id,
                selection.attempt_id AS selection_attempt_id,
                selection.revision AS selection_revision,
                selection.parent_selection_id AS selection_parent_selection_id,
                selection.state AS selection_state,
                selection.operation_universe_digest
                    AS selection_operation_universe_digest,
                selection.operation_count AS selection_operation_count,
                selection.disposition_digest AS selection_disposition_digest,
                selection.adoption_digest AS selection_adoption_digest,
                selection.workflow_contract_digest
                    AS selection_workflow_contract_digest,
                selection.actor_ref AS selection_actor_ref,
                selection.idempotency_key AS selection_idempotency_key,
                selection.request_digest AS selection_request_digest,
                selection.created_at AS selection_created_at,
                selection.sealed_at AS selection_sealed_at
            FROM scientific_selection_head_records AS head
            LEFT JOIN scientific_chain_selection_records AS selection
              ON selection.selection_id = head.selection_id
            WHERE head.attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        if row is None:
            return None
        if row["selection_selection_id"] is None:
            raise ScientificSelectionIntegrityError("selection_missing")
        if row["head_attempt_id"] != row["selection_attempt_id"]:
            raise ScientificSelectionIntegrityError("attempt_mismatch")
        if int(row["head_revision"]) != int(row["selection_revision"]):
            raise ScientificSelectionIntegrityError("revision_mismatch")
        head = ScientificSelectionHead(
            attempt_id=row["head_attempt_id"],
            selection_id=row["head_selection_id"],
            revision=int(row["head_revision"]),
            state_version=int(row["head_state_version"]),
            updated_at=row["head_updated_at"],
        )
        selection = ScientificChainSelection(
            selection_id=row["selection_selection_id"],
            attempt_id=row["selection_attempt_id"],
            revision=int(row["selection_revision"]),
            parent_selection_id=row["selection_parent_selection_id"],
            state=ScientificSelectionState(row["selection_state"]),
            operation_universe_digest=row["selection_operation_universe_digest"],
            operation_count=int(row["selection_operation_count"]),
            disposition_digest=row["selection_disposition_digest"],
            adoption_digest=row["selection_adoption_digest"],
            workflow_contract_digest=row["selection_workflow_contract_digest"],
            actor_ref=row["selection_actor_ref"],
            idempotency_key=row["selection_idempotency_key"],
            request_digest=row["selection_request_digest"],
            created_at=row["selection_created_at"],
            sealed_at=row["selection_sealed_at"],
        )
        return ResolvedScientificSelectionHead(head=head, selection=selection)

    def get_head(self, attempt_id: str) -> ScientificSelectionHead | None:
        resolved = self.resolve_head(attempt_id)
        return None if resolved is None else resolved.head

    def list_occurrences(
        self,
        selection_id: str,
    ) -> tuple[ScientificOccurrenceSnapshot, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_selection_occurrence_records
            WHERE selection_id = ?
            ORDER BY operation_id
            """,
            (selection_id,),
        ).fetchall()
        return tuple(
            ScientificOccurrenceSnapshot(
                selection_id=row["selection_id"],
                attempt_id=row["attempt_id"],
                operation_id=row["operation_id"],
                sandbox_run_id=row["sandbox_run_id"],
                occurrence_digest=row["occurrence_digest"],
                created_at=row["created_at"],
            )
            for row in rows
        )

    def seal(
        self,
        selection: ScientificChainSelection,
        *,
        expected_state: ScientificSelectionState,
    ) -> ScientificChainSelection:
        cursor = self.connection.execute(
            """
            UPDATE scientific_chain_selection_records
            SET state = ?,
                disposition_digest = ?,
                adoption_digest = ?,
                sealed_at = ?
            WHERE selection_id = ? AND state = ?
            """,
            (
                selection.state.value,
                selection.disposition_digest,
                selection.adoption_digest,
                selection.sealed_at,
                selection.selection_id,
                expected_state.value,
            ),
        )
        if cursor.rowcount != 1:
            existing = self.get(selection.selection_id)
            if existing == selection:
                _commit(self.connection)
                return selection
            raise ScientificAttemptVersionConflictError(
                "scientific selection was already sealed or changed"
            )
        _commit(self.connection)
        return selection

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificChainSelection:
        return ScientificChainSelection(
            selection_id=row["selection_id"],
            attempt_id=row["attempt_id"],
            revision=int(row["revision"]),
            parent_selection_id=row["parent_selection_id"],
            state=ScientificSelectionState(row["state"]),
            operation_universe_digest=row["operation_universe_digest"],
            operation_count=int(row["operation_count"]),
            disposition_digest=row["disposition_digest"],
            adoption_digest=row["adoption_digest"],
            workflow_contract_digest=row["workflow_contract_digest"],
            actor_ref=row["actor_ref"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
            sealed_at=row["sealed_at"],
        )


@dataclass(slots=True)
class ScientificDispositionRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: ScientificOperationDisposition,
    ) -> ScientificOperationDisposition:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_operation_disposition_records (
                    disposition_id,
                    schema_version,
                    selection_id,
                    attempt_id,
                    operation_id,
                    kind,
                    workflow_role,
                    reason_code,
                    replacement_operation_id,
                    actor_ref,
                    idempotency_key,
                    request_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.disposition_id,
                    SCIENTIFIC_OPERATION_DISPOSITION_SCHEMA_VERSION,
                    record.selection_id,
                    record.attempt_id,
                    record.operation_id,
                    record.kind.value,
                    record.workflow_role,
                    record.reason_code,
                    record.replacement_operation_id,
                    record.actor_ref,
                    record.idempotency_key,
                    record.request_digest,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                selection_id=record.selection_id,
                actor_ref=record.actor_ref,
                idempotency_key=record.idempotency_key,
            )
            if (
                existing is not None
                and replace(
                    record,
                    disposition_id=existing.disposition_id,
                    created_at=existing.created_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific disposition identity already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get_by_idempotency(
        self,
        *,
        selection_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificOperationDisposition | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_operation_disposition_records
            WHERE selection_id = ? AND actor_ref = ? AND idempotency_key = ?
            """,
            (selection_id, actor_ref, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_selection(
        self,
        selection_id: str,
    ) -> tuple[ScientificOperationDisposition, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_operation_disposition_records
            WHERE selection_id = ?
            ORDER BY operation_id
            """,
            (selection_id,),
        ).fetchall()
        return tuple(self._row(row) for row in rows)

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificOperationDisposition:
        return ScientificOperationDisposition(
            disposition_id=row["disposition_id"],
            selection_id=row["selection_id"],
            attempt_id=row["attempt_id"],
            operation_id=row["operation_id"],
            kind=ScientificOperationDispositionKind(row["kind"]),
            workflow_role=row["workflow_role"],
            reason_code=row["reason_code"],
            replacement_operation_id=row["replacement_operation_id"],
            actor_ref=row["actor_ref"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ScientificEffectAdoptionRepository:
    connection: sqlite3.Connection

    def add(self, record: ScientificEffectAdoption) -> ScientificEffectAdoption:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_effect_adoption_records (
                    adoption_id,
                    schema_version,
                    selection_id,
                    attempt_id,
                    workflow_role,
                    operation_id,
                    execution_id,
                    result_handle_id,
                    result_digest,
                    effect_certainty,
                    approval_digest,
                    actor_ref,
                    idempotency_key,
                    request_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.adoption_id,
                    SCIENTIFIC_EFFECT_ADOPTION_SCHEMA_VERSION,
                    record.selection_id,
                    record.attempt_id,
                    record.workflow_role,
                    record.operation_id,
                    record.execution_id,
                    record.result_handle_id,
                    record.result_digest,
                    record.effect_certainty,
                    record.approval_digest,
                    record.actor_ref,
                    record.idempotency_key,
                    record.request_digest,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                selection_id=record.selection_id,
                actor_ref=record.actor_ref,
                idempotency_key=record.idempotency_key,
            )
            if (
                existing is not None
                and replace(
                    record,
                    adoption_id=existing.adoption_id,
                    created_at=existing.created_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific effect adoption identity already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, adoption_id: str) -> ScientificEffectAdoption | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_effect_adoption_records
            WHERE adoption_id = ?
            """,
            (adoption_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency(
        self,
        *,
        selection_id: str,
        actor_ref: str,
        idempotency_key: str,
    ) -> ScientificEffectAdoption | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_effect_adoption_records
            WHERE selection_id = ? AND actor_ref = ? AND idempotency_key = ?
            """,
            (selection_id, actor_ref, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_selection(
        self,
        selection_id: str,
    ) -> tuple[ScientificEffectAdoption, ...]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM scientific_effect_adoption_records
            WHERE selection_id = ?
            ORDER BY workflow_role, operation_id
            """,
            (selection_id,),
        ).fetchall()
        return tuple(self._row(row) for row in rows)

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificEffectAdoption:
        return ScientificEffectAdoption(
            adoption_id=row["adoption_id"],
            selection_id=row["selection_id"],
            attempt_id=row["attempt_id"],
            workflow_role=row["workflow_role"],
            operation_id=row["operation_id"],
            execution_id=row["execution_id"],
            result_handle_id=row["result_handle_id"],
            result_digest=row["result_digest"],
            effect_certainty=row["effect_certainty"],
            approval_digest=row["approval_digest"],
            actor_ref=row["actor_ref"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ScientificAttemptClosureRequestRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: ScientificAttemptClosureRequest,
    ) -> ScientificAttemptClosureRequest:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_closure_request_records (
                    closure_request_id,
                    schema_version,
                    attempt_id,
                    selection_id,
                    actor_ref,
                    idempotency_key,
                    request_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.closure_request_id,
                    SCIENTIFIC_ATTEMPT_CLOSURE_REQUEST_SCHEMA_VERSION,
                    record.attempt_id,
                    record.selection_id,
                    record.actor_ref,
                    record.idempotency_key,
                    record.request_digest,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_attempt(record.attempt_id)
            if (
                existing is not None
                and replace(
                    record,
                    closure_request_id=existing.closure_request_id,
                    created_at=existing.created_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific attempt closure request already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(
        self,
        closure_request_id: str,
    ) -> ScientificAttemptClosureRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_closure_request_records
            WHERE closure_request_id = ?
            """,
            (closure_request_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_attempt(
        self,
        attempt_id: str,
    ) -> ScientificAttemptClosureRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_closure_request_records
            WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_session(
        self,
        session_id: str,
    ) -> list[ScientificAttemptClosureRequest]:
        rows = self.connection.execute(
            """
            SELECT request.*
            FROM scientific_attempt_closure_request_records AS request
            JOIN scientific_attempt_records AS attempt
              ON attempt.attempt_id = request.attempt_id
            WHERE attempt.session_id = ?
            ORDER BY request.created_at, request.closure_request_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificAttemptClosureRequest:
        return ScientificAttemptClosureRequest(
            closure_request_id=row["closure_request_id"],
            attempt_id=row["attempt_id"],
            selection_id=row["selection_id"],
            actor_ref=row["actor_ref"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class ScientificAttemptClosureRepository:
    connection: sqlite3.Connection

    def add(self, record: ScientificAttemptClosure) -> ScientificAttemptClosure:
        try:
            self.connection.execute(
                """
                INSERT INTO scientific_attempt_closure_records (
                    closure_id,
                    schema_version,
                    closure_request_id,
                    attempt_id,
                    selection_id,
                    operation_universe_digest,
                    disposition_digest,
                    adoption_digest,
                    authority_consumption_digest,
                    quiescence_receipt_id,
                    quiescence_receipt_digest,
                    closure_digest,
                    actor_ref,
                    idempotency_key,
                    request_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.closure_id,
                    SCIENTIFIC_ATTEMPT_CLOSURE_SCHEMA_VERSION,
                    record.closure_request_id,
                    record.attempt_id,
                    record.selection_id,
                    record.operation_universe_digest,
                    record.disposition_digest,
                    record.adoption_digest,
                    record.authority_consumption_digest,
                    record.quiescence_receipt_id,
                    record.quiescence_receipt_digest,
                    record.closure_digest,
                    record.actor_ref,
                    record.idempotency_key,
                    record.request_digest,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_attempt(record.attempt_id)
            if (
                existing is not None
                and replace(
                    record,
                    closure_id=existing.closure_id,
                    created_at=existing.created_at,
                )
                == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise ScientificAttemptIdentityConflictError(
                "scientific attempt closure identity already has different facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, closure_id: str) -> ScientificAttemptClosure | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_closure_records
            WHERE closure_id = ?
            """,
            (closure_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_attempt(self, attempt_id: str) -> ScientificAttemptClosure | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM scientific_attempt_closure_records
            WHERE attempt_id = ?
            """,
            (attempt_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_session(self, session_id: str) -> list[ScientificAttemptClosure]:
        rows = self.connection.execute(
            """
            SELECT closure.*
            FROM scientific_attempt_closure_records AS closure
            JOIN scientific_attempt_records AS attempt
              ON attempt.attempt_id = closure.attempt_id
            WHERE attempt.session_id = ?
            ORDER BY closure.created_at, closure.closure_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    @staticmethod
    def _row(row: sqlite3.Row) -> ScientificAttemptClosure:
        return ScientificAttemptClosure(
            closure_id=row["closure_id"],
            closure_request_id=row["closure_request_id"],
            attempt_id=row["attempt_id"],
            selection_id=row["selection_id"],
            operation_universe_digest=row["operation_universe_digest"],
            disposition_digest=row["disposition_digest"],
            adoption_digest=row["adoption_digest"],
            authority_consumption_digest=row["authority_consumption_digest"],
            quiescence_receipt_id=row["quiescence_receipt_id"],
            quiescence_receipt_digest=row["quiescence_receipt_digest"],
            closure_digest=row["closure_digest"],
            actor_ref=row["actor_ref"],
            idempotency_key=row["idempotency_key"],
            request_digest=row["request_digest"],
            created_at=row["created_at"],
        )


__all__ = [
    "ScientificAttemptAdmissionRequestRepository",
    "ScientificAttemptAuthorizationRepository",
    "ScientificAttemptBindingRepository",
    "ScientificAttemptClosureRequestRepository",
    "ScientificAttemptClosureRepository",
    "ScientificAttemptIdentityConflictError",
    "ScientificAttemptRepository",
    "ScientificAttemptRepositoryError",
    "ScientificAttemptVersionConflictError",
    "ScientificDispositionRepository",
    "ScientificEffectAdoptionRepository",
    "ScientificOccurrenceSnapshot",
    "ResolvedScientificSelectionHead",
    "ScientificSelectionHead",
    "ScientificSelectionIntegrityError",
    "ScientificSelectionRepository",
]
