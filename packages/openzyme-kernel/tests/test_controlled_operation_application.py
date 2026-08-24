from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace

import pytest

from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import UnitOfWorkReceipt
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import KernelContractError


def _digest(label: str) -> str:
    return canonical_sha256_digest({"label": label})


@dataclass
class _Clock:
    def now_iso(self) -> str:
        return "2026-08-20T10:00:00+00:00"


@dataclass
class _Ids:
    value: int = 0

    def new_id(self, *, namespace: str) -> str:
        self.value += 1
        return f"{namespace}-{self.value}"


class _Store:
    provider_id = "fake.control-store"
    provider_contract_digest = _digest("fake-store")

    def __init__(self) -> None:
        records = (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=4,
                payload={"status": "active"},
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
                            "scope_id": "workspace-1",
                            "operations": ["workspace.fs.write"],
                        }
                    ],
                },
            ),
        )
        self.records = {(item.entity_type, item.entity_id): item for item in records}
        self.events = []
        self.outbox = []

    def read(self, *, entity_type: str, entity_id: str):
        return self.records.get((entity_type, entity_id))

    def list_for_session(
        self,
        *,
        entity_type: str,
        session_id: str,
        max_items: int,
    ):
        matches = tuple(
            record
            for (kind, _entity_id), record in sorted(self.records.items())
            if kind == entity_type
            and record.payload.get("session_id") == session_id
        )
        return matches[:max_items]

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
        next_records = dict(self.store.records)
        for mutation in self.mutations:
            key = (mutation.entity_type, mutation.entity_id)
            current = next_records.get(key)
            if mutation.kind is KernelMutationKind.CREATE:
                if current is not None:
                    raise KernelContractError("fake_create_conflict", "create conflict")
                version = 1
            else:
                if current is None or current.state_version != mutation.expected_state_version:
                    raise KernelContractError("fake_cas_stale", "replace conflict")
                version = current.state_version + 1
            next_records[key] = KernelRecordSnapshot.create(
                entity_type=mutation.entity_type,
                entity_id=mutation.entity_id,
                state_version=version,
                payload=mutation.payload or {},
            )
        self.store.records = next_records
        self.store.events.extend(self.events)
        self.store.outbox.extend(self.outbox)
        self.completed = True
        return UnitOfWorkReceipt.create(
            unit_of_work_id=self.request.unit_of_work_id,
            command_id=self.request.command_id,
            committed=True,
            mutation_digests=tuple(item.mutation_digest for item in self.mutations),
            event_digests=tuple(item.event_digest for item in self.events),
            outbox_payload_digests=tuple(item.payload_digest for item in self.outbox),
            resulting_session_version=4,
        )

    def rollback(self) -> None:
        self.completed = True


def _context(*, phase: str, fence: int = 8) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-1.{phase}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=fence,
        expected_session_version=4,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"operation-1.{phase}",
        correlation_id="correlation-1",
        workspace_generation=2,
        route_id="local-workspace-route",
    )


def _command(
    operation: ControlledOperationCommandKind,
    *,
    payload: dict,
    phase: str | None = None,
    fence: int = 8,
) -> ControlledOperationApplicationCommand:
    return ControlledOperationApplicationCommand(
        context=_context(phase=phase or operation.value, fence=fence),
        operation=operation,
        operation_id="operation-1",
        intent_digest=_digest("operation-intent"),
        payload=payload,
    )


def _admission() -> ControlledOperationApplicationCommand:
    return _command(
        ControlledOperationCommandKind.ADMIT,
        payload={
            "workspace_id": "workspace-1",
            "workspace_generation": 2,
            "operation_name": "workspace.fs.mutate",
            "authority_operation": "workspace.fs.write",
            "request_digest": _digest("operation-intent"),
            "fallback_performed": False,
        },
    )


def _service(store: _Store) -> ControlledOperationKernelApplicationService:
    return ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=_Clock(),
        ids=_Ids(),
    )


def test_admit_then_terminal_observation_uses_one_generic_operation_truth() -> None:
    store = _Store()
    service = _service(store)
    admitted = service.execute(_admission())
    settled = service.execute(
        _command(
            ControlledOperationCommandKind.OBSERVE,
            payload={
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "adapter_receipt_digest": _digest("adapter-receipt"),
                "fallback_performed": False,
            },
        )
    )

    record = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert admitted.result["state"] == "admitted"
    assert admitted.effect_certainty.value == "no_effect"
    assert settled.result["state"] == "settled"
    assert settled.effect_certainty.value == "terminal_known"
    assert record.state_version == 2
    assert record.payload["dispatch_generation"] == 1
    assert record.payload["fallback_performed"] is False
    assert len(store.events) == len(store.outbox) == 2


def test_dispatch_in_doubt_requires_explicit_reconciliation_without_redispatch() -> None:
    store = _Store()
    service = _service(store)
    service.execute(_admission())
    uncertain = service.execute(
        _command(
            ControlledOperationCommandKind.RECONCILE,
            phase="initial-uncertain",
            payload={
                "effect_certainty": "dispatch_in_doubt",
                "mutation_applied": None,
                "error_code": "response_lost",
                "fallback_performed": False,
            },
        )
    )
    assert uncertain.result["state"] == "reconcile_required"
    assert uncertain.result["redispatch_performed"] is False

    settled = service.execute(
        _command(
            ControlledOperationCommandKind.RECONCILE,
            phase="terminal-reconcile",
            payload={
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "adapter_receipt_digest": _digest("observation"),
                "fallback_performed": False,
            },
        )
    )
    assert settled.result["state"] == "settled"
    assert settled.result["dispatch_generation"] == 1
    assert settled.result["redispatch_performed"] is False


def test_uncertain_effect_reconciles_after_authority_revoke_by_original_identity() -> None:
    store = _Store()
    service = _service(store)
    service.execute(_admission())
    service.execute(
        _command(
            ControlledOperationCommandKind.RECONCILE,
            phase="initial-uncertain",
            payload={
                "effect_certainty": "dispatch_in_doubt",
                "mutation_applied": None,
                "error_code": "response_lost",
                "fallback_performed": False,
            },
        )
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="lease-1")
    store.records[("agent_authority_lease", "lease-1")] = KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=lease.state_version + 1,
        payload={**lease.payload, "state": "revoked"},
    )

    settled = service.execute(
        _command(
            ControlledOperationCommandKind.RECONCILE,
            phase="terminal-after-revoke",
            payload={
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "adapter_receipt_digest": _digest("observation"),
                "terminal_receipt_digest": _digest("terminal"),
                "fallback_performed": False,
            },
        )
    )

    assert settled.result["state"] == "settled"
    assert settled.result["redispatch_performed"] is False
    record = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert record.payload["authority_lease_id"] == "lease-1"
    assert record.payload["authority_generation"] == 3
    assert record.payload["authority_fence"] == 8


def test_uncertain_effect_reconcile_rejects_different_actor_after_revoke() -> None:
    store = _Store()
    service = _service(store)
    service.execute(_admission())
    service.execute(
        _command(
            ControlledOperationCommandKind.RECONCILE,
            phase="initial-uncertain",
            payload={
                "effect_certainty": "dispatch_in_doubt",
                "mutation_applied": None,
                "error_code": "response_lost",
                "fallback_performed": False,
            },
        )
    )
    lease = store.read(entity_type="agent_authority_lease", entity_id="lease-1")
    store.records[("agent_authority_lease", "lease-1")] = KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=lease.state_version + 1,
        payload={**lease.payload, "state": "revoked"},
    )
    wrong_actor = replace(
        _command(
            ControlledOperationCommandKind.RECONCILE,
            phase="wrong-actor",
            payload={
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "adapter_receipt_digest": _digest("observation"),
                "fallback_performed": False,
            },
        ),
        context=replace(_context(phase="wrong-actor"), actor_id="agent-2"),
    )

    with pytest.raises(KernelContractError) as rejected:
        service.execute(wrong_actor)

    assert rejected.value.code == "controlled_operation_identity_stale"
    record = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert record.payload["state"] == "reconcile_required"
    assert record.state_version == 2


def test_effect_known_remains_observable_until_terminal_fact_arrives() -> None:
    store = _Store()
    service = _service(store)
    service.execute(_admission())
    active = service.execute(
        _command(
            ControlledOperationCommandKind.OBSERVE,
            phase="active",
            payload={
                "effect_certainty": "effect_known",
                "mutation_applied": True,
                "result_handle": "provider-handle-1",
                "fallback_performed": False,
            },
        )
    )
    terminal = service.execute(
        _command(
            ControlledOperationCommandKind.OBSERVE,
            phase="terminal",
            payload={
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "result_handle": "provider-handle-1",
                "terminal_receipt_digest": _digest("terminal-receipt"),
                "fallback_performed": False,
            },
        )
    )

    assert active.result["state"] == "active"
    assert terminal.result["state"] == "settled"


def test_exact_retry_returns_same_receipt_and_conflicting_reuse_fails_closed() -> None:
    store = _Store()
    service = _service(store)
    command = _admission()
    first = service.execute(command)
    event_count = len(store.events)
    replay = service.execute(command)
    assert replay.receipt_digest == first.receipt_digest
    assert len(store.events) == event_count

    conflict = replace(command, intent_digest=_digest("another-intent"))
    with pytest.raises(KernelContractError, match="reused") as rejected:
        service.execute(conflict)
    assert rejected.value.code == "controlled_operation_idempotency_conflict"


def test_stale_authority_and_reconcile_before_uncertainty_have_zero_mutation() -> None:
    store = _Store()
    service = _service(store)
    with pytest.raises(KernelContractError, match="stale") as stale:
        service.execute(replace(_admission(), context=_context(phase="admit", fence=9)))
    assert stale.value.code == "authority_fence_stale"
    assert store.read(entity_type="controlled_operation", entity_id="operation-1") is None

    service.execute(_admission())
    with pytest.raises(KernelContractError, match="dispatch_in_doubt") as early:
        service.execute(
            _command(
                ControlledOperationCommandKind.RECONCILE,
                payload={
                    "effect_certainty": "terminal_known",
                    "mutation_applied": True,
                    "fallback_performed": False,
                },
            )
        )
    assert early.value.code == "controlled_operation_reconcile_not_required"
    assert store.read(entity_type="controlled_operation", entity_id="operation-1").state_version == 1


def test_admission_requires_exact_unexpired_approval_and_future_deadline() -> None:
    store = _Store()
    store.records[("approval_request", "approval-1")] = KernelRecordSnapshot.create(
        entity_type="approval_request",
        entity_id="approval-1",
        state_version=2,
        payload={
            "session_id": "session-1",
            "intent_digest": _digest("operation-intent"),
            "status": "approved",
            "expires_at": "2026-08-20T10:30:00+00:00",
        },
    )
    service = _service(store)
    command = replace(
        _admission(),
        payload={
            **_admission().payload,
            "approval_required": True,
            "approval_id": "approval-1",
            "deadline": "2026-08-20T10:20:00+00:00",
        },
    )

    receipt = service.execute(command)

    assert receipt.result["state"] == "admitted"
    record = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert record.payload["approval_id"] == "approval-1"
    assert record.payload["deadline"] == "2026-08-20T10:20:00+00:00"

    expired_store = _Store()
    expired_store.records[("approval_request", "approval-1")] = (
        KernelRecordSnapshot.create(
            entity_type="approval_request",
            entity_id="approval-1",
            state_version=2,
            payload={
                "session_id": "session-1",
                "intent_digest": _digest("operation-intent"),
                "status": "approved",
                "expires_at": "2026-08-20T09:59:59+00:00",
            },
        )
    )
    with pytest.raises(KernelContractError) as expired:
        _service(expired_store).execute(command)
    assert expired.value.code == "controlled_operation_approval_invalid"
    assert expired_store.read(
        entity_type="controlled_operation", entity_id="operation-1"
    ) is None

    past_deadline = replace(
        _admission(),
        payload={
            **_admission().payload,
            "deadline": "2026-08-20T09:59:59+00:00",
        },
    )
    with pytest.raises(KernelContractError) as invalid_deadline:
        _service(_Store()).execute(past_deadline)
    assert invalid_deadline.value.code == "controlled_operation_deadline_invalid"


def test_cancel_intent_is_separate_and_original_operation_can_still_settle() -> None:
    store = _Store()
    service = _service(store)
    service.execute(_admission())
    cancelled = service.execute(
        replace(
            _command(
                ControlledOperationCommandKind.CANCEL,
                phase="cancel",
                payload={"fallback_performed": False},
            ),
            intent_digest=_digest("cancel-intent"),
        )
    )
    assert cancelled.result["state"] == "cancel_requested"
    assert cancelled.effect_certainty.value == "no_effect"

    terminal = service.execute(
        _command(
            ControlledOperationCommandKind.OBSERVE,
            phase="observe-after-cancel",
            payload={
                "effect_certainty": "terminal_known",
                "mutation_applied": True,
                "result_handle": "provider-handle-1",
                "terminal_receipt_digest": _digest("terminal-receipt"),
                "fallback_performed": False,
            },
        )
    )
    assert terminal.result["state"] == "settled"
    record = store.read(entity_type="controlled_operation", entity_id="operation-1")
    assert record.payload["cancel_intent_digest"] == _digest("cancel-intent")
    assert record.payload["intent_digest"] == _digest("operation-intent")
    assert record.payload["result_handle"] == "provider-handle-1"
