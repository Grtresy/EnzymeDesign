from __future__ import annotations

from dataclasses import FrozenInstanceError
from dataclasses import replace
from typing import Any

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import RetryEligibility
from openzyme_contracts import RuntimeContextSection
from openzyme_contracts import RuntimeContextSectionKind
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import ToolSpec
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import validate_failure_diagnostic_pair
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
from openzyme_runtime_spi import RuntimeTurnOutcomeReceipt
from openzyme_runtime_spi import RuntimeUsage


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _message() -> RuntimeMessage:
    return RuntimeMessage(
        message_id="message-1",
        role=RuntimeMessageRole.USER,
        content="Inspect the current Task and decide the next bounded action.",
    )


def _context() -> RuntimeTurnContext:
    return RuntimeTurnContext(
        context_id="context-1",
        session_id="session-1",
        agent_id="agent-1",
        agent_member_id="member-1",
        turn_id="turn-1",
        signal_id="signal-1",
        request_lineage_id="lineage-1",
        task_id="task-1",
        lane_id="lane-1",
        sections=tuple(
            RuntimeContextSection(kind=kind, items=())
            for kind in RuntimeContextSectionKind
        ),
        max_bytes=32_768,
        created_at="2026-08-24T00:00:00+00:00",
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
        workflow_authority_id="workflow-authority-1",
        workflow_authority_epoch=1,
        workflow_authority_digest=_digest("workflow-authority"),
        signal_authority_link_digest=_digest("signal-authority-link"),
        tool_exposure_snapshot_id="exposure-1",
        tool_exposure_snapshot_digest=_digest("tool-exposure"),
        context=_context(),
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
        assert (
            capability_gateway.list_tools(
                command_id=command.command_id,
                affordance_snapshot_digest=command.affordance_snapshot_digest,
            )
            == ()
        )
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
            workflow_authority_id=command.workflow_authority_id,
            workflow_authority_epoch=command.workflow_authority_epoch,
            workflow_authority_digest=command.workflow_authority_digest,
            tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
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
            workflow_authority_id=command.workflow_authority_id,
            workflow_authority_epoch=command.workflow_authority_epoch,
            workflow_authority_digest=command.workflow_authority_digest,
            tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
            disposition=RuntimeTurnDisposition.WAITING_APPROVAL,
            summary="approval identity missing",
        )


def test_runtime_command_and_full_outcome_receipt_round_trip_closed() -> None:
    command = _command()
    assert RuntimeTurnCommand.from_dict(command.to_dict()) == command
    outcome = _FakeRuntimeAdapter().run_turn(command, _FakeGateway())
    assert RuntimeTurnOutcome.from_dict(outcome.to_dict()) == outcome
    receipt = RuntimeTurnOutcomeReceipt(
        receipt_id="receipt-1",
        outcome=outcome,
        accepted_at="2026-08-24T00:01:00+00:00",
    )
    assert RuntimeTurnOutcomeReceipt.from_dict(receipt.to_dict()) == receipt

    with pytest.raises(ValueError, match="closed schema"):
        RuntimeTurnOutcomeReceipt.from_dict(
            {**receipt.to_dict(), "provider_response": {"secret": True}}
        )


@pytest.mark.parametrize(
    ("case", "expected_message"),
    (
        ("legacy_schema", "invalid closed schema"),
        ("missing_context", "invalid closed schema"),
        ("context_identity_drift", "identity differs"),
    ),
)
def test_runtime_command_from_dict_fails_closed_for_noncurrent_context_contracts(
    case: str,
    expected_message: str,
) -> None:
    payload = _command().to_dict()
    if case == "legacy_schema":
        payload["schema_version"] = "runtime_turn_command@1"
    elif case == "missing_context":
        payload.pop("context")
    else:
        context = dict(payload["context"])
        context["session_id"] = "session-other"
        context.pop("byte_size")
        context.pop("context_digest")
        payload["context"] = context
        payload.pop("command_digest")

    with pytest.raises(ValueError, match=expected_message):
        RuntimeTurnCommand.from_dict(payload)


def test_failed_outcome_private_diagnostic_is_exact_and_ephemeral() -> None:
    command = _command()
    records = observe_structured_failure(
        RuntimeError("operator-only-provider-token=top-secret"),
        context=StructuredFailureContext(
            failure_id="failure-provider-1",
            diagnostic_id="diagnostic-provider-1",
            session_id=command.session_id,
            component="openzyme.runtime.llm",
            operation="run_turn",
            phase="provider_invoke",
            source_kind="agent_runtime_adapter",
            source_ref=command.command_id,
            source_version=command.command_digest,
            created_at="2026-08-24T00:00:01+00:00",
            task_id=command.task_id,
            lane_id=command.lane_id,
            agent_id=command.agent_id,
        ),
        failure_class=FailureClass.PROVIDER,
        recoverability=FailureRecoverability.TERMINAL,
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        retry_eligibility=RetryEligibility.TERMINAL,
        actor_kind=FailureActorKind.SYSTEM,
        error_code="provider_failed",
        safe_summary="The selected provider failed.",
        safe_hint="Inspect the private diagnostic.",
        next_action="inspect_diagnostic",
        mutation_applied=False,
        private_context={"credential": "operator-only-provider-token=top-secret"},
    )
    outcome = RuntimeTurnOutcome(
        outcome_id="outcome-failed-1",
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
        disposition=RuntimeTurnDisposition.FAILED,
        summary="The selected provider failed without fallback.",
        failure=records.public,
        task_id=command.task_id,
        lane_id=command.lane_id,
        private_diagnostic=records.private,
    )
    validate_failure_diagnostic_pair(outcome.failure, outcome.private_diagnostic)

    payload = outcome.to_dict()
    public_roundtrip = RuntimeTurnOutcome.from_dict(payload)
    receipt = RuntimeTurnOutcomeReceipt(
        receipt_id="receipt-failed-1",
        outcome=outcome,
        accepted_at="2026-08-24T00:01:00+00:00",
    )

    assert "private_diagnostic" not in payload
    assert "private_diagnostic_digest" not in payload["failure"]
    assert "top-secret" not in str(payload)
    assert records.private.record_digest not in str(receipt.to_dict())
    assert public_roundtrip.private_diagnostic is None
    assert public_roundtrip.failure is not None
    assert public_roundtrip.failure.private_diagnostic_digest is None
    assert public_roundtrip.outcome_digest == outcome.outcome_digest

    with pytest.raises(ValueError, match="only for failed outcome"):
        replace(
            outcome,
            disposition=RuntimeTurnDisposition.IDLE,
            failure=None,
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
