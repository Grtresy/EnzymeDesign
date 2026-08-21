from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any
from typing import Callable

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspaceExecRequest
from openzyme_contracts import WorkspaceFilesystemMutation
from openzyme_contracts import WorkspaceFilesystemPort
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import WorkspaceObservation
from openzyme_contracts import WorkspaceObservationPort
from openzyme_contracts import WorkspaceObservationRequest
from openzyme_contracts import WorkspaceOperationReceipt
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkspaceProcessPort
from openzyme_contracts import WorkspaceRuntimeBinding
from openzyme_contracts import WorkspaceTransferDirection
from openzyme_contracts import WorkspaceTransferPort
from openzyme_contracts import WorkspaceTransferRequest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import AuthorityApplicationService
from openzyme_extension_spi import AuthorityCheckRequest
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationApplicationService
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import KernelMutationReceipt

from .errors import KernelContractError


class WorkspaceOperationSettlementState(StrEnum):
    SETTLED = "settled"
    RECONCILE_REQUIRED = "reconcile_required"


@dataclass(frozen=True, slots=True)
class WorkspaceOperationOutcome:
    operation_id: str
    intent_digest: str
    workspace_id: str
    generation: int
    state_version: int
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool | None
    settlement_state: WorkspaceOperationSettlementState
    controlled_operation_receipt_digest: str
    adapter_receipt: WorkspaceOperationReceipt | None = None
    error_code: str | None = None
    diagnostic_id: str | None = None
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_identifier(self.workspace_id, field_name="workspace_id")
        require_digest(self.intent_digest, field_name="intent_digest")
        require_digest(
            self.controlled_operation_receipt_digest,
            field_name="controlled_operation_receipt_digest",
        )
        if self.generation < 1 or self.state_version < 1:
            raise ValueError("workspace generation and state_version must be positive")
        if self.fallback_performed:
            raise ValueError("workspace operation outcome cannot hide fallback")
        if self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if self.mutation_applied is not False:
                raise ValueError("no_effect outcome requires mutation_applied=false")
        elif self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.mutation_applied is not None:
                raise ValueError("dispatch_in_doubt outcome requires unknown mutation fact")
            if self.settlement_state is not WorkspaceOperationSettlementState.RECONCILE_REQUIRED:
                raise ValueError("dispatch_in_doubt outcome requires reconciliation")
        elif self.mutation_applied is None:
            raise ValueError("known effect outcome requires a mutation fact")
        if self.error_code is not None:
            require_identifier(self.error_code, field_name="error_code")
        if self.diagnostic_id is not None:
            require_identifier(self.diagnostic_id, field_name="diagnostic_id")
        if self.adapter_receipt is not None:
            _validate_adapter_receipt(
                self.adapter_receipt,
                operation_id=self.operation_id,
                binding_identity=(
                    self.workspace_id,
                    self.generation,
                    self.state_version,
                ),
            )

    def to_safe_dict(self) -> dict[str, Any]:
        return {
            "operation_id": self.operation_id,
            "intent_digest": self.intent_digest,
            "workspace_id": self.workspace_id,
            "generation": self.generation,
            "state_version": self.state_version,
            "effect_certainty": self.effect_certainty.value,
            "mutation_applied": self.mutation_applied,
            "settlement_state": self.settlement_state.value,
            "controlled_operation_receipt_digest": (
                self.controlled_operation_receipt_digest
            ),
            "adapter_receipt_digest": (
                None
                if self.adapter_receipt is None
                else self.adapter_receipt.receipt_digest
            ),
            "error_code": self.error_code,
            "diagnostic_id": self.diagnostic_id,
            "fallback_performed": self.fallback_performed,
        }


class WorkspaceOperationCoordinationError(RuntimeError):
    def __init__(
        self,
        code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        diagnostic_id: str | None = None,
        controlled_operation_receipt_digest: str | None = None,
    ) -> None:
        super().__init__(message)
        require_identifier(code, field_name="code")
        if diagnostic_id is not None:
            require_identifier(diagnostic_id, field_name="diagnostic_id")
        if controlled_operation_receipt_digest is not None:
            require_digest(
                controlled_operation_receipt_digest,
                field_name="controlled_operation_receipt_digest",
            )
        if effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if mutation_applied is not False:
                raise ValueError("no_effect coordination error requires no mutation")
        elif effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if mutation_applied is not None:
                raise ValueError(
                    "dispatch_in_doubt coordination error requires unknown mutation"
                )
        elif mutation_applied is None:
            raise ValueError("known-effect coordination error requires mutation fact")
        self.code = code
        self.effect_certainty = effect_certainty
        self.mutation_applied = mutation_applied
        self.diagnostic_id = diagnostic_id
        self.controlled_operation_receipt_digest = (
            controlled_operation_receipt_digest
        )
        self.fallback_performed = False


class WorkspaceOperationCoordinator:
    """Routes exact workspace bindings through the one ControlledOperation seam."""

    def __init__(
        self,
        *,
        authority: AuthorityApplicationService,
        controlled_operations: ControlledOperationApplicationService,
        observation_ports: Mapping[str, WorkspaceObservationPort] | None = None,
        filesystem_ports: Mapping[str, WorkspaceFilesystemPort] | None = None,
        process_ports: Mapping[str, WorkspaceProcessPort] | None = None,
        transfer_ports: Mapping[str, WorkspaceTransferPort] | None = None,
    ) -> None:
        self._authority = authority
        self._controlled_operations = controlled_operations
        self._observation_ports = dict(observation_ports or {})
        self._filesystem_ports = dict(filesystem_ports or {})
        self._process_ports = dict(process_ports or {})
        self._transfer_ports = dict(transfer_ports or {})

    def observe(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceObservationRequest,
    ) -> WorkspaceObservation:
        binding = request.binding
        self._validate_context(context, binding, requires_route=False)
        self._authorize(
            context,
            binding,
            operation=_authority_operation(binding, "fs.read"),
        )
        port = self._resolve_port(
            self._observation_ports,
            binding,
            port_kind="observation",
        )
        try:
            result = port.observe(request)
        except WorkspacePortError as exc:
            if exc.effect_certainty is not ExternalEffectCertainty.NO_EFFECT:
                raise WorkspaceOperationCoordinationError(
                    "workspace_observation_contract_violation",
                    "query-only workspace observation reported a possible effect",
                    effect_certainty=exc.effect_certainty,
                    mutation_applied=exc.mutation_applied,
                    diagnostic_id=exc.diagnostic_id,
                ) from exc
            raise KernelContractError(
                exc.error_code,
                str(exc),
                details={"diagnostic_id": exc.diagnostic_id},
            ) from exc
        _validate_observation(result, request)
        return result

    def mutate_filesystem(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationOutcome:
        self._validate_request_authority(
            context,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
        )
        return self._execute_effect(
            context=context,
            binding=request.binding,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            intent_digest=request.intent_digest,
            operation_name=f"filesystem.{request.operation.value}",
            authority_operation=_authority_operation(request.binding, "fs.write"),
            port=self._resolve_port(
                self._filesystem_ports,
                request.binding,
                port_kind="filesystem",
            ),
            dispatch=lambda port: port.mutate(request),
        )

    def execute_process(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceExecRequest,
    ) -> WorkspaceOperationOutcome:
        self._validate_request_authority(
            context,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
        )
        return self._execute_effect(
            context=context,
            binding=request.binding,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            intent_digest=request.intent_digest,
            operation_name="process.exec",
            authority_operation=_authority_operation(request.binding, "process.exec"),
            port=self._resolve_port(
                self._process_ports,
                request.binding,
                port_kind="process",
            ),
            dispatch=lambda port: port.execute(request),
            max_result_bytes=request.max_output_bytes,
        )

    def transfer(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceTransferRequest,
    ) -> WorkspaceOperationOutcome:
        self._validate_request_authority(
            context,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
        )
        direction = (
            "transfer.read"
            if request.direction is WorkspaceTransferDirection.DOWNLOAD
            else "transfer.write"
        )
        return self._execute_effect(
            context=context,
            binding=request.binding,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            intent_digest=request.intent_digest,
            operation_name=f"transfer.{request.direction.value}",
            authority_operation=_authority_operation(request.binding, direction),
            port=self._resolve_port(
                self._transfer_ports,
                request.binding,
                port_kind="transfer",
            ),
            dispatch=lambda port: port.transfer(request),
        )

    def reconcile_filesystem(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceFilesystemMutation,
    ) -> WorkspaceOperationOutcome:
        self._validate_request_authority(
            context,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
        )
        return self._reconcile_effect(
            context=context,
            binding=request.binding,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            intent_digest=request.intent_digest,
            authority_operation=_authority_operation(request.binding, "fs.write"),
            port=self._resolve_port(
                self._filesystem_ports,
                request.binding,
                port_kind="filesystem",
            ),
            reconcile=lambda port: port.reconcile(request),
        )

    def reconcile_process(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceExecRequest,
    ) -> WorkspaceOperationOutcome:
        self._validate_request_authority(
            context,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
        )
        return self._reconcile_effect(
            context=context,
            binding=request.binding,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            intent_digest=request.intent_digest,
            authority_operation=_authority_operation(request.binding, "process.exec"),
            port=self._resolve_port(
                self._process_ports,
                request.binding,
                port_kind="process",
            ),
            reconcile=lambda port: port.reconcile(request),
            max_result_bytes=request.max_output_bytes,
        )

    def reconcile_transfer(
        self,
        *,
        context: KernelCommandContext,
        request: WorkspaceTransferRequest,
    ) -> WorkspaceOperationOutcome:
        self._validate_request_authority(
            context,
            authority_lease_id=request.authority_lease_id,
            authority_generation=request.authority_generation,
            authority_fence=request.authority_fence,
        )
        direction = (
            "transfer.read"
            if request.direction is WorkspaceTransferDirection.DOWNLOAD
            else "transfer.write"
        )
        return self._reconcile_effect(
            context=context,
            binding=request.binding,
            operation_id=request.operation_id,
            idempotency_key=request.idempotency_key,
            intent_digest=request.intent_digest,
            authority_operation=_authority_operation(request.binding, direction),
            port=self._resolve_port(
                self._transfer_ports,
                request.binding,
                port_kind="transfer",
            ),
            reconcile=lambda port: port.reconcile(request),
        )

    def _reconcile_effect(
        self,
        *,
        context: KernelCommandContext,
        binding: WorkspaceRuntimeBinding,
        operation_id: str,
        idempotency_key: str,
        intent_digest: str,
        authority_operation: str,
        port: Any,
        reconcile: Callable[[Any], WorkspaceOperationReceipt],
        max_result_bytes: int | None = None,
    ) -> WorkspaceOperationOutcome:
        """Observe one admitted effect without dispatching it again."""

        self._validate_context(context, binding, requires_route=True)
        if context.idempotency_key != idempotency_key:
            raise KernelContractError(
                "workspace_idempotency_mismatch",
                "workspace reconciliation differs from the original idempotency key",
            )
        self._authorize(context, binding, operation=authority_operation)
        try:
            adapter_receipt = reconcile(port)
            _validate_adapter_receipt(
                adapter_receipt,
                operation_id=operation_id,
                binding_identity=(
                    binding.workspace_id,
                    binding.generation,
                    binding.state_version,
                ),
            )
            if (
                max_result_bytes is not None
                and len(adapter_receipt.result_payload) > max_result_bytes
            ):
                return self._record_failure(
                    context=context,
                    binding=binding,
                    operation_id=operation_id,
                    intent_digest=intent_digest,
                    effect_certainty=adapter_receipt.effect_certainty,
                    mutation_applied=adapter_receipt.mutation_applied,
                    error_code="workspace_adapter_result_unbounded",
                    diagnostic_id=adapter_receipt.diagnostic_id,
                    command_kind=ControlledOperationCommandKind.RECONCILE,
                )
        except WorkspacePortError as exc:
            return self._record_failure(
                context=context,
                binding=binding,
                operation_id=operation_id,
                intent_digest=intent_digest,
                effect_certainty=exc.effect_certainty,
                mutation_applied=exc.mutation_applied,
                error_code=exc.error_code,
                diagnostic_id=exc.diagnostic_id,
                command_kind=ControlledOperationCommandKind.RECONCILE,
            )
        except Exception as exc:
            outcome = self._record_failure(
                context=context,
                binding=binding,
                operation_id=operation_id,
                intent_digest=intent_digest,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                error_code="workspace_reconciliation_unclassified_failure",
                diagnostic_id=None,
                command_kind=ControlledOperationCommandKind.RECONCILE,
            )
            raise WorkspaceOperationCoordinationError(
                "workspace_reconciliation_unclassified_failure",
                "workspace Adapter reconciliation failed without redispatch",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                controlled_operation_receipt_digest=(
                    outcome.controlled_operation_receipt_digest
                ),
            ) from exc

        settlement = self._record_settlement(
            context=context,
            operation_id=operation_id,
            intent_digest=intent_digest,
            command_kind=ControlledOperationCommandKind.RECONCILE,
            payload={
                "adapter_receipt_digest": adapter_receipt.receipt_digest,
                "effect_certainty": adapter_receipt.effect_certainty.value,
                "mutation_applied": adapter_receipt.mutation_applied,
                "redispatch_performed": False,
                "fallback_performed": False,
            },
            effect_certainty=adapter_receipt.effect_certainty,
            mutation_applied=adapter_receipt.mutation_applied,
        )
        return WorkspaceOperationOutcome(
            operation_id=operation_id,
            intent_digest=intent_digest,
            workspace_id=binding.workspace_id,
            generation=binding.generation,
            state_version=binding.state_version,
            effect_certainty=adapter_receipt.effect_certainty,
            mutation_applied=adapter_receipt.mutation_applied,
            settlement_state=(
                WorkspaceOperationSettlementState.RECONCILE_REQUIRED
                if adapter_receipt.effect_certainty
                is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else WorkspaceOperationSettlementState.SETTLED
            ),
            controlled_operation_receipt_digest=settlement.receipt_digest,
            adapter_receipt=adapter_receipt,
        )

    def _execute_effect(
        self,
        *,
        context: KernelCommandContext,
        binding: WorkspaceRuntimeBinding,
        operation_id: str,
        idempotency_key: str,
        intent_digest: str,
        operation_name: str,
        authority_operation: str,
        port: Any,
        dispatch: Callable[[Any], WorkspaceOperationReceipt],
        max_result_bytes: int | None = None,
    ) -> WorkspaceOperationOutcome:
        self._validate_context(context, binding, requires_route=True)
        if context.idempotency_key != idempotency_key:
            raise KernelContractError(
                "workspace_idempotency_mismatch",
                "workspace request idempotency differs from command context",
            )
        self._authorize(context, binding, operation=authority_operation)
        safe_intent = _safe_intent_payload(
            binding=binding,
            operation_name=operation_name,
            authority_operation=authority_operation,
            intent_digest=intent_digest,
        )
        admission = self._controlled_operations.execute(
            ControlledOperationApplicationCommand(
                context=_phase_context(context, "admit"),
                operation=ControlledOperationCommandKind.ADMIT,
                operation_id=operation_id,
                intent_digest=intent_digest,
                payload=safe_intent,
            )
        )
        _validate_controlled_receipt(
            admission,
            expected_operation=ControlledOperationCommandKind.ADMIT,
            expected_effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            require_mutation=True,
        )

        try:
            adapter_receipt = dispatch(port)
            _validate_adapter_receipt(
                adapter_receipt,
                operation_id=operation_id,
                binding_identity=(
                    binding.workspace_id,
                    binding.generation,
                    binding.state_version,
                ),
            )
            if (
                max_result_bytes is not None
                and len(adapter_receipt.result_payload) > max_result_bytes
            ):
                return self._record_failure(
                    context=context,
                    binding=binding,
                    operation_id=operation_id,
                    intent_digest=intent_digest,
                    effect_certainty=adapter_receipt.effect_certainty,
                    mutation_applied=adapter_receipt.mutation_applied,
                    error_code="workspace_adapter_result_unbounded",
                    diagnostic_id=adapter_receipt.diagnostic_id,
                )
        except WorkspacePortError as exc:
            return self._record_failure(
                context=context,
                binding=binding,
                operation_id=operation_id,
                intent_digest=intent_digest,
                effect_certainty=exc.effect_certainty,
                mutation_applied=exc.mutation_applied,
                error_code=exc.error_code,
                diagnostic_id=exc.diagnostic_id,
            )
        except Exception as exc:
            outcome = self._record_failure(
                context=context,
                binding=binding,
                operation_id=operation_id,
                intent_digest=intent_digest,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                error_code="workspace_adapter_unclassified_failure",
                diagnostic_id=None,
            )
            raise WorkspaceOperationCoordinationError(
                "workspace_adapter_unclassified_failure",
                "workspace Adapter failed after durable admission",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                mutation_applied=None,
                controlled_operation_receipt_digest=(
                    outcome.controlled_operation_receipt_digest
                ),
            ) from exc

        command_kind = (
            ControlledOperationCommandKind.RECONCILE
            if adapter_receipt.effect_certainty
            is ExternalEffectCertainty.DISPATCH_IN_DOUBT
            else ControlledOperationCommandKind.OBSERVE
        )
        settlement = self._record_settlement(
            context=context,
            operation_id=operation_id,
            intent_digest=intent_digest,
            command_kind=command_kind,
            payload={
                "adapter_receipt_digest": adapter_receipt.receipt_digest,
                "effect_certainty": adapter_receipt.effect_certainty.value,
                "mutation_applied": adapter_receipt.mutation_applied,
                "fallback_performed": False,
            },
            effect_certainty=adapter_receipt.effect_certainty,
            mutation_applied=adapter_receipt.mutation_applied,
        )
        state = (
            WorkspaceOperationSettlementState.RECONCILE_REQUIRED
            if command_kind is ControlledOperationCommandKind.RECONCILE
            else WorkspaceOperationSettlementState.SETTLED
        )
        return WorkspaceOperationOutcome(
            operation_id=operation_id,
            intent_digest=intent_digest,
            workspace_id=binding.workspace_id,
            generation=binding.generation,
            state_version=binding.state_version,
            effect_certainty=adapter_receipt.effect_certainty,
            mutation_applied=adapter_receipt.mutation_applied,
            settlement_state=state,
            controlled_operation_receipt_digest=settlement.receipt_digest,
            adapter_receipt=adapter_receipt,
        )

    def _record_failure(
        self,
        *,
        context: KernelCommandContext,
        binding: WorkspaceRuntimeBinding,
        operation_id: str,
        intent_digest: str,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        error_code: str,
        diagnostic_id: str | None,
        command_kind: ControlledOperationCommandKind | None = None,
    ) -> WorkspaceOperationOutcome:
        if command_kind is None:
            command_kind = (
                ControlledOperationCommandKind.RECONCILE
                if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else ControlledOperationCommandKind.OBSERVE
            )
        try:
            settlement = self._record_settlement(
                context=context,
                operation_id=operation_id,
                intent_digest=intent_digest,
                command_kind=command_kind,
                payload={
                    "error_code": error_code,
                    "diagnostic_id": diagnostic_id,
                    "effect_certainty": effect_certainty.value,
                    "mutation_applied": mutation_applied,
                    "fallback_performed": False,
                },
                effect_certainty=effect_certainty,
                mutation_applied=mutation_applied,
            )
        except Exception as settlement_error:
            error = WorkspaceOperationCoordinationError(
                "workspace_operation_settlement_failed",
                "workspace effect could not be durably settled",
                effect_certainty=effect_certainty,
                mutation_applied=mutation_applied,
                diagnostic_id=diagnostic_id,
            )
            raise error from settlement_error
        outcome = WorkspaceOperationOutcome(
            operation_id=operation_id,
            intent_digest=intent_digest,
            workspace_id=binding.workspace_id,
            generation=binding.generation,
            state_version=binding.state_version,
            effect_certainty=effect_certainty,
            mutation_applied=mutation_applied,
            settlement_state=(
                WorkspaceOperationSettlementState.RECONCILE_REQUIRED
                if effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT
                else WorkspaceOperationSettlementState.SETTLED
            ),
            controlled_operation_receipt_digest=settlement.receipt_digest,
            error_code=error_code,
            diagnostic_id=diagnostic_id,
        )
        return outcome

    def _record_settlement(
        self,
        *,
        context: KernelCommandContext,
        operation_id: str,
        intent_digest: str,
        command_kind: ControlledOperationCommandKind,
        payload: Mapping[str, Any],
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
    ) -> KernelMutationReceipt:
        try:
            receipt = self._controlled_operations.execute(
                ControlledOperationApplicationCommand(
                    context=_phase_context(context, command_kind.value),
                    operation=command_kind,
                    operation_id=operation_id,
                    intent_digest=intent_digest,
                    payload=payload,
                )
            )
        except Exception as exc:
            raise WorkspaceOperationCoordinationError(
                "workspace_operation_settlement_failed",
                "workspace effect could not be durably settled",
                effect_certainty=effect_certainty,
                mutation_applied=mutation_applied,
            ) from exc
        _validate_controlled_receipt(
            receipt,
            expected_operation=command_kind,
            expected_effect_certainty=effect_certainty,
            require_mutation=True,
        )
        return receipt

    def _authorize(
        self,
        context: KernelCommandContext,
        binding: WorkspaceRuntimeBinding,
        *,
        operation: str,
    ) -> None:
        decision = self._authority.authorize(
            AuthorityCheckRequest(
                context=context.to_query_context(),
                operation=operation,
                scope_id=binding.workspace_id,
                expected_generation=context.authority_generation,
                expected_fence=context.authority_fence,
            )
        )
        if (
            decision.operation != operation
            or decision.scope_id != binding.workspace_id
            or decision.authority_lease_id != context.authority_lease_id
            or decision.generation != context.authority_generation
            or decision.fence != context.authority_fence
        ):
            raise KernelContractError(
                "workspace_authority_decision_mismatch",
                "authority response does not bind the exact workspace request",
            )
        if not decision.allowed:
            raise KernelContractError(
                decision.denial_code or "workspace_authority_denied",
                "workspace operation is not authorized",
            )

    @staticmethod
    def _validate_request_authority(
        context: KernelCommandContext,
        *,
        authority_lease_id: str,
        authority_generation: int,
        authority_fence: int,
    ) -> None:
        if authority_lease_id != context.authority_lease_id:
            raise KernelContractError(
                "workspace_authority_lease_mismatch",
                "workspace request names another authority lease",
            )
        if (
            authority_generation != context.authority_generation
            or authority_fence != context.authority_fence
        ):
            raise KernelContractError(
                "workspace_authority_fence_mismatch",
                "workspace request names a stale authority generation or fence",
            )

    @staticmethod
    def _validate_context(
        context: KernelCommandContext,
        binding: WorkspaceRuntimeBinding,
        *,
        requires_route: bool,
    ) -> None:
        if context.session_id != binding.session_id:
            raise KernelContractError(
                "workspace_session_mismatch",
                "workspace binding belongs to another Session",
            )
        if context.actor_id != binding.owner_member_id:
            raise KernelContractError(
                "workspace_owner_mismatch",
                "workspace binding belongs to another Agent member",
            )
        if context.workspace_generation != binding.generation:
            raise KernelContractError(
                "workspace_generation_stale",
                "workspace binding generation differs from command context",
            )
        if requires_route and context.route_id is None:
            raise KernelContractError(
                "workspace_route_missing",
                "effectful workspace operation requires an explicit resolved route",
            )

    @staticmethod
    def _resolve_port(
        ports: Mapping[str, Any],
        binding: WorkspaceRuntimeBinding,
        *,
        port_kind: str,
    ) -> Any:
        port = ports.get(binding.provider_id)
        if port is None:
            raise KernelContractError(
                "workspace_provider_unavailable",
                "exact workspace provider has no selected Adapter Port",
                details={
                    "provider_id": binding.provider_id,
                    "port_kind": port_kind,
                },
            )
        return port


def _phase_context(context: KernelCommandContext, phase: str) -> KernelCommandContext:
    return replace(
        context,
        command_id=f"{context.command_id}.{phase}",
        idempotency_key=f"{context.idempotency_key}.{phase}",
    )


def _authority_operation(binding: WorkspaceRuntimeBinding, suffix: str) -> str:
    prefix = "hpc.workspace" if binding.workspace_kind is WorkspaceKind.EXECUTOR_REMOTE else "workspace"
    return f"{prefix}.{suffix}"


def _safe_intent_payload(
    *,
    binding: WorkspaceRuntimeBinding,
    operation_name: str,
    authority_operation: str,
    intent_digest: str,
) -> dict[str, Any]:
    return {
        "workspace_id": binding.workspace_id,
        "workspace_kind": binding.workspace_kind.value,
        "workspace_generation": binding.generation,
        "workspace_state_version": binding.state_version,
        "provider_id": binding.provider_id,
        "target_id": binding.target_id,
        "target_qualification_digest": binding.target_qualification_digest,
        "operation_name": operation_name,
        "authority_operation": authority_operation,
        "request_digest": intent_digest,
        "fallback_performed": False,
    }


def _validate_observation(
    result: WorkspaceObservation,
    request: WorkspaceObservationRequest,
) -> None:
    binding = request.binding
    if (
        result.workspace_id != binding.workspace_id
        or result.generation != binding.generation
        or result.state_version != binding.state_version
        or result.operation is not request.operation
    ):
        raise KernelContractError(
            "workspace_observation_identity_mismatch",
            "workspace observation does not bind the exact request identity",
        )
    if len(result.bounded_payload) > request.max_bytes:
        raise KernelContractError(
            "workspace_observation_unbounded",
            "workspace observation exceeded its declared byte budget",
        )


def _validate_adapter_receipt(
    receipt: WorkspaceOperationReceipt,
    *,
    operation_id: str,
    binding_identity: tuple[str, int, int],
) -> None:
    if (
        receipt.operation_id != operation_id
        or (
            receipt.workspace_id,
            receipt.generation,
            receipt.state_version,
        )
        != binding_identity
    ):
        raise KernelContractError(
            "workspace_receipt_identity_mismatch",
            "workspace Adapter receipt does not bind the exact operation",
        )
    if receipt.fallback_performed:
        raise KernelContractError(
            "workspace_fallback_forbidden",
            "workspace Adapter reported a hidden fallback",
        )


def _validate_controlled_receipt(
    receipt: KernelMutationReceipt,
    *,
    expected_operation: ControlledOperationCommandKind,
    expected_effect_certainty: ExternalEffectCertainty,
    require_mutation: bool,
) -> None:
    if (
        receipt.service_id != "controlled_operation"
        or receipt.operation != expected_operation.value
        or receipt.effect_certainty is not expected_effect_certainty
        or receipt.mutation_applied is not require_mutation
        or receipt.fallback_performed
    ):
        raise KernelContractError(
            "controlled_operation_receipt_mismatch",
            "ControlledOperation service returned an incompatible receipt",
        )


__all__ = [
    "WorkspaceOperationCoordinationError",
    "WorkspaceOperationCoordinator",
    "WorkspaceOperationOutcome",
    "WorkspaceOperationSettlementState",
]
