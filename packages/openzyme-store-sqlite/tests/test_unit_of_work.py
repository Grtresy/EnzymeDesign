from __future__ import annotations

from dataclasses import dataclass
import sqlite3

import pytest

from openzyme_extension_spi import ExtensionMutationPlan
from openzyme_extension_spi import ExtensionMutationResult
from openzyme_extension_spi import ExtensionStateCommand
from openzyme_extension_spi import ExtensionStateMutation
from openzyme_extension_spi import ExtensionStateMutationKind
from openzyme_extension_spi import ExtensionTransactionBudget
from openzyme_extension_spi import KernelCommandContext
from openzyme_store_sqlite import SQLiteExtensionTransactionCoordinator
from openzyme_store_sqlite import ExtensionStateStoreError
from openzyme_store_sqlite import SQLiteUnitOfWork
from openzyme_store_sqlite import SQLiteUnitOfWorkError
from openzyme_store_sqlite import install_store_schema_for_offline_migration


_DIGEST = "sha256:" + "a" * 64


def _connection() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    install_store_schema_for_offline_migration(connection)
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _command() -> ExtensionStateCommand:
    return ExtensionStateCommand(
        context=KernelCommandContext(
            command_id="command-1",
            session_id="session-1",
            actor_id="agent-1",
            owner_plugin_id="openzyme.science",
            authority_lease_id="lease-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            extension_bundle_digest=_DIGEST,
            capability_binding_digest="sha256:" + "b" * 64,
            idempotency_key="idempotency-1",
            correlation_id="correlation-1",
        ),
        participant_id="openzyme.science.attempt-state",
        namespace="openzyme.science",
        operation="attempt.create",
        payload={"attempt_id": "attempt-1"},
    )


@dataclass
class _Participant:
    participant_id: str = "openzyme.science.attempt-state"
    state_namespace: str = "openzyme.science"
    fail_after_write: bool = False
    attempt_cross_namespace_sql: bool = False
    omit_store_receipt: bool = False

    def prepare(self, command, state):
        assert state.get(
            namespace=self.state_namespace,
            entity_kind="attempt",
            entity_id="attempt-1",
        ) is None
        mutation = ExtensionStateMutation(
            mutation_kind=ExtensionStateMutationKind.UPSERT,
            namespace=self.state_namespace,
            entity_kind="attempt",
            entity_id="attempt-1",
            expected_state_version=None,
            payload={"status": "open"},
        )
        return ExtensionMutationPlan.create(
            plan_id="plan-1",
            participant_id=self.participant_id,
            namespace=self.state_namespace,
            command_id=command.context.command_id,
            mutations=(mutation,),
            budget=ExtensionTransactionBudget(
                max_reads=10,
                max_mutations=10,
                max_payload_bytes=4096,
                max_duration_ms=500,
            ),
        )

    def apply(self, plan, state):
        record = state.upsert(plan.mutations[0])
        if self.attempt_cross_namespace_sql:
            raw = state._ExtensionStateStore__connection
            raw.execute("SELECT * FROM openzyme_store_durable_event_records")
        if self.fail_after_write:
            raise RuntimeError("participant failed")
        return ExtensionMutationResult.create(
            plan_id=plan.plan_id,
            participant_id=plan.participant_id,
            namespace=plan.namespace,
            mutation_applied=True,
            changed_records=() if self.omit_store_receipt else (record,),
            result={"attempt_id": record.entity_id},
        )


def test_participant_and_core_event_commit_atomically() -> None:
    connection = _connection()
    coordinator = SQLiteExtensionTransactionCoordinator(connection)

    def core_mutation(raw: sqlite3.Connection) -> None:
        raw.execute(
            """
            INSERT INTO openzyme_store_durable_event_records (
                event_id, command_id, event_kind, event_digest,
                event_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                "event-1",
                "command-1",
                "attempt.created",
                "sha256:" + "c" * 64,
                "{}",
                "2026-08-20T00:00:00Z",
            ),
        )

    result = coordinator.execute(
        command=_command(),
        participant=_Participant(),
        timestamp="2026-08-20T00:00:00Z",
        core_mutation=core_mutation,
    )

    assert result.mutation_applied is True
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0] == 1


def test_participant_failure_rolls_back_core_and_extension_writes() -> None:
    connection = _connection()
    coordinator = SQLiteExtensionTransactionCoordinator(connection)

    def core_mutation(raw: sqlite3.Connection) -> None:
        raw.execute(
            """
            INSERT INTO openzyme_store_durable_event_records (
                event_id, command_id, event_kind, event_digest,
                event_json, created_at
            ) VALUES ('event-1', 'command-1', 'attempt.created', ?, '{}', ?)
            """,
            ("sha256:" + "c" * 64, "2026-08-20T00:00:00Z"),
        )

    with pytest.raises(SQLiteUnitOfWorkError, match="rolled back") as caught:
        coordinator.execute(
            command=_command(),
            participant=_Participant(fail_after_write=True),
            timestamp="2026-08-20T00:00:00Z",
            core_mutation=core_mutation,
        )

    assert caught.value.mutation_applied is False
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0] == 0


def test_participant_raw_cross_table_sql_is_denied_and_rolled_back() -> None:
    connection = _connection()
    coordinator = SQLiteExtensionTransactionCoordinator(connection)

    with pytest.raises(ExtensionStateStoreError) as caught:
        coordinator.execute(
            command=_command(),
            participant=_Participant(attempt_cross_namespace_sql=True),
            timestamp="2026-08-20T00:00:00Z",
        )

    assert caught.value.phase == "sqlite_authorizer"
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 0


def test_participant_cannot_claim_a_result_different_from_store_receipts() -> None:
    connection = _connection()
    coordinator = SQLiteExtensionTransactionCoordinator(connection)

    with pytest.raises(SQLiteUnitOfWorkError, match="differ from Store receipts"):
        coordinator.execute(
            command=_command(),
            participant=_Participant(omit_store_receipt=True),
            timestamp="2026-08-20T00:00:00Z",
        )

    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_extension_state_records"
    ).fetchone()[0] == 0


def test_event_and_outbox_roll_back_together_on_identity_conflict() -> None:
    connection = _connection()
    with SQLiteUnitOfWork(connection) as unit:
        unit.append_event_with_outbox(
            event_id="event-1",
            command_id="command-1",
            event_kind="task.changed",
            event={"task_id": "task-1"},
            outbox_id="outbox-1",
            destination="runtime",
            payload={"event_id": "event-1"},
            created_at="2026-08-20T00:00:00Z",
        )
        unit.commit()

    with pytest.raises(SQLiteUnitOfWorkError):
        with SQLiteUnitOfWork(connection) as unit:
            unit.append_event_with_outbox(
                event_id="event-2",
                command_id="command-2",
                event_kind="task.changed",
                event={"task_id": "task-2"},
                outbox_id="outbox-1",
                destination="runtime",
                payload={"event_id": "event-2"},
                created_at="2026-08-20T00:01:00Z",
            )

    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_durable_event_records"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM openzyme_store_outbox_records"
    ).fetchone()[0] == 1
