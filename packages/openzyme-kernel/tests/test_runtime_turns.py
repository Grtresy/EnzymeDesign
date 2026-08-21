from __future__ import annotations

from dataclasses import FrozenInstanceError
from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentRuntimeSignal
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import AgentRuntimeSignalStatus
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import SessionRuntimeLeaseMode
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolSpec
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_kernel import KernelContractError
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import RuntimeOutcomeConsumeDisposition
from openzyme_kernel import RuntimeOutcomeConsumeResult
from openzyme_kernel import RuntimeOutcomeConsumption
from openzyme_kernel import RuntimeTurnAdmission
from openzyme_kernel import RuntimeTurnBudget
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import validate_runtime_continuation_resume
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import RuntimeCapabilityGateway
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_runtime_spi import RuntimeUsage


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _release() -> LayeredReleaseIdentity:
    return LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )


def _binding() -> SessionCapabilityBindingRevision:
    return SessionCapabilityBindingRevision.create(
        binding_id="binding-1",
        session_id="session-1",
        revision=4,
        extension_bundle_digest=_digest("extensions"),
        route_catalog_digest=_digest("routes"),
        inventory_bindings=(),
        created_by_actor_id="operator-1",
        created_at="2026-08-19T00:00:00+00:00",
    )


def _snapshot(binding: SessionCapabilityBindingRevision) -> ToolAffordanceSnapshot:
    snapshot = ToolAffordanceSnapshot(
        snapshot_id="snapshot-1",
        session_id="session-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        declared_tool_catalog_digest=_digest("tools"),
        capability_binding_digest=binding.binding_digest,
        authority_lease_digest=_digest("authority"),
        workspace_generation=3,
        health_observation_digest=_digest("health"),
        subject_policy_digest=_digest("policy"),
        affordances=(),
        created_at="2026-08-19T00:00:01+00:00",
        snapshot_digest=_digest("placeholder"),
    )
    return replace(
        snapshot,
        snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
    )


def _signal() -> AgentRuntimeSignal:
    return AgentRuntimeSignal(
        signal_id="signal-1",
        session_id="session-1",
        agent_id="agent-1",
        reason=AgentRuntimeSignalReason.MANUAL_RESUME,
        status=AgentRuntimeSignalStatus.CLAIMED,
        created_at="2026-08-19T00:00:00+00:00",
        task_id="task-1",
        lane_id="lane-1",
        claimed_at="2026-08-19T00:00:02+00:00",
        claimed_by="runtime-owner-1",
        claim_expires_at="2026-08-19T00:05:00+00:00",
        attempt_count=2,
        session_lease_token="runtime-lease-1",
        session_fencing_token=7,
        capability_lease_id="authority-lease-1",
        workspace_generation=3,
    )


def _lease() -> SessionRuntimeLease:
    return SessionRuntimeLease(
        session_id="session-1",
        owner_id="runtime-owner-1",
        lease_token="runtime-lease-1",
        mode=SessionRuntimeLeaseMode.MANUAL_DRAIN,
        acquired_at="2026-08-19T00:00:00+00:00",
        heartbeat_at="2026-08-19T00:00:02+00:00",
        expires_at="2026-08-19T00:05:00+00:00",
        fencing_token=7,
    )


class FakeGateway(RuntimeCapabilityGateway):
    def list_tools(
        self,
        *,
        command_id: str,
        affordance_snapshot_digest: str,
    ) -> tuple[ToolSpec, ...]:
        return ()

    def invoke(
        self,
        *,
        command_id: str,
        request: RuntimeToolRequest,
    ) -> ToolResult:
        raise AssertionError("test Adapter does not invoke tools")


class FakeRuntimeAdapter(AgentRuntimeAdapter):
    adapter_id = "test.runtime.fake"
    adapter_contract_digest = _digest("runtime-adapter")

    def __init__(self, disposition: RuntimeTurnDisposition = RuntimeTurnDisposition.IDLE):
        self.disposition = disposition
        self.calls = 0

    def run_turn(
        self,
        command: RuntimeTurnCommand,
        capability_gateway: RuntimeCapabilityGateway,
    ) -> RuntimeTurnOutcome:
        self.calls += 1
        return _outcome(command, disposition=self.disposition)


class InMemoryOutcomeRepository:
    def __init__(self) -> None:
        self.by_command: dict[str, RuntimeOutcomeConsumption] = {}
        self.by_outcome: dict[str, RuntimeOutcomeConsumption] = {}

    def consume(
        self,
        consumption: RuntimeOutcomeConsumption,
    ) -> RuntimeOutcomeConsumeResult:
        existing = self.by_command.get(consumption.command_id)
        outcome_owner = self.by_outcome.get(consumption.outcome_id)
        if existing is not None:
            if (
                existing.command_digest != consumption.command_digest
                or existing.outcome_digest != consumption.outcome_digest
            ):
                raise KernelContractError(
                    "runtime_command_outcome_collision",
                    "command already consumed another outcome",
                )
            return RuntimeOutcomeConsumeResult(
                disposition=RuntimeOutcomeConsumeDisposition.DUPLICATE,
                command_digest=existing.command_digest,
                outcome_digest=existing.outcome_digest,
                consumption_digest=existing.consumption_digest,
            )
        if outcome_owner is not None:
            raise KernelContractError(
                "runtime_outcome_identity_collision",
                "outcome identity belongs to another command",
            )
        self.by_command[consumption.command_id] = consumption
        self.by_outcome[consumption.outcome_id] = consumption
        return RuntimeOutcomeConsumeResult(
            disposition=RuntimeOutcomeConsumeDisposition.ACCEPTED,
            command_digest=consumption.command_digest,
            outcome_digest=consumption.outcome_digest,
            consumption_digest=consumption.consumption_digest,
        )


def _admission(
    *,
    adapter: FakeRuntimeAdapter,
    signal: AgentRuntimeSignal | None = None,
    snapshot: ToolAffordanceSnapshot | None = None,
) -> RuntimeTurnAdmission:
    binding = _binding()
    return RuntimeTurnAdmission(
        command_id="command-1",
        turn_id="turn-1",
        agent_member_id="member-1",
        signal_claim_token="signal-claim-1",
        signal=signal or _signal(),
        session_lease=_lease(),
        runtime_lease_generation=5,
        process_epoch=3,
        distribution_id="openzyme.standard",
        distribution_manifest_digest=_digest("distribution"),
        release_identity=_release(),
        capability_binding=binding,
        affordance_snapshot=snapshot or _snapshot(binding),
        runtime_adapter_id=adapter.adapter_id,
        runtime_adapter_contract_digest=adapter.adapter_contract_digest,
        budget=RuntimeTurnBudget(
            max_steps=8,
            max_duration_seconds=120,
            max_input_units=16_000,
            max_output_units=4_000,
        ),
        messages=(
            RuntimeMessage(
                message_id="message-1",
                role=RuntimeMessageRole.USER,
                content="Inspect the current canonical facts.",
            ),
        ),
        observed_at="2026-08-19T00:00:03+00:00",
    )


def _outcome(
    command: RuntimeTurnCommand,
    *,
    disposition: RuntimeTurnDisposition = RuntimeTurnDisposition.IDLE,
    outcome_id: str = "outcome-1",
) -> RuntimeTurnOutcome:
    continuation_id = (
        "continuation-1"
        if disposition is RuntimeTurnDisposition.WAITING_CONTINUATION
        else None
    )
    return RuntimeTurnOutcome(
        outcome_id=outcome_id,
        command_id=command.command_id,
        command_digest=command.command_digest,
        turn_id=command.turn_id,
        session_id=command.session_id,
        agent_id=command.agent_id,
        agent_member_id=command.agent_member_id,
        signal_id=command.signal_id,
        signal_attempt=command.signal_attempt,
        runtime_lease_generation=command.runtime_lease_generation,
        runtime_fence=command.runtime_fence,
        process_epoch=command.process_epoch,
        disposition=disposition,
        summary="Bounded turn completed without a Task transition.",
        usage=RuntimeUsage(
            input_units=100,
            output_units=20,
            total_units=120,
            provider_reported=False,
        ),
        continuation_id=continuation_id,
    )


def test_coordinator_builds_one_immutable_exact_identity_command() -> None:
    adapter = FakeRuntimeAdapter()
    coordinator = RuntimeTurnCoordinator(adapter, InMemoryOutcomeRepository())

    command = coordinator.build_command(_admission(adapter=adapter))

    assert command.session_id == "session-1"
    assert command.agent_id == "agent-1"
    assert command.agent_member_id == "member-1"
    assert command.signal_attempt == 2
    assert command.runtime_lease_generation == 5
    assert command.runtime_fence == 7
    assert command.capability_binding_id == "binding-1"
    assert command.capability_binding_revision == 4
    assert command.affordance_snapshot_id == "snapshot-1"
    assert command.adapter_bundle_digest == _digest("adapters")
    with pytest.raises(FrozenInstanceError):
        command.process_epoch = 9  # type: ignore[misc]


def test_outcome_consumption_is_once_only_without_adapter_reexecution() -> None:
    adapter = FakeRuntimeAdapter()
    repository = InMemoryOutcomeRepository()
    coordinator = RuntimeTurnCoordinator(adapter, repository)
    command = coordinator.build_command(_admission(adapter=adapter))
    outcome = adapter.run_turn(command, FakeGateway())

    accepted = coordinator.consume_outcome(
        command,
        outcome,
        consumed_at="2026-08-19T00:00:04+00:00",
    )
    duplicate = coordinator.consume_outcome(
        command,
        outcome,
        consumed_at="2026-08-19T00:00:05+00:00",
    )

    assert accepted.disposition is RuntimeOutcomeConsumeDisposition.ACCEPTED
    assert duplicate.disposition is RuntimeOutcomeConsumeDisposition.DUPLICATE
    assert adapter.calls == 1
    assert len(repository.by_command) == 1


def test_cross_session_member_and_stale_claim_are_rejected_before_adapter() -> None:
    adapter = FakeRuntimeAdapter()
    coordinator = RuntimeTurnCoordinator(adapter, InMemoryOutcomeRepository())
    binding = _binding()
    wrong_member = replace(_snapshot(binding), agent_member_id="member-2")
    wrong_member = replace(
        wrong_member,
        snapshot_digest=canonical_sha256_digest(wrong_member.digest_payload()),
    )

    with pytest.raises(KernelContractError) as member_error:
        coordinator.build_command(_admission(adapter=adapter, snapshot=wrong_member))
    assert member_error.value.code == "runtime_turn_identity_drift"

    stale_signal = replace(_signal(), session_fencing_token=6)
    with pytest.raises(KernelContractError) as stale_error:
        coordinator.build_command(_admission(adapter=adapter, signal=stale_signal))
    assert stale_error.value.code == "runtime_signal_claim_stale"
    assert adapter.calls == 0


@pytest.mark.parametrize(
    ("field_name", "value"),
    (
        ("session_id", "session-2"),
        ("agent_member_id", "member-2"),
        ("process_epoch", 4),
    ),
)
def test_outcome_identity_drift_fails_before_consumption(
    field_name: str,
    value: str | int,
) -> None:
    adapter = FakeRuntimeAdapter()
    repository = InMemoryOutcomeRepository()
    coordinator = RuntimeTurnCoordinator(adapter, repository)
    command = coordinator.build_command(_admission(adapter=adapter))

    drifted = replace(_outcome(command), **{field_name: value})
    with pytest.raises(KernelContractError) as identity_error:
        coordinator.consume_outcome(
            command,
            drifted,
            consumed_at="2026-08-19T00:00:04+00:00",
        )
    assert identity_error.value.code == "runtime_outcome_identity_drift"
    assert repository.by_command == {}


def test_outcome_budget_drift_fails_before_consumption() -> None:
    adapter = FakeRuntimeAdapter()
    repository = InMemoryOutcomeRepository()
    coordinator = RuntimeTurnCoordinator(adapter, repository)
    command = coordinator.build_command(_admission(adapter=adapter))

    over_budget = replace(
        _outcome(command),
        usage=RuntimeUsage(
            input_units=16_001,
            output_units=20,
            total_units=16_021,
            provider_reported=True,
        ),
    )
    with pytest.raises(KernelContractError) as budget_error:
        coordinator.consume_outcome(
            command,
            over_budget,
            consumed_at="2026-08-19T00:00:04+00:00",
        )
    assert budget_error.value.code == "runtime_outcome_budget_exceeded"
    assert repository.by_command == {}


def test_continuation_and_runtime_settlement_are_separate_outbox_intents() -> None:
    adapter = FakeRuntimeAdapter(RuntimeTurnDisposition.WAITING_CONTINUATION)
    repository = InMemoryOutcomeRepository()
    coordinator = RuntimeTurnCoordinator(adapter, repository)

    outcome, result = coordinator.run_turn(
        _admission(adapter=adapter),
        FakeGateway(),
        consumed_at="2026-08-19T00:00:04+00:00",
    )

    assert result.disposition is RuntimeOutcomeConsumeDisposition.ACCEPTED
    record = repository.by_command["command-1"]
    assert record.continuation_intent is not None
    assert record.continuation_intent.continuation_id == outcome.continuation_id
    assert record.continuation_intent.release_digest == _release().release_digest
    assert record.continuation_intent.extension_bundle_digest == _digest("extensions")
    assert record.continuation_intent.declared_tool_catalog_digest == _digest("tools")
    assert record.continuation_intent.capability_binding_id == "binding-1"
    assert record.continuation_intent.capability_binding_revision == 4
    assert record.continuation_intent.capability_binding_digest == _binding().binding_digest
    assert record.continuation_intent.affordance_snapshot_id == "snapshot-1"
    assert record.continuation_intent.affordance_snapshot_digest == (
        _snapshot(_binding()).snapshot_digest
    )
    assert record.settlement_intent.disposition is (
        RuntimeTurnDisposition.WAITING_CONTINUATION
    )
    assert record.settlement_intent.task_transition_performed is False
    assert "task_status" not in record.settlement_intent.to_dict()


def test_continuation_resume_rejects_contract_drift_and_blocks_stale_dispatch() -> None:
    adapter = FakeRuntimeAdapter(RuntimeTurnDisposition.WAITING_CONTINUATION)
    repository = InMemoryOutcomeRepository()
    coordinator = RuntimeTurnCoordinator(adapter, repository)
    admission = _admission(adapter=adapter)
    command = coordinator.build_command(admission)
    coordinator.run_turn(
        admission,
        FakeGateway(),
        consumed_at="2026-08-19T00:00:04+00:00",
    )
    intent = repository.by_command["command-1"].continuation_intent
    assert intent is not None
    command = replace(command, continuation_id=intent.continuation_id)

    exact = validate_runtime_continuation_resume(intent, command)
    assert exact.conversation_resume_allowed is True
    assert exact.dispatch_allowed is True
    assert exact.blocker_code is None

    stale_binding = validate_runtime_continuation_resume(
        intent,
        replace(
            command,
            capability_binding_revision=command.capability_binding_revision + 1,
            capability_binding_digest=_digest("new-binding"),
        ),
    )
    assert stale_binding.conversation_resume_allowed is True
    assert stale_binding.dispatch_allowed is False
    assert stale_binding.blocker_code == "runtime_continuation_binding_stale"
    assert stale_binding.mutation_applied is False
    assert stale_binding.fallback_performed is False

    with pytest.raises(KernelContractError) as stale_contract:
        validate_runtime_continuation_resume(
            intent,
            replace(command, release_digest=_digest("other-release")),
        )
    assert stale_contract.value.code == "runtime_continuation_contract_stale"


def _control_store_for_command(
    command: RuntimeTurnCommand,
    *,
    member_epoch: int | None = None,
) -> InMemoryControlStore:
    signal_payload = _signal().to_dict()
    signal_payload.update(
        {
            "agent_member_id": command.agent_member_id,
            "claim_token": command.signal_claim_token,
        }
    )
    lease_payload = _lease().to_dict()
    lease_payload["generation"] = command.runtime_lease_generation
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id=command.session_id,
                state_version=4,
                payload={"status": "active"},
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_runtime_signal",
                entity_id=command.signal_id,
                state_version=2,
                payload=signal_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="session_runtime_lease",
                entity_id=command.session_id,
                state_version=1,
                payload=lease_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id=command.agent_member_id,
                state_version=1,
                payload={
                    "session_id": command.session_id,
                    "agent_id": command.agent_id,
                    "status": "working",
                    "process_epoch": member_epoch or command.process_epoch,
                },
            ),
        )
    )


def test_control_store_outcome_owner_registers_and_settles_without_task_mutation() -> None:
    adapter = FakeRuntimeAdapter(RuntimeTurnDisposition.WAITING_CONTINUATION)
    command = RuntimeTurnCoordinator(
        adapter, InMemoryOutcomeRepository()
    ).build_command(_admission(adapter=adapter))
    store = _control_store_for_command(command)
    repository = ControlStoreRuntimeOutcomeRepository(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 19, 0, 0, 3, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )
    coordinator = RuntimeTurnCoordinator(adapter, repository)

    assert repository.register_command(command) == command.command_digest
    outcome = _outcome(command, disposition=RuntimeTurnDisposition.WAITING_CONTINUATION)
    accepted = coordinator.consume_outcome(
        command, outcome, consumed_at="2026-08-19T00:00:04+00:00"
    )
    duplicate = coordinator.consume_outcome(
        command, outcome, consumed_at="2026-08-19T00:00:05+00:00"
    )

    assert accepted.disposition is RuntimeOutcomeConsumeDisposition.ACCEPTED
    assert duplicate.disposition is RuntimeOutcomeConsumeDisposition.DUPLICATE
    signal = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    assert signal.payload["status"] == "completed"
    assert store.read(
        entity_type="runtime_continuation_intent", entity_id="continuation-1"
    ) is not None
    assert store.read(entity_type="task", entity_id="task-1") is None


def test_control_store_runtime_command_rejects_late_process_epoch() -> None:
    adapter = FakeRuntimeAdapter()
    command = RuntimeTurnCoordinator(
        adapter, InMemoryOutcomeRepository()
    ).build_command(_admission(adapter=adapter))
    store = _control_store_for_command(
        command, member_epoch=command.process_epoch + 1
    )
    repository = ControlStoreRuntimeOutcomeRepository(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 19, 0, 0, 3, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )
    with pytest.raises(KernelContractError) as stale:
        repository.register_command(command)
    assert stale.value.code == "runtime_command_fence_stale"


def test_same_command_cannot_consume_a_different_outcome() -> None:
    adapter = FakeRuntimeAdapter()
    repository = InMemoryOutcomeRepository()
    coordinator = RuntimeTurnCoordinator(adapter, repository)
    command = coordinator.build_command(_admission(adapter=adapter))
    first = _outcome(command)
    second = _outcome(command, outcome_id="outcome-2")

    coordinator.consume_outcome(
        command,
        first,
        consumed_at="2026-08-19T00:00:04+00:00",
    )
    with pytest.raises(KernelContractError) as collision:
        coordinator.consume_outcome(
            command,
            second,
            consumed_at="2026-08-19T00:00:04+00:00",
        )
    assert collision.value.code == "runtime_command_outcome_collision"
