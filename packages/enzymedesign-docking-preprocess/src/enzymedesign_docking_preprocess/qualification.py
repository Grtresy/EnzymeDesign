from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalScientificQualificationOperationPort
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest


PREPROCESS_QUALIFICATION_OPERATIONS = (
    "convert_format",
    "prepare_ligand",
    "prepare_receptor",
    "smiles_to_3d",
)


@dataclass(slots=True)
class PreprocessQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: ExternalScientificQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "enzymedesign.docking.preprocess":
            raise ValueError("preprocess bridge requires the selected Plugin binding")
        _verify_scientific_port(self.binding, self.operation_port)
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=PREPROCESS_QUALIFICATION_OPERATIONS,
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
    "PREPROCESS_QUALIFICATION_OPERATIONS",
    "PreprocessQualificationProbeBridge",
]


def _verify_scientific_port(
    binding: ExternalQualificationBridgeBinding,
    port: ExternalScientificQualificationOperationPort,
) -> None:
    if (
        port.driver_component_id != binding.component_id
        or port.component_id != binding.component_id
        or port.route_id != binding.route_id
        or port.subject_digest != binding.subject_digest
        or port.workload_input_digest != binding.input_digest
        or port.result_schema_digest != binding.expected_result_schema_digest
        or not port.formal_compute_only
    ):
        raise ValueError(
            "preprocess qualification port must bind exact formal Compute workload"
        )
