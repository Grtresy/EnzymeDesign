from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalScientificQualificationOperationPort
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest


HMMER_QUALIFICATION_OPERATIONS = ("hmmbuild", "hmmsearch")


@dataclass(slots=True)
class HmmerQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: ExternalScientificQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id not in {
            "enzymedesign.hmmer.local",
            "enzymedesign.hmmer.hpc",
        }:
            raise ValueError("HMMER bridge requires one selected HMMER Driver binding")
        _verify_scientific_port(self.binding, self.operation_port)
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=HMMER_QUALIFICATION_OPERATIONS,
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


__all__ = ["HMMER_QUALIFICATION_OPERATIONS", "HmmerQualificationProbeBridge"]


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
            "HMMER qualification port must bind exact formal Compute workload"
        )
