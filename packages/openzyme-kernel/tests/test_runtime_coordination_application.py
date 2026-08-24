from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import SessionRuntimeLeaseMode
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthoritySignalSourceKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import KernelContractError
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_kernel import RuntimeLeaseAction
from openzyme_kernel import RuntimeSignalClaimCommand
from openzyme_kernel import RuntimeSignalEnqueueCommand
from openzyme_kernel import SessionRuntimeLeaseCommand
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _context(command_id: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=command_id,
        session_id="session-1",
        actor_id="runtime-owner-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="runtime-authority-1",
        authority_generation=3,
        authority_fence=5,
        expected_session_version=4,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"idempotency-{command_id}",
        correlation_id=f"correlation-{command_id}",
    )


def _authority_payload(
    *, lease_id: str, member_id: str, operations: tuple[str, ...], workspace: int | None
) -> dict[str, object]:
    payload = {
        "lease_id": lease_id,
        "session_id": "session-1",
        "agent_member_id": member_id,
        "agent_id": "agent-1" if member_id == "member-1" else "runtime-owner-agent",
        "generation": 3,
        "fence": 5,
        "state": "active",
        "expires_at": "2026-08-19T01:00:00+00:00",
        "workspace_generation": workspace,
        "grants": [
            {
                "scope_id": "session-1",
                "operations": list(operations),
            }
        ],
    }
    payload["lease_digest"] = _digest(lease_id)
    return payload


def _store() -> InMemoryControlStore:
    workflow = _workflow_authority()
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="workflow_authority_binding",
                entity_id=workflow.authority_id,
                state_version=1,
                payload=workflow.to_dict(),
            ),
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=4,
                payload={"status": "active"},
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="member-1",
                state_version=1,
                payload={
                    "session_id": "session-1",
                    "agent_id": "agent-1",
                    "status": "working",
                    "process_epoch": 2,
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id="runtime-authority-1",
                state_version=1,
                payload=_authority_payload(
                    lease_id="runtime-authority-1",
                    member_id="runtime-owner-1",
                    operations=(
                        "runtime.lease.acquire",
                        "runtime.lease.heartbeat",
                        "runtime.lease.release",
                        "runtime.signal.enqueue",
                        "runtime.signal.claim",
                    ),
                    workspace=None,
                ),
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id="target-authority-1",
                state_version=1,
                payload=_authority_payload(
                    lease_id="target-authority-1",
                    member_id="member-1",
                    operations=("runtime.turn",),
                    workspace=7,
                ),
            ),
        )
    )


def _workflow_authority() -> WorkflowAuthorityBinding:
    registry_digest = _digest("workflow-registry")
    selected_refs = ("workflow.manual-resume",)
    return WorkflowAuthorityBinding(
        authority_id="workflow-authority-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="request-lineage-1",
        source_message_id="message-1",
        source_principal_id="user-1",
        authorized_actor_id="member-1",
        selected_workflow_refs=selected_refs,
        selection_digest=canonical_sha256_digest(
            {
                "schema_version": "workflow_selection_binding@1",
                "registry_snapshot_digest": registry_digest,
                "selected_workflow_refs": list(selected_refs),
            }
        ),
        registry_snapshot_digest=registry_digest,
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-19T00:00:00+00:00",
        updated_at="2026-08-19T00:00:00+00:00",
        task_id="task-1",
    )


def _service(
    store: InMemoryControlStore,
) -> tuple[RuntimeCoordinationKernelApplicationService, DeterministicClock]:
    clock = DeterministicClock(datetime(2026, 8, 19, 0, 0, tzinfo=UTC))
    return (
        RuntimeCoordinationKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=DeterministicIdGenerator(),
        ),
        clock,
    )


def _acquire(service: RuntimeCoordinationKernelApplicationService):  # noqa: ANN202
    service.mutate_session_lease(
        SessionRuntimeLeaseCommand(
            context=_context("command-acquire"),
            action=RuntimeLeaseAction.ACQUIRE,
            owner_id="runtime-owner-1",
            mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
            lease_seconds=300,
        )
    )


def _enqueue(service: RuntimeCoordinationKernelApplicationService):  # noqa: ANN202
    workflow = _workflow_authority()
    return service.enqueue_signal(
        RuntimeSignalEnqueueCommand(
            context=_context("command-enqueue"),
            signal_id="signal-1",
            agent_id="agent-1",
            agent_member_id="member-1",
            reason=AgentRuntimeSignalReason.MANUAL_RESUME,
            target_authority_lease_id="target-authority-1",
            workspace_generation=7,
            workflow_authority_id=workflow.authority_id,
            workflow_authority_epoch=workflow.epoch,
            workflow_authority_digest=workflow.binding_digest,
            workflow_authority_source_kind=(
                WorkflowAuthoritySignalSourceKind.CONTINUATION
            ),
            task_id="task-1",
            source_ref="manual-resume-1",
        )
    )


def _claim(
    service: RuntimeCoordinationKernelApplicationService,
    store: InMemoryControlStore,
    *,
    expected_version: int,
):
    lease = store.read(entity_type="session_runtime_lease", entity_id="session-1")
    assert lease is not None
    return service.claim_signal(
        RuntimeSignalClaimCommand(
            context=_context(f"command-claim-{expected_version}"),
            signal_id="signal-1",
            runtime_owner_id="runtime-owner-1",
            runtime_lease_token=str(lease.payload["lease_token"]),
            runtime_lease_generation=int(lease.payload["generation"]),
            runtime_fence=int(lease.payload["fencing_token"]),
            expected_signal_version=expected_version,
            claim_seconds=30,
        )
    )


def test_runtime_lease_signal_and_claim_are_atomic_canonical_facts() -> None:
    store = _store()
    service, _ = _service(store)

    _acquire(service)
    enqueue = _enqueue(service)
    claim = _claim(service, store, expected_version=1)

    lease = store.read(entity_type="session_runtime_lease", entity_id="session-1")
    signal = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert lease is not None and signal is not None
    assert lease.payload["generation"] == 1
    assert lease.payload["fencing_token"] == 1
    assert signal.payload["status"] == "claimed"
    assert signal.payload["session_lease_token"] == lease.payload["lease_token"]
    assert signal.payload["runtime_lease_generation"] == 1
    assert signal.payload["session_fencing_token"] == 1
    assert signal.payload["attempt_count"] == 1
    assert signal.payload["process_epoch"] == 2
    link = store.read(
        entity_type="runtime_signal_authority_link",
        entity_id="signal-1",
    )
    assert link is not None
    assert link.payload["authority_id"] == "workflow-authority-1"
    assert enqueue.mutation_applied is True
    assert claim.mutation_applied is True
    assert store.read(entity_type="task", entity_id="task-1") is None
    assert len(store.events) == len(store.outbox) == 3
    assert all(
        event.payload["task_transition_performed"] is False for event in store.events
    )


def test_duplicate_signal_enqueue_returns_the_same_current_authority_link() -> None:
    store = _store()
    service, _ = _service(store)

    first = _enqueue(service)
    duplicate = _enqueue(service)

    assert first.mutation_applied is True
    assert duplicate.mutation_applied is False
    assert duplicate.result["workflow_authority_id"] == "workflow-authority-1"
    assert duplicate.result["workflow_authority_epoch"] == 1
    links = tuple(
        record
        for record in store.records
        if record.entity_type == "runtime_signal_authority_link"
    )
    assert len(links) == 1


def test_expired_claim_can_be_reclaimed_only_under_same_live_runtime_lease() -> None:
    store = _store()
    service, clock = _service(store)
    _acquire(service)
    _enqueue(service)
    _claim(service, store, expected_version=1)
    first = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert first is not None
    first_token = first.payload["claim_token"]

    clock.advance(seconds=31)
    _claim(service, store, expected_version=2)

    reclaimed = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert reclaimed is not None
    assert reclaimed.payload["attempt_count"] == 2
    assert reclaimed.payload["claim_token"] != first_token
    assert reclaimed.payload["last_error"] == "previous claim expired before reclaim"


def test_stale_process_epoch_rejects_claim_without_mutation() -> None:
    store = _store()
    service, _ = _service(store)
    _acquire(service)
    _enqueue(service)
    before = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert before is not None

    context = _context("member-restart")
    unit = store.begin(
        UnitOfWorkRequest(
            unit_of_work_id="uow-member-restart",
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=_digest("member-restart"),
        )
    )
    member = unit.read(entity_type="agent_member", entity_id="member-1")
    assert member is not None
    restarted = dict(member.payload)
    restarted["process_epoch"] = 3
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-member-restart",
            kind=KernelMutationKind.REPLACE,
            entity_type="agent_member",
            entity_id="member-1",
            expected_state_version=member.state_version,
            payload=restarted,
        )
    )
    unit.commit()

    with pytest.raises(KernelContractError) as stale:
        _claim(service, store, expected_version=1)
    assert stale.value.code == "runtime_signal_process_epoch_stale"
    after = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert after is not None and after.record_digest == before.record_digest


def test_revoked_workflow_epoch_rejects_signal_claim_without_runtime_effect() -> None:
    store = _store()
    service, _ = _service(store)
    _acquire(service)
    _enqueue(service)
    current = store.read(
        entity_type="workflow_authority_binding",
        entity_id="workflow-authority-1",
    )
    assert current is not None
    binding = WorkflowAuthorityBinding.from_dict(current.payload)
    revoked = replace(
        binding,
        status=WorkflowAuthorityStatus.REVOKED,
        epoch=2,
        state_version=2,
        updated_at="2026-08-19T00:00:01+00:00",
        revoked_at="2026-08-19T00:00:01+00:00",
    )
    context = _context("revoke-workflow")
    unit = store.begin(
        UnitOfWorkRequest(
            unit_of_work_id="uow-revoke-workflow",
            command_id=context.command_id,
            session_id=context.session_id,
            actor_id=context.actor_id,
            authority_lease_id=context.authority_lease_id,
            authority_generation=context.authority_generation,
            authority_fence=context.authority_fence,
            expected_session_version=context.expected_session_version,
            idempotency_key=context.idempotency_key,
            command_digest=_digest("revoke-workflow"),
        )
    )
    unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-revoke-workflow",
            kind=KernelMutationKind.REPLACE,
            entity_type="workflow_authority_binding",
            entity_id=binding.authority_id,
            expected_state_version=current.state_version,
            payload=revoked.to_dict(),
        )
    )
    unit.commit()

    with pytest.raises(KernelContractError) as stale:
        _claim(service, store, expected_version=1)

    assert stale.value.code == "workflow_authority_stale"
    signal = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert signal is not None and signal.payload["status"] == "pending"


def test_expired_runtime_lease_rejects_claim_and_reacquire_advances_fence() -> None:
    store = _store()
    service, clock = _service(store)
    service.mutate_session_lease(
        SessionRuntimeLeaseCommand(
            context=_context("short-acquire"),
            action=RuntimeLeaseAction.ACQUIRE,
            owner_id="runtime-owner-1",
            mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
            lease_seconds=5,
        )
    )
    _enqueue(service)
    clock.advance(seconds=6)

    with pytest.raises(KernelContractError) as expired:
        _claim(service, store, expected_version=1)
    assert expired.value.code == "session_runtime_lease_expired"

    service.mutate_session_lease(
        SessionRuntimeLeaseCommand(
            context=_context("reacquire"),
            action=RuntimeLeaseAction.ACQUIRE,
            owner_id="runtime-owner-1",
            mode=SessionRuntimeLeaseMode.RECOVERY,
            lease_seconds=300,
        )
    )
    current = store.read(entity_type="session_runtime_lease", entity_id="session-1")
    assert current is not None
    assert current.payload["generation"] == 2
    assert current.payload["fencing_token"] == 2
    _claim(service, store, expected_version=1)


def test_heartbeat_and_release_require_exact_identity() -> None:
    store = _store()
    service, _ = _service(store)
    _acquire(service)
    lease = store.read(entity_type="session_runtime_lease", entity_id="session-1")
    assert lease is not None

    with pytest.raises(KernelContractError) as stale:
        service.mutate_session_lease(
            SessionRuntimeLeaseCommand(
                context=_context("bad-heartbeat"),
                action=RuntimeLeaseAction.HEARTBEAT,
                owner_id="runtime-owner-1",
                mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
                lease_seconds=300,
                expected_lease_token=str(lease.payload["lease_token"]),
                expected_generation=1,
                expected_fence=2,
            )
        )
    assert stale.value.code == "session_runtime_lease_stale"

    service.mutate_session_lease(
        SessionRuntimeLeaseCommand(
            context=_context("release"),
            action=RuntimeLeaseAction.RELEASE,
            owner_id="runtime-owner-1",
            mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
            lease_seconds=300,
            expected_lease_token=str(lease.payload["lease_token"]),
            expected_generation=1,
            expected_fence=1,
        )
    )
    released = store.read(entity_type="session_runtime_lease", entity_id="session-1")
    assert released is not None and released.payload["released_at"] is not None
