from dataclasses import replace

import pytest

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationEvidence
from openzyme_contracts import ExternalQualificationFailure
from openzyme_contracts import ExternalQualificationLifecycle
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationProfileRef
from openzyme_contracts import ExternalQualificationReadinessReceipt
from openzyme_contracts import ExternalQualificationReadinessReport
from openzyme_contracts import ExternalQualificationReadinessStatus
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import ExternalQualificationUnit
from openzyme_contracts import QualificationCredentialLocator
from openzyme_contracts import adopt_qualified_external_capability
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import verify_external_qualification_readiness


DIGEST = "sha256:" + "1" * 64
OBSERVED_AT = "2026-08-22T00:00:00+00:00"
VALID_UNTIL = "2026-08-23T00:00:00+00:00"
NEGATIVE_TESTS = (
    "auth.failure",
    "operation.mismatch",
    "response.loss",
    "schema.mismatch",
    "timeout.before.effect",
)


def _unit(*, operation: str = "turn") -> ExternalQualificationUnit:
    return ExternalQualificationUnit.create(
        component_id="openzyme.runtime.llm",
        capability_id="openzyme.agent.turn",
        operation=operation,
        route_id="openzyme.runtime.llm.turn@1",
        subject_kind=ExternalQualificationSubjectKind.PROVIDER,
        subject_id="provider.primary",
        source_digest=DIGEST,
        build_digest=DIGEST,
        configuration_digest=DIGEST,
        contract_digest=DIGEST,
        qualification_spec_id="openzyme.runtime.llm.qualification@1",
        qualification_spec_digest=DIGEST,
        validator_id="openzyme.runtime.llm.validator@1",
        expected_result_schema_digest=DIGEST,
        credential_locator=QualificationCredentialLocator(
            credential_slot_id="llm.primary",
            credential_locator_id="credential.llm.primary",
            scope_digest=DIGEST,
        ),
    )


def _plan(unit: ExternalQualificationUnit) -> ExternalQualificationPlan:
    return ExternalQualificationPlan.create(
        plan_id="readiness.plan.1",
        distribution_id="enzymedesign",
        distribution_digest=DIGEST,
        enabled_profiles=("base",),
        profiles=(
            ExternalQualificationProfileRef(
                profile_id="base",
                required=True,
                unit_digests=(unit.unit_digest,),
                required_negative_tests=NEGATIVE_TESTS,
            ),
        ),
        units=(unit,),
        created_at=OBSERVED_AT,
        live_allowed=False,
    )


def _receipt(
    plan: ExternalQualificationPlan,
    unit: ExternalQualificationUnit,
) -> ExternalQualificationReadinessReceipt:
    return ExternalQualificationReadinessReceipt.create(
        receipt_id="readiness.receipt.1",
        plan_digest=plan.plan_digest,
        unit_digest=unit.unit_digest,
        status=ExternalQualificationReadinessStatus.READY_NON_LIVE,
        backend_id="recording.backend@1",
        fixture_id="fixture.llm.turn.success@1",
        observed_operation=unit.operation,
        expected_result_schema_digest=unit.expected_result_schema_digest,
        observed_result_schema_digest=unit.expected_result_schema_digest,
        backend_receipt_digest=canonical_sha256_digest({"attempt": "one"}),
        negative_tests=NEGATIVE_TESTS,
        diagnostic_id="diagnostic.readiness.1",
        effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        external_effect_performed=False,
        credential_material_accessed=False,
        fallback_performed=False,
        observed_at=OBSERVED_AT,
        valid_until=VALID_UNTIL,
    )


def test_readiness_plan_and_report_are_canonical_and_verifiable() -> None:
    unit = _unit()
    plan = _plan(unit)
    receipt = _receipt(plan, unit)
    report = ExternalQualificationReadinessReport.create(
        report_id="readiness.report.1",
        plan_digest=plan.plan_digest,
        receipts=(receipt,),
        failures=(),
        verified_at=OBSERVED_AT,
        lifecycle_claim=ExternalQualificationLifecycle.READY_NON_LIVE,
        external_effect_performed=False,
        credential_material_accessed=False,
        fallback_performed=False,
    )

    verify_external_qualification_readiness(
        plan,
        report,
        verified_at="2026-08-22T12:00:00+00:00",
    )
    assert plan.to_dict()["plan_digest"] == plan.plan_digest
    assert report.to_dict()["lifecycle_claim"] == "ready_non_live"


def test_one_operation_cannot_qualify_another() -> None:
    unit = _unit(operation="turn")
    plan = _plan(unit)
    with pytest.raises(ExternalQualificationError, match="different operation"):
        receipt = _receipt(plan, unit)
        drifted = replace(
            receipt,
            observed_operation="embed",
            receipt_digest=canonical_sha256_digest(
                {
                    **receipt.identity_payload,
                    "observed_operation": "embed",
                }
            ),
        )
        report = ExternalQualificationReadinessReport.create(
            report_id="readiness.report.operation-drift",
            plan_digest=plan.plan_digest,
            receipts=(drifted,),
            failures=(),
            verified_at=OBSERVED_AT,
            lifecycle_claim=ExternalQualificationLifecycle.READY_NON_LIVE,
            external_effect_performed=False,
            credential_material_accessed=False,
            fallback_performed=False,
        )
        verify_external_qualification_readiness(plan, report, verified_at=OBSERVED_AT)


def test_tampered_unit_and_expired_receipt_fail_closed() -> None:
    unit = _unit()
    with pytest.raises(ExternalQualificationError, match="unit digest"):
        replace(unit, configuration_digest="sha256:" + "2" * 64)

    plan = _plan(unit)
    receipt = _receipt(plan, unit)
    report = ExternalQualificationReadinessReport.create(
        report_id="readiness.report.expired",
        plan_digest=plan.plan_digest,
        receipts=(receipt,),
        failures=(),
        verified_at=OBSERVED_AT,
        lifecycle_claim=ExternalQualificationLifecycle.READY_NON_LIVE,
        external_effect_performed=False,
        credential_material_accessed=False,
        fallback_performed=False,
    )
    with pytest.raises(ExternalQualificationError, match="expired"):
        verify_external_qualification_readiness(
            plan,
            report,
            verified_at="2026-08-24T00:00:00+00:00",
        )


def test_readiness_cannot_claim_qualified_or_external_effect() -> None:
    unit = _unit()
    plan = _plan(unit)
    receipt = _receipt(plan, unit)
    with pytest.raises(ExternalQualificationError, match="cannot claim"):
        ExternalQualificationReadinessReport.create(
            report_id="readiness.report.overclaim",
            plan_digest=plan.plan_digest,
            receipts=(receipt,),
            failures=(),
            verified_at=OBSERVED_AT,
            lifecycle_claim=ExternalQualificationLifecycle.QUALIFIED,
            external_effect_performed=False,
            credential_material_accessed=False,
            fallback_performed=False,
        )
    with pytest.raises(ExternalQualificationError, match="no-effect"):
        replace(receipt, external_effect_performed=True)


def test_public_failure_rejects_secret_bearing_summary() -> None:
    with pytest.raises(ExternalQualificationError, match="not secret-safe"):
        ExternalQualificationFailure(
            error_code="provider_auth_failed",
            component="openzyme.runtime.llm",
            phase="dispatch",
            diagnostic_id="diagnostic.secret.1",
            plan_digest=DIGEST,
            unit_digest=DIGEST,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            mutation_applied=False,
            fallback_performed=False,
            retry_policy="none",
            reconcile_policy="not_required",
            operator_action="replace_locator",
            safe_summary="api_key=sk-secret-material-123456789",
        )


def test_profile_closure_rejects_unreferenced_unit() -> None:
    first = _unit(operation="turn")
    second = _unit(operation="embed")
    with pytest.raises(ExternalQualificationError, match="exact closure"):
        ExternalQualificationPlan.create(
            plan_id="readiness.plan.incomplete",
            distribution_id="enzymedesign",
            distribution_digest=DIGEST,
            enabled_profiles=("base",),
            profiles=(
                ExternalQualificationProfileRef(
                    profile_id="base",
                    required=True,
                    unit_digests=(first.unit_digest,),
                    required_negative_tests=NEGATIVE_TESTS,
                ),
            ),
            units=(first, second),
            created_at=OBSERVED_AT,
            live_allowed=False,
        )


def test_readiness_receipt_cannot_be_adopted_as_qualified_fact() -> None:
    unit = _unit()
    plan = _plan(unit)
    readiness = _receipt(plan, unit)

    with pytest.raises(ExternalQualificationError) as captured:
        adopt_qualified_external_capability(
            unit,
            readiness,
            adopted_at=OBSERVED_AT,
        )
    assert captured.value.error_code == "qualification_readiness_not_adoptable"


def test_exact_real_qualification_evidence_can_form_a_typed_fact() -> None:
    unit = _unit()
    evidence = ExternalQualificationEvidence.create(
        receipt_id="qualification.receipt.real-shape.1",
        lifecycle_claim=ExternalQualificationLifecycle.QUALIFIED,
        unit_digest=unit.unit_digest,
        capability_id=unit.capability_id,
        operation=unit.operation,
        route_id=unit.route_id,
        subject_kind=unit.subject_kind,
        subject_id=unit.subject_id,
        source_digest=unit.source_digest,
        build_digest=unit.build_digest,
        configuration_digest=unit.configuration_digest,
        validator_id=unit.validator_id,
        observed_at=OBSERVED_AT,
        valid_until=VALID_UNTIL,
    )

    fact = adopt_qualified_external_capability(
        unit,
        evidence,
        adopted_at="2026-08-22T12:00:00+00:00",
    )
    assert fact.operation == unit.operation
    assert fact.route_id == unit.route_id
    assert fact.qualification_receipt_digest == evidence.receipt_digest

    with pytest.raises(ExternalQualificationError, match="expired"):
        adopt_qualified_external_capability(
            unit,
            evidence,
            adopted_at="2026-08-24T00:00:00+00:00",
        )
