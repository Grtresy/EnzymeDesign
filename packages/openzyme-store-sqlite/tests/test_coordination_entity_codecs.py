from __future__ import annotations

import sqlite3

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import RetryEligibility
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import ApprovalRequestSQLiteKernelEntityCodec
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import ContinuationSQLiteKernelEntityCodec
from openzyme_store_sqlite import FailureObservationSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionRuntimeLeaseSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


NOW = "2026-08-21T00:00:00+00:00"


def _store() -> tuple[sqlite3.Connection, SQLiteControlStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    store = SQLiteControlStore(
        connection,
        codecs=(
            AgentMemberSQLiteKernelEntityCodec(),
            ApprovalRequestSQLiteKernelEntityCodec(),
            ContinuationSQLiteKernelEntityCodec(),
            FailureObservationSQLiteKernelEntityCodec(),
            SessionRuntimeLeaseSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
        ),
    )
    _commit(
        store,
        command="session-create",
        entity_type="session",
        entity_id="session-1",
        payload={
            "session_id": "session-1",
            "project_id": "project-1",
            "title": "Coordination codec qualification",
            "objective": "prove structured target owner mappings",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
        },
    )
    _commit(
        store,
        command="member-create",
        entity_type="agent_member",
        entity_id="agent-1",
        payload={
            "agent_member_id": "agent-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "parent_agent_id": None,
            "lane_id": None,
            "name": "Master",
            "role": "master",
            "status": "active",
            "process_epoch": 1,
            "active_authority_lease_id": None,
            "workspace_generation": None,
            "owned_task_ids": [],
            "retirement_reason": None,
            "terminal_proof_digest": None,
            "retirement_settled": False,
            "retired_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        },
    )
    return connection, store


def _commit(
    store: SQLiteControlStore,
    *,
    command: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
    kind: KernelMutationKind = KernelMutationKind.CREATE,
    expected_state_version: int | None = None,
) -> None:
    request = UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command}",
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="operator-1",
        authority_lease_id="authority-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key=f"idempotency-{command}",
        command_digest=canonical_sha256_digest({"command": command}),
    )
    unit = store.begin(request)
    unit.stage(
        KernelStateMutation.create(
            mutation_id=f"mutation-{command}",
            kind=kind,
            entity_type=entity_type,
            entity_id=entity_id,
            expected_state_version=expected_state_version,
            payload=payload,
        )
    )
    next_version = 1 if expected_state_version is None else expected_state_version + 1
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"{entity_type}.{command}",
        source_entity_type=entity_type,
        source_entity_id=entity_id,
        source_state_version=next_version,
        command_id=f"command-{command}",
        payload={"entity_id": entity_id},
    )
    unit.append_event(event)
    outbox_payload = {"event_id": event.event_id}
    unit.append_outbox(
        OutboxRecord(
            outbox_id=f"outbox-{command}",
            session_id="session-1",
            topic="openzyme.kernel.codec-qualification",
            occurrence_id=event.event_id,
            payload=outbox_payload,
            payload_digest=canonical_sha256_digest(outbox_payload),
            created_at=NOW,
        )
    )
    unit.commit()


def test_approval_request_codec_uses_target_columns_and_cas() -> None:
    connection, store = _store()
    pending = {
        "approval_id": "approval-1",
        "session_id": "session-1",
        "requester_actor_id": "agent-1",
        "intent_digest": canonical_sha256_digest({"intent": "run"}),
        "requested_action": "external operation",
        "scope_id": "scope-1",
        "task_id": None,
        "reason": "operator review required",
        "status": "pending",
        "created_at": NOW,
        "expires_at": "2026-08-22T00:00:00+00:00",
        "resolved_at": None,
        "resolver_actor_id": None,
        "resolution_ref": None,
        "operation_dispatched": False,
    }
    _commit(
        store,
        command="approval-create",
        entity_type="approval_request",
        entity_id="approval-1",
        payload=pending,
    )

    assert store.read(
        entity_type="approval_request", entity_id="approval-1"
    ) == KernelRecordSnapshot.create(
        entity_type="approval_request",
        entity_id="approval-1",
        state_version=1,
        payload=pending,
    )
    assert connection.execute(
        """
        SELECT record_kind, kind, requester_actor_id, scope_id,
               operation_dispatched
        FROM approval_requests WHERE approval_id = 'approval-1'
        """
    ).fetchone() == (
        "kernel_approval_request",
        "kernel_authority",
        "agent-1",
        "scope-1",
        0,
    )

    approved = {
        **pending,
        "status": "approved",
        "reason": "approved by operator",
        "resolved_at": "2026-08-21T00:05:00+00:00",
        "resolver_actor_id": "operator-1",
        "resolution_ref": "resolution-1",
    }
    _commit(
        store,
        command="approval-resolve",
        entity_type="approval_request",
        entity_id="approval-1",
        payload=approved,
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )
    assert store.read(
        entity_type="approval_request", entity_id="approval-1"
    ).state_version == 2


def test_session_runtime_lease_codec_reuses_one_target_owner_row() -> None:
    connection, store = _store()
    acquired = {
        "session_id": "session-1",
        "owner_id": "runtime-owner-1",
        "lease_token": "runtime-lease-1",
        "mode": "drain",
        "generation": 1,
        "fencing_token": 1,
        "acquired_at": NOW,
        "heartbeat_at": NOW,
        "expires_at": "2026-08-21T00:05:00+00:00",
        "released_at": None,
        "last_error": None,
        "acquire_command_digest": canonical_sha256_digest({"command": "acquire"}),
    }
    _commit(
        store,
        command="lease-acquire",
        entity_type="session_runtime_lease",
        entity_id="session-1",
        payload=acquired,
    )
    released = {
        **acquired,
        "heartbeat_at": "2026-08-21T00:01:00+00:00",
        "released_at": "2026-08-21T00:01:00+00:00",
    }
    _commit(
        store,
        command="lease-release",
        entity_type="session_runtime_lease",
        entity_id="session-1",
        payload=released,
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )

    assert store.read(
        entity_type="session_runtime_lease", entity_id="session-1"
    ) == KernelRecordSnapshot.create(
        entity_type="session_runtime_lease",
        entity_id="session-1",
        state_version=2,
        payload=released,
    )
    assert connection.execute(
        """
        SELECT record_kind, kernel_entity_id, generation, fencing_token
        FROM session_runtime_leases
        """
    ).fetchall() == [("kernel_session_runtime_lease", "session-1", 1, 1)]


def test_continuation_codec_separates_target_state_from_legacy_links() -> None:
    connection, store = _store()
    ready = {
        "continuation_id": "continuation-1",
        "session_id": "session-1",
        "owner_actor_id": "agent-1",
        "source_version": 1,
        "source_ref": "operation-1",
        "source_digest": canonical_sha256_digest({"source": "operation-1"}),
        "recipient_actor_id": "agent-1",
        "resume_strategy": "journaled_sdk_call_boundary",
        "process_epoch": 1,
        "state": "ready",
        "delivery_attempt": 0,
        "delivery_receipt_digest": None,
        "failure_id": None,
        "error_code": None,
        "created_at": NOW,
        "updated_at": NOW,
        "task_transition_performed": False,
    }
    _commit(
        store,
        command="continuation-register",
        entity_type="continuation",
        entity_id="continuation-1",
        payload=ready,
    )
    delivered = {
        **ready,
        "state": "delivered",
        "delivery_attempt": 1,
        "delivery_receipt_digest": canonical_sha256_digest({"delivery": 1}),
        "updated_at": "2026-08-21T00:05:00+00:00",
    }
    _commit(
        store,
        command="continuation-deliver",
        entity_type="continuation",
        entity_id="continuation-1",
        payload=delivered,
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )

    assert store.read(
        entity_type="continuation", entity_id="continuation-1"
    ) == KernelRecordSnapshot.create(
        entity_type="continuation",
        entity_id="continuation-1",
        state_version=2,
        payload=delivered,
    )
    assert connection.execute(
        """
        SELECT record_kind, operation_id, sandbox_run_id, approval_id,
               kernel_state, delivery_attempt
        FROM continuation_state_records WHERE continuation_id = 'continuation-1'
        """
    ).fetchone() == (
        "kernel_continuation",
        None,
        None,
        None,
        "delivered",
        1,
    )


def test_failure_observation_codec_round_trips_structured_public_facts() -> None:
    connection, store = _store()
    observation = FailureObservation(
        failure_id="failure-1",
        session_id="session-1",
        source_kind="runtime",
        source_ref="runtime-command-1",
        source_version="1",
        phase="dispatch",
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.RUNTIME_RETRY,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.SAME_PHASE_SAFE,
        actor_kind=FailureActorKind.HARNESS,
        error_code="runtime_unavailable",
        safe_summary="Runtime was unavailable before dispatch",
        facts={"provider": "fake"},
        likely_causes=("runtime_not_ready",),
        evidence_refs=("diagnostic-1",),
        created_at=NOW,
        component="runtime",
        operation="dispatch",
        identities={"runtime_command_id": "runtime-command-1"},
        diagnostic_id="diagnostic-1",
        next_action="retry_runtime",
    )
    _commit(
        store,
        command="failure-record",
        entity_type="failure_observation",
        entity_id="failure-1",
        payload=observation.to_dict(),
    )

    assert store.read(
        entity_type="failure_observation", entity_id="failure-1"
    ) == KernelRecordSnapshot.create(
        entity_type="failure_observation",
        entity_id="failure-1",
        state_version=1,
        payload=observation.to_dict(),
    )
    assert connection.execute(
        """
        SELECT facts_json, mutation_applied, fallback_performed, diagnostic_id
        FROM failure_observation_records WHERE failure_id = 'failure-1'
        """
    ).fetchone() == ('{"provider":"fake"}', 0, 0, "diagnostic-1")
