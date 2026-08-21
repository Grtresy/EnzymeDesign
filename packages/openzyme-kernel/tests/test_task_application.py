from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import EvidenceKind
from openzyme_contracts import EvidenceRef
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import UnitOfWorkReceipt
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import TaskApplicationCommand
from openzyme_extension_spi import TaskCommandKind
from openzyme_extension_spi import TaskEvidenceValidation
from openzyme_kernel import FinishValidatorBinding
from openzyme_kernel import FinishValidatorRegistry
from openzyme_kernel import KernelContractError
from openzyme_kernel import TaskKernelApplicationService


def _digest(label: str) -> str:
    return canonical_sha256_digest({"label": label})


@dataclass
class _Clock:
    value: str = "2026-08-20T10:00:00+00:00"

    def now_iso(self) -> str:
        return self.value


@dataclass
class _Ids:
    value: int = 0

    def new_id(self, *, namespace: str) -> str:
        self.value += 1
        return f"{namespace}-{self.value}"


class _Store:
    provider_id = "fake.control-store"
    provider_contract_digest = _digest("fake-control-store")

    def __init__(self, records: tuple[KernelRecordSnapshot, ...]) -> None:
        self.records = {
            (record.entity_type, record.entity_id): record for record in records
        }
        self.events = []
        self.outbox = []

    def read(self, *, entity_type: str, entity_id: str):
        return self.records.get((entity_type, entity_id))

    def begin(self, request):  # noqa: ANN001
        return _Unit(self, request)


class _Unit:
    def __init__(self, store: _Store, request) -> None:  # noqa: ANN001
        self.store = store
        self.request = request
        self.mutations = []
        self.events = []
        self.outbox = []
        self.completed = False

    def read(self, *, entity_type: str, entity_id: str):
        return self.store.read(entity_type=entity_type, entity_id=entity_id)

    def stage(self, mutation) -> None:  # noqa: ANN001
        self.mutations.append(mutation)

    def append_event(self, event) -> None:  # noqa: ANN001
        self.events.append(event)

    def append_outbox(self, record) -> None:  # noqa: ANN001
        self.outbox.append(record)

    def commit(self) -> UnitOfWorkReceipt:
        if self.completed:
            raise AssertionError("Unit of Work already completed")
        next_records = dict(self.store.records)
        for mutation in self.mutations:
            key = (mutation.entity_type, mutation.entity_id)
            current = next_records.get(key)
            if mutation.kind is not KernelMutationKind.REPLACE or current is None:
                raise AssertionError("test fake supports exact replace only")
            if current.state_version != mutation.expected_state_version:
                raise KernelContractError("fake_cas_stale", "fake CAS rejected")
            next_records[key] = KernelRecordSnapshot.create(
                entity_type=mutation.entity_type,
                entity_id=mutation.entity_id,
                state_version=current.state_version + 1,
                payload=mutation.payload or {},
            )
        self.store.records = next_records
        self.store.events.extend(self.events)
        self.store.outbox.extend(self.outbox)
        self.completed = True
        session = self.store.read(
            entity_type="session",
            entity_id=self.request.session_id,
        )
        return UnitOfWorkReceipt.create(
            unit_of_work_id=self.request.unit_of_work_id,
            command_id=self.request.command_id,
            committed=True,
            mutation_digests=tuple(item.mutation_digest for item in self.mutations),
            event_digests=tuple(item.event_digest for item in self.events),
            outbox_payload_digests=tuple(
                item.payload_digest for item in self.outbox
            ),
            resulting_session_version=session.state_version,
        )

    def rollback(self) -> None:
        self.completed = True


@dataclass
class _Validator:
    validator_id: str = "openzyme.science.finish"
    accepted: bool = True
    calls: int = 0

    def validate(self, context, task, evidence_refs):  # noqa: ANN001
        self.calls += 1
        codes = () if self.accepted else ("scientific_closure_missing",)
        return TaskEvidenceValidation(
            accepted=self.accepted,
            validator_ids=(self.validator_id,),
            rejection_codes=codes,
            validation_digest=_digest(
                f"validation:{task.entity.state_version}:{len(evidence_refs)}:"
                f"{self.accepted}"
            ),
        )


def _records(*, owner: str = "agent-1") -> tuple[KernelRecordSnapshot, ...]:
    evidence = _evidence()
    return (
        KernelRecordSnapshot.create(
            entity_type="session",
            entity_id="session-1",
            state_version=4,
            payload={
                "project_id": "project-1",
                "status": "active",
                "updated_at": "2026-08-20T09:00:00+00:00",
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="task",
            entity_id="task-1",
            state_version=2,
            payload={
                "session_id": "session-1",
                "owner_actor_id": owner,
                "status": "in_progress",
                "subject": "Design enzyme",
                "finish_validator_ids": ["openzyme.science.finish"],
                "updated_at": "2026-08-20T09:00:00+00:00",
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_authority_lease",
            entity_id="lease-1",
            state_version=1,
            payload={
                "session_id": "session-1",
                "agent_member_id": "agent-1",
                "state": "active",
                "generation": 3,
                "fence": 8,
                "expires_at": "2026-08-20T11:00:00+00:00",
                "grants": [
                    {
                        "scope_id": "task-1",
                        "operations": ["task.update", "task.finish"],
                    }
                ],
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="task_evidence",
            entity_id=evidence.evidence_id,
            state_version=1,
            payload={
                "session_id": "session-1",
                "task_id": "task-1",
                "evidence_digest": evidence.evidence_digest,
                "evidence_ref": evidence.to_dict(),
            },
        ),
    )


def _context(*, actor_id: str = "agent-1") -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command-1",
        session_id="session-1",
        actor_id=actor_id,
        owner_plugin_id="openzyme.science",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=4,
        extension_bundle_digest=_digest("extension-bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="finish-task-1",
        correlation_id="correlation-1",
    )


def _evidence() -> EvidenceRef:
    return EvidenceRef(
        evidence_id="evidence-1",
        evidence_kind=EvidenceKind.EXTENSION,
        contract_id="science-closure-1",
        owner_component_id="openzyme.science",
        project_id="project-1",
        session_id="session-1",
        task_id="task-1",
        subject_ref="closure-1",
        subject_digest=_digest("closure-1"),
        attributes={},
    )


def _service(store: _Store, validator: _Validator) -> TaskKernelApplicationService:
    return TaskKernelApplicationService(
        store=store,
        reader=store,
        clock=_Clock(),
        ids=_Ids(),
        finish_validators=FinishValidatorRegistry(
            (FinishValidatorBinding("openzyme.science", validator),)
        ),
    )


def test_explicit_owner_finish_validates_then_commits_task_event_and_outbox_atomically() -> None:
    store = _Store(_records())
    validator = _Validator()
    receipt = _service(store, validator).execute(
        TaskApplicationCommand(
            context=_context(),
            operation=TaskCommandKind.FINISH,
            task_id="task-1",
            expected_task_version=2,
            payload={"terminal_status": "completed"},
            evidence_refs=(_evidence(),),
        )
    )

    task = store.read(entity_type="task", entity_id="task-1")
    session = store.read(entity_type="session", entity_id="session-1")
    assert task.state_version == 3
    assert task.payload["status"] == "completed"
    assert task.payload["finished_by_actor_id"] == "agent-1"
    assert task.payload["finish_validation_digest"]
    assert session.state_version == 5
    assert validator.calls == 1
    assert len(store.events) == len(store.outbox) == 1
    assert store.events[0].payload["explicit_finish"] is True
    assert receipt.mutation_applied is True
    assert receipt.effect_certainty.value == "no_effect"
    assert receipt.fallback_performed is False


def test_non_terminal_update_cannot_smuggle_a_terminal_transition() -> None:
    store = _Store(_records())
    with pytest.raises(KernelContractError, match="explicit task.finish") as rejected:
        _service(store, _Validator()).execute(
            TaskApplicationCommand(
                context=_context(),
                operation=TaskCommandKind.UPDATE_NON_TERMINAL,
                task_id="task-1",
                expected_task_version=2,
                payload={"status": "completed"},
            )
        )
    assert rejected.value.code == "task_terminal_transition_requires_finish"
    assert store.read(entity_type="task", entity_id="task-1").state_version == 2
    assert store.events == []


def test_validator_receipt_or_failure_never_completes_task_by_itself() -> None:
    store = _Store(_records())
    validator = _Validator(accepted=False)
    service = _service(store, validator)
    with pytest.raises(KernelContractError, match="rejected") as rejected:
        service.execute(
            TaskApplicationCommand(
                context=_context(),
                operation=TaskCommandKind.FINISH,
                task_id="task-1",
                expected_task_version=2,
                payload={"terminal_status": "completed"},
                evidence_refs=(_evidence(),),
            )
        )

    assert rejected.value.code == "task_finish_evidence_rejected"
    assert validator.calls == 1
    assert store.read(entity_type="task", entity_id="task-1").payload["status"] == "in_progress"
    assert store.events == []


def test_finish_requires_task_owner_and_exact_active_lease_fence() -> None:
    store = _Store(_records(owner="agent-2"))
    with pytest.raises(KernelContractError, match="canonical Task owner") as owner:
        _service(store, _Validator()).execute(
            TaskApplicationCommand(
                context=_context(),
                operation=TaskCommandKind.FINISH,
                task_id="task-1",
                expected_task_version=2,
                payload={},
                evidence_refs=(_evidence(),),
            )
        )
    assert owner.value.code == "task_finish_owner_required"

    store = _Store(_records())
    stale = replace(_context(), authority_fence=9)
    with pytest.raises(KernelContractError, match="stale") as fence:
        _service(store, _Validator()).execute(
            TaskApplicationCommand(
                context=stale,
                operation=TaskCommandKind.FINISH,
                task_id="task-1",
                expected_task_version=2,
                payload={},
                evidence_refs=(_evidence(),),
            )
        )
    assert fence.value.code == "authority_fence_stale"
    assert store.read(entity_type="task", entity_id="task-1").state_version == 2
