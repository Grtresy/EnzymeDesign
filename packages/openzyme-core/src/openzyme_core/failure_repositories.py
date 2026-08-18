from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import sqlite3

from openzyme_domain import FAILURE_OBSERVATION_SCHEMA_VERSION
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoverability
from openzyme_domain import PrivateDiagnosticRecord
from openzyme_domain import RetryEligibility

from .repositories import _commit
from .repositories import _json_dumps
from .repositories import _json_loads_list
from .repositories import _json_loads_object
from .repositories import _json_loads_object_tuple
from .repositories import _require_enum_member
from .repositories import _require_session_exists


class FailureObservationConflictError(RuntimeError):
    """The same source version was already observed with different facts."""


class PrivateDiagnosticConflictError(RuntimeError):
    """The immutable diagnostic identity already has different evidence."""


@dataclass(slots=True)
class PrivateDiagnosticRepository:
    connection: sqlite3.Connection

    def add(self, record: PrivateDiagnosticRecord) -> PrivateDiagnosticRecord:
        try:
            self.connection.execute(
                """
                INSERT INTO private_diagnostic_records (
                    diagnostic_id, schema_version, failure_id, session_id,
                    component, operation, phase, exception_type,
                    exception_message, traceback_text, cause_chain_json,
                    errno, return_code, bounded_stdout, bounded_stderr,
                    private_context_json, source_kind, source_ref,
                    source_version, correlation_id, created_at, record_digest
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                (
                    record.diagnostic_id,
                    record.schema_version,
                    record.failure_id,
                    record.session_id,
                    record.component,
                    record.operation,
                    record.phase,
                    record.exception_type,
                    record.exception_message,
                    record.traceback_text,
                    _json_dumps(list(record.cause_chain)),
                    record.errno,
                    record.return_code,
                    record.bounded_stdout,
                    record.bounded_stderr,
                    _json_dumps(record.private_context),
                    record.source_kind,
                    record.source_ref,
                    record.source_version,
                    record.correlation_id,
                    record.created_at,
                    record.record_digest,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self._get(record.diagnostic_id)
            if existing == record:
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise PrivateDiagnosticConflictError(
                "private diagnostic identity already has different immutable evidence"
            ) from exc
        _commit(self.connection)
        return record

    def get_for_operator(
        self,
        diagnostic_id: str,
        *,
        operator_authorized: bool,
    ) -> PrivateDiagnosticRecord | None:
        if not operator_authorized:
            raise PermissionError("private diagnostic lookup requires operator authority")
        return self._get(diagnostic_id)

    def _get(self, diagnostic_id: str) -> PrivateDiagnosticRecord | None:
        row = self.connection.execute(
            "SELECT * FROM private_diagnostic_records WHERE diagnostic_id = ?",
            (diagnostic_id,),
        ).fetchone()
        if row is None:
            return None
        return PrivateDiagnosticRecord(
            diagnostic_id=row["diagnostic_id"],
            failure_id=row["failure_id"],
            session_id=row["session_id"],
            component=row["component"],
            operation=row["operation"],
            phase=row["phase"],
            exception_type=row["exception_type"],
            exception_message=row["exception_message"],
            traceback_text=row["traceback_text"],
            cause_chain=_json_loads_object_tuple(row["cause_chain_json"]),
            errno=row["errno"],
            return_code=row["return_code"],
            bounded_stdout=row["bounded_stdout"],
            bounded_stderr=row["bounded_stderr"],
            private_context=_json_loads_object(row["private_context_json"]) or {},
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            source_version=row["source_version"],
            correlation_id=row["correlation_id"],
            created_at=row["created_at"],
            record_digest=row["record_digest"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class FailureObservationRepository:
    connection: sqlite3.Connection

    def add(self, record: FailureObservation) -> FailureObservation:
        self._validate(record)
        try:
            self.connection.execute(
                """
                INSERT INTO failure_observation_records (
                    failure_id,
                    schema_version,
                    session_id,
                    task_id,
                    lane_id,
                    agent_id,
                    source_kind,
                    source_ref,
                    source_version,
                    phase,
                    failure_class,
                    recoverability,
                    effect_certainty,
                    retry_eligibility,
                    actor_kind,
                    error_code,
                    safe_summary,
                    safe_hint,
                    facts_json,
                    likely_causes_json,
                    evidence_refs_json,
                    private_diagnostic_digest,
                    component,
                    operation,
                    identities_json,
                    mutation_applied,
                    fallback_performed,
                    cause_chain_json,
                    diagnostic_id,
                    next_action,
                    created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                """,
                self._record_values(record),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_source(
                session_id=record.session_id,
                source_kind=record.source_kind,
                source_ref=record.source_ref,
                source_version=record.source_version,
                phase=record.phase,
                error_code=record.error_code,
            )
            if (
                existing is not None
                and replace(record, created_at=existing.created_at) == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise FailureObservationConflictError(
                "failure source version already has different canonical facts"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, failure_id: str) -> FailureObservation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM failure_observation_records
            WHERE failure_id = ?
            """,
            (failure_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_source(
        self,
        *,
        session_id: str,
        source_kind: str,
        source_ref: str,
        source_version: str,
        phase: str,
        error_code: str,
    ) -> FailureObservation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM failure_observation_records
            WHERE session_id = ?
              AND source_kind = ?
              AND source_ref = ?
              AND source_version = ?
              AND phase = ?
              AND error_code = ?
            """,
            (
                session_id,
                source_kind,
                source_ref,
                source_version,
                phase,
                error_code,
            ),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 1_000,
    ) -> list[FailureObservation]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("failure observation limit is invalid")
        rows = self.connection.execute(
            """
            SELECT *
            FROM failure_observation_records
            WHERE session_id = ?
            ORDER BY created_at, failure_id
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_source(
        self,
        *,
        session_id: str,
        source_kind: str,
        source_ref: str,
    ) -> list[FailureObservation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM failure_observation_records
            WHERE session_id = ?
              AND source_kind = ?
              AND source_ref = ?
            ORDER BY created_at, failure_id
            """,
            (session_id, source_kind, source_ref),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _validate(self, record: FailureObservation) -> None:
        _require_session_exists(self.connection, record.session_id)
        _require_enum_member(
            record.failure_class,
            FailureClass,
            "FailureObservation.failure_class",
        )
        _require_enum_member(
            record.recoverability,
            FailureRecoverability,
            "FailureObservation.recoverability",
        )
        _require_enum_member(
            record.effect_certainty,
            ExternalEffectCertainty,
            "FailureObservation.effect_certainty",
        )
        _require_enum_member(
            record.retry_eligibility,
            RetryEligibility,
            "FailureObservation.retry_eligibility",
        )
        _require_enum_member(
            record.actor_kind,
            FailureActorKind,
            "FailureObservation.actor_kind",
        )
        for name, value in (
            ("failure_id", record.failure_id),
            ("source_kind", record.source_kind),
            ("source_ref", record.source_ref),
            ("source_version", record.source_version),
            ("phase", record.phase),
            ("error_code", record.error_code),
            ("safe_summary", record.safe_summary),
            ("created_at", record.created_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"FailureObservation.{name} must be non-empty")

    @staticmethod
    def _record_values(record: FailureObservation) -> tuple[object, ...]:
        return (
            record.failure_id,
            FAILURE_OBSERVATION_SCHEMA_VERSION,
            record.session_id,
            record.task_id,
            record.lane_id,
            record.agent_id,
            record.source_kind,
            record.source_ref,
            record.source_version,
            record.phase,
            record.failure_class.value,
            record.recoverability.value,
            record.effect_certainty.value,
            record.retry_eligibility.value,
            record.actor_kind.value,
            record.error_code,
            record.safe_summary,
            record.safe_hint,
            _json_dumps(record.facts),
            _json_dumps(list(record.likely_causes)),
            _json_dumps(list(record.evidence_refs)),
            record.private_diagnostic_digest,
            record.component,
            record.operation,
            _json_dumps(record.identities or {}),
            int(record.mutation_applied),
            int(record.fallback_performed),
            _json_dumps(list(record.cause_chain)),
            record.diagnostic_id,
            record.next_action,
            record.created_at,
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> FailureObservation:
        return FailureObservation(
            failure_id=row["failure_id"],
            session_id=row["session_id"],
            task_id=row["task_id"],
            lane_id=row["lane_id"],
            agent_id=row["agent_id"],
            source_kind=row["source_kind"],
            source_ref=row["source_ref"],
            source_version=row["source_version"],
            phase=row["phase"],
            failure_class=FailureClass(row["failure_class"]),
            recoverability=FailureRecoverability(row["recoverability"]),
            effect_certainty=ExternalEffectCertainty(row["effect_certainty"]),
            retry_eligibility=RetryEligibility(row["retry_eligibility"]),
            actor_kind=FailureActorKind(row["actor_kind"]),
            error_code=row["error_code"],
            safe_summary=row["safe_summary"],
            safe_hint=row["safe_hint"],
            facts=_json_loads_object(row["facts_json"]) or {},
            likely_causes=_json_loads_list(row["likely_causes_json"]),
            evidence_refs=_json_loads_list(row["evidence_refs_json"]),
            private_diagnostic_digest=row["private_diagnostic_digest"],
            component=row["component"],
            operation=row["operation"],
            identities=_json_loads_object(row["identities_json"]) or {},
            mutation_applied=bool(row["mutation_applied"]),
            fallback_performed=bool(row["fallback_performed"]),
            cause_chain=_json_loads_object_tuple(row["cause_chain_json"]),
            diagnostic_id=row["diagnostic_id"],
            next_action=row["next_action"],
            created_at=row["created_at"],
        )


__all__ = [
    "FailureObservationConflictError",
    "FailureObservationRepository",
    "PrivateDiagnosticConflictError",
    "PrivateDiagnosticRepository",
]
