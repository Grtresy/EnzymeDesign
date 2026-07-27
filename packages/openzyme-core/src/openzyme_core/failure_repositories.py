from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
import sqlite3
from typing import Any

from openzyme_domain import FAILURE_HYPOTHESIS_SCHEMA_VERSION
from openzyme_domain import FAILURE_OBSERVATION_SCHEMA_VERSION
from openzyme_domain import FAILURE_RECOVERY_DISPOSITION_SCHEMA_VERSION
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureClass
from openzyme_domain import FailureHypothesis
from openzyme_domain import FailureHypothesisConfidence
from openzyme_domain import FailureObservation
from openzyme_domain import FailureRecoveryDisposition
from openzyme_domain import FailureRecoveryDispositionKind
from openzyme_domain import FailureRecoverability
from openzyme_domain import RetryEligibility

from .repositories import _commit
from .repositories import _json_dumps
from .repositories import _json_loads_list
from .repositories import _json_loads_object
from .repositories import _require_enum_member
from .repositories import _require_session_exists


class FailureObservationConflictError(RuntimeError):
    """The same source version was already observed with different facts."""


class FailureHypothesisConflictError(RuntimeError):
    """An idempotency identity already names different hypothesis content."""


class FailureRecoveryDispositionConflictError(RuntimeError):
    """An idempotency identity already names a different recovery decision."""


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
                    agent_hypothesis,
                    agent_hypothesis_confidence,
                    agent_hypothesis_evidence_refs_json,
                    private_diagnostic_digest,
                    created_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                    ?, ?, ?, ?, ?, ?, ?, ?
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
            record.agent_hypothesis,
            record.agent_hypothesis_confidence,
            _json_dumps(list(record.agent_hypothesis_evidence_refs)),
            record.private_diagnostic_digest,
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
            agent_hypothesis=row["agent_hypothesis"],
            agent_hypothesis_confidence=row["agent_hypothesis_confidence"],
            agent_hypothesis_evidence_refs=_json_loads_list(
                row["agent_hypothesis_evidence_refs_json"]
            ),
            private_diagnostic_digest=row["private_diagnostic_digest"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class FailureHypothesisRepository:
    connection: sqlite3.Connection

    def add(self, record: FailureHypothesis) -> FailureHypothesis:
        self._validate(record)
        try:
            self.connection.execute(
                """
                INSERT INTO failure_hypothesis_records (
                    hypothesis_id,
                    schema_version,
                    failure_id,
                    session_id,
                    agent_id,
                    hypothesis,
                    confidence,
                    evidence_refs_json,
                    idempotency_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.hypothesis_id,
                    FAILURE_HYPOTHESIS_SCHEMA_VERSION,
                    record.failure_id,
                    record.session_id,
                    record.agent_id,
                    record.hypothesis,
                    record.confidence.value,
                    _json_dumps(list(record.evidence_refs)),
                    record.idempotency_digest,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                session_id=record.session_id,
                agent_id=record.agent_id,
                idempotency_digest=record.idempotency_digest,
            )
            if (
                existing is not None
                and replace(record, created_at=existing.created_at) == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise FailureHypothesisConflictError(
                "failure hypothesis idempotency identity already has different content"
            ) from exc
        _commit(self.connection)
        return record

    def get(self, hypothesis_id: str) -> FailureHypothesis | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM failure_hypothesis_records
            WHERE hypothesis_id = ?
            """,
            (hypothesis_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_idempotency(
        self,
        *,
        session_id: str,
        agent_id: str,
        idempotency_digest: str,
    ) -> FailureHypothesis | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM failure_hypothesis_records
            WHERE session_id = ?
              AND agent_id = ?
              AND idempotency_digest = ?
            """,
            (session_id, agent_id, idempotency_digest),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_failure(self, failure_id: str) -> list[FailureHypothesis]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM failure_hypothesis_records
            WHERE failure_id = ?
            ORDER BY created_at, hypothesis_id
            """,
            (failure_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 1_000,
    ) -> list[FailureHypothesis]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("failure hypothesis limit is invalid")
        rows = self.connection.execute(
            """
            SELECT *
            FROM failure_hypothesis_records
            WHERE session_id = ?
            ORDER BY created_at, hypothesis_id
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _validate(self, record: FailureHypothesis) -> None:
        _require_session_exists(self.connection, record.session_id)
        _require_enum_member(
            record.confidence,
            FailureHypothesisConfidence,
            "FailureHypothesis.confidence",
        )
        for name, value in (
            ("hypothesis_id", record.hypothesis_id),
            ("failure_id", record.failure_id),
            ("agent_id", record.agent_id),
            ("hypothesis", record.hypothesis),
            ("idempotency_digest", record.idempotency_digest),
            ("created_at", record.created_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"FailureHypothesis.{name} must be non-empty")
        if len(record.hypothesis) > 2_000:
            raise ValueError("FailureHypothesis.hypothesis exceeds 2000 characters")
        if len(record.evidence_refs) > 32 or any(
            not isinstance(value, str) or not value.strip()
            for value in record.evidence_refs
        ):
            raise ValueError("FailureHypothesis.evidence_refs are invalid")
        if len(set(record.evidence_refs)) != len(record.evidence_refs):
            raise ValueError("FailureHypothesis.evidence_refs must be unique")
        failure = self.connection.execute(
            """
            SELECT session_id
            FROM failure_observation_records
            WHERE failure_id = ?
            """,
            (record.failure_id,),
        ).fetchone()
        if failure is None or failure["session_id"] != record.session_id:
            raise ValueError(
                "FailureHypothesis.failure_id must belong to the same session"
            )
        agent = self.connection.execute(
            """
            SELECT 1
            FROM agent_members
            WHERE session_id = ?
              AND agent_id = ?
            """,
            (record.session_id, record.agent_id),
        ).fetchone()
        if agent is None:
            raise ValueError(
                "FailureHypothesis.agent_id must name a canonical session agent"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> FailureHypothesis:
        return FailureHypothesis(
            hypothesis_id=row["hypothesis_id"],
            failure_id=row["failure_id"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            hypothesis=row["hypothesis"],
            confidence=FailureHypothesisConfidence(row["confidence"]),
            evidence_refs=_json_loads_list(row["evidence_refs_json"]),
            idempotency_digest=row["idempotency_digest"],
            created_at=row["created_at"],
        )


@dataclass(slots=True)
class FailureRecoveryDispositionRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: FailureRecoveryDisposition,
    ) -> FailureRecoveryDisposition:
        self._validate(record)
        try:
            self.connection.execute(
                """
                INSERT INTO failure_recovery_disposition_records (
                    disposition_id,
                    schema_version,
                    failure_id,
                    session_id,
                    agent_id,
                    disposition,
                    condition_task_ids_json,
                    rationale,
                    idempotency_digest,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    record.disposition_id,
                    FAILURE_RECOVERY_DISPOSITION_SCHEMA_VERSION,
                    record.failure_id,
                    record.session_id,
                    record.agent_id,
                    record.disposition.value,
                    _json_dumps(list(record.condition_task_ids)),
                    record.rationale,
                    record.idempotency_digest,
                    record.created_at,
                ),
            )
        except sqlite3.IntegrityError as exc:
            existing = self.get_by_idempotency(
                session_id=record.session_id,
                agent_id=record.agent_id,
                idempotency_digest=record.idempotency_digest,
            )
            if (
                existing is not None
                and replace(record, created_at=existing.created_at) == existing
            ):
                _commit(self.connection)
                return existing
            _commit(self.connection)
            raise FailureRecoveryDispositionConflictError(
                "failure recovery disposition idempotency identity already "
                "has different content"
            ) from exc
        _commit(self.connection)
        return record

    def get(
        self,
        disposition_id: str,
    ) -> FailureRecoveryDisposition | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM failure_recovery_disposition_records
            WHERE disposition_id = ?
            """,
            (disposition_id,),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def get_by_idempotency(
        self,
        *,
        session_id: str,
        agent_id: str,
        idempotency_digest: str,
    ) -> FailureRecoveryDisposition | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM failure_recovery_disposition_records
            WHERE session_id = ?
              AND agent_id = ?
              AND idempotency_digest = ?
            """,
            (session_id, agent_id, idempotency_digest),
        ).fetchone()
        return None if row is None else self._row_to_record(row)

    def list_by_failure(
        self,
        failure_id: str,
    ) -> list[FailureRecoveryDisposition]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM failure_recovery_disposition_records
            WHERE failure_id = ?
            ORDER BY created_at, disposition_id
            """,
            (failure_id,),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def list_by_session(
        self,
        session_id: str,
        *,
        limit: int = 1_000,
    ) -> list[FailureRecoveryDisposition]:
        if limit <= 0 or limit > 10_000:
            raise ValueError("failure recovery disposition limit is invalid")
        rows = self.connection.execute(
            """
            SELECT *
            FROM failure_recovery_disposition_records
            WHERE session_id = ?
            ORDER BY created_at, disposition_id
            LIMIT ?
            """,
            (session_id, limit),
        ).fetchall()
        return [self._row_to_record(row) for row in rows]

    def _validate(self, record: FailureRecoveryDisposition) -> None:
        _require_session_exists(self.connection, record.session_id)
        _require_enum_member(
            record.disposition,
            FailureRecoveryDispositionKind,
            "FailureRecoveryDisposition.disposition",
        )
        for name, value in (
            ("disposition_id", record.disposition_id),
            ("failure_id", record.failure_id),
            ("agent_id", record.agent_id),
            ("rationale", record.rationale),
            ("idempotency_digest", record.idempotency_digest),
            ("created_at", record.created_at),
        ):
            if not isinstance(value, str) or not value.strip():
                raise ValueError(
                    f"FailureRecoveryDisposition.{name} must be non-empty"
                )
        if len(record.rationale) > 2_000:
            raise ValueError(
                "FailureRecoveryDisposition.rationale exceeds 2000 characters"
            )
        if (
            not record.condition_task_ids
            or len(record.condition_task_ids) > 32
            or any(
                not isinstance(value, str) or not value.strip()
                for value in record.condition_task_ids
            )
        ):
            raise ValueError(
                "FailureRecoveryDisposition.condition_task_ids are invalid"
            )
        if len(set(record.condition_task_ids)) != len(
            record.condition_task_ids
        ):
            raise ValueError(
                "FailureRecoveryDisposition.condition_task_ids must be unique"
            )
        if record.condition_task_ids != tuple(
            sorted(record.condition_task_ids)
        ):
            raise ValueError(
                "FailureRecoveryDisposition.condition_task_ids must be "
                "canonically sorted"
            )
        failure = self.connection.execute(
            """
            SELECT session_id, agent_id
            FROM failure_observation_records
            WHERE failure_id = ?
            """,
            (record.failure_id,),
        ).fetchone()
        if (
            failure is None
            or failure["session_id"] != record.session_id
            or failure["agent_id"] != record.agent_id
        ):
            raise ValueError(
                "FailureRecoveryDisposition.failure_id must belong to the "
                "same session and canonical agent"
            )
        agent = self.connection.execute(
            """
            SELECT 1
            FROM agent_members
            WHERE session_id = ?
              AND agent_id = ?
            """,
            (record.session_id, record.agent_id),
        ).fetchone()
        if agent is None:
            raise ValueError(
                "FailureRecoveryDisposition.agent_id must name a canonical "
                "session agent"
            )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> FailureRecoveryDisposition:
        return FailureRecoveryDisposition(
            disposition_id=row["disposition_id"],
            failure_id=row["failure_id"],
            session_id=row["session_id"],
            agent_id=row["agent_id"],
            disposition=FailureRecoveryDispositionKind(row["disposition"]),
            condition_task_ids=_json_loads_list(
                row["condition_task_ids_json"]
            ),
            rationale=row["rationale"],
            idempotency_digest=row["idempotency_digest"],
            created_at=row["created_at"],
        )


def project_failure_observation(
    repositories: Any,
    observation: FailureObservation,
) -> dict[str, Any]:
    """Join immutable agent records without rewriting Host-owned facts."""

    payload = observation.to_dict()
    hypotheses = repositories.failure_hypotheses.list_by_failure(observation.failure_id)
    payload["agent_hypotheses"] = [hypothesis.to_dict() for hypothesis in hypotheses]
    if hypotheses:
        latest = hypotheses[-1]
        payload["agent_hypothesis"] = latest.hypothesis
        payload["agent_hypothesis_confidence"] = latest.confidence.value
        payload["agent_hypothesis_evidence_refs"] = list(latest.evidence_refs)
    dispositions = (
        repositories.failure_recovery_dispositions.list_by_failure(
            observation.failure_id
        )
    )
    payload["agent_recovery_dispositions"] = [
        disposition.to_dict() for disposition in dispositions
    ]
    if dispositions:
        payload["latest_agent_recovery_disposition"] = dispositions[-1].to_dict()
    return payload


__all__ = [
    "FailureHypothesisConflictError",
    "FailureHypothesisRepository",
    "FailureObservationConflictError",
    "FailureObservationRepository",
    "FailureRecoveryDispositionConflictError",
    "FailureRecoveryDispositionRepository",
    "project_failure_observation",
]
