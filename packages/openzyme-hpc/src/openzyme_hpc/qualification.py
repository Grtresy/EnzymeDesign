from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import QualificationSpec

from .inventory import InventoryGeneration
from .inventory import QualificationReceiptStatus
from .inventory import SoftwareQualificationReceipt
from .inventory import TargetCapabilityFact
from .inventory import TargetToolchainInventory


class TargetQualificationActorKind(StrEnum):
    OPERATOR = "operator"
    ADMIN = "admin"
    AGENT = "agent"


class QualificationProbeKind(StrEnum):
    VERSION = "version"
    SMOKE = "smoke"


class TargetQualificationError(RuntimeError):
    def __init__(
        self,
        error_code: str,
        message: str,
        *,
        effect_certainty: ExternalEffectCertainty = ExternalEffectCertainty.NO_EFFECT,
    ) -> None:
        self.error_code = error_code
        self.effect_certainty = effect_certainty
        self.mutation_applied = False
        self.fallback_performed = False
        super().__init__(message)


@dataclass(frozen=True, slots=True)
class QualificationProbeRequest:
    operation_id: str
    target_id: str
    environment_digest: str
    qualification_spec_id: str
    qualification_spec_digest: str
    probe_kind: QualificationProbeKind
    argv: tuple[str, ...]
    expected_result_schema_digest: str
    request_digest: str

    @classmethod
    def create(
        cls,
        *,
        operation_id: str,
        target_id: str,
        environment_digest: str,
        spec: QualificationSpec,
        probe_kind: QualificationProbeKind,
    ) -> "QualificationProbeRequest":
        argv = (
            spec.version_argv
            if probe_kind is QualificationProbeKind.VERSION
            else spec.smoke_argv
        )
        expected_schema_digest = canonical_sha256_digest(
            spec.to_dict()["expected_result_schema"]
        )
        payload = {
            "operation_id": operation_id,
            "target_id": target_id,
            "environment_digest": environment_digest,
            "qualification_spec_id": spec.qualification_spec_id,
            "qualification_spec_digest": spec.qualification_spec_digest,
            "probe_kind": probe_kind.value,
            "argv": list(argv),
            "expected_result_schema_digest": expected_schema_digest,
        }
        return cls(
            operation_id=operation_id,
            target_id=target_id,
            environment_digest=environment_digest,
            qualification_spec_id=spec.qualification_spec_id,
            qualification_spec_digest=spec.qualification_spec_digest,
            probe_kind=probe_kind,
            argv=argv,
            expected_result_schema_digest=expected_schema_digest,
            request_digest=canonical_sha256_digest(payload),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "operation_id",
            "target_id",
            "qualification_spec_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "environment_digest",
            "qualification_spec_digest",
            "expected_result_schema_digest",
            "request_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if not self.argv or any(not value or "\x00" in value for value in self.argv):
            raise ValueError("qualification probe argv must be non-empty and closed")


@dataclass(frozen=True, slots=True)
class QualificationProbeOutcome:
    operation_id: str
    request_digest: str
    effect_certainty: ExternalEffectCertainty
    succeeded: bool
    output_digest: str | None
    backend_receipt_digest: str | None
    observed_version: str | None = None
    expected_schema_matched: bool | None = None

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.request_digest, field_name="request_digest")
        if self.output_digest is not None:
            require_digest(self.output_digest, field_name="output_digest")
        if self.backend_receipt_digest is not None:
            require_digest(
                self.backend_receipt_digest,
                field_name="backend_receipt_digest",
            )
        if self.observed_version is not None:
            require_identifier(self.observed_version, field_name="observed_version")


class ControlledQualificationProbePort(Protocol):
    """Adapter Port whose implementation uses one Kernel ControlledOperation."""

    def dispatch(self, request: QualificationProbeRequest) -> QualificationProbeOutcome: ...

    def reconcile(self, request: QualificationProbeRequest) -> QualificationProbeOutcome: ...


class TargetInventoryRepository(Protocol):
    def latest(self, target_id: str) -> TargetToolchainInventory | None: ...

    def publish(
        self,
        inventory: TargetToolchainInventory,
        generation: InventoryGeneration,
        receipts: tuple[SoftwareQualificationReceipt, ...],
        *,
        expected_previous_digest: str | None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class TargetQualificationCommand:
    command_id: str
    actor_id: str
    actor_kind: TargetQualificationActorKind
    target_id: str
    target_profile_digest: str
    environment_digest: str
    specs: tuple[QualificationSpec, ...]
    observed_at: str
    valid_until: str

    def __post_init__(self) -> None:
        for field_name in ("command_id", "actor_id", "target_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.target_profile_digest,
            field_name="target_profile_digest",
        )
        require_digest(self.environment_digest, field_name="environment_digest")
        spec_ids = [spec.qualification_spec_id for spec in self.specs]
        if not self.specs or len(spec_ids) != len(set(spec_ids)):
            raise ValueError("qualification specs must be non-empty and unique")


@dataclass(frozen=True, slots=True)
class TargetQualificationWorkflow:
    probe_port: ControlledQualificationProbePort
    inventory_repository: TargetInventoryRepository

    def execute(
        self,
        command: TargetQualificationCommand,
    ) -> TargetToolchainInventory:
        if command.actor_kind not in {
            TargetQualificationActorKind.OPERATOR,
            TargetQualificationActorKind.ADMIN,
        }:
            raise TargetQualificationError(
                "target_qualification_actor_forbidden",
                "only an operator or admin may run target qualification",
            )
        previous = self.inventory_repository.latest(command.target_id)
        generation_number = 1 if previous is None else previous.generation + 1
        receipts: list[SoftwareQualificationReceipt] = []
        facts: list[TargetCapabilityFact] = []
        for index, spec in enumerate(
            sorted(command.specs, key=lambda item: item.qualification_spec_id)
        ):
            version_request = QualificationProbeRequest.create(
                operation_id=f"{command.command_id}:version:{index}",
                target_id=command.target_id,
                environment_digest=command.environment_digest,
                spec=spec,
                probe_kind=QualificationProbeKind.VERSION,
            )
            version = self._settle(version_request)
            smoke_request = QualificationProbeRequest.create(
                operation_id=f"{command.command_id}:smoke:{index}",
                target_id=command.target_id,
                environment_digest=command.environment_digest,
                spec=spec,
                probe_kind=QualificationProbeKind.SMOKE,
            )
            smoke = self._settle(smoke_request)
            if (
                not version.succeeded
                or version.observed_version is None
                or not smoke.succeeded
                or smoke.expected_schema_matched is not True
                or version.backend_receipt_digest is None
                or smoke.backend_receipt_digest is None
                or version.output_digest is None
                or smoke.output_digest is None
            ):
                raise TargetQualificationError(
                    "target_qualification_probe_failed",
                    "version or deterministic smoke qualification failed",
                    effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
                )
            receipt = SoftwareQualificationReceipt.create(
                receipt_id=f"{command.command_id}:receipt:{index}",
                qualification_spec_id=spec.qualification_spec_id,
                qualification_spec_digest=spec.qualification_spec_digest,
                target_id=command.target_id,
                environment_digest=command.environment_digest,
                capability_id=spec.capability_id,
                observed_version=version.observed_version,
                version_query_receipt_digest=version.backend_receipt_digest,
                smoke_input_digest=smoke_request.request_digest,
                smoke_result_digest=smoke.output_digest,
                expected_result_schema_digest=(
                    smoke_request.expected_result_schema_digest
                ),
                status=QualificationReceiptStatus.PASSED,
                observed_at=command.observed_at,
                valid_until=command.valid_until,
            )
            receipts.append(receipt)
            facts.append(
                TargetCapabilityFact(
                    capability_id=spec.capability_id,
                    kind=ResourceCapabilityKind.SOFTWARE,
                    contract_version=spec.contract_version,
                    version=version.observed_version,
                    operations=(),
                    environment_digest=command.environment_digest,
                    qualification_digest=receipt.receipt_digest,
                    implementation_digest=version.output_digest,
                )
            )
        inventory = TargetToolchainInventory.create(
            target_id=command.target_id,
            generation=generation_number,
            target_profile_digest=command.target_profile_digest,
            facts=tuple(facts),
            qualification_receipt_digests=tuple(
                receipt.receipt_digest for receipt in receipts
            ),
            valid_until=command.valid_until,
            created_at=command.observed_at,
        )
        generation = InventoryGeneration.create(
            target_id=command.target_id,
            generation=generation_number,
            previous_inventory_digest=(
                None if previous is None else previous.inventory_digest
            ),
            inventory_digest=inventory.inventory_digest,
            published_by_actor_id=command.actor_id,
            published_at=command.observed_at,
        )
        self.inventory_repository.publish(
            inventory,
            generation,
            tuple(receipts),
            expected_previous_digest=(
                None if previous is None else previous.inventory_digest
            ),
        )
        return inventory

    def _settle(
        self,
        request: QualificationProbeRequest,
    ) -> QualificationProbeOutcome:
        outcome = self.probe_port.dispatch(request)
        self._validate_outcome(request, outcome)
        if outcome.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            outcome = self.probe_port.reconcile(request)
            self._validate_outcome(request, outcome)
        if outcome.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            raise TargetQualificationError(
                "target_qualification_dispatch_in_doubt",
                "qualification occurrence remains uncertain; inventory was not published",
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
            )
        if outcome.effect_certainty is not ExternalEffectCertainty.TERMINAL_KNOWN:
            raise TargetQualificationError(
                "target_qualification_not_terminal",
                "qualification occurrence lacks terminal settlement; inventory was not published",
                effect_certainty=outcome.effect_certainty,
            )
        return outcome

    @staticmethod
    def _validate_outcome(
        request: QualificationProbeRequest,
        outcome: QualificationProbeOutcome,
    ) -> None:
        if (
            outcome.operation_id != request.operation_id
            or outcome.request_digest != request.request_digest
        ):
            raise TargetQualificationError(
                "target_qualification_probe_identity_mismatch",
                "qualification Adapter response drifted from the exact occurrence",
                effect_certainty=outcome.effect_certainty,
            )


__all__ = [
    "ControlledQualificationProbePort",
    "QualificationProbeKind",
    "QualificationProbeOutcome",
    "QualificationProbeRequest",
    "TargetInventoryRepository",
    "TargetQualificationActorKind",
    "TargetQualificationCommand",
    "TargetQualificationError",
    "TargetQualificationWorkflow",
]
