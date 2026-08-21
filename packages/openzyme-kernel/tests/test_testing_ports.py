from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_kernel import KernelContractError
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _request() -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id="uow-1",
        command_id="command-1",
        session_id="session-1",
        actor_id="agent-1",
        authority_lease_id="lease-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=1,
        idempotency_key="idempotency-1",
        command_digest=_digest("command"),
    )


def _store() -> InMemoryControlStore:
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=1,
                payload={"status": "active"},
            ),
        )
    )


def test_fake_control_store_commits_state_event_and_outbox_atomically() -> None:
    store = _store()
    unit = store.begin(_request())
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-1",
            kind=KernelMutationKind.CREATE,
            entity_type="task",
            entity_id="task-1",
            expected_state_version=None,
            payload={"session_id": "session-1", "status": "pending"},
        )
    )
    event = DurableEventRecord.create(
        event_id="event-1",
        session_id="session-1",
        event_type="task.created",
        source_entity_type="task",
        source_entity_id="task-1",
        source_state_version=1,
        command_id="command-1",
        payload={"task_id": "task-1"},
    )
    unit.append_event(event)
    unit.append_outbox(
        OutboxRecord(
            outbox_id="outbox-1",
            session_id="session-1",
            topic="runtime",
            occurrence_id="event-1",
            payload={"event_id": "event-1"},
            payload_digest=canonical_sha256_digest({"event_id": "event-1"}),
            created_at="2026-08-20T00:00:00+00:00",
        )
    )

    receipt = unit.commit()

    assert receipt.committed is True
    assert store.read(entity_type="task", entity_id="task-1") is not None
    assert len(store.events) == len(store.outbox) == 1


def test_fake_control_store_rolls_back_without_partial_mutation() -> None:
    store = _store()
    unit = store.begin(_request())
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-1",
            kind=KernelMutationKind.CREATE,
            entity_type="task",
            entity_id="task-1",
            expected_state_version=None,
            payload={"session_id": "session-1"},
        )
    )
    unit.rollback()

    assert store.read(entity_type="task", entity_id="task-1") is None
    with pytest.raises(KernelContractError, match="cannot be reused"):
        unit.commit()


def test_deterministic_clock_and_ids_have_no_external_effects() -> None:
    clock = DeterministicClock(datetime(2026, 8, 20, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    clock.advance(seconds=5)

    assert clock.now_iso() == "2026-08-20T00:00:05+00:00"
    assert ids.new_id(namespace="event") == "event-1"
    assert ids.new_id(namespace="event") == "event-2"
