from __future__ import annotations

from dataclasses import dataclass

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceFilesystemMutationKind
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationKind
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceTransferDirection
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AuthorityCheckRequest
from openzyme_extension_spi import AuthorityDecision
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_kernel import KernelContractError
from openzyme_kernel import WorkspaceOperationCoordinationError
from openzyme_kernel import WorkspaceOperationCoordinator
from openzyme_kernel import WorkspaceOperationSettlementState


def _digest(seed: str) -> str:
    return canonical_sha256_digest({"seed": seed})


def _binding(
    *,
    kind: WorkspaceKind = WorkspaceKind.AGENT_LOCAL,
    provider_id: str = "workspace.local",
) -> WorkspaceRuntimeBinding:
    return WorkspaceRuntimeBinding(
        workspace_id="workspace-1",
        workspace_kind=kind,
        session_id="session-1",
        owner_member_id="member-1",
        generation=3,
        state_version=7,
        root_identity_digest=_digest("root"),
        provider_id=provider_id,
        target_id="local-host" if kind is WorkspaceKind.AGENT_LOCAL else "hpc-primary",
        target_qualification_digest=(
            None if kind is WorkspaceKind.AGENT_LOCAL else _digest("qualification")
        ),
    )


def _context(
    *,
    generation: int = 3,
    route_id: str | None = "route-workspace-local",
) -> KernelCommandContext:
    return KernelCommandContext(
        command_id="command-1",
        session_id="session-1",
        actor_id="member-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=11,
        expected_session_version=5,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="mutation-1",
        correlation_id="correlation-1",
        workspace_generation=generation,
        route_id=route_id,
    )


@dataclass
class FakeAuthorityService:
    allowed: bool = True

    def __post_init__(self) -> None:
        self.requests: list[AuthorityCheckRequest] = []

    def authorize(self, request: AuthorityCheckRequest) -> AuthorityDecision:
        self.requests.append(request)
        return AuthorityDecision(
            allowed=self.allowed,
            operation=request.operation,
            scope_id=request.scope_id,
            authority_lease_id=request.context.authority_lease_id,
            generation=request.expected_generation,
            fence=request.expected_fence,
            denial_code=None if self.allowed else "workspace_authority_denied",
        )


class FakeControlledOperationService:
    def __init__(self) -> None:
        self.commands: list[ControlledOperationApplicationCommand] = []

    def execute(
        self,
        command: ControlledOperationApplicationCommand,
    ) -> KernelMutationReceipt:
        self.commands.append(command)
        certainty = (
            ExternalEffectCertainty.NO_EFFECT
            if command.operation is ControlledOperationCommandKind.ADMIT
            else ExternalEffectCertainty(str(command.payload["effect_certainty"]))
        )
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id="controlled_operation",
            operation=command.operation.value,
            mutation_applied=True,
            effect_certainty=certainty,
        )


class FakeObservationPort:
    def __init__(self) -> None:
        self.calls = 0

    def observe(self, request: WorkspaceObservationRequest) -> WorkspaceObservation:
        self.calls += 1
        return WorkspaceObservation(
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            operation=request.operation,
            result_digest=_digest("observation"),
            bounded_payload=b"ready",
        )


class FakeFilesystemPort:
    def __init__(
        self,
        *,
        certainty: ExternalEffectCertainty = ExternalEffectCertainty.TERMINAL_KNOWN,
    ) -> None:
        self.certainty = certainty
        self.calls = 0
        self.reconcile_calls = 0

    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        self.calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=self.certainty,
            mutation_applied=(
                None
                if self.certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else True
            ),
        )

    def reconcile(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        self.reconcile_calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=self.certainty,
            mutation_applied=(
                None
                if self.certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else True
            ),
        )


class FakeTransferPort:
    def __init__(self) -> None:
        self.calls = 0
        self.reconcile_calls = 0

    def transfer(
        self,
        request: WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        self.calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=b'{"publication_performed":false}',
        )

    def reconcile(
        self,
        request: WorkspaceTransferRequest,
    ) -> WorkspaceOperationReceipt:
        self.reconcile_calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=b'{"publication_performed":false}',
        )


class FakeProcessPort:
    def __init__(self) -> None:
        self.calls = 0
        self.reconcile_calls = 0

    def execute(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt:
        self.calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=b'{"returncode":0}',
        )

    def reconcile(self, request: WorkspaceExecRequest) -> WorkspaceOperationReceipt:
        self.reconcile_calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=b'{"returncode":0}',
        )


class RefusingFilesystemPort:
    def __init__(self, error_code: str) -> None:
        self.error_code = error_code
        self.calls = 0

    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        self.calls += 1
        raise WorkspacePortError(
            self.error_code,
            "Adapter rejected the workspace path before mutation",
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            mutation_applied=False,
            diagnostic_id="diagnostic-1",
        )


class LostResponseFilesystemPort:
    def __init__(self) -> None:
        self.calls = 0
        self.reconcile_calls = 0

    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        self.calls += 1
        raise WorkspacePortError(
            "workspace_response_lost",
            "request may have reached the exact Adapter",
            effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            mutation_applied=None,
            diagnostic_id="diagnostic-1",
        )

    def reconcile(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        self.reconcile_calls += 1
        return WorkspaceOperationReceipt.create(
            operation_id=request.operation_id,
            workspace_id=request.binding.workspace_id,
            generation=request.binding.generation,
            state_version=request.binding.state_version,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            result_payload=b'{"reconciled":true}',
        )


class ExplodingFilesystemPort:
    def __init__(self) -> None:
        self.calls = 0

    def mutate(
        self,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationReceipt:
        self.calls += 1
        raise RuntimeError("private adapter traceback")


def _mutation(binding: WorkspaceRuntimeBinding | None = None) -> WorkspaceFilesystemMutation:
    return WorkspaceFilesystemMutation(
        operation_id="operation-1",
        binding=binding or _binding(),
        operation=WorkspaceFilesystemMutationKind.WRITE,
        path="results/output.txt",
        content=b"result",
        idempotency_key="mutation-1",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=11,
    )


def _transfer(binding: WorkspaceRuntimeBinding | None = None) -> WorkspaceTransferRequest:
    return WorkspaceTransferRequest(
        operation_id="operation-transfer-1",
        binding=binding or _binding(),
        direction=WorkspaceTransferDirection.SYNC_REVISION,
        path="imports/revision-1",
        transfer_ref="transfer:revision-1",
        transfer_manifest_digest=_digest("transfer-manifest"),
        max_bytes=1_048_576,
        timeout_seconds=120,
        idempotency_key="mutation-1",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=11,
    )


def _process(binding: WorkspaceRuntimeBinding | None = None) -> WorkspaceExecRequest:
    return WorkspaceExecRequest(
        operation_id="operation-process-1",
        binding=binding or _binding(),
        argv=("python", "script.py"),
        cwd="analysis",
        timeout_seconds=60,
        max_output_bytes=4_096,
        idempotency_key="mutation-1",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=11,
        process_epoch=9,
    )


def _coordinator(
    *,
    authority: FakeAuthorityService | None = None,
    controlled: FakeControlledOperationService | None = None,
    observation_port: FakeObservationPort | None = None,
    filesystem_port: object | None = None,
    process_port: object | None = None,
    transfer_port: object | None = None,
    provider_id: str = "workspace.local",
) -> tuple[
    WorkspaceOperationCoordinator,
    FakeAuthorityService,
    FakeControlledOperationService,
]:
    resolved_authority = authority or FakeAuthorityService()
    resolved_controlled = controlled or FakeControlledOperationService()
    return (
        WorkspaceOperationCoordinator(
            authority=resolved_authority,
            controlled_operations=resolved_controlled,
            observation_ports=(
                {} if observation_port is None else {provider_id: observation_port}
            ),
            filesystem_ports=(
                {} if filesystem_port is None else {provider_id: filesystem_port}
            ),
            process_ports=(
                {} if process_port is None else {provider_id: process_port}
            ),
            transfer_ports=(
                {} if transfer_port is None else {provider_id: transfer_port}
            ),
        ),
        resolved_authority,
        resolved_controlled,
    )


def test_observation_is_query_only_and_never_creates_controlled_operation() -> None:
    observation_port = FakeObservationPort()
    coordinator, authority, controlled = _coordinator(
        observation_port=observation_port,
    )

    result = coordinator.observe(
        context=_context(route_id=None),
        request=WorkspaceObservationRequest(
            binding=_binding(),
            operation=WorkspaceObservationKind.STATUS,
        ),
    )

    assert result.bounded_payload == b"ready"
    assert observation_port.calls == 1
    assert authority.requests[0].operation == "workspace.fs.read"
    assert controlled.commands == []


def test_mutation_is_admitted_before_exact_port_and_then_settled() -> None:
    port = FakeFilesystemPort()
    controlled = FakeControlledOperationService()
    coordinator, authority, _ = _coordinator(
        controlled=controlled,
        filesystem_port=port,
    )

    outcome = coordinator.mutate_filesystem(
        context=_context(),
        request=_mutation(),
    )

    assert port.calls == 1
    assert authority.requests[0].operation == "workspace.fs.write"
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.OBSERVE,
    ]
    assert outcome.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert outcome.mutation_applied is True
    assert outcome.settlement_state is WorkspaceOperationSettlementState.SETTLED
    assert outcome.fallback_performed is False


@pytest.mark.parametrize(
    "error_code",
    ["workspace_path_symlink_escape", "workspace_content_cas_mismatch"],
)
def test_adapter_path_or_cas_rejection_is_durable_no_effect(
    error_code: str,
) -> None:
    port = RefusingFilesystemPort(error_code)
    controlled = FakeControlledOperationService()
    coordinator, _, _ = _coordinator(
        controlled=controlled,
        filesystem_port=port,
    )

    outcome = coordinator.mutate_filesystem(
        context=_context(),
        request=_mutation(),
    )

    assert port.calls == 1
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.OBSERVE,
    ]
    assert outcome.error_code == error_code
    assert outcome.effect_certainty is ExternalEffectCertainty.NO_EFFECT
    assert outcome.mutation_applied is False


def test_lost_response_requires_reconcile_and_never_retries() -> None:
    port = LostResponseFilesystemPort()
    controlled = FakeControlledOperationService()
    coordinator, _, _ = _coordinator(
        controlled=controlled,
        filesystem_port=port,
    )

    outcome = coordinator.mutate_filesystem(
        context=_context(),
        request=_mutation(),
    )

    assert port.calls == 1
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.RECONCILE,
    ]
    assert outcome.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
    assert outcome.mutation_applied is None
    assert outcome.settlement_state is (
        WorkspaceOperationSettlementState.RECONCILE_REQUIRED
    )
    assert outcome.fallback_performed is False

    reconciled = coordinator.reconcile_filesystem(
        context=_context(),
        request=_mutation(),
    )

    assert port.calls == 1
    assert port.reconcile_calls == 1
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.RECONCILE,
        ControlledOperationCommandKind.RECONCILE,
    ]
    assert reconciled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert reconciled.settlement_state is WorkspaceOperationSettlementState.SETTLED
    assert controlled.commands[-1].payload["redispatch_performed"] is False


def test_unclassified_adapter_failure_preserves_cause_after_reconcile_record() -> None:
    port = ExplodingFilesystemPort()
    controlled = FakeControlledOperationService()
    coordinator, _, _ = _coordinator(
        controlled=controlled,
        filesystem_port=port,
    )

    with pytest.raises(WorkspaceOperationCoordinationError) as caught:
        coordinator.mutate_filesystem(
            context=_context(),
            request=_mutation(),
        )

    assert caught.value.code == "workspace_adapter_unclassified_failure"
    assert caught.value.effect_certainty is (
        ExternalEffectCertainty.DISPATCH_IN_DOUBT
    )
    assert isinstance(caught.value.__cause__, RuntimeError)
    assert port.calls == 1
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.RECONCILE,
    ]


def test_denied_authority_or_stale_generation_has_no_effect() -> None:
    denied = FakeAuthorityService(allowed=False)
    port = FakeFilesystemPort()
    controlled = FakeControlledOperationService()
    coordinator, _, _ = _coordinator(
        authority=denied,
        controlled=controlled,
        filesystem_port=port,
    )

    with pytest.raises(KernelContractError) as denied_error:
        coordinator.mutate_filesystem(context=_context(), request=_mutation())
    assert denied_error.value.effect_certainty == "no_effect"
    assert port.calls == 0
    assert controlled.commands == []

    with pytest.raises(KernelContractError) as stale_error:
        coordinator.mutate_filesystem(
            context=_context(generation=4),
            request=_mutation(),
        )
    assert stale_error.value.code == "workspace_generation_stale"
    assert port.calls == 0
    assert controlled.commands == []


def test_remote_binding_uses_hpc_authority_namespace_without_route_fallback() -> None:
    binding = _binding(
        kind=WorkspaceKind.EXECUTOR_REMOTE,
        provider_id="openzyme.hpc.ssh",
    )
    port = FakeFilesystemPort()
    coordinator, authority, controlled = _coordinator(
        filesystem_port=port,
        provider_id="openzyme.hpc.ssh",
    )

    outcome = coordinator.mutate_filesystem(
        context=_context(),
        request=_mutation(binding),
    )

    assert authority.requests[0].operation == "hpc.workspace.fs.write"
    assert outcome.fallback_performed is False
    assert len(controlled.commands) == 2


def test_transfer_uses_write_authority_and_one_controlled_operation() -> None:
    port = FakeTransferPort()
    authority = FakeAuthorityService()
    controlled = FakeControlledOperationService()
    coordinator = WorkspaceOperationCoordinator(
        authority=authority,
        controlled_operations=controlled,
        transfer_ports={"workspace.local": port},
    )

    outcome = coordinator.transfer(
        context=_context(),
        request=_transfer(),
    )

    assert port.calls == 1
    assert authority.requests[0].operation == "workspace.transfer.write"
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.OBSERVE,
    ]
    assert outcome.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert outcome.adapter_receipt is not None
    assert outcome.adapter_receipt.result_payload == (
        b'{"publication_performed":false}'
    )

    reconciled = coordinator.reconcile_transfer(
        context=_context(),
        request=_transfer(),
    )
    assert port.calls == 1
    assert port.reconcile_calls == 1
    assert reconciled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert controlled.commands[-1].operation is (
        ControlledOperationCommandKind.RECONCILE
    )


def test_process_reconciliation_observes_without_executing_again() -> None:
    port = FakeProcessPort()
    coordinator, _, controlled = _coordinator(process_port=port)

    executed = coordinator.execute_process(context=_context(), request=_process())
    reconciled = coordinator.reconcile_process(
        context=_context(),
        request=_process(),
    )

    assert executed.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert reconciled.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert port.calls == 1
    assert port.reconcile_calls == 1
    assert [item.operation for item in controlled.commands] == [
        ControlledOperationCommandKind.ADMIT,
        ControlledOperationCommandKind.OBSERVE,
        ControlledOperationCommandKind.RECONCILE,
    ]
    assert controlled.commands[-1].payload["redispatch_performed"] is False


def test_missing_exact_provider_fails_before_admission() -> None:
    coordinator, _, controlled = _coordinator()

    with pytest.raises(KernelContractError) as caught:
        coordinator.mutate_filesystem(context=_context(), request=_mutation())

    assert caught.value.code == "workspace_provider_unavailable"
    assert caught.value.effect_certainty == "no_effect"
    assert controlled.commands == []
