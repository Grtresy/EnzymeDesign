from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from typing import Protocol

from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOperationObservation
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalScientificQualificationRouteOutcome
from openzyme_contracts import ExternalScientificQualificationRoutePort
from openzyme_contracts import ExternalScientificQualificationWorkload
from openzyme_contracts import canonical_sha256_digest


class ScientificQualificationWorkloadCompiler(Protocol):
    """Owner compiler and terminal validator; it never performs an effect."""

    def compile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalScientificQualificationWorkload: ...

    def validate_terminal_result(
        self,
        workload: ExternalScientificQualificationWorkload,
        outcome: ExternalScientificQualificationRouteOutcome,
    ) -> None: ...


@dataclass(slots=True)
class FormalComputeScientificQualificationOperation:
    """Dispatch one exact owner-compiled workload through one selected Compute route."""

    component_id: str
    route_id: str
    subject_digest: str
    driver_component_id: str
    workload_input_digest: str
    result_schema_digest: str
    compiler: ScientificQualificationWorkloadCompiler = field(repr=False)
    compute_route: ExternalScientificQualificationRoutePort = field(repr=False)
    formal_compute_only: bool = True
    _workloads: dict[str, ExternalScientificQualificationWorkload] = field(
        default_factory=dict,
        init=False,
        repr=False,
    )

    def dispatch(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationOperationObservation:
        try:
            workload = self.compiler.compile(request)
            if (
                workload.driver_component_id != self.driver_component_id
                or workload.operation != request.operation
                or workload.route_kind != self.compute_route.route_kind
            ):
                raise ExternalQualificationError(
                    "qualification_compute_workload_binding_mismatch",
                    "owner-compiled scientific workload differs from the selected route",
                )
        except ExternalQualificationError as exc:
            return self._failure(request, exc.error_code)
        except (KeyError, TypeError, ValueError) as exc:
            return self._failure(
                request,
                getattr(exc, "error_code", "qualification_compute_compile_failed"),
            )
        self._workloads[request.attempt_id] = workload
        try:
            outcome = self.compute_route.dispatch(workload)
            return self._convert(request, workload, outcome)
        except (OSError, ExternalQualificationError) as exc:
            return self._failure(
                request,
                getattr(exc, "error_code", "qualification_compute_route_failed"),
                external_effect_performed=True,
                credential_material_accessed=(self.compute_route.route_kind == "hpc-primary"),
            )

    def reconcile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationOperationObservation:
        try:
            workload = self._workloads[request.attempt_id]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "scientific reconcile requires the exact dispatched workload",
            ) from exc
        return self._convert(
            request,
            workload,
            self.compute_route.reconcile(workload),
        )

    def restore_dispatched_attempt(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> None:
        workload = self.compiler.compile(request)
        if (
            workload.driver_component_id != self.driver_component_id
            or workload.operation != request.operation
            or workload.route_kind != self.compute_route.route_kind
        ):
            raise ExternalQualificationError(
                "qualification_compute_workload_binding_mismatch",
                "restored scientific workload differs from the selected route",
            )
        self._workloads[request.attempt_id] = workload

    def _convert(
        self,
        request: ExternalQualificationProbeRequest,
        workload: ExternalScientificQualificationWorkload,
        outcome: ExternalScientificQualificationRouteOutcome,
    ) -> ExternalQualificationOperationObservation:
        if outcome.workload_digest != workload.workload_digest:
            raise ExternalQualificationError(
                "qualification_compute_result_identity_mismatch",
                "scientific route result differs from the exact workload",
            )
        if outcome.succeeded:
            self.compiler.validate_terminal_result(workload, outcome)
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty=(
                "terminal_known" if outcome.terminal else "dispatch_in_doubt"
            ),
            terminal=outcome.terminal,
            succeeded=outcome.succeeded,
            output_digest=outcome.output_digest,
            receipt_digest=outcome.receipt_digest,
            error_code=outcome.error_code,
            external_effect_performed=outcome.external_effect_performed,
            credential_material_accessed=outcome.credential_material_accessed,
            fallback_performed=False,
        )

    @staticmethod
    def _failure(
        request: ExternalQualificationProbeRequest,
        error_code: str,
        *,
        external_effect_performed: bool = False,
        credential_material_accessed: bool = False,
    ) -> ExternalQualificationOperationObservation:
        payload = {
            "attempt_id": request.attempt_id,
            "request_digest": request.request_digest,
            "error_code": error_code,
        }
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty="no_effect",
            terminal=True,
            succeeded=False,
            output_digest=None,
            receipt_digest=canonical_sha256_digest(payload),
            error_code=error_code,
            external_effect_performed=external_effect_performed,
            credential_material_accessed=credential_material_accessed,
            fallback_performed=False,
        )


__all__ = [
    "FormalComputeScientificQualificationOperation",
    "ScientificQualificationWorkloadCompiler",
]
