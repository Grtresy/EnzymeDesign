from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from datetime import timedelta
from typing import Mapping
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationAuthorizationRevocation
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationSafeReceipt
from openzyme_contracts import ExternalQualificationUnit
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import verify_external_qualification_occurrence_authorization
from openzyme_contracts import verify_external_qualification_probe_request_binding

from .external_qualification import REQUIRED_NEGATIVE_TESTS
from .qualification_bridges import SelectedQualificationProbeRouter
from .qualification_bridges import build_external_qualification_probe_request
from .qualification_bridges import external_qualification_live_input_digest
from .qualification_planning import QualificationBudgetLedger


class LiveQualificationLedgerPort(Protocol):
    def record_occurrence_scope(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        source_identity_digest: str,
        unit_digests: tuple[str, ...],
    ) -> None: ...

    def restore_occurrence_scope(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[str, tuple[str, ...]] | None: ...

    def restore_occurrence_scopes_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> Mapping[str, tuple[str, tuple[str, ...]]]: ...

    def record_probe_outcome(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        unit_digest: str,
        outcome: ExternalQualificationProbeOutcome,
    ) -> None: ...

    def restore_probe_outcomes(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[tuple[str, ExternalQualificationProbeOutcome], ...]: ...

    def record_safe_receipts(
        self, receipts: tuple[ExternalQualificationSafeReceipt, ...]
    ) -> None: ...

    def restore_safe_receipts(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> tuple[ExternalQualificationSafeReceipt, ...]: ...

    def restore_safe_receipts_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> tuple[ExternalQualificationSafeReceipt, ...]: ...

    def record_occurrence_evidence(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
        cleanup_receipt_digest: str,
        cleanup_resources: Mapping[str, dict[str, object]],
        budget_settlements: Mapping[str, dict[str, object]],
    ) -> None: ...

    def restore_occurrence_evidence(
        self,
        *,
        dry_plan_digest: str,
        authorization_digest: str,
    ) -> Mapping[str, object] | None: ...

    def restore_occurrence_evidence_for_dry_plan(
        self,
        *,
        dry_plan_digest: str,
    ) -> Mapping[str, Mapping[str, object]]: ...


class LiveQualificationCleanupPort(Protocol):
    def cleanup(self) -> Mapping[str, dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class LiveQualificationExecutionReport:
    source_identity_digest: str
    dry_plan_digest: str
    authorization_digest: str
    negative_test_receipt_digest: str
    outcomes: tuple[tuple[str, ExternalQualificationProbeOutcome], ...]
    receipts: tuple[ExternalQualificationSafeReceipt, ...]
    cleanup_receipt_digest: str
    cleanup_resources: Mapping[str, dict[str, object]]
    budget_settlements: Mapping[str, dict[str, object]]
    selected_unit_digests: tuple[str, ...]
    planned_unit_count: int
    report_digest: str

    @classmethod
    def create(cls, **values):
        payload = {
            "schema_version": "external_live_qualification_execution_report@3",
            "source_identity_digest": values["source_identity_digest"],
            "dry_plan_digest": values["dry_plan_digest"],
            "authorization_digest": values["authorization_digest"],
            "negative_test_receipt_digest": values[
                "negative_test_receipt_digest"
            ],
            "outcomes": [
                {"unit_digest": unit_digest, "outcome": outcome.to_dict()}
                for unit_digest, outcome in values["outcomes"]
            ],
            "receipts": [item.to_dict() for item in values["receipts"]],
            "cleanup_receipt_digest": values["cleanup_receipt_digest"],
            "cleanup_resources": values["cleanup_resources"],
            "budget_settlements": values["budget_settlements"],
            "selected_unit_digests": list(values["selected_unit_digests"]),
            "planned_unit_count": values["planned_unit_count"],
        }
        return cls(**values, report_digest=canonical_sha256_digest(payload))

    @property
    def occurrence_qualified(self) -> bool:
        return bool(self.receipts) and len(self.receipts) == len(self.outcomes)

    @property
    def qualified(self) -> bool:
        return (
            self.occurrence_qualified
            and len(self.selected_unit_digests) == self.planned_unit_count
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "external_live_qualification_execution_report@3",
            "source_identity_digest": self.source_identity_digest,
            "dry_plan_digest": self.dry_plan_digest,
            "authorization_digest": self.authorization_digest,
            "negative_test_receipt_digest": self.negative_test_receipt_digest,
            "outcomes": [
                {"unit_digest": unit_digest, "outcome": outcome.to_dict()}
                for unit_digest, outcome in self.outcomes
            ],
            "receipts": [item.to_dict() for item in self.receipts],
            "cleanup_receipt_digest": self.cleanup_receipt_digest,
            "cleanup_resources": self.cleanup_resources,
            "budget_settlements": self.budget_settlements,
            "selected_unit_digests": list(self.selected_unit_digests),
            "planned_unit_count": self.planned_unit_count,
            "occurrence_qualified": self.occurrence_qualified,
            "qualified": self.qualified,
            "cutover": False,
            "report_digest": self.report_digest,
        }


@dataclass(frozen=True, slots=True)
class LiveQualificationReceiptSetReport:
    source_identity_digest: str
    dry_plan_digest: str
    verified_at: str
    selected_receipts: tuple[ExternalQualificationSafeReceipt, ...]
    missing_unit_digests: tuple[str, ...]
    rejected_receipts: tuple[tuple[str, str], ...]
    authorization_digests: tuple[str, ...]
    report_digest: str

    @classmethod
    def create(cls, **values):
        selected_receipts = tuple(
            sorted(values["selected_receipts"], key=lambda item: item.unit_digest)
        )
        missing_unit_digests = tuple(sorted(values["missing_unit_digests"]))
        rejected_receipts = tuple(sorted(values["rejected_receipts"]))
        authorization_digests = tuple(sorted(values["authorization_digests"]))
        payload = {
            "schema_version": "external_live_qualification_receipt_set@1",
            "source_identity_digest": values["source_identity_digest"],
            "dry_plan_digest": values["dry_plan_digest"],
            "verified_at": values["verified_at"],
            "selected_receipts": [item.to_dict() for item in selected_receipts],
            "missing_unit_digests": list(missing_unit_digests),
            "rejected_receipts": [
                {"receipt_digest": digest, "error_code": error_code}
                for digest, error_code in rejected_receipts
            ],
            "authorization_digests": list(authorization_digests),
        }
        return cls(
            source_identity_digest=values["source_identity_digest"],
            dry_plan_digest=values["dry_plan_digest"],
            verified_at=values["verified_at"],
            selected_receipts=selected_receipts,
            missing_unit_digests=missing_unit_digests,
            rejected_receipts=rejected_receipts,
            authorization_digests=authorization_digests,
            report_digest=canonical_sha256_digest(payload),
        )

    @property
    def qualified(self) -> bool:
        return bool(self.selected_receipts) and not self.missing_unit_digests

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "external_live_qualification_receipt_set@1",
            "source_identity_digest": self.source_identity_digest,
            "dry_plan_digest": self.dry_plan_digest,
            "verified_at": self.verified_at,
            "selected_receipts": [item.to_dict() for item in self.selected_receipts],
            "missing_unit_digests": list(self.missing_unit_digests),
            "rejected_receipts": [
                {"receipt_digest": digest, "error_code": error_code}
                for digest, error_code in self.rejected_receipts
            ],
            "authorization_digests": list(self.authorization_digests),
            "qualified": self.qualified,
            "cutover": False,
            "report_digest": self.report_digest,
        }


def bind_live_qualification_occurrence_scope(
    *,
    dry_plan: ExternalQualificationDryPlan,
    authorization: ExternalQualificationOccurrenceAuthorization,
    ledger: LiveQualificationLedgerPort,
    source_identity_digest: str,
    selected_unit_digests: tuple[str, ...] | None,
) -> tuple[str, ...]:
    planned_unit_digests = {
        item.unit_digest for item in dry_plan.unit_bindings
    }
    selected = tuple(
        sorted(
            planned_unit_digests
            if selected_unit_digests is None
            else selected_unit_digests
        )
    )
    if (
        not selected
        or len(set(selected)) != len(selected)
        or not set(selected).issubset(planned_unit_digests)
    ):
        raise ExternalQualificationError(
            "qualification_occurrence_scope_invalid",
            "qualification occurrence scope must be a non-empty dry-plan subset",
        )
    require_digest(source_identity_digest, field_name="source_identity_digest")
    restored_scope = ledger.restore_occurrence_scope(
        dry_plan_digest=dry_plan.dry_plan_digest,
        authorization_digest=authorization.authorization_digest,
    )
    if restored_scope is None:
        ledger.record_occurrence_scope(
            dry_plan_digest=dry_plan.dry_plan_digest,
            authorization_digest=authorization.authorization_digest,
            source_identity_digest=source_identity_digest,
            unit_digests=selected,
        )
        restored_scope = ledger.restore_occurrence_scope(
            dry_plan_digest=dry_plan.dry_plan_digest,
            authorization_digest=authorization.authorization_digest,
        )
    if restored_scope != (source_identity_digest, selected):
        raise ExternalQualificationError(
            "qualification_occurrence_scope_drift",
            "persisted qualification occurrence scope differs from the request",
        )
    return selected


def verify_live_qualification_receipt_set(
    *,
    dry_plan: ExternalQualificationDryPlan,
    readiness_plan: ExternalQualificationPlan,
    source_identity_digest: str,
    operator_id: str,
    authorizations: tuple[ExternalQualificationOccurrenceAuthorization, ...],
    ledger: LiveQualificationLedgerPort,
    verified_at: str,
) -> LiveQualificationReceiptSetReport:
    verified_time = datetime.fromisoformat(verified_at.replace("Z", "+00:00"))
    planned_unit_digests = {
        item.unit_digest for item in dry_plan.unit_bindings
    }
    units = {
        item.unit_digest: item
        for item in readiness_plan.units
        if item.unit_digest in planned_unit_digests
    }
    if set(units) != planned_unit_digests:
        raise ExternalQualificationError(
            "qualification_receipt_set_plan_coverage_drift",
            "readiness plan does not cover the exact dry-plan unit set",
        )
    bindings = {item.unit_digest: item for item in dry_plan.unit_bindings}
    authorization_by_digest: dict[
        str, ExternalQualificationOccurrenceAuthorization
    ] = {}
    for authorization in authorizations:
        if authorization.authorization_digest in authorization_by_digest:
            raise ExternalQualificationError(
                "qualification_receipt_set_authorization_duplicate",
                "receipt-set authorization digests must be unique",
            )
        verify_external_qualification_occurrence_authorization(
            dry_plan,
            authorization,
            observed_at=verified_at,
            expected_operator_id=operator_id,
        )
        authorization_by_digest[authorization.authorization_digest] = authorization
    occurrence_evidence = ledger.restore_occurrence_evidence_for_dry_plan(
        dry_plan_digest=dry_plan.dry_plan_digest
    )
    occurrence_scopes = ledger.restore_occurrence_scopes_for_dry_plan(
        dry_plan_digest=dry_plan.dry_plan_digest
    )
    candidates: dict[str, list[ExternalQualificationSafeReceipt]] = {}
    rejected: list[tuple[str, str]] = []
    for receipt in ledger.restore_safe_receipts_for_dry_plan(
        dry_plan_digest=dry_plan.dry_plan_digest
    ):
        error_code: str | None = None
        unit = units.get(receipt.unit_digest)
        binding = bindings.get(receipt.unit_digest)
        authorization = authorization_by_digest.get(receipt.authorization_digest)
        evidence = occurrence_evidence.get(receipt.authorization_digest)
        raw_scope = occurrence_scopes.get(receipt.authorization_digest)
        scope_source_identity_digest = None if raw_scope is None else raw_scope[0]
        scope = None if raw_scope is None else raw_scope[1]
        if unit is None or binding is None:
            error_code = "qualification_receipt_set_unknown_unit"
        elif authorization is None:
            error_code = "qualification_receipt_set_authorization_missing"
        elif scope is None or receipt.unit_digest not in scope:
            error_code = "qualification_receipt_set_scope_missing"
        elif scope_source_identity_digest != source_identity_digest:
            error_code = "qualification_receipt_set_source_identity_drift"
        elif evidence is None:
            error_code = "qualification_receipt_set_occurrence_evidence_missing"
        elif (
            receipt.component_id != unit.component_id
            or receipt.route_id != unit.route_id
            or receipt.operation != unit.operation
            or receipt.subject_digest != binding.subject_digest
            or receipt.expected_result_schema_digest
            != unit.expected_result_schema_digest
            or receipt.observed_result_schema_digest
            != unit.expected_result_schema_digest
        ):
            error_code = "qualification_receipt_set_binding_drift"
        else:
            observed_time = datetime.fromisoformat(
                receipt.observed_at.replace("Z", "+00:00")
            )
            authorized_time = datetime.fromisoformat(
                authorization.authorized_at.replace("Z", "+00:00")
            )
            valid_until = datetime.fromisoformat(
                receipt.valid_until.replace("Z", "+00:00")
            )
            if (
                observed_time < authorized_time
                or observed_time > verified_time
                or valid_until <= verified_time
            ):
                error_code = "qualification_receipt_set_expired_or_future"
        if error_code is None:
            assert evidence is not None
            assert scope is not None
            cleanup_resources = evidence.get("cleanup_resources")
            settlements = evidence.get("budget_settlements")
            settlement = (
                settlements.get(receipt.unit_digest)
                if isinstance(settlements, Mapping)
                else None
            )
            if (
                not set(scope).issubset(planned_unit_digests)
                or not isinstance(settlements, Mapping)
                or set(settlements) != set(scope)
                or evidence.get("dry_plan_digest") != dry_plan.dry_plan_digest
                or evidence.get("authorization_digest")
                != receipt.authorization_digest
            ):
                error_code = "qualification_receipt_set_occurrence_scope_drift"
            elif (
                evidence.get("cleanup_receipt_digest")
                != receipt.cleanup_receipt_digest
                or not isinstance(cleanup_resources, Mapping)
                or not _unit_cleanup_ok(unit, cleanup_resources)
            ):
                error_code = "qualification_receipt_set_cleanup_drift"
            elif not isinstance(settlement, Mapping) or canonical_sha256_digest(
                dict(settlement)
            ) != receipt.budget_settlement_digest:
                error_code = "qualification_receipt_set_budget_drift"
            elif exercise_live_qualification_negative_gate(
                dry_plan=dry_plan,
                readiness_plan=readiness_plan,
                authorization=authorization,
                operator_id=operator_id,
                observed_at=receipt.observed_at,
            ) != receipt.negative_test_receipt_digest:
                error_code = "qualification_receipt_set_negative_gate_drift"
        if error_code is not None:
            rejected.append((receipt.receipt_digest, error_code))
            continue
        candidates.setdefault(receipt.unit_digest, []).append(receipt)
    selected: list[ExternalQualificationSafeReceipt] = []
    for unit_digest in sorted(planned_unit_digests):
        unit_candidates = candidates.get(unit_digest, ())
        if unit_candidates:
            selected.append(
                max(
                    unit_candidates,
                    key=lambda item: (
                        datetime.fromisoformat(
                            item.observed_at.replace("Z", "+00:00")
                        ),
                        item.receipt_digest,
                    ),
                )
            )
    selected_units = {item.unit_digest for item in selected}
    return LiveQualificationReceiptSetReport.create(
        source_identity_digest=source_identity_digest,
        dry_plan_digest=dry_plan.dry_plan_digest,
        verified_at=verified_at,
        selected_receipts=tuple(selected),
        missing_unit_digests=tuple(sorted(planned_unit_digests - selected_units)),
        rejected_receipts=tuple(rejected),
        authorization_digests=tuple(
            sorted({item.authorization_digest for item in selected})
        ),
    )


def exercise_live_qualification_negative_gate(
    *,
    dry_plan: ExternalQualificationDryPlan,
    readiness_plan: ExternalQualificationPlan,
    authorization: ExternalQualificationOccurrenceAuthorization,
    operator_id: str,
    observed_at: str,
) -> str:
    required = {
        test_id
        for profile in readiness_plan.profiles
        for test_id in profile.required_negative_tests
    }
    if required != set(REQUIRED_NEGATIVE_TESTS) or dry_plan.max_retries != 0:
        raise ExternalQualificationError(
            "qualification_negative_gate_policy_drift",
            "live qualification negative-test or retry policy drifted",
        )
    failures: dict[str, str] = {}
    try:
        verify_external_qualification_occurrence_authorization(
            dry_plan,
            None,
            observed_at=observed_at,
            expected_operator_id=operator_id,
        )
    except ExternalQualificationError as exc:
        failures["auth.failure"] = exc.error_code
    else:
        raise AssertionError("missing authorization negative gate did not fail")
    selected_unit_digests = {item.unit_digest for item in dry_plan.unit_bindings}
    unit = next(
        item for item in readiness_plan.units if item.unit_digest in selected_unit_digests
    )
    subject = next(
        item for item in dry_plan.unit_bindings if item.unit_digest == unit.unit_digest
    )
    if subject.subject_digest is None:
        raise ExternalQualificationError(
            "blocked_identity",
            "negative gate requires one resolved exact unit",
        )
    binding = ExternalQualificationBridgeBinding.create(
        component_id=unit.component_id,
        operation=unit.operation,
        route_id=unit.route_id,
        plan_digest=dry_plan.dry_plan_digest,
        unit_digest=unit.unit_digest,
        subject_digest=subject.subject_digest,
        input_digest=external_qualification_live_input_digest(
            dry_plan_digest=dry_plan.dry_plan_digest,
            unit_digest=unit.unit_digest,
        ),
        expected_result_schema_digest=unit.expected_result_schema_digest,
        authorization_digest=authorization.authorization_digest,
        credential_locator_id=subject.credential_locator_id,
    )
    valid = build_external_qualification_probe_request(
        dry_plan=dry_plan,
        readiness_unit=unit,
        attempt_id="negative-gate.identity",
        timeout_seconds=30,
    )
    for test_id, request in (
        (
            "operation.mismatch",
            ExternalQualificationProbeRequest.create(
                attempt_id="negative-gate.operation",
                plan_digest=valid.plan_digest,
                unit_digest=valid.unit_digest,
                operation="unauthorized-operation",
                timeout_seconds=valid.timeout_seconds,
                input_digest=valid.input_digest,
                expected_result_schema_digest=valid.expected_result_schema_digest,
                credential_locator_id=valid.credential_locator_id,
            ),
        ),
        (
            "schema.mismatch",
            ExternalQualificationProbeRequest.create(
                attempt_id="negative-gate.schema",
                plan_digest=valid.plan_digest,
                unit_digest=valid.unit_digest,
                operation=valid.operation,
                timeout_seconds=valid.timeout_seconds,
                input_digest=valid.input_digest,
                expected_result_schema_digest=canonical_sha256_digest(
                    {"negative": "schema-mismatch"}
                ),
                credential_locator_id=valid.credential_locator_id,
            ),
        ),
    ):
        try:
            verify_external_qualification_probe_request_binding(binding, request)
        except ExternalQualificationError as exc:
            failures[test_id] = exc.error_code
        else:
            raise AssertionError(f"{test_id} negative gate did not fail")
    try:
        ExternalQualificationProbeRequest.create(
            attempt_id="negative-gate.timeout",
            plan_digest=valid.plan_digest,
            unit_digest=valid.unit_digest,
            operation=valid.operation,
            timeout_seconds=0,
            input_digest=valid.input_digest,
            expected_result_schema_digest=valid.expected_result_schema_digest,
            credential_locator_id=valid.credential_locator_id,
        )
    except ValueError:
        failures["timeout.before.effect"] = "qualification_timeout_rejected"
    else:
        raise AssertionError("timeout-before-effect negative gate did not fail")
    response_loss_units = tuple(
        sorted(
            item.unit_digest
            for item in readiness_plan.units
            if item.unit_digest in selected_unit_digests
            if item.operation in {"response-loss-reconcile", "reconcile"}
        )
    )
    if not response_loss_units:
        raise ExternalQualificationError(
            "qualification_response_loss_fixture_missing",
            "live plan lacks an exact same-attempt response-loss unit",
        )
    failures["response.loss"] = "planned_same_attempt_reconcile"
    return canonical_sha256_digest(
        {
            "schema_version": "external_live_qualification_negative_gate@1",
            "dry_plan_digest": dry_plan.dry_plan_digest,
            "authorization_digest": authorization.authorization_digest,
            "operator_id": operator_id,
            "checks": failures,
            "response_loss_unit_digests": list(response_loss_units),
            "external_effect_performed": False,
            "credential_material_accessed": False,
            "fallback_performed": False,
        }
    )


@dataclass(slots=True)
class ExternalLiveQualificationCoordinator:
    source_identity_digest: str
    dry_plan: ExternalQualificationDryPlan
    readiness_plan: ExternalQualificationPlan
    authorization: ExternalQualificationOccurrenceAuthorization
    operator_id: str
    router: SelectedQualificationProbeRouter = field(repr=False)
    ledger: LiveQualificationLedgerPort = field(repr=False)
    cleanup_port: LiveQualificationCleanupPort = field(repr=False)
    revocation: ExternalQualificationAuthorizationRevocation | None = None

    def execute(
        self,
        *,
        observed_at: str,
        selected_unit_digests: tuple[str, ...] | None = None,
    ) -> LiveQualificationExecutionReport:
        verify_external_qualification_occurrence_authorization(
            self.dry_plan,
            self.authorization,
            observed_at=observed_at,
            expected_operator_id=self.operator_id,
            revocation=self.revocation,
        )
        planned_unit_digests = {
            item.unit_digest for item in self.dry_plan.unit_bindings
        }
        selected = bind_live_qualification_occurrence_scope(
            dry_plan=self.dry_plan,
            authorization=self.authorization,
            ledger=self.ledger,
            source_identity_digest=self.source_identity_digest,
            selected_unit_digests=selected_unit_digests,
        )
        negative_digest = exercise_live_qualification_negative_gate(
            dry_plan=self.dry_plan,
            readiness_plan=self.readiness_plan,
            authorization=self.authorization,
            operator_id=self.operator_id,
            observed_at=observed_at,
        )
        restored = dict(
            self.ledger.restore_probe_outcomes(
                dry_plan_digest=self.dry_plan.dry_plan_digest,
                authorization_digest=self.authorization.authorization_digest,
            )
        )
        restored_receipts = self.ledger.restore_safe_receipts(
            dry_plan_digest=self.dry_plan.dry_plan_digest,
            authorization_digest=self.authorization.authorization_digest,
        )
        selected_unit_digest_set = set(selected)
        if not set(restored).issubset(selected_unit_digest_set) or any(
            item.unit_digest not in selected_unit_digest_set
            for item in restored_receipts
        ):
            raise ExternalQualificationError(
                "qualification_occurrence_scope_drift",
                "persisted outcomes or receipts escape the occurrence scope",
            )
        if len(restored) == len(selected_unit_digest_set) and len(
            restored_receipts
        ) == len(selected_unit_digest_set):
            occurrence_evidence = self.ledger.restore_occurrence_evidence(
                dry_plan_digest=self.dry_plan.dry_plan_digest,
                authorization_digest=self.authorization.authorization_digest,
            )
            if occurrence_evidence is None:
                raise ExternalQualificationError(
                    "qualification_restored_occurrence_evidence_missing",
                    "persisted qualification receipts lack occurrence evidence",
                )
            cleanup_digests = {item.cleanup_receipt_digest for item in restored_receipts}
            negative_digests = {
                item.negative_test_receipt_digest for item in restored_receipts
            }
            if len(cleanup_digests) != 1 or negative_digests != {negative_digest}:
                raise ExternalQualificationError(
                    "qualification_restored_receipt_closure_drift",
                    "persisted qualification receipt closure is inconsistent",
                )
            cleanup_digest = next(iter(cleanup_digests))
            if occurrence_evidence.get("cleanup_receipt_digest") != cleanup_digest:
                raise ExternalQualificationError(
                    "qualification_restored_occurrence_evidence_drift",
                    "persisted qualification occurrence evidence has drifted",
                )
            return LiveQualificationExecutionReport.create(
                source_identity_digest=self.source_identity_digest,
                dry_plan_digest=self.dry_plan.dry_plan_digest,
                authorization_digest=self.authorization.authorization_digest,
                negative_test_receipt_digest=negative_digest,
                outcomes=tuple(sorted(restored.items())),
                receipts=tuple(
                    sorted(restored_receipts, key=lambda item: item.unit_digest)
                ),
                cleanup_receipt_digest=cleanup_digest,
                cleanup_resources=occurrence_evidence["cleanup_resources"],
                budget_settlements=occurrence_evidence["budget_settlements"],
                selected_unit_digests=selected,
                planned_unit_count=len(planned_unit_digests),
            )
        units = tuple(
            sorted(
                (
                    item
                    for item in self.readiness_plan.units
                    if item.unit_digest in selected_unit_digest_set
                ),
                key=_unit_execution_key,
            )
        )
        budget_ledger = QualificationBudgetLedger(self.dry_plan.budgets)
        reservations = {
            unit.unit_digest: tuple(
                budget_ledger.reserve(
                    reservation_id=f"reservation.{unit.unit_digest[7:31]}.{budget_id}",
                    budget_id=budget_id,
                    amount=amount,
                )
                for budget_id, amount in _unit_budget_charges(unit)
            )
            for unit in units
        }
        outcomes: dict[str, ExternalQualificationProbeOutcome] = {}
        settlements: dict[str, dict[str, object]] = {}
        try:
            for unit in units:
                request = build_external_qualification_probe_request(
                    dry_plan=self.dry_plan,
                    readiness_unit=unit,
                    attempt_id=(
                        f"qualification.{self.authorization.authorization_digest[7:23]}."
                        f"{unit.unit_digest[7:23]}"
                    ),
                    timeout_seconds=_unit_timeout_seconds(unit),
                )
                outcome = restored.get(unit.unit_digest)
                if outcome is None:
                    outcome = self.router.dispatch(request)
                    self._record(unit, outcome)
                elif outcome.request_digest != request.request_digest:
                    raise ExternalQualificationError(
                        "qualification_restored_request_identity_drift",
                        "persisted qualification outcome differs from the exact request",
                    )
                if unit.unit_digest in restored and _restores_cleanup_context(unit):
                    self.router.restore_dispatched_attempt(request)
                if (
                    outcome.disposition
                    is ExternalQualificationProbeDisposition.RECONCILE_REQUIRED
                ):
                    if unit.unit_digest in restored and not _restores_cleanup_context(
                        unit
                    ):
                        self.router.restore_dispatched_attempt(request)
                    outcome = self.router.reconcile(request)
                    self._record(unit, outcome)
                outcomes[unit.unit_digest] = outcome
                charged = outcome.external_effect_performed
                for reservation in reservations[unit.unit_digest]:
                    budget_ledger.settle(
                        reservation_id=reservation.reservation_id,
                        actual_amount=reservation.amount if charged else 0.0,
                    )
                settlements[unit.unit_digest] = {
                    "unit_digest": unit.unit_digest,
                    "reservations": [
                        {
                            "budget_id": item.budget_id,
                            "reserved": item.amount,
                            "settled": item.amount if charged else 0.0,
                            "warning_crossed": item.warning_crossed,
                        }
                        for item in reservations[unit.unit_digest]
                    ],
                    "max_retries": 0,
                }
        finally:
            cleanup_payload = dict(self.cleanup_port.cleanup())
        cleanup_digest = canonical_sha256_digest(
            {
                "schema_version": "external_live_qualification_cleanup@1",
                "dry_plan_digest": self.dry_plan.dry_plan_digest,
                "resources": cleanup_payload,
            }
        )
        self.ledger.record_occurrence_evidence(
            dry_plan_digest=self.dry_plan.dry_plan_digest,
            authorization_digest=self.authorization.authorization_digest,
            cleanup_receipt_digest=cleanup_digest,
            cleanup_resources=cleanup_payload,
            budget_settlements=settlements,
        )
        receipts: list[ExternalQualificationSafeReceipt] = []
        unit_bindings = {
            item.unit_digest: item for item in self.dry_plan.unit_bindings
        }
        observed = datetime.fromisoformat(observed_at.replace("Z", "+00:00"))
        for unit in units:
            outcome = outcomes[unit.unit_digest]
            if not _successful_terminal_outcome(unit, outcome) or not _unit_cleanup_ok(
                unit, cleanup_payload
            ):
                continue
            ttl = _unit_ttl_seconds(unit)
            binding = unit_bindings[unit.unit_digest]
            assert binding.subject_digest is not None
            receipt = ExternalQualificationSafeReceipt.create(
                receipt_id=f"receipt.{outcome.attempt_id}",
                dry_plan_digest=self.dry_plan.dry_plan_digest,
                unit_digest=unit.unit_digest,
                subject_digest=binding.subject_digest,
                authorization_digest=self.authorization.authorization_digest,
                attempt_id=outcome.attempt_id,
                component_id=unit.component_id,
                route_id=unit.route_id,
                operation=unit.operation,
                backend_receipt_digest=outcome.backend_receipt_digest,
                output_digest=outcome.output_digest,
                expected_result_schema_digest=unit.expected_result_schema_digest,
                observed_result_schema_digest=outcome.observed_result_schema_digest,
                negative_test_receipt_digest=negative_digest,
                budget_settlement_digest=canonical_sha256_digest(
                    settlements[unit.unit_digest]
                ),
                cleanup_receipt_digest=cleanup_digest,
                effect_certainty=outcome.effect_certainty.value,
                fallback_performed=False,
                diagnostic_id=f"diagnostic.{outcome.attempt_id}",
                observed_at=observed_at,
                valid_until=(observed + timedelta(seconds=ttl)).isoformat(),
            )
            receipts.append(receipt)
        self.ledger.record_safe_receipts(tuple(receipts))
        return LiveQualificationExecutionReport.create(
            source_identity_digest=self.source_identity_digest,
            dry_plan_digest=self.dry_plan.dry_plan_digest,
            authorization_digest=self.authorization.authorization_digest,
            negative_test_receipt_digest=negative_digest,
            outcomes=tuple(sorted(outcomes.items())),
            receipts=tuple(sorted(receipts, key=lambda item: item.unit_digest)),
            cleanup_receipt_digest=cleanup_digest,
            cleanup_resources=cleanup_payload,
            budget_settlements=settlements,
            selected_unit_digests=selected,
            planned_unit_count=len(planned_unit_digests),
        )

    def _record(
        self,
        unit: ExternalQualificationUnit,
        outcome: ExternalQualificationProbeOutcome,
    ) -> None:
        self.ledger.record_probe_outcome(
            dry_plan_digest=self.dry_plan.dry_plan_digest,
            authorization_digest=self.authorization.authorization_digest,
            unit_digest=unit.unit_digest,
            outcome=outcome,
        )


def _unit_execution_key(unit: ExternalQualificationUnit) -> tuple[int, int, str]:
    component_order = (
        "openzyme.runtime.llm",
        "enzymedesign.bio-provider-http",
        "openzyme.research.tavily",
        "openzyme.workspace.git.lfs",
        "openzyme.process.podman",
        "openzyme.hpc.ssh",
        "openzyme.hpc.slurm",
        "enzymedesign.hmmer.local",
        "enzymedesign.hmmer.hpc",
        "enzymedesign.vina.local",
        "enzymedesign.vina.hpc",
        "enzymedesign.fpocket.local",
        "enzymedesign.fpocket.hpc",
        "enzymedesign.docking.preprocess",
    )
    operation_order = {
        "clone": 1,
        "checkpoint": 2,
        "publish": 3,
        "lfs-fetch": 4,
        "container-start": 1,
        "mount": 2,
        "create": 3,
        "read": 4,
        "update": 5,
        "delete": 6,
        "exec": 7,
        "timeout": 8,
        "retire": 9,
        "helper-identity": 1,
        "version": 2,
        "submit": 1,
        "observe": 2,
        "cancel": 3,
        "hmmbuild": 1,
        "hmmsearch": 2,
    }
    return (
        component_order.index(unit.component_id),
        operation_order.get(unit.operation, 50),
        unit.unit_digest,
    )


def _unit_budget_charges(unit: ExternalQualificationUnit) -> tuple[tuple[str, float], ...]:
    if unit.component_id == "openzyme.runtime.llm":
        return (
            ("budget.batch-1.cash", 25.0),
            ("budget.llm.cash", 25.0),
            ("budget.llm.requests", 1.0),
        )
    if unit.component_id == "openzyme.research.tavily":
        return (
            ("budget.batch-1.cash", 10.0),
            ("budget.tavily.cash", 10.0),
        )
    if unit.component_id == "openzyme.workspace.git.lfs" and unit.operation == "checkpoint":
        return (("budget.git.payload", 1.0),)
    if unit.component_id == "openzyme.process.podman":
        charges: list[tuple[str, float]] = [("budget.podman.time", 60.0)]
        if unit.operation == "container-start":
            charges.append(("budget.podman.memory", 2048.0))
        return tuple(charges)
    if unit.component_id.endswith((".local",)) or unit.component_id == (
        "enzymedesign.docking.preprocess"
    ):
        return (("budget.podman.time", 120.0),)
    if unit.component_id == "openzyme.hpc.slurm" or unit.component_id.endswith(".hpc"):
        return (("budget.slurm.cpu-time", 10.0),)
    return ()


def _unit_timeout_seconds(unit: ExternalQualificationUnit) -> int:
    if unit.component_id.startswith(("enzymedesign.hmmer", "enzymedesign.vina")):
        return 600
    if unit.component_id.startswith("enzymedesign.fpocket"):
        return 600
    if unit.component_id == "enzymedesign.docking.preprocess":
        return 600
    return 120


def _unit_ttl_seconds(unit: ExternalQualificationUnit) -> int:
    if unit.subject_kind.value == "provider":
        return 24 * 60 * 60
    if unit.component_id.startswith(
        ("enzymedesign.hmmer", "enzymedesign.vina", "enzymedesign.fpocket")
    ) or unit.component_id == "enzymedesign.docking.preprocess":
        return 30 * 24 * 60 * 60
    return 7 * 24 * 60 * 60


def _successful_terminal_outcome(
    unit: ExternalQualificationUnit,
    outcome: ExternalQualificationProbeOutcome,
) -> bool:
    return (
        outcome.disposition is ExternalQualificationProbeDisposition.SUCCEEDED
        and outcome.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
        and outcome.observed_operation == unit.operation
        and outcome.output_digest is not None
        and outcome.backend_receipt_digest is not None
        and outcome.observed_result_schema_digest == unit.expected_result_schema_digest
        and not outcome.fallback_performed
    )


def _unit_cleanup_ok(
    unit: ExternalQualificationUnit,
    cleanup_payload: Mapping[str, dict[str, object]],
) -> bool:
    checks = {
        "openzyme.workspace.git.lfs": ("workspace_removed", "repository_preserved"),
        "openzyme.process.podman": ("container_absent",),
        "openzyme.hpc.ssh": ("workspace_removed",),
        "openzyme.hpc.slurm": ("scheduler_cleanup_attempted", "command_accepted"),
    }
    component_ids: tuple[str, ...]
    if unit.component_id.endswith(".hpc"):
        component_ids = ("openzyme.hpc.ssh", "openzyme.hpc.slurm")
    elif unit.component_id.endswith(".local") or unit.component_id == (
        "enzymedesign.docking.preprocess"
    ):
        component_ids = ("openzyme.process.podman",)
    else:
        component_ids = (unit.component_id,)
    for component_id in component_ids:
        required = checks.get(component_id)
        if required is None:
            continue
        payload = cleanup_payload.get(component_id)
        if payload is None or any(
            payload.get(field_name) is not True for field_name in required
        ):
            return False
    return True


def _restores_cleanup_context(unit: ExternalQualificationUnit) -> bool:
    return (
        unit.component_id == "openzyme.process.podman"
        and unit.operation == "container-start"
    ) or unit.operation == "response-loss-reconcile" or (
        unit.component_id == "openzyme.hpc.slurm" and unit.operation == "reconcile"
    )


__all__ = [
    "ExternalLiveQualificationCoordinator",
    "LiveQualificationCleanupPort",
    "LiveQualificationExecutionReport",
    "LiveQualificationReceiptSetReport",
    "LiveQualificationLedgerPort",
    "bind_live_qualification_occurrence_scope",
    "exercise_live_qualification_negative_gate",
    "verify_live_qualification_receipt_set",
]
