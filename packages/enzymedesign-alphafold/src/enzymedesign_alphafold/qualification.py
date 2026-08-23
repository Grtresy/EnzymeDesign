from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationOperationPort


ALPHAFOLD_QUALIFICATION_OPERATIONS = ("predict",)


@dataclass(slots=True)
class AlphaFoldQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: ExternalScientificQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "enzymedesign.alphafold.hpc":
            raise ValueError("AlphaFold bridge requires the selected HPC Driver")
        port = self.operation_port
        if (
            port.driver_component_id != self.binding.component_id
            or port.component_id != self.binding.component_id
            or port.route_id != self.binding.route_id
            or port.subject_digest != self.binding.subject_digest
            or port.workload_input_digest != self.binding.input_digest
            or port.result_schema_digest != self.binding.expected_result_schema_digest
            or not port.formal_compute_only
        ):
            raise ValueError(
                "AlphaFold qualification port must bind exact formal Compute workload"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=port,
            allowed_operations=ALPHAFOLD_QUALIFICATION_OPERATIONS,
        )

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.dispatch(request)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        return self._bridge.reconcile(request)

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None:
        self._bridge.restore_dispatched_attempt(request)


__all__ = [
    "ALPHAFOLD_QUALIFICATION_OPERATIONS",
    "AlphaFoldQualificationProbeBridge",
]
