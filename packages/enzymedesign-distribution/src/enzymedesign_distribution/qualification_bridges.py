from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationUnit
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import verify_external_qualification_occurrence_authorization
from openzyme_contracts import verify_external_qualification_probe_request_binding


class SelectedQualificationProbeBridge(Protocol):
    binding: ExternalQualificationBridgeBinding

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome: ...

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome: ...


QualificationProbeBridgeBuilder = Callable[
    [ExternalQualificationBridgeBinding],
    SelectedQualificationProbeBridge,
]


def external_qualification_live_input_digest(
    *,
    dry_plan_digest: str,
    unit_digest: str,
) -> str:
    return canonical_sha256_digest(
        {
            "schema_version": "external_qualification_live_input@1",
            "dry_plan_digest": dry_plan_digest,
            "unit_digest": unit_digest,
        }
    )


def build_external_qualification_probe_request(
    *,
    dry_plan: ExternalQualificationDryPlan,
    readiness_unit: ExternalQualificationUnit,
    attempt_id: str,
    timeout_seconds: int,
) -> ExternalQualificationProbeRequest:
    binding = next(
        (
            item
            for item in dry_plan.unit_bindings
            if item.unit_digest == readiness_unit.unit_digest
        ),
        None,
    )
    if binding is None or binding.subject_digest is None or binding.gap_ids:
        raise ExternalQualificationError(
            "blocked_identity",
            "live probe request requires one resolved exact unit binding",
        )
    return ExternalQualificationProbeRequest.create(
        attempt_id=attempt_id,
        plan_digest=dry_plan.dry_plan_digest,
        unit_digest=readiness_unit.unit_digest,
        operation=readiness_unit.operation,
        timeout_seconds=timeout_seconds,
        input_digest=external_qualification_live_input_digest(
            dry_plan_digest=dry_plan.dry_plan_digest,
            unit_digest=readiness_unit.unit_digest,
        ),
        expected_result_schema_digest=(readiness_unit.expected_result_schema_digest),
        credential_locator_id=binding.credential_locator_id,
    )


@dataclass(slots=True)
class SelectedQualificationProbeRouter:
    """Authorization-bound exact-unit router with no route or backend fallback."""

    dry_plan: ExternalQualificationDryPlan
    readiness_plan: ExternalQualificationPlan
    authorization: ExternalQualificationOccurrenceAuthorization
    observed_at: str
    bridge_builders: Mapping[str, QualificationProbeBridgeBuilder]
    backend_id: str = "enzymedesign.selected-live-qualification-router@1"
    _bridges: dict[str, SelectedQualificationProbeBridge] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )
    _attempt_units: dict[str, str] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def __post_init__(self) -> None:
        verify_external_qualification_occurrence_authorization(
            self.dry_plan,
            self.authorization,
            observed_at=self.observed_at,
        )
        if self.dry_plan.readiness_plan_digest != self.readiness_plan.plan_digest:
            raise ExternalQualificationError(
                "qualification_readiness_plan_drift",
                "live router readiness plan differs from the authorized dry plan",
            )
        units = {item.unit_digest: item for item in self.readiness_plan.units}
        bindings = {item.unit_digest: item for item in self.dry_plan.unit_bindings}
        if set(units).intersection(bindings) != set(bindings):
            raise ExternalQualificationError(
                "qualification_bridge_unit_not_selected",
                "authorized dry plan contains a unit outside the selected readiness plan",
            )
        for unit_digest, subject_binding in bindings.items():
            if subject_binding.subject_digest is None or subject_binding.gap_ids:
                raise ExternalQualificationError(
                    "blocked_identity",
                    "live router cannot construct a bridge for an unresolved subject",
                )
            unit = units[unit_digest]
            try:
                builder = self.bridge_builders[unit.component_id]
            except KeyError as exc:
                raise ExternalQualificationError(
                    "qualification_live_bridge_missing",
                    "no owner-scoped bridge is installed for one exact unit",
                ) from exc
            binding = ExternalQualificationBridgeBinding.create(
                component_id=unit.component_id,
                operation=unit.operation,
                route_id=unit.route_id,
                plan_digest=self.dry_plan.dry_plan_digest,
                unit_digest=unit.unit_digest,
                subject_digest=subject_binding.subject_digest,
                input_digest=external_qualification_live_input_digest(
                    dry_plan_digest=self.dry_plan.dry_plan_digest,
                    unit_digest=unit.unit_digest,
                ),
                expected_result_schema_digest=(unit.expected_result_schema_digest),
                authorization_digest=self.authorization.authorization_digest,
                credential_locator_id=subject_binding.credential_locator_id,
            )
            bridge = builder(binding)
            if bridge.binding.binding_digest != binding.binding_digest:
                raise ExternalQualificationError(
                    "qualification_live_bridge_binding_mismatch",
                    "owner bridge does not expose the exact authorized binding",
                )
            self._bridges[unit_digest] = bridge

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        bridge = self._bridge_for_request(request)
        if request.attempt_id in self._attempt_units:
            raise ExternalQualificationError(
                "qualification_probe_redispatch_forbidden",
                "live qualification router forbids repeated dispatch",
            )
        self._attempt_units[request.attempt_id] = request.unit_digest
        return bridge.dispatch(request)

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        bridge = self._bridge_for_request(request)
        if self._attempt_units.get(request.attempt_id) != request.unit_digest:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "live qualification reconcile requires the exact prior attempt",
            )
        return bridge.reconcile(request)

    def _bridge_for_request(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> SelectedQualificationProbeBridge:
        try:
            bridge = self._bridges[request.unit_digest]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_probe_unit_unknown",
                "live qualification request names an unauthorized unit",
            ) from exc
        verify_external_qualification_probe_request_binding(bridge.binding, request)
        return bridge


__all__ = [
    "QualificationProbeBridgeBuilder",
    "SelectedQualificationProbeBridge",
    "SelectedQualificationProbeRouter",
    "build_external_qualification_probe_request",
    "external_qualification_live_input_digest",
]
