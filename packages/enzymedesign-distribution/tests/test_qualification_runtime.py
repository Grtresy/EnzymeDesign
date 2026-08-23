import pytest

from enzymedesign_distribution import ExternalQualificationReadinessCoordinator
from enzymedesign_distribution import QualificationDisclosureMatrix
from enzymedesign_distribution import RecordingQualificationProbeBackend
from enzymedesign_distribution import RejectingQualificationCredentialResolver
from enzymedesign_distribution import REQUIRED_NEGATIVE_TESTS
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationLifecycle
from openzyme_contracts import verify_external_qualification_readiness


OBSERVED_AT = "2026-08-22T00:00:00+00:00"


def _plan():
    return build_enzymedesign_external_qualification_plan(
        plan_id="readiness.runtime.base",
        created_at=OBSERVED_AT,
    )


def test_recording_backend_closes_base_without_external_effect() -> None:
    plan = _plan()
    backend = RecordingQualificationProbeBackend(units=plan.units)
    coordinator = ExternalQualificationReadinessCoordinator(
        probe=backend,
        negative_fixtures=backend,
    )

    report = coordinator.execute(plan, observed_at=OBSERVED_AT)
    verify_external_qualification_readiness(
        plan,
        report,
        verified_at="2026-08-22T00:30:00+00:00",
    )
    matrix = QualificationDisclosureMatrix.create(plan=plan, report=report)

    assert report.lifecycle_claim is ExternalQualificationLifecycle.READY_NON_LIVE
    assert len(report.receipts) == len(plan.units) == 18
    assert report.external_effect_performed is False
    assert report.credential_material_accessed is False
    assert report.fallback_performed is False
    assert backend.negative_tests_exercised == list(REQUIRED_NEGATIVE_TESTS)
    assert all(count == 1 for count in backend.dispatch_count.values())
    assert all(entry.deterministic_substitute for entry in matrix.entries)
    assert all(not entry.qualified for entry in matrix.entries)
    assert all(not entry.cutover for entry in matrix.entries)
    assert all(not entry.live_occurrence for entry in matrix.entries)


def test_response_loss_reconciles_same_attempt_without_redispatch() -> None:
    plan = _plan()
    unit = plan.units[0]
    backend = RecordingQualificationProbeBackend(
        units=plan.units,
        response_loss_unit_digests=frozenset({unit.unit_digest}),
    )
    report = ExternalQualificationReadinessCoordinator(
        probe=backend,
        negative_fixtures=backend,
    ).execute(plan, observed_at=OBSERVED_AT)

    attempt_id = f"{plan.plan_id}.attempt.1"
    assert report.lifecycle_claim is ExternalQualificationLifecycle.READY_NON_LIVE
    assert backend.dispatch_count[attempt_id] == 1
    assert backend.reconcile_count[attempt_id] == 1


def test_unresolved_reconcile_blocks_only_the_exact_unit() -> None:
    plan = _plan()
    unit = plan.units[0]
    backend = RecordingQualificationProbeBackend(
        units=plan.units,
        response_loss_unit_digests=frozenset({unit.unit_digest}),
        unresolved_unit_digests=frozenset({unit.unit_digest}),
    )
    coordinator = ExternalQualificationReadinessCoordinator(
        probe=backend,
        negative_fixtures=backend,
    )
    report = coordinator.execute(plan, observed_at=OBSERVED_AT)

    assert report.lifecycle_claim is ExternalQualificationLifecycle.RUNTIME_MOUNTED
    assert len(report.failures) == 1
    assert report.failures[0].unit_digest == unit.unit_digest
    assert report.failures[0].fallback_performed is False
    assert len(report.receipts) == len(plan.units) - 1
    assert coordinator.private_diagnostics[0].diagnostic_id == (
        report.failures[0].diagnostic_id
    )


@pytest.mark.parametrize(
    ("backend_field", "error_code"),
    [
        ("operation_mismatch_unit_digests", "qualification_operation_mismatch"),
        ("schema_mismatch_unit_digests", "qualification_schema_mismatch"),
    ],
)
def test_drifted_probe_result_is_blocked(
    backend_field: str,
    error_code: str,
) -> None:
    plan = _plan()
    unit = plan.units[0]
    backend = RecordingQualificationProbeBackend(
        units=plan.units,
        **{backend_field: frozenset({unit.unit_digest})},
    )
    report = ExternalQualificationReadinessCoordinator(
        probe=backend,
        negative_fixtures=backend,
    ).execute(plan, observed_at=OBSERVED_AT)

    assert report.failures[0].error_code == error_code
    assert backend.dispatch_count[f"{plan.plan_id}.attempt.1"] == 1


def test_missing_negative_fixture_blocks_every_readiness_claim() -> None:
    plan = _plan()
    backend = RecordingQualificationProbeBackend(
        units=plan.units,
        available_negative_tests=frozenset(
            set(REQUIRED_NEGATIVE_TESTS) - {"auth.failure"}
        ),
    )
    report = ExternalQualificationReadinessCoordinator(
        probe=backend,
        negative_fixtures=backend,
    ).execute(plan, observed_at=OBSERVED_AT)

    assert report.lifecycle_claim is ExternalQualificationLifecycle.RUNTIME_MOUNTED
    assert not report.receipts
    assert len(report.failures) == len(plan.units)
    assert {item.error_code for item in report.failures} == {
        "qualification_negative_fixture_incomplete"
    }


def test_non_live_credential_resolver_never_returns_material() -> None:
    unit = next(item for item in _plan().units if item.credential_locator is not None)
    resolver = RejectingQualificationCredentialResolver()

    with pytest.raises(ExternalQualificationError) as captured:
        resolver.resolve(unit=unit, locator=unit.credential_locator)  # type: ignore[arg-type]
    assert captured.value.error_code == "qualification_credential_resolution_forbidden"
    assert resolver.resolution_attempts == [
        (unit.unit_digest, unit.credential_locator.credential_locator_id)  # type: ignore[union-attr]
    ]
