from __future__ import annotations

import sqlite3

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import AgentAuthorityLeaseSQLiteKernelEntityCodec
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import AgentRuntimeSignalSQLiteKernelEntityCodec
from openzyme_store_sqlite import ControlledOperationSQLiteKernelEntityCodec
from openzyme_store_sqlite import RuntimeContinuationIntentSQLiteKernelEntityCodec
from openzyme_store_sqlite import RuntimeOutcomeConsumptionSQLiteKernelEntityCodec
from openzyme_store_sqlite import RuntimeSettlementIntentSQLiteKernelEntityCodec
from openzyme_store_sqlite import RuntimeTurnCommandSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionRuntimeLeaseSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import WorkspaceGenerationSQLiteKernelEntityCodec
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


NOW = "2026-08-21T00:00:00+00:00"
FUTURE = "2099-08-21T00:00:00+00:00"


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
    unit = store.begin(
        UnitOfWorkRequest(
            unit_of_work_id=f"uow-{command}",
            command_id=f"command-{command}",
            session_id="session-1",
            actor_id="agent-member-1",
            authority_lease_id="authority-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            idempotency_key=f"idempotency-{command}",
            command_digest=canonical_sha256_digest({"command": command}),
        )
    )
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
            topic="openzyme.kernel.runtime-signal-qualification",
            occurrence_id=event.event_id,
            payload=outbox_payload,
            payload_digest=canonical_sha256_digest(outbox_payload),
            created_at=NOW,
        )
    )
    unit.commit()


def _store() -> tuple[sqlite3.Connection, SQLiteControlStore, AgentAuthorityLease]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    store = SQLiteControlStore(
        connection,
        codecs=(
            AgentAuthorityLeaseSQLiteKernelEntityCodec(),
            AgentMemberSQLiteKernelEntityCodec(),
            AgentRuntimeSignalSQLiteKernelEntityCodec(),
            ControlledOperationSQLiteKernelEntityCodec(),
            RuntimeContinuationIntentSQLiteKernelEntityCodec(),
            RuntimeOutcomeConsumptionSQLiteKernelEntityCodec(),
            RuntimeSettlementIntentSQLiteKernelEntityCodec(),
            RuntimeTurnCommandSQLiteKernelEntityCodec(),
            WorkspaceGenerationSQLiteKernelEntityCodec(),
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
            "title": "Runtime signal qualification",
            "objective": "prove target runtime signal fences",
            "status": "active",
            "created_at": NOW,
            "updated_at": NOW,
        },
    )
    _commit(
        store,
        command="member-create",
        entity_type="agent_member",
        entity_id="agent-member-1",
        payload={
            "agent_member_id": "agent-member-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "parent_agent_id": None,
            "lane_id": None,
            "name": "Master",
            "role": "master",
            "status": "active",
            "process_epoch": 1,
            "active_authority_lease_id": None,
            "workspace_generation": 1,
            "owned_task_ids": [],
            "retirement_reason": None,
            "terminal_proof_digest": None,
            "retirement_settled": False,
            "retired_at": None,
            "created_at": NOW,
            "updated_at": NOW,
        },
    )
    _commit(
        store,
        command="workspace-create",
        entity_type="workspace_generation",
        entity_id="workspace-1",
        payload=WorkspaceGeneration(
            workspace_id="workspace-1",
            workspace_kind=WorkspaceKind.AGENT_LOCAL,
            session_id="session-1",
            owner_member_id="agent-member-1",
            generation=1,
            state_version=3,
            status=WorkspaceGenerationStatus.READY,
            provider_id="openzyme.workspace.git-lfs",
            target_id="local:host",
            created_at=NOW,
            updated_at=NOW,
            root_identity_digest=canonical_sha256_digest({"root": "workspace-1"}),
            transition_receipt_digest=canonical_sha256_digest(
                {"receipt": "workspace-1"}
            ),
            controlled_operation_id="workspace-provision-1",
        ).to_dict(),
    )
    grant = AuthorityGrant.create(
        grant_id="grant-1",
        scope_id="session-1",
        operations=("runtime.signal.claim",),
        generation=1,
        fence=1,
    )
    authority = AgentAuthorityLease.create(
        lease_id="authority-1",
        session_id="session-1",
        agent_member_id="agent-member-1",
        grants=(grant,),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=NOW,
        expires_at=FUTURE,
        agent_id="agent-1",
        workspace_generation=1,
        parent_lease_id=None,
        policy_digest=canonical_sha256_digest({"policy": "runtime"}),
        idempotency_key="authority-1",
        updated_at=NOW,
    )
    _commit(
        store,
        command="authority-create",
        entity_type="agent_authority_lease",
        entity_id="authority-1",
        payload=authority.to_dict(),
    )
    return connection, store, authority


def _pending_signal(authority: AgentAuthorityLease) -> dict[str, object]:
    return {
        "signal_id": "signal-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "agent-member-1",
        "reason": "manual_resume",
        "status": "pending",
        "created_at": NOW,
        "task_id": None,
        "lane_id": None,
        "correlation_id": "correlation-1",
        "source_ref": "source-1",
        "claimed_at": None,
        "claimed_by": None,
        "claim_token": None,
        "claim_expires_at": None,
        "attempt_count": 0,
        "completed_at": None,
        "error_message": None,
        "last_error": None,
        "session_lease_token": None,
        "session_fencing_token": None,
        "runtime_lease_generation": None,
        "capability_lease_id": authority.lease_id,
        "capability_lease_digest": authority.lease_digest,
        "workspace_generation": 1,
        "process_epoch": 1,
        "enqueue_command_digest": canonical_sha256_digest({"command": "enqueue"}),
        "claim_command_digest": None,
    }


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _claim_runtime_signal(
    store: SQLiteControlStore,
    authority: AgentAuthorityLease,
) -> dict[str, object]:
    pending = _pending_signal(authority)
    _commit(
        store,
        command="signal-enqueue",
        entity_type="agent_runtime_signal",
        entity_id="signal-1",
        payload=pending,
    )
    _commit(
        store,
        command="lease-acquire",
        entity_type="session_runtime_lease",
        entity_id="session-1",
        payload={
            "session_id": "session-1",
            "owner_id": "runtime-owner-1",
            "lease_token": "runtime-lease-1",
            "mode": "manual_drain",
            "generation": 1,
            "fencing_token": 1,
            "acquired_at": NOW,
            "heartbeat_at": NOW,
            "expires_at": FUTURE,
            "released_at": None,
            "last_error": None,
            "acquire_command_digest": canonical_sha256_digest(
                {"command": "acquire"}
            ),
        },
    )
    claimed = {
        **pending,
        "status": "claimed",
        "claimed_at": "2026-08-21T00:01:00+00:00",
        "claimed_by": "runtime-owner-1",
        "claim_token": "signal-claim-1",
        "claim_expires_at": FUTURE,
        "attempt_count": 1,
        "session_lease_token": "runtime-lease-1",
        "session_fencing_token": 1,
        "runtime_lease_generation": 1,
        "claim_command_digest": canonical_sha256_digest({"command": "claim"}),
    }
    _commit(
        store,
        command="signal-claim",
        entity_type="agent_runtime_signal",
        entity_id="signal-1",
        payload=claimed,
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )
    return claimed


def test_runtime_signal_codec_binds_target_authority_and_runtime_fence() -> None:
    connection, store, authority = _store()
    claimed = _claim_runtime_signal(store, authority)

    assert store.read(
        entity_type="agent_runtime_signal", entity_id="signal-1"
    ) == KernelRecordSnapshot.create(
        entity_type="agent_runtime_signal",
        entity_id="signal-1",
        state_version=2,
        payload=claimed,
    )
    assert connection.execute(
        """
        SELECT record_kind, agent_member_id, capability_lease_digest,
               runtime_lease_generation, claim_token
        FROM agent_runtime_signals WHERE signal_id = 'signal-1'
        """
    ).fetchone() == (
        "kernel_runtime_signal",
        "agent-member-1",
        authority.lease_digest,
        1,
        "signal-claim-1",
    )


def test_bounded_runtime_records_use_target_tables_and_atomic_intent_refs() -> None:
    connection, store, authority = _store()
    _claim_runtime_signal(store, authority)
    command: dict[str, object] = {
        "schema_version": "runtime_turn_command@1",
        "command_id": "turn-command-1",
        "turn_id": "turn-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "agent-member-1",
        "signal_id": "signal-1",
        "signal_attempt": 1,
        "signal_claim_token": "signal-claim-1",
        "runtime_lease_token": "runtime-lease-1",
        "runtime_lease_generation": 1,
        "runtime_fence": 1,
        "process_epoch": 1,
        "distribution_id": "openzyme.standard",
        "distribution_manifest_digest": _digest("distribution"),
        "release_digest": _digest("release"),
        "adapter_bundle_digest": _digest("adapters"),
        "extension_bundle_digest": _digest("extensions"),
        "declared_tool_catalog_digest": _digest("tools"),
        "capability_binding_id": "binding-1",
        "capability_binding_revision": 1,
        "capability_binding_digest": _digest("binding"),
        "affordance_snapshot_id": "snapshot-1",
        "affordance_snapshot_digest": _digest("snapshot"),
        "runtime_adapter_id": "runtime-fake",
        "runtime_adapter_contract_digest": _digest("runtime-adapter"),
        "max_steps": 4,
        "max_duration_seconds": 60,
        "max_input_units": 1000,
        "max_output_units": 500,
        "messages": [
            {
                "schema_version": "runtime_message@1",
                "message_id": "message-1",
                "role": "user",
                "content": "Inspect the exact runtime facts.",
                "correlation_id": None,
                "tool_call_id": None,
            }
        ],
        "task_id": None,
        "lane_id": None,
        "continuation_id": None,
    }
    command["command_digest"] = canonical_sha256_digest(command)
    _commit(
        store,
        command="turn-command-create",
        entity_type="runtime_turn_command",
        entity_id="turn-command-1",
        payload=command,
    )

    continuation: dict[str, object] = {
        "schema_version": "runtime_continuation_intent@1",
        "continuation_id": "runtime-continuation-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "agent-member-1",
        "source_command_id": "turn-command-1",
        "source_command_digest": command["command_digest"],
        "source_outcome_id": "outcome-1",
        "source_outcome_digest": _digest("outcome"),
        "process_epoch": 1,
        "release_digest": _digest("release"),
        "extension_bundle_digest": _digest("extensions"),
        "declared_tool_catalog_digest": _digest("tools"),
        "capability_binding_id": "binding-1",
        "capability_binding_revision": 1,
        "capability_binding_digest": _digest("binding"),
        "affordance_snapshot_id": "snapshot-1",
        "affordance_snapshot_digest": _digest("snapshot"),
    }
    settlement: dict[str, object] = {
        "schema_version": "runtime_settlement_intent@1",
        "settlement_id": "runtime-settlement-1",
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "agent-member-1",
        "signal_id": "signal-1",
        "signal_attempt": 1,
        "source_command_id": "turn-command-1",
        "source_command_digest": command["command_digest"],
        "source_outcome_id": "outcome-1",
        "source_outcome_digest": _digest("outcome"),
        "disposition": "waiting_continuation",
        "waiting_approval_id": None,
        "failure_id": None,
        "task_transition_performed": False,
    }
    consumption: dict[str, object] = {
        "schema_version": "runtime_outcome_consumption@1",
        "consumption_id": "consumption-1",
        "command_id": "turn-command-1",
        "command_digest": command["command_digest"],
        "outcome_id": "outcome-1",
        "outcome_digest": _digest("outcome"),
        "session_id": "session-1",
        "agent_id": "agent-1",
        "agent_member_id": "agent-member-1",
        "signal_id": "signal-1",
        "signal_attempt": 1,
        "continuation_intent": continuation,
        "settlement_intent": settlement,
        "consumed_at": "2026-08-21T00:02:00+00:00",
    }
    consumption["consumption_digest"] = canonical_sha256_digest(consumption)
    unit = store.begin(
        UnitOfWorkRequest(
            unit_of_work_id="uow-outcome-consume",
            command_id="command-outcome-consume",
            session_id="session-1",
            actor_id="agent-member-1",
            authority_lease_id="authority-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            idempotency_key="outcome-consume",
            command_digest=_digest("outcome-consume"),
        )
    )
    for entity_type, entity_id, payload in (
        ("runtime_outcome_consumption", "turn-command-1", consumption),
        ("runtime_continuation_intent", "runtime-continuation-1", continuation),
        ("runtime_settlement_intent", "runtime-settlement-1", settlement),
    ):
        unit.stage(
            KernelStateMutation.create(
                mutation_id=f"mutation-{entity_type}",
                kind=KernelMutationKind.CREATE,
                entity_type=entity_type,
                entity_id=entity_id,
                expected_state_version=None,
                payload=payload,
            )
        )
    event = DurableEventRecord.create(
        event_id="event-outcome-consume",
        session_id="session-1",
        event_type="runtime.outcome.consumed",
        source_entity_type="runtime_outcome_consumption",
        source_entity_id="turn-command-1",
        source_state_version=1,
        command_id="command-outcome-consume",
        payload={"command_id": "turn-command-1"},
    )
    unit.append_event(event)
    outbox_payload = {"event_id": event.event_id}
    unit.append_outbox(
        OutboxRecord(
            outbox_id="outbox-outcome-consume",
            session_id="session-1",
            topic="openzyme.kernel.runtime-settlement",
            occurrence_id=event.event_id,
            payload=outbox_payload,
            payload_digest=canonical_sha256_digest(outbox_payload),
            created_at=NOW,
        )
    )
    unit.commit()

    assert store.read(
        entity_type="runtime_turn_command", entity_id="turn-command-1"
    ) == KernelRecordSnapshot.create(
        entity_type="runtime_turn_command",
        entity_id="turn-command-1",
        state_version=1,
        payload=command,
    )
    assert store.read(
        entity_type="runtime_outcome_consumption", entity_id="turn-command-1"
    ) == KernelRecordSnapshot.create(
        entity_type="runtime_outcome_consumption",
        entity_id="turn-command-1",
        state_version=1,
        payload=consumption,
    )
    assert connection.execute(
        "SELECT command_type FROM runtime_command_records"
    ).fetchall() == []
    assert connection.execute(
        """
        SELECT continuation_intent_id, settlement_intent_id
        FROM runtime_outcome_consumption_records
        WHERE command_id = 'turn-command-1'
        """
    ).fetchone() == ("runtime-continuation-1", "runtime-settlement-1")


def test_controlled_operation_codec_preserves_effect_certainty_facts() -> None:
    connection, store, authority = _store()
    admitted = {
        "session_id": "session-1",
        "actor_id": "agent-member-1",
        "owner_plugin_id": "enzymedesign.hmmer",
        "operation_id": "operation-1",
        "intent_digest": canonical_sha256_digest({"intent": "hmmer-search"}),
        "route_id": "hpc-primary/hmmer-3.4",
        "authority_lease_id": authority.lease_id,
        "authority_generation": 1,
        "authority_fence": 1,
        "authority_operation": "external_compute",
        "scope_id": "session-1",
        "dispatch_generation": 1,
        "state": "admitted",
        "effect_certainty": "no_effect",
        "mutation_applied": False,
        "deadline": FUTURE,
        "approval_required": False,
        "approval_id": None,
        "cancel_intent_digest": None,
        "result_handle": None,
        "terminal_receipt_digest": None,
        "last_observation_digest": None,
        "error_code": None,
        "diagnostic_id": None,
        "created_at": NOW,
        "updated_at": NOW,
        "safe_intent": {
            "authority_operation": "external_compute",
            "scope_id": "session-1",
            "approval_required": False,
        },
        "fallback_performed": False,
    }
    _commit(
        store,
        command="operation-admit",
        entity_type="controlled_operation",
        entity_id="operation-1",
        payload=admitted,
    )
    uncertain = {
        **admitted,
        "state": "reconcile_required",
        "effect_certainty": "dispatch_in_doubt",
        "mutation_applied": None,
        "last_observation_digest": canonical_sha256_digest({"observation": 1}),
        "updated_at": "2026-08-21T00:05:00+00:00",
    }
    _commit(
        store,
        command="operation-observe",
        entity_type="controlled_operation",
        entity_id="operation-1",
        payload=uncertain,
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )

    assert store.read(
        entity_type="controlled_operation", entity_id="operation-1"
    ) == KernelRecordSnapshot.create(
        entity_type="controlled_operation",
        entity_id="operation-1",
        state_version=2,
        payload=uncertain,
    )
    assert connection.execute(
        """
        SELECT record_kind, logical_operation_key, kernel_state,
               effect_certainty, mutation_applied, fallback_performed
        FROM controlled_operation_records WHERE operation_id = 'operation-1'
        """
    ).fetchone() == (
        "kernel_controlled_operation",
        None,
        "reconcile_required",
        "dispatch_in_doubt",
        None,
        0,
    )
