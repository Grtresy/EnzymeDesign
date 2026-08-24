from __future__ import annotations

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureObservation
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import RetryEligibility
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import observe_structured_failure
from openzyme_contracts.identity import json_compatible
from openzyme_extension_spi import ContinuationApplicationCommand
from openzyme_extension_spi import ContinuationCommandKind
from openzyme_extension_spi import FailureRecordCommand
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import ContinuationKernelApplicationService
from openzyme_kernel import FailureKernelApplicationService
from openzyme_kernel import KernelContractError

from test_controlled_operation_application import _Clock
from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store
from test_controlled_operation_application import _digest


def _store() -> _Store:
    store = _Store()
    store.records[("agent_member", "agent-1")] = KernelRecordSnapshot.create(
        entity_type="agent_member",
        entity_id="agent-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "status": "active",
            "process_epoch": 5,
        },
    )
    store.records[("agent_authority_lease", "lease-1")] = KernelRecordSnapshot.create(
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
                    "scope_id": "session-1",
                    "operations": [
                        "continuation.register",
                        "continuation.deliver",
                        "continuation.fail",
                        "failure.record",
                    ],
                }
            ],
        },
    )
    return store


def _context(*, phase: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-{phase}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=4,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"coordination-{phase}",
        correlation_id="correlation-1",
    )


def test_continuation_register_and_delivery_are_fenced_and_do_not_finish_task() -> None:
    store = _store()
    service = ContinuationKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
    )
    registered = service.execute(
        ContinuationApplicationCommand(
            context=_context(phase="register"),
            operation=ContinuationCommandKind.REGISTER,
            continuation_id="continuation-1",
            source_version=3,
            payload={
                "source_ref": "runtime-outcome-1",
                "source_digest": _digest("runtime-outcome-1"),
                "recipient_actor_id": "agent-1",
                "resume_strategy": "journaled_sdk_call_boundary",
            },
        )
    )
    delivered = service.execute(
        ContinuationApplicationCommand(
            context=_context(phase="deliver"),
            operation=ContinuationCommandKind.DELIVER,
            continuation_id="continuation-1",
            source_version=3,
            payload={
                "delivery_receipt_digest": _digest("delivery"),
                "process_epoch": 5,
            },
        )
    )
    assert registered.result["state"] == "ready"
    assert delivered.result["state"] == "delivered"
    assert delivered.result["task_transition_performed"] is False
    record = store.read(entity_type="continuation", entity_id="continuation-1")
    assert record.state_version == 2
    assert record.payload["delivery_attempt"] == 1


def test_stale_continuation_epoch_is_rejected_before_delivery_mutation() -> None:
    store = _store()
    service = ContinuationKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
    )
    service.execute(
        ContinuationApplicationCommand(
            context=_context(phase="register"),
            operation=ContinuationCommandKind.REGISTER,
            continuation_id="continuation-1",
            source_version=3,
            payload={
                "source_ref": "runtime-outcome-1",
                "source_digest": _digest("runtime-outcome-1"),
                "recipient_actor_id": "agent-1",
                "resume_strategy": "journaled_sdk_call_boundary",
            },
        )
    )
    with pytest.raises(KernelContractError, match="process epoch") as stale:
        service.execute(
            ContinuationApplicationCommand(
                context=_context(phase="deliver"),
                operation=ContinuationCommandKind.DELIVER,
                continuation_id="continuation-1",
                source_version=3,
                payload={
                    "delivery_receipt_digest": _digest("delivery"),
                    "process_epoch": 6,
                },
            )
        )
    assert stale.value.code == "continuation_process_epoch_stale"
    assert (
        store.read(entity_type="continuation", entity_id="continuation-1").state_version
        == 1
    )


def _failure() -> FailureObservation:
    return FailureObservation(
        failure_id="failure-1",
        session_id="session-1",
        source_kind="workspace.process",
        source_ref="operation-1",
        source_version="1",
        phase="dispatch",
        failure_class=FailureClass.CONTROLLED_EFFECT,
        recoverability=FailureRecoverability.RECONCILIATION_REQUIRED,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        retry_eligibility=RetryEligibility.RECONCILE_REQUIRED,
        actor_kind=FailureActorKind.HARNESS,
        error_code="response_lost",
        safe_summary="Provider response was lost after dispatch.",
        facts={"fallback_performed": False},
        likely_causes=("provider_response_lost",),
        evidence_refs=(),
        created_at="2026-08-20T10:00:00+00:00",
        component="openzyme.workspace",
        operation="workspace.exec",
        mutation_applied=False,
        fallback_performed=False,
        diagnostic_id="diagnostic-1",
        next_action="reconcile",
    )


def test_failure_record_preserves_effect_certainty_and_is_immutable() -> None:
    store = _store()
    service = FailureKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
    )
    command = FailureRecordCommand(
        context=_context(phase="failure"),
        observation=_failure(),
    )
    receipt = service.record(command)
    assert receipt.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert receipt.result["task_transition_performed"] is False
    record = store.read(entity_type="failure_observation", entity_id="failure-1")
    assert record.payload["effect_certainty"] == "dispatch_in_doubt"
    assert "private_diagnostic_digest" not in record.payload

    duplicate = service.record(command)
    assert duplicate.mutation_applied is False
    assert duplicate.event_refs == ()
    assert duplicate.result["duplicate"] is True


def test_failure_record_atomically_preserves_exact_private_pair_and_reuses_ingress_authority() -> (
    None
):
    store = _store()
    authority = store.read(entity_type="agent_authority_lease", entity_id="lease-1")
    store.records[("agent_authority_lease", "lease-1")] = KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=authority.state_version,
        payload={
            **authority.payload,
            "grants": [
                {
                    "scope_id": "session-1",
                    "operations": ["conversation.message.ingress"],
                }
            ],
        },
    )
    records = observe_structured_failure(
        RuntimeError("operator-only-token=top-secret"),
        context=StructuredFailureContext(
            failure_id="failure-private-1",
            diagnostic_id="diagnostic-private-1",
            session_id="session-1",
            component="openzyme.kernel.message-ingress",
            operation="resolve_workflow",
            phase="workflow_resolution",
            source_kind="conversation_message",
            source_ref="message-1",
            source_version=_digest("message-1"),
            created_at="2026-08-20T10:00:00+00:00",
            correlation_id="correlation-1",
        ),
        failure_class=FailureClass.RUNTIME,
        recoverability=FailureRecoverability.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.HARNESS,
        error_code="workflow_resolution_failed",
        safe_summary="Workflow resolution failed before message admission.",
        safe_hint="Inspect the operator diagnostic.",
        next_action="inspect_diagnostic",
        mutation_applied=False,
        private_context={"raw_workflow_ref": "operator-only-token=top-secret"},
    )
    service = FailureKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
    )
    command = FailureRecordCommand(
        context=_context(phase="failure-private"),
        observation=records.public,
    )

    receipt = service.record(
        command,
        private_diagnostic=records.private,
        authorization_operation="conversation.message.ingress",
    )
    assert receipt.mutation_applied is True
    public = store.read(
        entity_type="failure_observation", entity_id=records.public.failure_id
    )
    private = store.read(
        entity_type="private_diagnostic", entity_id=records.private.diagnostic_id
    )
    assert json_compatible(public.payload) == records.public.to_internal_dict()
    assert json_compatible(private.payload) == records.private.to_dict()
    assert "top-secret" not in str(records.public.to_dict())
    assert "private_diagnostic_digest" not in records.public.to_dict()

    event_count = len(store.events)
    outbox_count = len(store.outbox)
    duplicate = service.record(
        command,
        private_diagnostic=records.private,
        authorization_operation="conversation.message.ingress",
    )
    assert duplicate.mutation_applied is False
    assert duplicate.result["duplicate"] is True
    assert len(store.events) == event_count
    assert len(store.outbox) == outbox_count
