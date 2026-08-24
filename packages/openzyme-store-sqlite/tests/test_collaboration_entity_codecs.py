from __future__ import annotations

import sqlite3

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import AgentMemberSQLiteKernelEntityCodec
from openzyme_store_sqlite import ConversationMessageSQLiteKernelEntityCodec
from openzyme_store_sqlite import InboxMessageSQLiteKernelEntityCodec
from openzyme_store_sqlite import MemorySQLiteKernelEntityCodec
from openzyme_store_sqlite import ProtocolRecordSQLiteKernelEntityCodec
from openzyme_store_sqlite import SessionSQLiteKernelEntityCodec
from openzyme_store_sqlite import SQLiteControlStore
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration


def _store() -> tuple[sqlite3.Connection, SQLiteControlStore]:
    connection = sqlite3.connect(":memory:")
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(connection)
    install_store_schema_for_offline_migration(connection)
    return connection, SQLiteControlStore(
        connection,
        codecs=(
            AgentMemberSQLiteKernelEntityCodec(),
            ConversationMessageSQLiteKernelEntityCodec(),
            InboxMessageSQLiteKernelEntityCodec(),
            MemorySQLiteKernelEntityCodec(),
            ProtocolRecordSQLiteKernelEntityCodec(),
            SessionSQLiteKernelEntityCodec(),
        ),
    )


def _request(command: str) -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id=f"uow-{command}",
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="agent-1",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key=f"idempotency-{command}",
        command_digest=canonical_sha256_digest({"command": command}),
    )


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
    unit = store.begin(_request(command))
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
    state_version = 1 if expected_state_version is None else expected_state_version + 1
    event = DurableEventRecord.create(
        event_id=f"event-{command}",
        session_id="session-1",
        event_type=f"{entity_type}.{command}",
        source_entity_type=entity_type,
        source_entity_id=entity_id,
        source_state_version=state_version,
        command_id=f"command-{command}",
        payload={"entity_id": entity_id},
    )
    occurrence = {"event_id": event.event_id}
    unit.append_event(event)
    unit.append_outbox(
        OutboxRecord(
            outbox_id=f"outbox-{command}",
            session_id="session-1",
            topic="openzyme.kernel.collaboration-events",
            occurrence_id=event.event_id,
            payload=occurrence,
            payload_digest=canonical_sha256_digest(occurrence),
            created_at="2026-08-20T00:00:00+00:00",
        )
    )
    unit.commit()


def _bootstrap_session(store: SQLiteControlStore) -> None:
    _commit(
        store,
        command="session-created",
        entity_type="session",
        entity_id="session-1",
        payload={
            "session_id": "session-1",
            "project_id": "project-1",
            "title": "Kernel qualification",
            "objective": "prove collaboration owner codecs",
            "status": "active",
            "created_at": "2026-08-20T00:00:00+00:00",
            "updated_at": "2026-08-20T00:00:00+00:00",
        },
    )


def test_agent_conversation_and_memory_use_existing_semantic_owner_tables() -> None:
    connection, store = _store()
    _bootstrap_session(store)
    agent = {
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
        "created_at": "2026-08-20T00:01:00+00:00",
        "updated_at": "2026-08-20T00:01:00+00:00",
    }
    _commit(
        store,
        command="agent-created",
        entity_type="agent_member",
        entity_id="agent-1",
        payload=agent,
    )
    assert store.read(entity_type="agent_member", entity_id="agent-1") == (
        KernelRecordSnapshot.create(
            entity_type="agent_member",
            entity_id="agent-1",
            state_version=1,
            payload=agent,
        )
    )

    updated_agent = {
        **agent,
        "owned_task_ids": ["task-1"],
        "workspace_generation": 1,
        "updated_at": "2026-08-20T00:02:00+00:00",
    }
    _commit(
        store,
        command="agent-updated",
        entity_type="agent_member",
        entity_id="agent-1",
        payload=updated_agent,
        kind=KernelMutationKind.REPLACE,
        expected_state_version=1,
    )
    assert store.read(entity_type="agent_member", entity_id="agent-1") == (
        KernelRecordSnapshot.create(
            entity_type="agent_member",
            entity_id="agent-1",
            state_version=2,
            payload=updated_agent,
        )
    )

    conversation = {
        "message_id": "message-1",
        "session_id": "session-1",
        "sender_actor_id": "agent-1",
        "admitted_by_actor_id": "agent-1",
        "sender_kind": "agent",
        "content": "Use the exact published revision.",
        "message_type": "instruction",
        "correlation_id": None,
        "task_id": None,
        "lane_id": None,
        "request_lineage_id": None,
        "workflow_refs": [],
        "skill_keys": [],
        "created_at": "2026-08-20T00:03:00+00:00",
    }
    _commit(
        store,
        command="conversation-created",
        entity_type="conversation_message",
        entity_id="message-1",
        payload=conversation,
    )
    assert store.read(entity_type="conversation_message", entity_id="message-1") == (
        KernelRecordSnapshot.create(
            entity_type="conversation_message",
            entity_id="message-1",
            state_version=1,
            payload=conversation,
        )
    )
    assert connection.execute(
        "SELECT document_kind, invocation_id FROM engine_documents WHERE document_id = ?",
        ("message-1",),
    ).fetchone() == ("conversation_message", None)

    memory = {
        "memory_id": "memory-1",
        "session_id": "session-1",
        "scope_kind": "task",
        "scope_ref": "task-1",
        "kind": "note",
        "summary": "Use immutable inputs only.",
        "source_range": None,
        "author_actor_id": "agent-1",
        "created_at": "2026-08-20T00:04:00+00:00",
    }
    _commit(
        store,
        command="memory-created",
        entity_type="memory",
        entity_id="memory-1",
        payload=memory,
    )
    assert store.read(entity_type="memory", entity_id="memory-1") == (
        KernelRecordSnapshot.create(
            entity_type="memory",
            entity_id="memory-1",
            state_version=1,
            payload=memory,
        )
    )
    assert connection.execute(
        "SELECT importance, author_actor_id FROM memory_entries WHERE memory_id = ?",
        ("memory-1",),
    ).fetchone() == (0, "agent-1")

    protocol = {
        "protocol_ref": "protocol-1",
        "session_id": "session-1",
        "sender_actor_id": "agent-1",
        "recipient_actor_id": "agent-2",
        "operation": "send",
        "payload": {
            "recipient_actor_id": "agent-2",
            "message_type": "status_request",
            "content": "Inspect the current revision.",
        },
        "status": "delivered_to_inbox",
        "created_at": "2026-08-20T00:05:00+00:00",
        "recipient_runtime_executed": False,
        "task_transition_performed": False,
    }
    _commit(
        store,
        command="protocol-created",
        entity_type="protocol_record",
        entity_id="protocol-1",
        payload=protocol,
    )
    assert store.read(entity_type="protocol_record", entity_id="protocol-1") == (
        KernelRecordSnapshot.create(
            entity_type="protocol_record",
            entity_id="protocol-1",
            state_version=1,
            payload=protocol,
        )
    )

    inbox = {
        "message_id": "inbox-1",
        "session_id": "session-1",
        "sender_actor_id": "agent-1",
        "sender_kind": "agent",
        "recipient_actor_id": "agent-2",
        "protocol_ref": "protocol-1",
        "message_type": "send",
        "correlation_id": "correlation-1",
        "status": "unread",
        "created_at": "2026-08-20T00:05:00+00:00",
    }
    _commit(
        store,
        command="inbox-created",
        entity_type="inbox_message",
        entity_id="inbox-1",
        payload=inbox,
    )
    assert store.read(entity_type="inbox_message", entity_id="inbox-1") == (
        KernelRecordSnapshot.create(
            entity_type="inbox_message",
            entity_id="inbox-1",
            state_version=1,
            payload=inbox,
        )
    )
    assert connection.execute(
        """
        SELECT sender_kind, recipient_kind, payload_ref
        FROM inbox_messages WHERE message_id = ?
        """,
        ("inbox-1",),
    ).fetchone() == ("agent", "agent", "protocol-1")

    assert "payload_json" not in {
        row[1]
        for row in connection.execute(
            "PRAGMA table_info(openzyme_store_kernel_entity_versions)"
        ).fetchall()
    }
