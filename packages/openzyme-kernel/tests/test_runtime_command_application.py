from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import RuntimeCommandStatus
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel.errors import KernelContractError
from openzyme_kernel.runtime_command_application import RuntimeCommandAdmissionCommand
from openzyme_kernel.runtime_command_application import RuntimeCommandClaimCommand
from openzyme_kernel.runtime_command_application import (
    RuntimeCommandKernelApplicationService,
)
from openzyme_kernel.runtime_command_application import RuntimeCommandSettlementCommand
from openzyme_kernel.runtime_command_application import _record
from openzyme_kernel.runtime_command_application import observe_runtime_command_failure
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


_DIGEST = "sha256:" + "1" * 64


def _context(
    *,
    command_id: str,
    idempotency_key: str,
    expected_session_version: int = 1,
) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=command_id,
        session_id="session-1",
        actor_id="operator-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="authority-1",
        authority_generation=1,
        authority_fence=1,
        expected_session_version=expected_session_version,
        extension_bundle_digest=_DIGEST,
        capability_binding_digest=_DIGEST,
        idempotency_key=idempotency_key,
        correlation_id="correlation-1",
    )


def _runtime() -> tuple[
    RuntimeCommandKernelApplicationService,
    InMemoryControlStore,
    DeterministicClock,
]:
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=1,
                payload={"session_id": "session-1"},
            ),
        )
    )
    clock = DeterministicClock(datetime(2026, 8, 24, tzinfo=UTC))
    return (
        RuntimeCommandKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=DeterministicIdGenerator(),
        ),
        store,
        clock,
    )


def test_runtime_drain_admission_is_durable_and_executes_nothing() -> None:
    application, store, _ = _runtime()
    command = RuntimeCommandAdmissionCommand(
        context=_context(command_id="admit-1", idempotency_key="drain-1"),
        max_signals=4,
        max_steps_per_agent=2,
    )

    receipt = application.admit(command)
    duplicate = application.admit(
        RuntimeCommandAdmissionCommand(
            context=_context(command_id="admit-2", idempotency_key="drain-1"),
            max_signals=4,
            max_steps_per_agent=2,
        )
    )

    assert receipt.mutation_applied is True
    assert duplicate.mutation_applied is False
    assert duplicate.result == receipt.result
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False
    assert receipt.result["fallback_performed"] is False
    assert receipt.result["runtime_command_status"] == "accepted"
    assert (
        store.read(
            entity_type="runtime_command",
            entity_id=str(receipt.result["runtime_command_id"]),
        )
        is not None
    )

    with pytest.raises(KernelContractError) as collision:
        application.admit(
            RuntimeCommandAdmissionCommand(
                context=_context(command_id="admit-3", idempotency_key="drain-1"),
                max_signals=5,
                max_steps_per_agent=2,
            )
        )
    assert collision.value.code == "runtime_command_idempotency_collision"


def test_runtime_command_claim_is_fenced_and_expiry_allows_one_reclaim() -> None:
    application, store, clock = _runtime()
    admitted = application.admit(
        RuntimeCommandAdmissionCommand(
            context=_context(command_id="admit-1", idempotency_key="drain-1"),
            max_signals=1,
            max_steps_per_agent=1,
        )
    )
    identity = str(admitted.result["runtime_command_id"])
    claimed = application.claim(
        RuntimeCommandClaimCommand(
            context=_context(command_id="claim-1", idempotency_key="claim-1"),
            runtime_command_id=identity,
            claim_owner="worker-1",
            expected_state_version=1,
            claim_seconds=30,
        )
    )
    assert claimed.result["fencing_token"] == 1

    with pytest.raises(KernelContractError) as busy:
        application.claim(
            RuntimeCommandClaimCommand(
                context=_context(command_id="claim-2", idempotency_key="claim-2"),
                runtime_command_id=identity,
                claim_owner="worker-2",
                expected_state_version=2,
                claim_seconds=30,
            )
        )
    assert busy.value.code == "runtime_command_claim_busy"

    clock.advance(seconds=31)
    reclaimed = application.claim(
        RuntimeCommandClaimCommand(
            context=_context(command_id="claim-3", idempotency_key="claim-3"),
            runtime_command_id=identity,
            claim_owner="worker-2",
            expected_state_version=2,
            claim_seconds=30,
        )
    )
    assert reclaimed.result["fencing_token"] == 2
    record = store.read(entity_type="runtime_command", entity_id=identity)
    assert record is not None and record.state_version == 3


def test_runtime_command_settlement_rejects_stale_fence_and_is_idempotent() -> None:
    application, store, clock = _runtime()
    admitted = application.admit(
        RuntimeCommandAdmissionCommand(
            context=_context(command_id="admit-1", idempotency_key="drain-1"),
            max_signals=1,
            max_steps_per_agent=1,
        )
    )
    identity = str(admitted.result["runtime_command_id"])
    claimed = application.claim(
        RuntimeCommandClaimCommand(
            context=_context(command_id="claim-1", idempotency_key="claim-1"),
            runtime_command_id=identity,
            claim_owner="worker-1",
            expected_state_version=1,
            claim_seconds=30,
        )
    )
    lease_token = str(claimed.result["lease_token"])
    claimed_snapshot = store.read(entity_type="runtime_command", entity_id=identity)
    assert claimed_snapshot is not None
    claimed_record = _record(claimed_snapshot)
    private_error = RuntimeError("private stale settlement detail")
    failure_records = observe_runtime_command_failure(
        private_error,
        record=claimed_record,
        component="openzyme.standard.runtime_worker",
        phase="runtime_context_projection",
        created_at=clock.now_iso(),
        error_code="runtime_context_identity_stale",
        safe_summary="Runtime context identity changed before provider invocation",
        safe_hint="Inspect the canonical diagnostic; no fallback occurred",
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        correlation_id=identity,
    )

    with pytest.raises(KernelContractError) as stale:
        application.settle(
            RuntimeCommandSettlementCommand(
                context=_context(command_id="settle-0", idempotency_key="settle-0"),
                runtime_command_id=identity,
                claim_owner="worker-1",
                lease_token=lease_token,
                fencing_token=2,
                expected_state_version=2,
                status=RuntimeCommandStatus.FAILED,
                bounded_outcome_summary={
                    "processed_signals": 0,
                    "turns": [],
                    "runtime_executed": False,
                    "task_transition_performed": False,
                    "fallback_performed": False,
                },
                error_code="runtime_context_identity_stale",
                safe_error_summary=(
                    "Runtime context identity changed before provider invocation"
                ),
                safe_retry_hint=(
                    "Inspect the canonical diagnostic; no fallback occurred"
                ),
                failure_records=failure_records,
            )
        )
    assert stale.value.code == "runtime_command_fence_stale"
    assert (
        store.read(
            entity_type="failure_observation",
            entity_id=failure_records.public.failure_id,
        )
        is None
    )
    assert (
        store.read(
            entity_type="private_diagnostic",
            entity_id=failure_records.private.diagnostic_id,
        )
        is None
    )

    command = RuntimeCommandSettlementCommand(
        context=_context(command_id="settle-1", idempotency_key="settle-1"),
        runtime_command_id=identity,
        claim_owner="worker-1",
        lease_token=lease_token,
        fencing_token=1,
        expected_state_version=2,
        status=RuntimeCommandStatus.COMPLETED,
        bounded_outcome_summary={
            "runtime_executed": True,
            "processed_signals": 1,
            "task_transition_performed": False,
        },
    )
    receipt = application.settle(command)
    duplicate = application.settle(command)

    assert receipt.result["runtime_command_status"] == "completed"
    assert receipt.result["runtime_executed"] is True
    assert receipt.result["task_transition_performed"] is False
    assert receipt.result["fallback_performed"] is False
    assert duplicate.mutation_applied is False
    assert duplicate.result == receipt.result


def test_failed_runtime_command_atomically_persists_public_private_diagnostic_pair() -> (
    None
):
    application, store, clock = _runtime()
    admitted = application.admit(
        RuntimeCommandAdmissionCommand(
            context=_context(
                command_id="admit-failure", idempotency_key="drain-failure"
            ),
            max_signals=1,
            max_steps_per_agent=1,
        )
    )
    identity = str(admitted.result["runtime_command_id"])
    claimed = application.claim(
        RuntimeCommandClaimCommand(
            context=_context(
                command_id="claim-failure", idempotency_key="claim-failure"
            ),
            runtime_command_id=identity,
            claim_owner="worker-1",
            expected_state_version=1,
            claim_seconds=30,
        )
    )
    claimed_snapshot = store.read(entity_type="runtime_command", entity_id=identity)
    assert claimed_snapshot is not None
    claimed_record = _record(claimed_snapshot)
    private_error = RuntimeError("private token=/tmp/operator-only")
    records = observe_runtime_command_failure(
        private_error,
        record=claimed_record,
        component="openzyme.standard.runtime_worker",
        phase="runtime_context_projection",
        created_at=clock.now_iso(),
        error_code="runtime_context_projection_failed",
        safe_summary="Runtime context projection failed before provider invocation",
        safe_hint="Inspect the exact diagnostic; no provider or fallback ran",
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        correlation_id=identity,
    )
    command = RuntimeCommandSettlementCommand(
        context=_context(command_id="settle-failure", idempotency_key="settle-failure"),
        runtime_command_id=identity,
        claim_owner="worker-1",
        lease_token=str(claimed.result["lease_token"]),
        fencing_token=1,
        expected_state_version=2,
        status=RuntimeCommandStatus.FAILED,
        bounded_outcome_summary={
            "processed_signals": 0,
            "turns": [],
            "runtime_executed": False,
            "task_transition_performed": False,
            "fallback_performed": False,
        },
        error_code=records.public.error_code,
        safe_error_summary=records.public.safe_summary,
        safe_retry_hint=records.public.safe_hint,
        failure_records=records,
    )

    receipt = application.settle(command)
    duplicate = application.settle(command)

    terminal = store.read(entity_type="runtime_command", entity_id=identity)
    public_failure = store.read(
        entity_type="failure_observation",
        entity_id=records.public.failure_id,
    )
    private_diagnostic = store.read(
        entity_type="private_diagnostic",
        entity_id=records.private.diagnostic_id,
    )
    assert terminal is not None and terminal.payload["status"] == "failed"
    assert terminal.payload["failure_id"] == records.public.failure_id
    assert terminal.payload["diagnostic_id"] == records.private.diagnostic_id
    assert public_failure is not None
    assert public_failure.payload["private_diagnostic_digest"] == (
        records.private.record_digest
    )
    assert private_diagnostic is not None
    assert "operator-only" in str(private_diagnostic.payload["exception_message"])
    assert "operator-only" not in str(records.public.to_dict())
    assert receipt.result["failure_id"] == records.public.failure_id
    assert receipt.result["diagnostic_id"] == records.private.diagnostic_id
    assert duplicate.mutation_applied is False
    assert len(store.events) == 3
    assert len(store.outbox) == 3


def test_failure_identity_collision_rolls_back_command_and_private_sidecar() -> None:
    application, store, clock = _runtime()
    admitted = application.admit(
        RuntimeCommandAdmissionCommand(
            context=_context(
                command_id="admit-collision", idempotency_key="drain-collision"
            ),
            max_signals=1,
            max_steps_per_agent=1,
        )
    )
    identity = str(admitted.result["runtime_command_id"])
    claimed = application.claim(
        RuntimeCommandClaimCommand(
            context=_context(
                command_id="claim-collision", idempotency_key="claim-collision"
            ),
            runtime_command_id=identity,
            claim_owner="worker-1",
            expected_state_version=1,
            claim_seconds=30,
        )
    )
    claimed_snapshot = store.read(entity_type="runtime_command", entity_id=identity)
    assert claimed_snapshot is not None
    records = observe_runtime_command_failure(
        RuntimeError("private collision detail"),
        record=_record(claimed_snapshot),
        component="openzyme.standard.runtime_worker",
        phase="runtime_context_projection",
        created_at=clock.now_iso(),
        error_code="runtime_context_projection_failed",
        safe_summary="Runtime context projection failed before provider invocation",
        safe_hint="Inspect the exact diagnostic; no provider or fallback ran",
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        correlation_id=identity,
    )
    collision_unit = store.begin(
        UnitOfWorkRequest(
            unit_of_work_id="uow-seed-collision",
            command_id="command-seed-collision",
            session_id="session-1",
            actor_id="operator-1",
            authority_lease_id="authority-1",
            authority_generation=1,
            authority_fence=1,
            expected_session_version=1,
            idempotency_key="seed-collision",
            command_digest=canonical_sha256_digest({"seed": "collision"}),
        )
    )
    collision_unit.stage(
        KernelStateMutation.create(
            mutation_id="mutation-seed-collision",
            kind=KernelMutationKind.CREATE,
            entity_type="failure_observation",
            entity_id=records.public.failure_id,
            expected_state_version=None,
            payload=records.public.to_internal_dict(),
        )
    )
    collision_unit.commit()
    commits_before = store.commit_count

    with pytest.raises(KernelContractError) as collision:
        application.settle(
            RuntimeCommandSettlementCommand(
                context=_context(
                    command_id="settle-collision",
                    idempotency_key="settle-collision",
                ),
                runtime_command_id=identity,
                claim_owner="worker-1",
                lease_token=str(claimed.result["lease_token"]),
                fencing_token=1,
                expected_state_version=2,
                status=RuntimeCommandStatus.FAILED,
                bounded_outcome_summary={
                    "processed_signals": 0,
                    "turns": [],
                    "runtime_executed": False,
                    "task_transition_performed": False,
                    "fallback_performed": False,
                },
                error_code=records.public.error_code,
                safe_error_summary=records.public.safe_summary,
                safe_retry_hint=records.public.safe_hint,
                failure_records=records,
            )
        )

    assert collision.value.code == "runtime_command_failure_identity_collision"
    current = store.read(entity_type="runtime_command", entity_id=identity)
    assert current is not None and current.payload["status"] == "claimed"
    assert (
        store.read(
            entity_type="private_diagnostic",
            entity_id=records.private.diagnostic_id,
        )
        is None
    )
    assert store.commit_count == commits_before
