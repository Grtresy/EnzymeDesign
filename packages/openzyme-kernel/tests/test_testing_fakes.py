from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import ControlledEffectObservationRequest
from openzyme_contracts import ControlledOperationDispatchRequest
from openzyme_contracts import ControlledOperationProviderDispatchReceipt
from openzyme_contracts import ControlledOperationProviderObservationReceipt
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import RuntimeContextSection
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationKind
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_kernel import KernelContractError
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import ScriptedAgentRuntimeAdapter
from openzyme_kernel.testing import ScriptedControlledEffectAdapter
from openzyme_kernel.testing import ScriptedWorkspaceRuntimeAdapter
from openzyme_runtime_spi import RuntimeCapabilityGateway
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeToolRequest
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


class _NoToolGateway(RuntimeCapabilityGateway):
    def list_tools(self, *, command_id: str, affordance_snapshot_digest: str):  # noqa: ANN201
        del command_id, affordance_snapshot_digest
        return ()

    def invoke(self, *, command_id: str, request: RuntimeToolRequest):  # noqa: ANN201
        del command_id, request
        raise AssertionError("the scripted runtime must not invent tool calls")


def _runtime_command(adapter: ScriptedAgentRuntimeAdapter) -> RuntimeTurnCommand:
    context = RuntimeTurnContext(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="request-lineage-1",
        sections=tuple(
            RuntimeContextSection(kind=kind, items=())
            for kind in RuntimeContextSectionKind
        ),
        max_bytes=131_072,
        created_at="2026-08-20T00:00:00+00:00",
    )
    return RuntimeTurnCommand(
        command_id="command-1",
        turn_id="turn-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        signal_id="signal-1",
        signal_attempt=1,
        signal_claim_token="claim-1",
        runtime_lease_token="runtime-lease-1",
        runtime_lease_generation=1,
        runtime_fence=7,
        process_epoch=2,
        distribution_id="openzyme.standard",
        distribution_manifest_digest=_digest("distribution"),
        release_digest=_digest("release"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("tools"),
        capability_binding_id="binding-1",
        capability_binding_revision=1,
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_id="snapshot-1",
        affordance_snapshot_digest=_digest("affordance"),
        workflow_authority_id="workflow-authority-1",
        workflow_authority_epoch=1,
        workflow_authority_digest=_digest("workflow-authority"),
        signal_authority_link_digest=_digest("signal-authority-link"),
        tool_exposure_snapshot_id="exposure-1",
        tool_exposure_snapshot_digest=_digest("tool-exposure"),
        context=context,
        runtime_adapter_id=adapter.adapter_id,
        runtime_adapter_contract_digest=adapter.adapter_contract_digest,
        max_steps=4,
        max_duration_seconds=60,
        max_input_units=4_000,
        max_output_units=1_000,
        messages=(
            RuntimeMessage(
                message_id="message-1",
                role=RuntimeMessageRole.USER,
                content="Take one bounded turn.",
            ),
        ),
    )


def _runtime_outcome(command: RuntimeTurnCommand) -> RuntimeTurnOutcome:
    return RuntimeTurnOutcome(
        outcome_id="outcome-1",
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
        workflow_authority_id=command.workflow_authority_id,
        workflow_authority_epoch=command.workflow_authority_epoch,
        workflow_authority_digest=command.workflow_authority_digest,
        tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
        tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
        disposition=RuntimeTurnDisposition.IDLE,
        summary="No tool invocation was needed.",
    )


def _workspace_binding() -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=3,
        state_version=5,
        root_identity_digest=_digest("root"),
        provider_id="openzyme.testing.workspace",
        target_id="local-host",
    )


def _exec_request() -> WorkspaceExecRequest:
    return WorkspaceExecRequest(
        operation_id="operation-1",
        binding=_workspace_binding(),
        argv=("python", "script.py"),
        cwd="analysis",
        timeout_seconds=30,
        max_output_bytes=1_024,
        idempotency_key="exec-1",
        authority_lease_id="lease-1",
        authority_generation=2,
        authority_fence=9,
        process_epoch=4,
    )


def test_scripted_runtime_is_exact_and_missing_scripts_fail_closed() -> None:
    adapter = ScriptedAgentRuntimeAdapter()
    command = _runtime_command(adapter)
    outcome = _runtime_outcome(command)

    with pytest.raises(KernelContractError) as missing:
        adapter.run_turn(command, _NoToolGateway())
    assert missing.value.code == "fake_runtime_outcome_missing"

    adapter.script(command=command, outcome=outcome)
    assert adapter.run_turn(command, _NoToolGateway()) is outcome
    assert adapter.commands == [command]


def test_scripted_workspace_reconcile_never_redispatches() -> None:
    adapter = ScriptedWorkspaceRuntimeAdapter()
    request = _exec_request()
    doubtful = WorkspaceOperationReceipt.create(
        operation_id=request.operation_id,
        workspace_id=request.binding.workspace_id,
        generation=request.binding.generation,
        state_version=request.binding.state_version,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        mutation_applied=None,
    )
    settled = WorkspaceOperationReceipt.create(
        operation_id=request.operation_id,
        workspace_id=request.binding.workspace_id,
        generation=request.binding.generation,
        state_version=request.binding.state_version,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        mutation_applied=True,
        result_payload=b'{"exit_code":0}',
    )
    adapter.script_dispatch(request, doubtful)
    adapter.script_reconcile(request, settled)

    assert adapter.execute(request) is doubtful
    assert adapter.reconcile(request) is settled
    assert adapter.dispatch_requests == [request]
    assert adapter.reconcile_requests == [request]

    observe_request = WorkspaceObservationRequest(
        binding=request.binding,
        operation=WorkspaceObservationKind.STATUS,
    )
    observation = WorkspaceObservation(
        workspace_id=request.binding.workspace_id,
        generation=request.binding.generation,
        state_version=request.binding.state_version,
        operation=WorkspaceObservationKind.STATUS,
        result_digest=_digest("status"),
        bounded_payload=b"{}",
    )
    adapter.script_observation(observe_request, observation)
    assert adapter.observe(observe_request) is observation


def test_scripted_controlled_effect_observe_does_not_repeat_dispatch() -> None:
    adapter = ScriptedControlledEffectAdapter()
    dispatch = ControlledOperationDispatchRequest(
        request_id="request-1",
        execution_id="execution-1",
        operation_id="operation-1",
        session_id="session-1",
        request_digest=_digest("request"),
        request_envelope={"kind": "fake"},
        request_size_bytes=16,
        created_at="2026-08-20T00:00:00+00:00",
    )
    dispatch_receipt = ControlledOperationProviderDispatchReceipt(
        receipt_id="receipt-1",
        execution_id=dispatch.execution_id,
        operation_id=dispatch.operation_id,
        session_id=dispatch.session_id,
        dispatch_generation=1,
        provider_request_id="provider-request-1",
        provider_id=adapter.provider_id,
        external_handle_ref="opaque-handle-1",
        receipt_digest=_digest("dispatch-receipt"),
        receipt_envelope={"accepted": True},
        receipt_size_bytes=16,
        created_at="2026-08-20T00:00:01+00:00",
    )
    observe = ControlledEffectObservationRequest(
        observation_id="observation-1",
        execution_id=dispatch.execution_id,
        operation_id=dispatch.operation_id,
        route_id="route-1",
        dispatch_generation=1,
        provider_request_identity="provider-request-1",
        authority_fence=9,
    )
    observation_receipt = ControlledOperationProviderObservationReceipt(
        observation_id="provider-observation-1",
        dispatch_receipt_id=dispatch_receipt.receipt_id,
        execution_id=dispatch.execution_id,
        operation_id=dispatch.operation_id,
        session_id=dispatch.session_id,
        dispatch_generation=1,
        observation_index=1,
        provider_request_id="provider-request-1",
        provider_id=adapter.provider_id,
        external_handle_ref="opaque-handle-1",
        observation_digest=_digest("observation-receipt"),
        observation_envelope={"terminal": True},
        observation_size_bytes=16,
        created_at="2026-08-20T00:00:02+00:00",
    )
    adapter.script_dispatch(request=dispatch, receipt=dispatch_receipt)
    adapter.script_observation(request=observe, receipt=observation_receipt)

    assert adapter.dispatch(dispatch) is dispatch_receipt
    assert adapter.observe(observe) is observation_receipt
    assert len(adapter.dispatch_requests) == 1
    assert len(adapter.observation_requests) == 1


def test_deterministic_clock_is_explicitly_advanced() -> None:
    clock = DeterministicClock(datetime(2026, 8, 20, tzinfo=UTC))
    before = clock.now_iso()
    assert clock.now_iso() == before
    clock.advance(seconds=5)
    assert clock.now_iso() == "2026-08-20T00:00:05+00:00"
