import pytest

from enzymedesign_distribution import EnzymeDesignExternalQualificationAdmission
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationEvidence
from openzyme_contracts import ExternalQualificationLifecycle
from openzyme_contracts import adopt_qualified_external_capability


OBSERVED_AT = "2026-08-22T00:00:00+00:00"
VALID_UNTIL = "2026-08-23T00:00:00+00:00"


def _evidence(unit):
    return ExternalQualificationEvidence.create(
        receipt_id=f"qualification.receipt.{unit.component_id}.{unit.operation}",
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


def test_admission_preserves_multiple_exact_routes_without_selecting_one() -> None:
    plan = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.admission.hmmer",
        created_at=OBSERVED_AT,
        enabled_optional_profiles=("hmmer",),
    )
    hmmbuild_units = tuple(
        unit
        for unit in plan.units
        if unit.capability_id == "software.hmmer" and unit.operation == "hmmbuild"
    )
    facts = tuple(
        adopt_qualified_external_capability(
            unit,
            _evidence(unit),
            adopted_at=OBSERVED_AT,
        )
        for unit in hmmbuild_units
    )
    admission = EnzymeDesignExternalQualificationAdmission.create(
        plan=plan,
        facts=facts,
        as_of="2026-08-22T12:00:00+00:00",
    )

    available = admission.available_routes(
        capability_id="software.hmmer",
        operation="hmmbuild",
    )
    assert len(available) == 2
    assert {item.subject_id for item in available} == {"local", "hpc-primary"}
    selected = available[0]
    assert admission.admit_occurrence(
        unit_digest=selected.unit_digest,
        route_id=selected.route_id,
        subject_id=selected.subject_id,
    ) == selected


def test_missing_expired_or_drifted_unit_is_blocked_without_fallback() -> None:
    plan = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.admission.expired",
        created_at=OBSERVED_AT,
        enabled_optional_profiles=("hmmer",),
    )
    unit = next(item for item in plan.units if item.capability_id == "software.hmmer")
    expired_fact = adopt_qualified_external_capability(
        unit,
        _evidence(unit),
        adopted_at=OBSERVED_AT,
    )
    admission = EnzymeDesignExternalQualificationAdmission.create(
        plan=plan,
        facts=(expired_fact,),
        as_of="2026-08-24T00:00:00+00:00",
    )

    assert not admission.available_routes(
        capability_id=unit.capability_id,
        operation=unit.operation,
    )
    with pytest.raises(ExternalQualificationError) as captured:
        admission.admit_occurrence(
            unit_digest=unit.unit_digest,
            route_id=unit.route_id,
            subject_id=unit.subject_id,
        )
    assert captured.value.error_code == "blocked_qualification"
    assert "blocked_qualification_expired" in str(captured.value)
