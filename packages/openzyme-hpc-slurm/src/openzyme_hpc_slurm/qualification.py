from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest


SLURM_QUALIFICATION_OPERATIONS = ("cancel", "observe", "reconcile", "submit")


class SlurmQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    qualification_account_only: bool
    same_attempt_reconcile: bool


@dataclass(slots=True)
class SlurmQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: SlurmQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.hpc.slurm":
            raise ValueError("Slurm bridge requires the selected Adapter binding")
        if (
            self.operation_port.component_id != self.binding.component_id
            or self.operation_port.route_id != self.binding.route_id
            or self.operation_port.subject_digest != self.binding.subject_digest
            or not self.operation_port.qualification_account_only
            or not self.operation_port.same_attempt_reconcile
        ):
            raise ValueError(
                "Slurm qualification port must bind one exact qualification account"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=SLURM_QUALIFICATION_OPERATIONS,
        )

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.dispatch(request)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.reconcile(request)


__all__ = [
    "SLURM_QUALIFICATION_OPERATIONS",
    "SlurmQualificationOperationPort",
    "SlurmQualificationProbeBridge",
]
