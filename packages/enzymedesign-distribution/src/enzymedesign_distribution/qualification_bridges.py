from __future__ import annotations

from collections.abc import Callable
from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationAuthorizationRevocation
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

    def restore_dispatched_attempt(
        self, request: ExternalQualificationProbeRequest
    ) -> None: ...


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
    operator_id: str
    observed_at: str
    bridge_builders: Mapping[str, QualificationProbeBridgeBuilder]
    selected_unit_digests: tuple[str, ...] | None = None
    revocation: ExternalQualificationAuthorizationRevocation | None = None
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
            expected_operator_id=self.operator_id,
            revocation=self.revocation,
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
        selected = (
            set(bindings)
            if self.selected_unit_digests is None
            else set(self.selected_unit_digests)
        )
        if (
            not selected
            or len(selected)
            != (
                len(bindings)
                if self.selected_unit_digests is None
                else len(self.selected_unit_digests)
            )
            or not selected.issubset(bindings)
        ):
            raise ExternalQualificationError(
                "qualification_occurrence_scope_invalid",
                "live router scope must be a non-empty dry-plan subset",
            )
        self.selected_unit_digests = tuple(sorted(selected))
        for unit_digest in self.selected_unit_digests:
            subject_binding = bindings[unit_digest]
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

    def restore_dispatched_attempt(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> None:
        """Rehydrate an exact persisted in-doubt attempt for reconcile only."""
        bridge = self._bridge_for_request(request)
        existing = self._attempt_units.get(request.attempt_id)
        if existing is not None and existing != request.unit_digest:
            raise ExternalQualificationError(
                "qualification_probe_attempt_identity_drift",
                "persisted qualification attempt binds a different unit",
            )
        restore = getattr(bridge, "restore_dispatched_attempt", None)
        if restore is None:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_restore_unsupported",
                "owner bridge cannot safely restore this persisted in-doubt attempt",
            )
        restore(request)
        self._attempt_units[request.attempt_id] = request.unit_digest

    def _bridge_for_request(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> SelectedQualificationProbeBridge:
        if request.unit_digest not in self._bridges:
            raise ExternalQualificationError(
                "qualification_probe_outside_occurrence_scope",
                "qualification request is outside the persisted occurrence scope",
            )
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
