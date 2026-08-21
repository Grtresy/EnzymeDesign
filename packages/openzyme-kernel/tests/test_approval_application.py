from __future__ import annotations

import pytest

from openzyme_contracts import KernelRecordSnapshot
from openzyme_extension_spi import ApprovalApplicationCommand
from openzyme_extension_spi import ApprovalCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import ApprovalKernelApplicationService
from openzyme_kernel import KernelContractError

from test_controlled_operation_application import _Clock
from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store
from test_controlled_operation_application import _digest


def _store() -> _Store:
    store = _Store()
    store.records[("agent_authority_lease", "lease-1")] = KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "agent_member_id": "agent-1",
            "agent_id": "agent-1",
            "workspace_generation": 1,
            "state": "active",
            "generation": 3,
            "fence": 8,
            "lease_digest": _digest("lease-1"),
            "expires_at": "2026-08-20T11:00:00+00:00",
            "grants": [
                {
                    "scope_id": "session-1",
                    "operations": ["approval.request", "approval.consume"],
                }
            ],
        },
    )
    store.records[("agent_member", "agent-1")] = KernelRecordSnapshot.create(
        entity_type="agent_member",
        entity_id="agent-1",
        state_version=1,
        payload={
            "agent_member_id": "agent-1",
            "agent_id": "agent-1",
            "session_id": "session-1",
            "lane_id": None,
            "status": "active",
            "process_epoch": 1,
            "active_authority_lease_id": "lease-1",
            "workspace_generation": 1,
        },
    )
    return store


def _context(*, phase: str, session_version: int) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-{phase}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=session_version,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"approval-{phase}",
        correlation_id="correlation-1",
    )


def _service(store: _Store, *, clock: _Clock | None = None):
    return ApprovalKernelApplicationService(
        store=store,
        clock=clock or _Clock(),
        ids=_Ids(),
    )


def _request(*, expires_at: str = "2026-08-20T10:30:00+00:00"):
    return ApprovalApplicationCommand(
        context=_context(phase="request", session_version=4),
        operation=ApprovalCommandKind.REQUEST,
        approval_id="approval-1",
        intent_digest=_digest("external-effect-intent"),
        payload={
            "requested_action": "external.compute.submit",
            "scope_id": "operation-1",
            "expires_at": expires_at,
            "reason": "requires external compute",
        },
    )


def test_request_and_consume_are_distinct_from_operation_dispatch() -> None:
    store = _store()
    service = _service(store)
    requested = service.execute(_request())
    resolved = service.execute(
        ApprovalApplicationCommand(
            context=_context(phase="consume", session_version=5),
            operation=ApprovalCommandKind.CONSUME,
            approval_id="approval-1",
            intent_digest=_digest("external-effect-intent"),
            payload={
                "decision": "approved",
                "resolution_ref": "operator-resolution-1",
            },
        )
    )

    approval = store.read(entity_type="approval_request", entity_id="approval-1")
    assert requested.result == {
        "approval_id": "approval-1",
        "status": "pending",
        "operation_dispatched": False,
    }
    assert resolved.result["status"] == "approved"
    assert resolved.result["operation_dispatched"] is False
    assert approval.payload["status"] == "approved"
    assert approval.payload["operation_dispatched"] is False
    signals = [
        record
        for (kind, _), record in store.records.items()
        if kind == "agent_runtime_signal"
    ]
    assert len(signals) == 1
    assert signals[0].payload["reason"] == "approval_resolved"


def test_intent_drift_and_duplicate_resolution_fail_closed() -> None:
    store = _store()
    service = _service(store)
    service.execute(_request())
    wrong = ApprovalApplicationCommand(
        context=_context(phase="wrong", session_version=5),
        operation=ApprovalCommandKind.CONSUME,
        approval_id="approval-1",
        intent_digest=_digest("another-intent"),
        payload={"decision": "approved", "resolution_ref": "resolution-1"},
    )
    with pytest.raises(KernelContractError, match="exact request intent") as drift:
        service.execute(wrong)
    assert drift.value.code == "approval_intent_mismatch"

    valid = ApprovalApplicationCommand(
        context=_context(phase="valid", session_version=5),
        operation=ApprovalCommandKind.CONSUME,
        approval_id="approval-1",
        intent_digest=_digest("external-effect-intent"),
        payload={"decision": "rejected", "resolution_ref": "resolution-2"},
    )
    service.execute(valid)
    duplicate = ApprovalApplicationCommand(
        context=_context(phase="duplicate", session_version=6),
        operation=ApprovalCommandKind.CONSUME,
        approval_id="approval-1",
        intent_digest=_digest("external-effect-intent"),
        payload={"decision": "approved", "resolution_ref": "resolution-3"},
    )
    with pytest.raises(KernelContractError, match="cannot be resolved again"):
        service.execute(duplicate)


def test_expired_request_is_rejected_without_approval_record() -> None:
    store = _store()
    with pytest.raises(KernelContractError, match="future") as expired:
        _service(store).execute(_request(expires_at="2026-08-20T09:00:00+00:00"))
    assert expired.value.code == "approval_expiry_invalid"
    assert store.read(entity_type="approval_request", entity_id="approval-1") is None
    assert store.events == []
