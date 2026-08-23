import json

from openzyme_contracts import ExternalQualificationBudgetPolicy
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationEffectPolicy
from openzyme_contracts import ExternalQualificationFaultPolicy
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationStoragePolicy
from openzyme_contracts import ExternalQualificationTtlPolicy
from openzyme_contracts import ExternalQualificationUnitSubjectBinding
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import create_external_identity_preparation_success
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger


DIGEST = "sha256:" + "1" * 64


def _plan() -> ExternalQualificationDryPlan:
    return ExternalQualificationDryPlan.create(
        plan_id="qualification.batch-1.plan",
        batch_id="batch-1",
        source_digest=DIGEST,
        readiness_plan_digest=DIGEST,
        discovery_report_digest=DIGEST,
        unit_bindings=(
            ExternalQualificationUnitSubjectBinding(
                unit_digest=DIGEST,
                profile_id="base",
                subject_digest=None,
                gap_ids=("gap.subject",),
            ),
        ),
        subjects=(),
        budgets=(
            ExternalQualificationBudgetPolicy(
                "budget.batch.cash", "batch-1", "cash", 20, 100, "usd"
            ),
        ),
        credential_locator_ids=(),
        effect_policies=(
            ExternalQualificationEffectPolicy(
                "bio-http.read-smoke", "scope.bio", False, None, None
            ),
        ),
        fault_policies=(
            ExternalQualificationFaultPolicy(
                "timeout-before-effect", "adapter.dispatch", False
            ),
        ),
        ttl_policies=(
            ExternalQualificationTtlPolicy(
                "ttl.provider", "provider", 24 * 60 * 60
            ),
        ),
        storage_policy=ExternalQualificationStoragePolicy(
            ledger_id="qualification.ledger.sqlite",
            private_evidence_root_id="qualification.evidence.root",
            public_export_secret_safe=True,
            credential_material_persisted=False,
        ),
        max_retries=0,
        created_at="2026-08-22T12:00:00+00:00",
        live_effect_authorized=False,
    )


def test_adapter_owned_ledger_records_only_safe_plan_payload(tmp_path) -> None:
    plan = _plan()
    ledger = SQLiteProtectedQualificationLedger(tmp_path / "qualification.sqlite3")
    ledger.record_dry_plan(plan)
    stored = ledger.read_dry_plan(plan.dry_plan_digest)
    assert stored is not None
    assert stored["dry_plan_digest"] == plan.dry_plan_digest
    assert "api_key" not in json.dumps(stored)


def test_adapter_owned_ledger_records_safe_preparation_result_once(tmp_path) -> None:
    ledger = SQLiteProtectedQualificationLedger(tmp_path / "qualification.sqlite3")
    result = create_external_identity_preparation_success(
        occurrence_id="occurrence.preparation.store",
        preparation_plan_digest=DIGEST,
        authorization_digest="sha256:" + "2" * 64,
        action_id="prepare.batch-1.provider",
        owner_component_id="provider.owner",
        effect_id="provider.locator.configure",
        input_binding_digest="sha256:" + "3" * 64,
        request_digest="sha256:" + "4" * 64,
        safe_identity_fields=(SafeIdentityField("locator_digest", DIGEST),),
        receipt_payload={"locator_digest": DIGEST},
        external_effect_performed=True,
        credential_material_accessed=True,
    )

    next_occurrence = create_external_identity_preparation_success(
        occurrence_id="occurrence.preparation.store.next",
        preparation_plan_digest=DIGEST,
        authorization_digest="sha256:" + "5" * 64,
        action_id="prepare.batch-1.provider",
        owner_component_id="provider.owner",
        effect_id="provider.locator.configure",
        input_binding_digest="sha256:" + "3" * 64,
        request_digest="sha256:" + "6" * 64,
        safe_identity_fields=(SafeIdentityField("locator_digest", DIGEST),),
        receipt_payload={"locator_digest": DIGEST},
        external_effect_performed=True,
        credential_material_accessed=True,
    )

    ledger.record_preparation_result(result)
    ledger.record_preparation_result(result)
    ledger.record_preparation_result(next_occurrence)
    stored = ledger.read_preparation_results(DIGEST)

    assert len(stored) == 2
    assert {item["result_digest"] for item in stored} == {
        result.result_digest,
        next_occurrence.result_digest,
    }
    assert "secret-canary" not in json.dumps(stored)
    assert ledger.restore_preparation_results(
        DIGEST,
        result.authorization_digest,
    ) == (result,)
    assert ledger.restore_preparation_results(
        DIGEST,
        next_occurrence.authorization_digest,
    ) == (next_occurrence,)


def test_adapter_owned_ledger_restores_terminal_probe_without_redispatch(
    tmp_path,
) -> None:
    ledger = SQLiteProtectedQualificationLedger(tmp_path / "qualification.sqlite3")
    authorization_digest = "sha256:" + "2" * 64
    outcome = ExternalQualificationProbeOutcome(
        attempt_id="occurrence.qualification.unit-1",
        request_digest="sha256:" + "3" * 64,
        disposition=ExternalQualificationProbeDisposition.SUCCEEDED,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        observed_operation="bounded-turn",
        output_digest="sha256:" + "4" * 64,
        observed_result_schema_digest="sha256:" + "5" * 64,
        backend_receipt_digest="sha256:" + "6" * 64,
        external_effect_performed=True,
        credential_material_accessed=True,
        fallback_performed=False,
    )

    ledger.record_probe_outcome(
        dry_plan_digest=DIGEST,
        authorization_digest=authorization_digest,
        unit_digest="sha256:" + "7" * 64,
        outcome=outcome,
    )
    ledger.record_probe_outcome(
        dry_plan_digest=DIGEST,
        authorization_digest=authorization_digest,
        unit_digest="sha256:" + "7" * 64,
        outcome=outcome,
    )

    assert ledger.restore_probe_outcomes(
        dry_plan_digest=DIGEST,
        authorization_digest=authorization_digest,
    ) == (("sha256:" + "7" * 64, outcome),)


def test_adapter_owned_ledger_advances_in_doubt_probe_to_one_terminal_outcome(
    tmp_path,
) -> None:
    ledger = SQLiteProtectedQualificationLedger(tmp_path / "qualification.sqlite3")
    authorization_digest = "sha256:" + "2" * 64
    unit_digest = "sha256:" + "7" * 64
    pending = ExternalQualificationProbeOutcome(
        attempt_id="occurrence.qualification.unit-1",
        request_digest="sha256:" + "3" * 64,
        disposition=ExternalQualificationProbeDisposition.RECONCILE_REQUIRED,
        effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
        observed_operation=None,
        output_digest=None,
        observed_result_schema_digest=None,
        backend_receipt_digest="sha256:" + "6" * 64,
        error_code="qualification_response_lost",
        external_effect_performed=True,
        credential_material_accessed=True,
        fallback_performed=False,
    )
    terminal = ExternalQualificationProbeOutcome(
        attempt_id=pending.attempt_id,
        request_digest=pending.request_digest,
        disposition=ExternalQualificationProbeDisposition.SUCCEEDED,
        effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
        observed_operation="reconcile",
        output_digest="sha256:" + "4" * 64,
        observed_result_schema_digest="sha256:" + "5" * 64,
        backend_receipt_digest="sha256:" + "8" * 64,
        external_effect_performed=True,
        credential_material_accessed=True,
        fallback_performed=False,
    )

    ledger.record_probe_outcome(
        dry_plan_digest=DIGEST,
        authorization_digest=authorization_digest,
        unit_digest=unit_digest,
        outcome=pending,
    )
    ledger.record_probe_outcome(
        dry_plan_digest=DIGEST,
        authorization_digest=authorization_digest,
        unit_digest=unit_digest,
        outcome=terminal,
    )

    assert ledger.restore_probe_outcomes(
        dry_plan_digest=DIGEST,
        authorization_digest=authorization_digest,
    ) == ((unit_digest, terminal),)
