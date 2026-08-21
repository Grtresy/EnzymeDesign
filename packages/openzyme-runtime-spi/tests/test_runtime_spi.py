from __future__ import annotations

from dataclasses import FrozenInstanceError
from dataclasses import replace
from typing import Any

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ToolSpec
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import IsolatedProcessState
from openzyme_runtime_spi import ProcessIsolationReceipt
from openzyme_runtime_spi import ProcessIsolationRequest
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


def _message() -> RuntimeMessage:
    return RuntimeMessage(
        message_id="message-1",
        role=RuntimeMessageRole.USER,
        content="Inspect the current Task and decide the next bounded action.",
    )


def _command() -> RuntimeTurnCommand:
    return RuntimeTurnCommand(
        command_id="command-1",
        turn_id="turn-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        signal_id="signal-1",
        signal_attempt=1,
        signal_claim_token="signal-claim-1",
        runtime_lease_token="runtime-lease-1",
        runtime_lease_generation=2,
        runtime_fence=7,
        process_epoch=3,
        distribution_id="openzyme.standard",
        distribution_manifest_digest=_digest("distribution"),
        release_digest=_digest("release"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("extensions"),
        declared_tool_catalog_digest=_digest("catalog"),
        capability_binding_id="binding-1",
        capability_binding_revision=4,
        capability_binding_digest=_digest("binding"),
        affordance_snapshot_id="snapshot-1",
        affordance_snapshot_digest=_digest("affordance"),
        runtime_adapter_id="test.runtime.fake",
        runtime_adapter_contract_digest=_digest("fake-adapter"),
        max_steps=8,
        max_duration_seconds=120,
        max_input_units=16_000,
        max_output_units=4_000,
        messages=(_message(),),
        task_id="task-1",
        lane_id="lane-1",
    )


class _FakeGateway(RuntimeCapabilityGateway):
    def list_tools(
        self,
        *,
        command_id: str,
        affordance_snapshot_digest: str,
    ) -> tuple[ToolSpec, ...]:
        assert command_id == "command-1"
        assert affordance_snapshot_digest == _digest("affordance")
        return ()

    def invoke(
        self,
        *,
        command_id: str,
        request: RuntimeToolRequest,
    ) -> ToolResult:
        raise AssertionError("the deterministic no-tool adapter must not invoke tools")


class _FakeRuntimeAdapter(AgentRuntimeAdapter):
    adapter_id = "test.runtime.fake"
    adapter_contract_digest = _digest("fake-adapter")

    def run_turn(
        self,
        command: RuntimeTurnCommand,
        capability_gateway: RuntimeCapabilityGateway,
    ) -> RuntimeTurnOutcome:
        assert capability_gateway.list_tools(
            command_id=command.command_id,
            affordance_snapshot_digest=command.affordance_snapshot_digest,
        ) == ()
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
            disposition=RuntimeTurnDisposition.IDLE,
            summary="No capability invocation was required.",
            usage=RuntimeUsage(
                input_units=100,
                output_units=20,
                total_units=120,
                provider_reported=False,
            ),
        )


def test_runtime_spi_supports_a_deterministic_framework_free_adapter() -> None:
    command = _command()
    outcome = _FakeRuntimeAdapter().run_turn(command, _FakeGateway())

    assert outcome.command_digest == command.command_digest
    assert outcome.disposition is RuntimeTurnDisposition.IDLE
    assert outcome.to_dict()["usage"]["total_units"] == 120
    with pytest.raises(FrozenInstanceError):
        command.max_steps = 9  # type: ignore[misc]


def test_runtime_command_binds_exact_catalog_capability_and_fence_identity() -> None:
    command = _command()
    payload = command.to_dict()

    assert payload["command_digest"] == command.command_digest
    assert payload["runtime_fence"] == 7
    assert payload["capability_binding_id"] == "binding-1"
    assert payload["capability_binding_revision"] == 4
    assert payload["affordance_snapshot_id"] == "snapshot-1"
    assert payload["declared_tool_catalog_digest"] == _digest("catalog")
    assert payload["affordance_snapshot_digest"] == _digest("affordance")
    assert "provider_response" not in payload
    assert "process_handle" not in payload


def test_runtime_outcome_rejects_task_mutation_and_inconsistent_wait_state() -> None:
    command = _command()
    with pytest.raises(TypeError):
        RuntimeTurnOutcome(  # type: ignore[call-arg]
            outcome_id="outcome-1",
            command_id=command.command_id,
            command_digest=command.command_digest,
            turn_id=command.turn_id,
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=1,
            runtime_lease_generation=2,
            runtime_fence=7,
            process_epoch=3,
            disposition=RuntimeTurnDisposition.IDLE,
            summary="invalid",
            task_status="completed",
        )
    with pytest.raises(ValueError, match="approval wait"):
        RuntimeTurnOutcome(
            outcome_id="outcome-2",
            command_id=command.command_id,
            command_digest=command.command_digest,
            turn_id=command.turn_id,
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=1,
            runtime_lease_generation=2,
            runtime_fence=7,
            process_epoch=3,
            disposition=RuntimeTurnDisposition.WAITING_APPROVAL,
            summary="approval identity missing",
        )


def test_runtime_tool_request_keeps_provider_objects_out_of_the_contract() -> None:
    invocation = ToolInvocation(
        call_id="call-1",
        tool_name="workspace.fs.read",
        arguments={"path": "README.md"},
        session_id="session-1",
        agent_member_id="member-1",
        route_id="route-local",
        affordance_snapshot_digest=_digest("affordance"),
    )
    request = RuntimeToolRequest(
        request_id="request-1",
        invocation=invocation,
        affordance_snapshot_digest=_digest("affordance"),
    )

    assert request.to_dict()["invocation"]["route_id"] == "route-local"
    with pytest.raises(TypeError):
        RuntimeToolRequest(  # type: ignore[call-arg]
            request_id="request-2",
            invocation=invocation,
            affordance_snapshot_digest=_digest("affordance"),
            provider_response=object(),
        )


def _workspace() -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="member-1",
        generation=5,
        state_version=2,
        root_identity_digest=_digest("workspace-root"),
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
    )


def test_process_isolation_request_is_owner_generation_and_epoch_bound() -> None:
    request = ProcessIsolationRequest(
        request_id="process-request-1",
        command_id="command-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace=_workspace(),
        process_epoch=3,
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        argv=("python", "worker.py"),
        cwd_relative="runtime",
        environment={"PYTHONUNBUFFERED": "1"},
        image_identity="openzyme-runtime-image:v1",
        mount_manifest_digest=_digest("mounts"),
        timeout_seconds=120,
    )

    assert request.to_dict()["workspace"]["generation"] == 5
    assert request.to_dict()["request_digest"] == request.request_digest
    with pytest.raises(ValueError, match="another Session"):
        replace(request, session_id="session-2")


def test_process_receipt_exposes_opaque_identity_not_process_handle() -> None:
    request = ProcessIsolationRequest(
        request_id="process-request-1",
        command_id="command-1",
        session_id="session-1",
        agent_member_id="member-1",
        workspace=_workspace(),
        process_epoch=3,
        authority_lease_id="authority-lease-1",
        authority_generation=2,
        authority_fence=7,
        argv=("python", "worker.py"),
        cwd_relative="runtime",
        environment={},
        image_identity="openzyme-runtime-image:v1",
        mount_manifest_digest=_digest("mounts"),
        timeout_seconds=120,
    )
    receipt = ProcessIsolationReceipt(
        receipt_id="process-receipt-1",
        request_id=request.request_id,
        request_digest=request.request_digest,
        process_identity="process-opaque-1",
        process_epoch=3,
        workspace_generation=5,
        authority_generation=2,
        authority_fence=7,
        state=IsolatedProcessState.EXITED,
        exit_code=0,
        stdout_summary="ok",
        stderr_summary="",
        stdout_truncated=False,
        stderr_truncated=False,
        duration_ms=1_000,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        fallback_performed=False,
        started_at="2026-08-19T00:00:00Z",
        ended_at="2026-08-19T00:00:01Z",
    )

    payload: dict[str, Any] = receipt.to_dict()
    assert payload["process_identity"] == "process-opaque-1"
    assert "process_handle" not in payload
