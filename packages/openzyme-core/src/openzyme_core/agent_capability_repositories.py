from __future__ import annotations

from dataclasses import dataclass
import sqlite3

from openzyme_domain import AgentCapability
from openzyme_domain import AgentCapabilityLease
from openzyme_domain import AgentCapabilityLeaseEventKind
from openzyme_domain import AgentCapabilityLeaseLifecycleEvent
from openzyme_domain import AgentCapabilityLeaseStatus
from openzyme_domain import AgentCapabilityProfile
from openzyme_domain import AgentCapabilityRevocationReason
from openzyme_domain import AgentCapabilityRevocationScope
from openzyme_domain import AgentRetirementCleanupProofRecord
from openzyme_domain import AgentRetirementReason
from openzyme_domain import AgentRetirementRecord
from openzyme_domain import AgentRetirementRequest
from openzyme_domain import AgentWorkspaceGenerationReservation
from openzyme_domain import AgentWorkspaceGenerationStatus
from openzyme_domain import AgentWorkspaceReadinessOwnerKind

from .repositories import _commit
from .repositories import _json_dumps
from .repositories import _json_loads_list


class AgentCapabilityRepositoryError(RuntimeError):
    """Base error for canonical agent capability state."""


class AgentCapabilityVersionConflictError(AgentCapabilityRepositoryError):
    """A compare-and-swap capability state transition lost its version."""


@dataclass(slots=True)
class AgentWorkspaceGenerationReservationRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: AgentWorkspaceGenerationReservation,
    ) -> AgentWorkspaceGenerationReservation:
        self.connection.execute(
            """
            INSERT INTO agent_workspace_generation_reservations (
                reservation_id,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                status,
                readiness_owner_kind,
                readiness_owner_ref,
                readiness_ref,
                readiness_digest,
                ready_at,
                replaced_by_generation,
                replaced_at,
                state_version,
                reserved_at,
                updated_at,
                immutable_fingerprint,
                canonical_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.reservation_id,
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.workspace_generation,
                record.status.value,
                None
                if record.readiness_owner_kind is None
                else record.readiness_owner_kind.value,
                record.readiness_owner_ref,
                record.readiness_ref,
                record.readiness_digest,
                record.ready_at,
                record.replaced_by_generation,
                record.replaced_at,
                record.state_version,
                record.reserved_at,
                record.updated_at,
                record.immutable_fingerprint,
                record.canonical_digest,
                record.schema_version,
            ),
        )
        _commit(self.connection)
        return record

    def update(
        self,
        record: AgentWorkspaceGenerationReservation,
        *,
        expected_state_version: int,
    ) -> AgentWorkspaceGenerationReservation:
        cursor = self.connection.execute(
            """
            UPDATE agent_workspace_generation_reservations
            SET session_id = ?,
                agent_member_id = ?,
                agent_id = ?,
                workspace_generation = ?,
                status = ?,
                readiness_owner_kind = ?,
                readiness_owner_ref = ?,
                readiness_ref = ?,
                readiness_digest = ?,
                ready_at = ?,
                replaced_by_generation = ?,
                replaced_at = ?,
                state_version = ?,
                reserved_at = ?,
                updated_at = ?,
                immutable_fingerprint = ?,
                canonical_digest = ?,
                schema_version = ?
            WHERE reservation_id = ? AND state_version = ?
            """,
            (
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.workspace_generation,
                record.status.value,
                None
                if record.readiness_owner_kind is None
                else record.readiness_owner_kind.value,
                record.readiness_owner_ref,
                record.readiness_ref,
                record.readiness_digest,
                record.ready_at,
                record.replaced_by_generation,
                record.replaced_at,
                record.state_version,
                record.reserved_at,
                record.updated_at,
                record.immutable_fingerprint,
                record.canonical_digest,
                record.schema_version,
                record.reservation_id,
                expected_state_version,
            ),
        )
        _commit(self.connection)
        if cursor.rowcount != 1:
            raise AgentCapabilityVersionConflictError(
                "workspace generation state version conflict"
            )
        return record

    def get(
        self,
        reservation_id: str,
    ) -> AgentWorkspaceGenerationReservation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_workspace_generation_reservations
            WHERE reservation_id = ?
            """,
            (reservation_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_generation(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
    ) -> AgentWorkspaceGenerationReservation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_workspace_generation_reservations
            WHERE session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (session_id, agent_member_id, workspace_generation),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_current(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> AgentWorkspaceGenerationReservation | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_workspace_generation_reservations
            WHERE session_id = ?
              AND agent_member_id = ?
              AND status IN ('reserved', 'ready')
            """,
            (session_id, agent_member_id),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_agent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> list[AgentWorkspaceGenerationReservation]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_workspace_generation_reservations
            WHERE session_id = ? AND agent_member_id = ?
            ORDER BY workspace_generation
            """,
            (session_id, agent_member_id),
        ).fetchall()
        return [self._row(row) for row in rows]

    def _row(self, row: sqlite3.Row) -> AgentWorkspaceGenerationReservation:
        readiness_owner_kind = row["readiness_owner_kind"]
        return AgentWorkspaceGenerationReservation(
            reservation_id=row["reservation_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            status=AgentWorkspaceGenerationStatus(row["status"]),
            state_version=int(row["state_version"]),
            reserved_at=row["reserved_at"],
            updated_at=row["updated_at"],
            immutable_fingerprint=row["immutable_fingerprint"],
            canonical_digest=row["canonical_digest"],
            readiness_owner_kind=None
            if readiness_owner_kind is None
            else AgentWorkspaceReadinessOwnerKind(readiness_owner_kind),
            readiness_owner_ref=row["readiness_owner_ref"],
            readiness_ref=row["readiness_ref"],
            readiness_digest=row["readiness_digest"],
            ready_at=row["ready_at"],
            replaced_by_generation=None
            if row["replaced_by_generation"] is None
            else int(row["replaced_by_generation"]),
            replaced_at=row["replaced_at"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class AgentCapabilityLeaseRepository:
    connection: sqlite3.Connection

    def add(self, record: AgentCapabilityLease) -> AgentCapabilityLease:
        self.connection.execute(
            """
            INSERT INTO agent_capability_lease_records (
                lease_id,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                profile,
                capabilities_json,
                capability_set_digest,
                target_ids_json,
                target_scope_digest,
                policy_version,
                policy_digest,
                parent_lease_id,
                idempotency_key,
                status,
                state_version,
                issued_at,
                updated_at,
                activated_at,
                revoked_at,
                revocation_scope,
                revocation_reason,
                immutable_fingerprint,
                canonical_digest,
                schema_version
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            )
            """,
            self._values(record),
        )
        _commit(self.connection)
        return record

    def update(
        self,
        record: AgentCapabilityLease,
        *,
        expected_state_version: int,
    ) -> AgentCapabilityLease:
        cursor = self.connection.execute(
            """
            UPDATE agent_capability_lease_records
            SET session_id = ?,
                agent_member_id = ?,
                agent_id = ?,
                workspace_generation = ?,
                profile = ?,
                capabilities_json = ?,
                capability_set_digest = ?,
                target_ids_json = ?,
                target_scope_digest = ?,
                policy_version = ?,
                policy_digest = ?,
                parent_lease_id = ?,
                idempotency_key = ?,
                status = ?,
                state_version = ?,
                issued_at = ?,
                updated_at = ?,
                activated_at = ?,
                revoked_at = ?,
                revocation_scope = ?,
                revocation_reason = ?,
                immutable_fingerprint = ?,
                canonical_digest = ?,
                schema_version = ?
            WHERE lease_id = ? AND state_version = ?
            """,
            (
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.workspace_generation,
                record.profile.value,
                _json_dumps([capability.value for capability in record.capabilities]),
                record.capability_set_digest,
                _json_dumps(list(record.target_ids)),
                record.target_scope_digest,
                record.policy_version,
                record.policy_digest,
                record.parent_lease_id,
                record.idempotency_key,
                record.status.value,
                record.state_version,
                record.issued_at,
                record.updated_at,
                record.activated_at,
                record.revoked_at,
                None
                if record.revocation_scope is None
                else record.revocation_scope.value,
                None
                if record.revocation_reason is None
                else record.revocation_reason.value,
                record.immutable_fingerprint,
                record.canonical_digest,
                record.schema_version,
                record.lease_id,
                expected_state_version,
            ),
        )
        _commit(self.connection)
        if cursor.rowcount != 1:
            raise AgentCapabilityVersionConflictError(
                "agent capability lease state version conflict"
            )
        return record

    def get(self, lease_id: str) -> AgentCapabilityLease | None:
        row = self.connection.execute(
            "SELECT * FROM agent_capability_lease_records WHERE lease_id = ?",
            (lease_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_generation(
        self,
        *,
        session_id: str,
        agent_member_id: str,
        workspace_generation: int,
    ) -> AgentCapabilityLease | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_records
            WHERE session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (session_id, agent_member_id, workspace_generation),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_idempotency_key(
        self,
        *,
        session_id: str,
        idempotency_key: str,
    ) -> AgentCapabilityLease | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_records
            WHERE session_id = ? AND idempotency_key = ?
            """,
            (session_id, idempotency_key),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_active(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> AgentCapabilityLease | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_records
            WHERE session_id = ?
              AND agent_member_id = ?
              AND status = 'active'
            """,
            (session_id, agent_member_id),
        ).fetchone()
        return None if row is None else self._row(row)

    def list_by_agent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> list[AgentCapabilityLease]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_records
            WHERE session_id = ? AND agent_member_id = ?
            ORDER BY workspace_generation
            """,
            (session_id, agent_member_id),
        ).fetchall()
        return [self._row(row) for row in rows]

    def list_by_session(self, session_id: str) -> list[AgentCapabilityLease]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_records
            WHERE session_id = ?
            ORDER BY issued_at, lease_id
            """,
            (session_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def list_direct_children(self, parent_lease_id: str) -> list[AgentCapabilityLease]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_records
            WHERE parent_lease_id = ?
            ORDER BY issued_at, lease_id
            """,
            (parent_lease_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def _values(self, record: AgentCapabilityLease) -> tuple[object, ...]:
        return (
            record.lease_id,
            record.session_id,
            record.agent_member_id,
            record.agent_id,
            record.workspace_generation,
            record.profile.value,
            _json_dumps([capability.value for capability in record.capabilities]),
            record.capability_set_digest,
            _json_dumps(list(record.target_ids)),
            record.target_scope_digest,
            record.policy_version,
            record.policy_digest,
            record.parent_lease_id,
            record.idempotency_key,
            record.status.value,
            record.state_version,
            record.issued_at,
            record.updated_at,
            record.activated_at,
            record.revoked_at,
            None if record.revocation_scope is None else record.revocation_scope.value,
            None
            if record.revocation_reason is None
            else record.revocation_reason.value,
            record.immutable_fingerprint,
            record.canonical_digest,
            record.schema_version,
        )

    def _row(self, row: sqlite3.Row) -> AgentCapabilityLease:
        revocation_scope = row["revocation_scope"]
        revocation_reason = row["revocation_reason"]
        return AgentCapabilityLease(
            lease_id=row["lease_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            profile=AgentCapabilityProfile(row["profile"]),
            capabilities=tuple(
                AgentCapability(value)
                for value in _json_loads_list(row["capabilities_json"])
            ),
            capability_set_digest=row["capability_set_digest"],
            target_ids=_json_loads_list(row["target_ids_json"]),
            target_scope_digest=row["target_scope_digest"],
            policy_version=row["policy_version"],
            policy_digest=row["policy_digest"],
            parent_lease_id=row["parent_lease_id"],
            idempotency_key=row["idempotency_key"],
            status=AgentCapabilityLeaseStatus(row["status"]),
            state_version=int(row["state_version"]),
            issued_at=row["issued_at"],
            updated_at=row["updated_at"],
            immutable_fingerprint=row["immutable_fingerprint"],
            canonical_digest=row["canonical_digest"],
            activated_at=row["activated_at"],
            revoked_at=row["revoked_at"],
            revocation_scope=None
            if revocation_scope is None
            else AgentCapabilityRevocationScope(revocation_scope),
            revocation_reason=None
            if revocation_reason is None
            else AgentCapabilityRevocationReason(revocation_reason),
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class AgentCapabilityLeaseLifecycleEventRepository:
    connection: sqlite3.Connection

    def append(
        self,
        event: AgentCapabilityLeaseLifecycleEvent,
    ) -> AgentCapabilityLeaseLifecycleEvent:
        self.connection.execute(
            """
            INSERT INTO agent_capability_lease_lifecycle_events (
                event_id,
                lease_id,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                event_kind,
                previous_status,
                status,
                state_version,
                actor_ref,
                revocation_scope,
                revocation_reason,
                occurred_at,
                event_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.event_id,
                event.lease_id,
                event.session_id,
                event.agent_member_id,
                event.agent_id,
                event.workspace_generation,
                event.event_kind.value,
                None if event.previous_status is None else event.previous_status.value,
                event.status.value,
                event.state_version,
                event.actor_ref,
                None
                if event.revocation_scope is None
                else event.revocation_scope.value,
                None
                if event.revocation_reason is None
                else event.revocation_reason.value,
                event.occurred_at,
                event.event_digest,
                event.schema_version,
            ),
        )
        _commit(self.connection)
        return event

    def list_by_lease(
        self,
        lease_id: str,
    ) -> list[AgentCapabilityLeaseLifecycleEvent]:
        rows = self.connection.execute(
            """
            SELECT *
            FROM agent_capability_lease_lifecycle_events
            WHERE lease_id = ?
            ORDER BY state_version
            """,
            (lease_id,),
        ).fetchall()
        return [self._row(row) for row in rows]

    def _row(self, row: sqlite3.Row) -> AgentCapabilityLeaseLifecycleEvent:
        previous_status = row["previous_status"]
        revocation_scope = row["revocation_scope"]
        revocation_reason = row["revocation_reason"]
        return AgentCapabilityLeaseLifecycleEvent(
            event_id=row["event_id"],
            lease_id=row["lease_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            event_kind=AgentCapabilityLeaseEventKind(row["event_kind"]),
            previous_status=None
            if previous_status is None
            else AgentCapabilityLeaseStatus(previous_status),
            status=AgentCapabilityLeaseStatus(row["status"]),
            state_version=int(row["state_version"]),
            actor_ref=row["actor_ref"],
            occurred_at=row["occurred_at"],
            event_digest=row["event_digest"],
            revocation_scope=None
            if revocation_scope is None
            else AgentCapabilityRevocationScope(revocation_scope),
            revocation_reason=None
            if revocation_reason is None
            else AgentCapabilityRevocationReason(revocation_reason),
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class AgentRetirementRequestRepository:
    connection: sqlite3.Connection

    def add(self, record: AgentRetirementRequest) -> AgentRetirementRequest:
        self.connection.execute(
            """
            INSERT INTO agent_retirement_requests (
                request_id,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                capability_lease_id,
                shutdown_request_ref,
                cleanup_provider_id,
                actor_ref,
                requested_at,
                canonical_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.request_id,
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.workspace_generation,
                record.capability_lease_id,
                record.shutdown_request_ref,
                record.cleanup_provider_id,
                record.actor_ref,
                record.requested_at,
                record.canonical_digest,
                record.schema_version,
            ),
        )
        _commit(self.connection)
        return record

    def get(self, request_id: str) -> AgentRetirementRequest | None:
        row = self.connection.execute(
            "SELECT * FROM agent_retirement_requests WHERE request_id = ?",
            (request_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_agent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> AgentRetirementRequest | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_retirement_requests
            WHERE session_id = ? AND agent_member_id = ?
            """,
            (session_id, agent_member_id),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> AgentRetirementRequest:
        return AgentRetirementRequest(
            request_id=row["request_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            capability_lease_id=row["capability_lease_id"],
            shutdown_request_ref=row["shutdown_request_ref"],
            cleanup_provider_id=row["cleanup_provider_id"],
            actor_ref=row["actor_ref"],
            requested_at=row["requested_at"],
            canonical_digest=row["canonical_digest"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class AgentRetirementCleanupProofRepository:
    connection: sqlite3.Connection

    def add(
        self,
        record: AgentRetirementCleanupProofRecord,
    ) -> AgentRetirementCleanupProofRecord:
        self.connection.execute(
            """
            INSERT INTO agent_retirement_cleanup_proofs (
                proof_id,
                retirement_request_id,
                retirement_request_digest,
                session_id,
                agent_member_id,
                agent_id,
                workspace_generation,
                capability_lease_id,
                shutdown_request_ref,
                provider_id,
                cleanup_proof_digest,
                reason,
                observed_at,
                canonical_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.proof_id,
                record.retirement_request_id,
                record.retirement_request_digest,
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.workspace_generation,
                record.capability_lease_id,
                record.shutdown_request_ref,
                record.provider_id,
                record.cleanup_proof_digest,
                record.reason.value,
                record.observed_at,
                record.canonical_digest,
                record.schema_version,
            ),
        )
        _commit(self.connection)
        return record

    def get(self, proof_id: str) -> AgentRetirementCleanupProofRecord | None:
        row = self.connection.execute(
            "SELECT * FROM agent_retirement_cleanup_proofs WHERE proof_id = ?",
            (proof_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_request(
        self,
        request_id: str,
    ) -> AgentRetirementCleanupProofRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_retirement_cleanup_proofs
            WHERE retirement_request_id = ?
            """,
            (request_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    @staticmethod
    def _row(row: sqlite3.Row) -> AgentRetirementCleanupProofRecord:
        return AgentRetirementCleanupProofRecord(
            proof_id=row["proof_id"],
            retirement_request_id=row["retirement_request_id"],
            retirement_request_digest=row["retirement_request_digest"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            workspace_generation=int(row["workspace_generation"]),
            capability_lease_id=row["capability_lease_id"],
            shutdown_request_ref=row["shutdown_request_ref"],
            provider_id=row["provider_id"],
            cleanup_proof_digest=row["cleanup_proof_digest"],
            reason=AgentRetirementReason(row["reason"]),
            observed_at=row["observed_at"],
            canonical_digest=row["canonical_digest"],
            schema_version=row["schema_version"],
        )


@dataclass(slots=True)
class AgentRetirementRecordRepository:
    connection: sqlite3.Connection

    def add(self, record: AgentRetirementRecord) -> AgentRetirementRecord:
        self.connection.execute(
            """
            INSERT INTO agent_retirement_records (
                retirement_id,
                session_id,
                agent_member_id,
                agent_id,
                retirement_request_id,
                retirement_request_digest,
                workspace_generation,
                capability_lease_id,
                shutdown_request_ref,
                cleanup_proof_id,
                cleanup_proof_digest,
                cleanup_proof_record_digest,
                actor_ref,
                reason,
                retired_at,
                canonical_digest,
                schema_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                record.retirement_id,
                record.session_id,
                record.agent_member_id,
                record.agent_id,
                record.retirement_request_id,
                record.retirement_request_digest,
                record.workspace_generation,
                record.capability_lease_id,
                record.shutdown_request_ref,
                record.cleanup_proof_id,
                record.cleanup_proof_digest,
                record.cleanup_proof_record_digest,
                record.actor_ref,
                record.reason.value,
                record.retired_at,
                record.canonical_digest,
                record.schema_version,
            ),
        )
        _commit(self.connection)
        return record

    def get(self, retirement_id: str) -> AgentRetirementRecord | None:
        row = self.connection.execute(
            "SELECT * FROM agent_retirement_records WHERE retirement_id = ?",
            (retirement_id,),
        ).fetchone()
        return None if row is None else self._row(row)

    def get_by_agent(
        self,
        *,
        session_id: str,
        agent_member_id: str,
    ) -> AgentRetirementRecord | None:
        row = self.connection.execute(
            """
            SELECT *
            FROM agent_retirement_records
            WHERE session_id = ? AND agent_member_id = ?
            """,
            (session_id, agent_member_id),
        ).fetchone()
        return None if row is None else self._row(row)

    def _row(self, row: sqlite3.Row) -> AgentRetirementRecord:
        return AgentRetirementRecord(
            retirement_id=row["retirement_id"],
            session_id=row["session_id"],
            agent_member_id=row["agent_member_id"],
            agent_id=row["agent_id"],
            retirement_request_id=row["retirement_request_id"],
            retirement_request_digest=row["retirement_request_digest"],
            workspace_generation=int(row["workspace_generation"]),
            capability_lease_id=row["capability_lease_id"],
            shutdown_request_ref=row["shutdown_request_ref"],
            cleanup_proof_id=row["cleanup_proof_id"],
            cleanup_proof_digest=row["cleanup_proof_digest"],
            cleanup_proof_record_digest=row["cleanup_proof_record_digest"],
            actor_ref=row["actor_ref"],
            reason=AgentRetirementReason(row["reason"]),
            retired_at=row["retired_at"],
            canonical_digest=row["canonical_digest"],
            schema_version=row["schema_version"],
        )


__all__ = [
    "AgentCapabilityLeaseLifecycleEventRepository",
    "AgentCapabilityLeaseRepository",
    "AgentCapabilityRepositoryError",
    "AgentCapabilityVersionConflictError",
    "AgentRetirementCleanupProofRepository",
    "AgentRetirementRecordRepository",
    "AgentRetirementRequestRepository",
    "AgentWorkspaceGenerationReservationRepository",
]
