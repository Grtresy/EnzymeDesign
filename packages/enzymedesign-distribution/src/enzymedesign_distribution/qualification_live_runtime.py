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
from openzyme_contracts import verify_external_qualification_occurrence_authorization
from openzyme_contracts import verify_external_qualification_probe_request_binding

from .external_qualification import REQUIRED_NEGATIVE_TESTS
from .qualification_bridges import SelectedQualificationProbeRouter
from .qualification_bridges import build_external_qualification_probe_request
from .qualification_bridges import external_qualification_live_input_digest
from .qualification_planning import QualificationBudgetLedger


class LiveQualificationLedgerPort(Protocol):
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


class LiveQualificationCleanupPort(Protocol):
    def cleanup(self) -> Mapping[str, dict[str, object]]: ...


@dataclass(frozen=True, slots=True)
class LiveQualificationExecutionReport:
    dry_plan_digest: str
    authorization_digest: str
    negative_test_receipt_digest: str
    outcomes: tuple[tuple[str, ExternalQualificationProbeOutcome], ...]
    receipts: tuple[ExternalQualificationSafeReceipt, ...]
    cleanup_receipt_digest: str
    report_digest: str

    @classmethod
    def create(cls, **values):
        payload = {
            "schema_version": "external_live_qualification_execution_report@1",
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
        }
        return cls(**values, report_digest=canonical_sha256_digest(payload))

    @property
    def qualified(self) -> bool:
        return bool(self.receipts) and len(self.receipts) == len(self.outcomes)

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": "external_live_qualification_execution_report@1",
            "dry_plan_digest": self.dry_plan_digest,
            "authorization_digest": self.authorization_digest,
            "negative_test_receipt_digest": self.negative_test_receipt_digest,
            "outcomes": [
                {"unit_digest": unit_digest, "outcome": outcome.to_dict()}
                for unit_digest, outcome in self.outcomes
            ],
            "receipts": [item.to_dict() for item in self.receipts],
            "cleanup_receipt_digest": self.cleanup_receipt_digest,
            "qualified": self.qualified,
            "cutover": False,
            "report_digest": self.report_digest,
        }


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
    dry_plan: ExternalQualificationDryPlan
    readiness_plan: ExternalQualificationPlan
    authorization: ExternalQualificationOccurrenceAuthorization
    operator_id: str
    router: SelectedQualificationProbeRouter = field(repr=False)
    ledger: LiveQualificationLedgerPort = field(repr=False)
    cleanup_port: LiveQualificationCleanupPort = field(repr=False)
    revocation: ExternalQualificationAuthorizationRevocation | None = None

    def execute(self, *, observed_at: str) -> LiveQualificationExecutionReport:
        verify_external_qualification_occurrence_authorization(
            self.dry_plan,
            self.authorization,
            observed_at=observed_at,
            expected_operator_id=self.operator_id,
            revocation=self.revocation,
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
        selected_unit_digests = {
            item.unit_digest for item in self.dry_plan.unit_bindings
        }
        if len(restored) == len(selected_unit_digests) and len(
            restored_receipts
        ) == len(selected_unit_digests):
            cleanup_digests = {item.cleanup_receipt_digest for item in restored_receipts}
            negative_digests = {
                item.negative_test_receipt_digest for item in restored_receipts
            }
            if len(cleanup_digests) != 1 or negative_digests != {negative_digest}:
                raise ExternalQualificationError(
                    "qualification_restored_receipt_closure_drift",
                    "persisted qualification receipt closure is inconsistent",
                )
            return LiveQualificationExecutionReport.create(
                dry_plan_digest=self.dry_plan.dry_plan_digest,
                authorization_digest=self.authorization.authorization_digest,
                negative_test_receipt_digest=negative_digest,
                outcomes=tuple(sorted(restored.items())),
                receipts=tuple(
                    sorted(restored_receipts, key=lambda item: item.unit_digest)
                ),
                cleanup_receipt_digest=next(iter(cleanup_digests)),
            )
        units = tuple(
            sorted(
                (
                    item
                    for item in self.readiness_plan.units
                    if item.unit_digest in selected_unit_digests
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
        settlements: dict[str, str] = {}
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
                settlements[unit.unit_digest] = canonical_sha256_digest(
                    {
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
                )
        finally:
            cleanup_payload = dict(self.cleanup_port.cleanup())
        cleanup_digest = canonical_sha256_digest(
            {
                "schema_version": "external_live_qualification_cleanup@1",
                "dry_plan_digest": self.dry_plan.dry_plan_digest,
                "resources": cleanup_payload,
            }
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
                budget_settlement_digest=settlements[unit.unit_digest],
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
            dry_plan_digest=self.dry_plan.dry_plan_digest,
            authorization_digest=self.authorization.authorization_digest,
            negative_test_receipt_digest=negative_digest,
            outcomes=tuple(sorted(outcomes.items())),
            receipts=tuple(sorted(receipts, key=lambda item: item.unit_digest)),
            cleanup_receipt_digest=cleanup_digest,
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
    required = checks.get(unit.component_id)
    if required is None:
        return True
    payload = cleanup_payload.get(unit.component_id)
    return payload is not None and all(payload.get(field_name) is True for field_name in required)


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
    "LiveQualificationLedgerPort",
    "exercise_live_qualification_negative_gate",
]
