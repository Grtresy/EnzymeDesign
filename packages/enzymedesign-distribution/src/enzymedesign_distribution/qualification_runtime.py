from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from datetime import timedelta
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationFailure
from openzyme_contracts import ExternalQualificationLifecycle
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationReadinessReceipt
from openzyme_contracts import ExternalQualificationReadinessReport
from openzyme_contracts import ExternalQualificationReadinessStatus
from openzyme_contracts import ExternalQualificationUnit
from openzyme_contracts import QualificationCredentialLocator
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import sanitize_public_diagnostic_text

from .external_qualification import REQUIRED_NEGATIVE_TESTS


class ExternalQualificationProbePort(Protocol):
    def dispatch(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationProbeOutcome: ...

    def reconcile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationProbeOutcome: ...


class QualificationCredentialResolverPort(Protocol):
    def resolve(
        self,
        *,
        unit: ExternalQualificationUnit,
        locator: QualificationCredentialLocator,
    ) -> object: ...


class QualificationNegativeFixturePort(Protocol):
    def exercise_negative(self, test_id: str) -> "NegativeFixtureResult": ...


@dataclass(frozen=True, slots=True)
class NegativeFixtureResult:
    test_id: str
    passed: bool
    external_effect_performed: bool
    credential_material_accessed: bool
    fallback_performed: bool
    fixture_receipt_digest: str


@dataclass(frozen=True, slots=True)
class PrivateQualificationDiagnostic:
    diagnostic_id: str
    error_code: str
    cause_type: str
    bounded_context: str


@dataclass(frozen=True, slots=True)
class QualificationDisclosureEntry:
    component_id: str
    capability_id: str
    operation: str
    route_id: str
    subject_id: str
    declaration_verified: bool
    runtime_mounted: bool
    non_live_exercised: bool
    deterministic_substitute: bool
    qualified: bool
    cutover: bool
    live_occurrence: bool
    receipt_digest: str

    def to_dict(self) -> dict[str, object]:
        return {
            "component_id": self.component_id,
            "capability_id": self.capability_id,
            "operation": self.operation,
            "route_id": self.route_id,
            "subject_id": self.subject_id,
            "declaration_verified": self.declaration_verified,
            "runtime_mounted": self.runtime_mounted,
            "non_live_exercised": self.non_live_exercised,
            "deterministic_substitute": self.deterministic_substitute,
            "qualified": self.qualified,
            "cutover": self.cutover,
            "live_occurrence": self.live_occurrence,
            "receipt_digest": self.receipt_digest,
        }


@dataclass(frozen=True, slots=True)
class QualificationDisclosureMatrix:
    plan_digest: str
    report_digest: str
    entries: tuple[QualificationDisclosureEntry, ...]
    matrix_digest: str

    @classmethod
    def create(
        cls,
        *,
        plan: ExternalQualificationPlan,
        report: ExternalQualificationReadinessReport,
    ) -> "QualificationDisclosureMatrix":
        receipts = {item.unit_digest: item for item in report.receipts}
        entries = tuple(
            QualificationDisclosureEntry(
                component_id=unit.component_id,
                capability_id=unit.capability_id,
                operation=unit.operation,
                route_id=unit.route_id,
                subject_id=unit.subject_id,
                declaration_verified=True,
                runtime_mounted=True,
                non_live_exercised=unit.unit_digest in receipts,
                deterministic_substitute=True,
                qualified=False,
                cutover=False,
                live_occurrence=False,
                receipt_digest=receipts[unit.unit_digest].receipt_digest,
            )
            for unit in plan.units
            if unit.unit_digest in receipts
        )
        payload = {
            "schema_version": "qualification_disclosure_matrix@1",
            "plan_digest": plan.plan_digest,
            "report_digest": report.report_digest,
            "entries": [item.to_dict() for item in entries],
        }
        return cls(
            plan_digest=plan.plan_digest,
            report_digest=report.report_digest,
            entries=entries,
            matrix_digest=canonical_sha256_digest(payload),
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "qualification_disclosure_matrix@1",
            "plan_digest": self.plan_digest,
            "report_digest": self.report_digest,
            "entries": [item.to_dict() for item in self.entries],
            "matrix_digest": self.matrix_digest,
        }


class RejectingQualificationCredentialResolver:
    """Non-live resolver that proves credential material is unreachable."""

    def __init__(self) -> None:
        self.resolution_attempts: list[tuple[str, str]] = []

    def resolve(
        self,
        *,
        unit: ExternalQualificationUnit,
        locator: QualificationCredentialLocator,
    ) -> object:
        self.resolution_attempts.append((unit.unit_digest, locator.credential_locator_id))
        raise ExternalQualificationError(
            "qualification_credential_resolution_forbidden",
            "credential material resolution is forbidden in non-live readiness",
        )


class RecordingQualificationProbeBackend:
    """Deterministic no-effect backend for qualification control semantics."""

    backend_id = "enzymedesign.recording-qualification-backend@1"

    def __init__(
        self,
        *,
        units: tuple[ExternalQualificationUnit, ...],
        response_loss_unit_digests: frozenset[str] = frozenset(),
        unresolved_unit_digests: frozenset[str] = frozenset(),
        failed_unit_digests: frozenset[str] = frozenset(),
        operation_mismatch_unit_digests: frozenset[str] = frozenset(),
        schema_mismatch_unit_digests: frozenset[str] = frozenset(),
        available_negative_tests: frozenset[str] = frozenset(
            REQUIRED_NEGATIVE_TESTS
        ),
    ) -> None:
        self._units = {item.unit_digest: item for item in units}
        self._response_loss = response_loss_unit_digests
        self._unresolved = unresolved_unit_digests
        self._failed = failed_unit_digests
        self._operation_mismatch = operation_mismatch_unit_digests
        self._schema_mismatch = schema_mismatch_unit_digests
        self._available_negative_tests = available_negative_tests
        self.dispatch_count: dict[str, int] = {}
        self.reconcile_count: dict[str, int] = {}
        self.negative_tests_exercised: list[str] = []

    def dispatch(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationProbeOutcome:
        unit = self._require_request(request)
        self.dispatch_count[request.attempt_id] = (
            self.dispatch_count.get(request.attempt_id, 0) + 1
        )
        if self.dispatch_count[request.attempt_id] != 1:
            raise ExternalQualificationError(
                "qualification_probe_redispatch_forbidden",
                "recording backend observed a duplicate dispatch attempt",
            )
        if unit.unit_digest in self._response_loss:
            return ExternalQualificationProbeOutcome(
                attempt_id=request.attempt_id,
                request_digest=request.request_digest,
                disposition=ExternalQualificationProbeDisposition.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                observed_operation=None,
                output_digest=None,
                observed_result_schema_digest=None,
                backend_receipt_digest=canonical_sha256_digest(
                    {"attempt_id": request.attempt_id, "dispatch_recorded": True}
                ),
                error_code="qualification_probe_response_lost",
            )
        return self._terminal_outcome(request, unit)

    def reconcile(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationProbeOutcome:
        unit = self._require_request(request)
        if self.dispatch_count.get(request.attempt_id) != 1:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_without_dispatch",
                "reconcile requires exactly one prior dispatch",
            )
        self.reconcile_count[request.attempt_id] = (
            self.reconcile_count.get(request.attempt_id, 0) + 1
        )
        if self.reconcile_count[request.attempt_id] != 1:
            raise ExternalQualificationError(
                "qualification_probe_reconcile_repeated",
                "recording backend observed repeated reconcile",
            )
        if unit.unit_digest in self._unresolved:
            return ExternalQualificationProbeOutcome(
                attempt_id=request.attempt_id,
                request_digest=request.request_digest,
                disposition=ExternalQualificationProbeDisposition.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                observed_operation=None,
                output_digest=None,
                observed_result_schema_digest=None,
                backend_receipt_digest=None,
                error_code="qualification_probe_reconcile_unresolved",
            )
        return self._terminal_outcome(request, unit)

    def exercise_negative(self, test_id: str) -> NegativeFixtureResult:
        self.negative_tests_exercised.append(test_id)
        passed = test_id in self._available_negative_tests
        return NegativeFixtureResult(
            test_id=test_id,
            passed=passed,
            external_effect_performed=False,
            credential_material_accessed=False,
            fallback_performed=False,
            fixture_receipt_digest=canonical_sha256_digest(
                {
                    "backend_id": self.backend_id,
                    "test_id": test_id,
                    "passed": passed,
                    "external_effect_performed": False,
                }
            ),
        )

    def _require_request(
        self,
        request: ExternalQualificationProbeRequest,
    ) -> ExternalQualificationUnit:
        try:
            unit = self._units[request.unit_digest]
        except KeyError as exc:
            raise ExternalQualificationError(
                "qualification_probe_unit_unknown",
                "recording backend received an unplanned unit",
            ) from exc
        if (
            request.operation != unit.operation
            or request.expected_result_schema_digest
            != unit.expected_result_schema_digest
            or request.credential_locator_id
            != (
                None
                if unit.credential_locator is None
                else unit.credential_locator.credential_locator_id
            )
        ):
            raise ExternalQualificationError(
                "qualification_probe_request_identity_drift",
                "recording backend request differs from its exact unit",
            )
        return unit

    def _terminal_outcome(
        self,
        request: ExternalQualificationProbeRequest,
        unit: ExternalQualificationUnit,
    ) -> ExternalQualificationProbeOutcome:
        if unit.unit_digest in self._failed:
            return ExternalQualificationProbeOutcome(
                attempt_id=request.attempt_id,
                request_digest=request.request_digest,
                disposition=ExternalQualificationProbeDisposition.FAILED,
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                observed_operation=None,
                output_digest=None,
                observed_result_schema_digest=None,
                backend_receipt_digest=None,
                error_code="qualification_fixture_typed_failure",
            )
        operation = (
            "mismatched-operation"
            if unit.unit_digest in self._operation_mismatch
            else unit.operation
        )
        schema_digest = (
            canonical_sha256_digest({"schema": "mismatched"})
            if unit.unit_digest in self._schema_mismatch
            else unit.expected_result_schema_digest
        )
        result = {
            "operation": operation,
            "subject_id": unit.subject_id,
            "deterministic_result": True,
        }
        return ExternalQualificationProbeOutcome(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            disposition=ExternalQualificationProbeDisposition.SUCCEEDED,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            observed_operation=operation,
            output_digest=canonical_sha256_digest(result),
            observed_result_schema_digest=schema_digest,
            backend_receipt_digest=canonical_sha256_digest(
                {
                    "backend_id": self.backend_id,
                    "attempt_id": request.attempt_id,
                    "request_digest": request.request_digest,
                    "result": result,
                    "external_effect_performed": False,
                    "credential_material_accessed": False,
                }
            ),
        )


class ExternalQualificationReadinessCoordinator:
    def __init__(
        self,
        *,
        probe: ExternalQualificationProbePort,
        negative_fixtures: QualificationNegativeFixturePort,
    ) -> None:
        self._probe = probe
        self._negative_fixtures = negative_fixtures
        self.private_diagnostics: list[PrivateQualificationDiagnostic] = []

    def execute(
        self,
        plan: ExternalQualificationPlan,
        *,
        observed_at: str,
        validity_seconds: int = 3600,
    ) -> ExternalQualificationReadinessReport:
        if plan.live_allowed:
            raise ExternalQualificationError(
                "qualification_readiness_live_plan_forbidden",
                "non-live coordinator rejects live-enabled plans",
            )
        if not isinstance(validity_seconds, int) or not 1 <= validity_seconds <= 86400:
            raise ValueError("validity_seconds must be in [1, 86400]")
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        if observed.tzinfo is None or observed.utcoffset() is None:
            raise ValueError("observed_at must include an explicit timezone")
        valid_until = (observed + timedelta(seconds=validity_seconds)).isoformat()
        negative_tests = tuple(
            sorted(
                {
                    test_id
                    for profile in plan.profiles
                    for test_id in profile.required_negative_tests
                }
            )
        )
        negative_results = tuple(
            self._negative_fixtures.exercise_negative(test_id)
            for test_id in negative_tests
        )
        negative_ok = all(
            item.passed
            and not item.external_effect_performed
            and not item.credential_material_accessed
            and not item.fallback_performed
            for item in negative_results
        )
        receipts: list[ExternalQualificationReadinessReceipt] = []
        failures: list[ExternalQualificationFailure] = []
        for index, unit in enumerate(plan.units):
            request = ExternalQualificationProbeRequest.create(
                attempt_id=f"{plan.plan_id}.attempt.{index + 1}",
                plan_digest=plan.plan_digest,
                unit_digest=unit.unit_digest,
                operation=unit.operation,
                timeout_seconds=30,
                input_digest=canonical_sha256_digest(
                    {
                        "fixture_schema": "qualification_fixture@1",
                        "unit_digest": unit.unit_digest,
                    }
                ),
                expected_result_schema_digest=unit.expected_result_schema_digest,
                credential_locator_id=(
                    None
                    if unit.credential_locator is None
                    else unit.credential_locator.credential_locator_id
                ),
            )
            try:
                outcome = self._probe.dispatch(request)
                if (
                    outcome.disposition
                    is ExternalQualificationProbeDisposition.RECONCILE_REQUIRED
                ):
                    outcome = self._probe.reconcile(request)
                self._validate_outcome(request, unit, outcome)
                if not negative_ok:
                    raise ExternalQualificationError(
                        "qualification_negative_fixture_incomplete",
                        "one or more required negative fixtures did not pass",
                    )
                receipt = ExternalQualificationReadinessReceipt.create(
                    receipt_id=f"{plan.plan_id}.receipt.{index + 1}",
                    plan_digest=plan.plan_digest,
                    unit_digest=unit.unit_digest,
                    status=ExternalQualificationReadinessStatus.READY_NON_LIVE,
                    backend_id=getattr(
                        self._probe,
                        "backend_id",
                        "external-qualification-probe",
                    ),
                    fixture_id=f"fixture.{unit.component_id}.{unit.operation}@1",
                    observed_operation=outcome.observed_operation,
                    expected_result_schema_digest=unit.expected_result_schema_digest,
                    observed_result_schema_digest=(
                        outcome.observed_result_schema_digest
                    ),
                    backend_receipt_digest=outcome.backend_receipt_digest,
                    negative_tests=negative_tests,
                    diagnostic_id=f"diagnostic.{plan.plan_id}.{index + 1}",
                    effect_certainty=outcome.effect_certainty,
                    external_effect_performed=outcome.external_effect_performed,
                    credential_material_accessed=outcome.credential_material_accessed,
                    fallback_performed=outcome.fallback_performed,
                    observed_at=observed_at,
                    valid_until=valid_until,
                )
                receipts.append(receipt)
            except Exception as exc:
                diagnostic_id = f"diagnostic.{plan.plan_id}.{index + 1}"
                error_code = getattr(
                    exc,
                    "error_code",
                    "qualification_probe_failed",
                )
                safe_summary = sanitize_public_diagnostic_text(str(exc))
                failures.append(
                    ExternalQualificationFailure(
                        error_code=error_code,
                        component=unit.component_id,
                        phase="nonlive-probe",
                        diagnostic_id=diagnostic_id,
                        plan_digest=plan.plan_digest,
                        unit_digest=unit.unit_digest,
                        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                        mutation_applied=False,
                        fallback_performed=False,
                        retry_policy="none",
                        reconcile_policy="same-attempt-only",
                        operator_action="inspect-private-diagnostic",
                        safe_summary=safe_summary,
                    )
                )
                self.private_diagnostics.append(
                    PrivateQualificationDiagnostic(
                        diagnostic_id=diagnostic_id,
                        error_code=error_code,
                        cause_type=type(exc).__name__,
                        bounded_context=str(exc)[:4096],
                    )
                )
        lifecycle = (
            ExternalQualificationLifecycle.READY_NON_LIVE
            if not failures and len(receipts) == len(plan.units)
            else ExternalQualificationLifecycle.RUNTIME_MOUNTED
        )
        return ExternalQualificationReadinessReport.create(
            report_id=f"{plan.plan_id}.report",
            plan_digest=plan.plan_digest,
            receipts=tuple(receipts),
            failures=tuple(failures),
            verified_at=observed_at,
            lifecycle_claim=lifecycle,
            external_effect_performed=False,
            credential_material_accessed=False,
            fallback_performed=False,
        )

    @staticmethod
    def _validate_outcome(
        request: ExternalQualificationProbeRequest,
        unit: ExternalQualificationUnit,
        outcome: ExternalQualificationProbeOutcome,
    ) -> None:
        if outcome.attempt_id != request.attempt_id or (
            outcome.request_digest != request.request_digest
        ):
            raise ExternalQualificationError(
                "qualification_probe_attempt_mismatch",
                "probe outcome differs from its exact attempt",
            )
        if outcome.disposition is not ExternalQualificationProbeDisposition.SUCCEEDED:
            raise ExternalQualificationError(
                outcome.error_code or "qualification_probe_unsettled",
                "qualification probe did not settle successfully",
            )
        if outcome.observed_operation != unit.operation:
            raise ExternalQualificationError(
                "qualification_operation_mismatch",
                "probe observed a different operation",
            )
        if (
            outcome.observed_result_schema_digest
            != unit.expected_result_schema_digest
            or outcome.output_digest is None
            or outcome.backend_receipt_digest is None
        ):
            raise ExternalQualificationError(
                "qualification_schema_mismatch",
                "probe result differs from its exact schema",
            )
        if (
            outcome.effect_certainty is not ExternalEffectCertainty.NO_EFFECT
            or outcome.external_effect_performed
            or outcome.credential_material_accessed
            or outcome.fallback_performed
        ):
            raise ExternalQualificationError(
                "qualification_non_live_policy_violated",
                "non-live probe reported effect, credential access or fallback",
            )


__all__ = [
    "ExternalQualificationProbePort",
    "ExternalQualificationReadinessCoordinator",
    "NegativeFixtureResult",
    "PrivateQualificationDiagnostic",
    "QualificationCredentialResolverPort",
    "QualificationDisclosureEntry",
    "QualificationDisclosureMatrix",
    "QualificationNegativeFixturePort",
    "RecordingQualificationProbeBackend",
    "RejectingQualificationCredentialResolver",
]
