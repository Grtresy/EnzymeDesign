from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import KernelUnitOfWork
from openzyme_contracts import OutboxRecord
from openzyme_contracts import UnitOfWorkReceipt
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _request() -> UnitOfWorkRequest:
    return UnitOfWorkRequest(
        unit_of_work_id="uow-1",
        command_id="command-1",
        session_id="session-1",
        actor_id="member-1",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=7,
        expected_session_version=4,
        idempotency_key="task-update-1",
        command_digest=_digest("command"),
    )


class _FakeUnitOfWork(KernelUnitOfWork):
    def __init__(self, request: UnitOfWorkRequest) -> None:
        self.request = request
        self.records: dict[tuple[str, str], KernelRecordSnapshot] = {}
        self.mutations: list[KernelStateMutation] = []
        self.events: list[DurableEventRecord] = []
        self.outbox: list[OutboxRecord] = []
        self.rolled_back = False

    def read(
        self,
        *,
        entity_type: str,
        entity_id: str,
    ) -> KernelRecordSnapshot | None:
        return self.records.get((entity_type, entity_id))

    def stage(self, mutation: KernelStateMutation) -> None:
        self.mutations.append(mutation)

    def append_event(self, event: DurableEventRecord) -> None:
        self.events.append(event)

    def append_outbox(self, record: OutboxRecord) -> None:
        self.outbox.append(record)

    def commit(self) -> UnitOfWorkReceipt:
        return UnitOfWorkReceipt.create(
            unit_of_work_id=self.request.unit_of_work_id,
            command_id=self.request.command_id,
            committed=True,
            mutation_digests=tuple(item.mutation_digest for item in self.mutations),
            event_digests=tuple(item.event_digest for item in self.events),
            outbox_payload_digests=tuple(
                item.payload_digest for item in self.outbox
            ),
            resulting_session_version=self.request.expected_session_version + 1,
        )

    def rollback(self) -> None:
        self.rolled_back = True


class _FakeStore(ControlStorePort):
    provider_id = "test.store.memory"
    provider_contract_digest = _digest("store")

    def begin(self, request: UnitOfWorkRequest) -> KernelUnitOfWork:
        return _FakeUnitOfWork(request)


def test_control_store_port_has_bounded_cas_mutation_event_and_outbox() -> None:
    request = _request()
    unit_of_work = _FakeStore().begin(request)
    mutation = KernelStateMutation.create(
        mutation_id="mutation-1",
        kind=KernelMutationKind.REPLACE,
        entity_type="Task",
        entity_id="task-1",
        expected_state_version=2,
        payload={"status": "in_progress"},
    )
    event = DurableEventRecord.create(
        event_id="event-1",
        session_id="session-1",
        event_type="task.updated",
        source_entity_type="Task",
        source_entity_id="task-1",
        source_state_version=3,
        command_id="command-1",
        payload={"status": "in_progress"},
    )
    outbox = OutboxRecord(
        outbox_id="outbox-1",
        session_id="session-1",
        topic="runtime.wakeup",
        occurrence_id="signal-1",
        payload={"signal_id": "signal-1"},
        payload_digest=canonical_sha256_digest({"signal_id": "signal-1"}),
        created_at="2026-08-19T00:00:00Z",
    )

    unit_of_work.stage(mutation)
    unit_of_work.append_event(event)
    unit_of_work.append_outbox(outbox)
    receipt = unit_of_work.commit()

    assert receipt.committed is True
    assert receipt.mutation_digests == (mutation.mutation_digest,)
    assert receipt.event_digests == (event.event_digest,)
    assert receipt.outbox_payload_digests == (outbox.payload_digest,)
    assert receipt.resulting_session_version == 5
    assert receipt.to_dict()["receipt_digest"] == receipt.receipt_digest


def test_record_and_mutation_payloads_are_immutable_and_digest_bound() -> None:
    record = KernelRecordSnapshot.create(
        entity_type="Task",
        entity_id="task-1",
        state_version=2,
        payload={"status": "todo"},
    )
    mutation = KernelStateMutation.create(
        mutation_id="mutation-1",
        kind=KernelMutationKind.CREATE,
        entity_type="Task",
        entity_id="task-2",
        expected_state_version=None,
        payload={"status": "todo"},
    )

    with pytest.raises(TypeError):
        record.payload["status"] = "completed"  # type: ignore[index]
    with pytest.raises(FrozenInstanceError):
        mutation.entity_id = "task-3"  # type: ignore[misc]
    with pytest.raises(ValueError, match="does not match"):
        KernelRecordSnapshot(
            entity_type="Task",
            entity_id="task-1",
            state_version=2,
            payload={"status": "todo"},
            record_digest=_digest("wrong"),
        )


def test_mutation_requires_explicit_compare_and_swap_semantics() -> None:
    with pytest.raises(ValueError, match="requires expected_state_version"):
        KernelStateMutation.create(
            mutation_id="mutation-1",
            kind=KernelMutationKind.REPLACE,
            entity_type="Task",
            entity_id="task-1",
            expected_state_version=None,
            payload={"status": "completed"},
        )
    with pytest.raises(ValueError, match="must not carry payload"):
        KernelStateMutation.create(
            mutation_id="mutation-2",
            kind=KernelMutationKind.DELETE,
            entity_type="Task",
            entity_id="task-1",
            expected_state_version=2,
            payload={"status": "deleted"},
        )
