from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalBoundQualificationOperationPort
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest


PODMAN_QUALIFICATION_OPERATIONS = (
    "container-start",
    "create",
    "delete",
    "exec",
    "mount",
    "read",
    "retire",
    "timeout",
    "update",
)


class PodmanQualificationOperationPort(
    ExternalBoundQualificationOperationPort,
    Protocol,
):
    qualification_isolated: bool
    image_digest_pinned: bool


@dataclass(slots=True)
class PodmanQualificationProbeBridge:
    binding: ExternalQualificationBridgeBinding
    operation_port: PodmanQualificationOperationPort
    _bridge: BoundExternalQualificationOperationBridge = field(init=False, repr=False)

    def __post_init__(self) -> None:
        if self.binding.component_id != "openzyme.process.podman":
            raise ValueError("Podman bridge requires the selected Adapter binding")
        if (
            self.operation_port.component_id != self.binding.component_id
            or self.operation_port.route_id != self.binding.route_id
            or self.operation_port.subject_digest != self.binding.subject_digest
            or not self.operation_port.qualification_isolated
            or not self.operation_port.image_digest_pinned
        ):
            raise ValueError(
                "Podman qualification port must bind one isolated digest-pinned subject"
            )
        self._bridge = BoundExternalQualificationOperationBridge(
            binding=self.binding,
            operation_port=self.operation_port,
            allowed_operations=PODMAN_QUALIFICATION_OPERATIONS,
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
    "PODMAN_QUALIFICATION_OPERATIONS",
    "PodmanQualificationOperationPort",
    "PodmanQualificationProbeBridge",
]
