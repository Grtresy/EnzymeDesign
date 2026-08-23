from dataclasses import replace

import pytest

from openzyme_contracts import ExternalIdentityGap
from openzyme_contracts import BoundExternalQualificationOperationBridge
from openzyme_contracts import ExternalIdentityPreparationAction
from openzyme_contracts import ExternalIdentityPreparationAuthorizationRevocation
from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
from openzyme_contracts import ExternalIdentityPreparationPlan
from openzyme_contracts import ExternalIdentityResolutionCandidate
from openzyme_contracts import ExternalIdentityResolutionDecision
from openzyme_contracts import ExternalQualificationBudgetPolicy
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationEffectPolicy
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationFaultPolicy
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationOperationObservation
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationStoragePolicy
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import ExternalQualificationTtlPolicy
from openzyme_contracts import ExternalQualificationUnitSubjectBinding
from openzyme_contracts import ExternalSubjectIdentityObservation
from openzyme_contracts import ExternalSubjectIdentityStatus
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import verify_external_identity_decision
from openzyme_contracts import (
    verify_external_identity_preparation_authorization_not_revoked,
)
from openzyme_contracts import (
    verify_external_identity_preparation_occurrence_authorization,
)
from openzyme_contracts import verify_external_identity_preparation_plan
from openzyme_contracts import verify_external_qualification_dry_plan
from openzyme_contracts import verify_external_qualification_occurrence_authorization


DIGEST = "sha256:" + "1" * 64
OTHER_DIGEST = "sha256:" + "2" * 64
OBSERVED_AT = "2026-08-22T12:00:00+00:00"


def _gap() -> ExternalIdentityGap:
    observation = ExternalSubjectIdentityObservation.create(
        observation_id="observation.llm",
        logical_subject_id="provider.llm.primary",
        subject_kind=ExternalQualificationSubjectKind.PROVIDER,
        status=ExternalSubjectIdentityStatus.PARTIAL,
        source_id="snapshot.current",
        source_digest=DIGEST,
        safe_fields=(SafeIdentityField("model", "gpt-5.5"),),
        missing_fields=("account_locator_digest",),
        affected_unit_digests=(DIGEST,),
    )
    return ExternalIdentityGap.create(
        gap_id="gap.llm",
        logical_subject_id=observation.logical_subject_id,
        observation_digest=observation.observation_digest,
        missing_fields=observation.missing_fields,
        affected_unit_digests=observation.affected_unit_digests,
        candidates=(
            ExternalIdentityResolutionCandidate(
                candidate_id="bind-account",
                title="绑定专用 account",
                operator_action="提供非 secret account locator digest",
                effect_summary="当前无 effect",
                cost_summary="未来受预算约束",
                security_summary="最小 scope",
                recommended=True,
            ),
            ExternalIdentityResolutionCandidate(
                candidate_id="keep-blocked",
                title="保持阻塞",
                operator_action="不解析凭据",
                effect_summary="无 effect",
                cost_summary="无费用",
                security_summary="无凭据访问",
            ),
        ),
    )


def _blocked_plan() -> ExternalQualificationDryPlan:
    gap = _gap()
    return ExternalQualificationDryPlan.create(
        plan_id="qualification.batch-1.plan",
        batch_id="batch-1",
        source_digest=DIGEST,
        readiness_plan_digest=OTHER_DIGEST,
        discovery_report_digest=DIGEST,
        unit_bindings=(
            ExternalQualificationUnitSubjectBinding(
                unit_digest=DIGEST,
                profile_id="base",
                subject_digest=None,
                gap_ids=(gap.gap_id,),
            ),
        ),
        subjects=(),
        budgets=(
            ExternalQualificationBudgetPolicy(
                budget_id="budget.batch.cash",
                scope_id="batch-1",
                resource_kind="cash",
                warning_limit=20,
                hard_limit=100,
                unit="usd",
            ),
        ),
        credential_locator_ids=(),
        effect_policies=(
            ExternalQualificationEffectPolicy(
                "llm.bounded-turn", "scope.llm", False, None, None
            ),
        ),
        fault_policies=(
            ExternalQualificationFaultPolicy(
                "timeout-before-effect", "adapter.dispatch", False
            ),
        ),
        ttl_policies=(
            ExternalQualificationTtlPolicy("ttl.provider", "provider", 24 * 60 * 60),
        ),
        storage_policy=ExternalQualificationStoragePolicy(
            ledger_id="qualification.ledger.sqlite",
            private_evidence_root_id="qualification.evidence.root",
            public_export_secret_safe=True,
            credential_material_persisted=False,
        ),
        max_retries=0,
        created_at=OBSERVED_AT,
        live_effect_authorized=False,
    )


def _preparation_plan() -> ExternalIdentityPreparationPlan:
    gap = _gap()
    decision = ExternalIdentityResolutionDecision.create(
        decision_id="decision.llm",
        gap_digest=gap.gap_digest,
        candidate_id="bind-account",
        operator_id="operator.owner",
        decided_at=OBSERVED_AT,
    )
    return ExternalIdentityPreparationPlan.create(
        plan_id="preparation.batch-1",
        batch_id="batch-1",
        source_digest=DIGEST,
        discovery_report_digest=OTHER_DIGEST,
        decisions=(decision,),
        actions=(
            ExternalIdentityPreparationAction.create(
                action_id="prepare.llm.locator",
                owner_component_id="openzyme.runtime.llm",
                logical_subject_id="provider.llm.primary",
                gap_digests=(gap.gap_digest,),
                decision_digests=(decision.decision_digest,),
                effect_id="provider.llm.locator.configure",
                input_schema_id="provider-locator-preparation@1",
                safe_input_fields=(SafeIdentityField("provider_id", "test-provider"),),
                credential_locator_id="credential.llm.qualification",
                mutating=True,
                requires_credential_material=True,
                expected_identity_fields=("account_locator_digest",),
                cleanup_action_id="cleanup.provider.llm.locator",
                cleanup_deadline_seconds=3600,
            ),
        ),
        budgets=(
            ExternalQualificationBudgetPolicy(
                "budget.batch.cash", "batch-1", "cash", 20, 100, "usd"
            ),
        ),
        credential_locator_ids=("credential.llm.qualification",),
        operator_constraints=("first-effect-requires-new-authorization",),
        storage_policy=ExternalQualificationStoragePolicy(
            ledger_id="qualification.ledger.sqlite",
            private_evidence_root_id="qualification.evidence.root",
            public_export_secret_safe=True,
            credential_material_persisted=False,
        ),
        max_retries=0,
        created_at=OBSERVED_AT,
        live_effect_authorized=False,
    )


def test_preparation_action_rejects_input_binding_tamper() -> None:
    action = _preparation_plan().actions[0]
    with pytest.raises(ExternalQualificationError) as captured:
        replace(action, input_binding_digest="sha256:" + "9" * 64)
    assert captured.value.error_code == (
        "qualification_preparation_input_binding_digest_mismatch"
    )


def test_preparation_plan_locators_must_match_exact_action_bindings() -> None:
    with pytest.raises(ExternalQualificationError) as captured:
        replace(
            _preparation_plan(),
            credential_locator_ids=("credential.other.qualification",),
        )
    assert captured.value.error_code == (
        "qualification_preparation_credential_locator_coverage_mismatch"
    )


def test_safe_observation_rejects_secret_canary() -> None:
    with pytest.raises(ExternalQualificationError) as captured:
        SafeIdentityField("unsafe", "api_key=sk-secret-material-123456789")
    assert captured.value.error_code == "qualification_public_identity_not_secret_safe"


def test_gap_requires_explicit_current_candidate_decision() -> None:
    gap = _gap()
    decision = ExternalIdentityResolutionDecision.create(
        decision_id="decision.llm",
        gap_digest=gap.gap_digest,
        candidate_id="bind-account",
        operator_id="operator.owner",
        decided_at=OBSERVED_AT,
    )
    assert verify_external_identity_decision(gap, decision).recommended is True

    drifted_gap = ExternalIdentityGap.create(
        gap_id=gap.gap_id,
        logical_subject_id=gap.logical_subject_id,
        observation_digest=OTHER_DIGEST,
        missing_fields=gap.missing_fields,
        affected_unit_digests=gap.affected_unit_digests,
        candidates=gap.candidates,
    )
    with pytest.raises(ExternalQualificationError) as captured:
        verify_external_identity_decision(drifted_gap, decision)
    assert captured.value.error_code == "qualification_identity_decision_stale"


def test_budget_warning_is_strictly_lower_than_hard_limit() -> None:
    policy = ExternalQualificationBudgetPolicy(
        "budget.llm.cash", "llm", "cash", 5, 25, "usd"
    )
    assert policy.warning_limit == 5
    assert policy.hard_limit == 25
    with pytest.raises(ValueError, match="lower"):
        replace(policy, warning_limit=25)


def test_blocked_dry_plan_verifies_but_cannot_receive_occurrence_authority() -> None:
    plan = _blocked_plan()
    verify_external_qualification_dry_plan(
        plan,
        expected_source_digest=DIGEST,
        expected_readiness_plan_digest=OTHER_DIGEST,
    )
    assert plan.authorizable is False
    assert plan.live_effect_authorized is False

    authorization = ExternalQualificationOccurrenceAuthorization.create(
        authorization_id="authorization.batch-1",
        dry_plan_digest=plan.dry_plan_digest,
        batch_id=plan.batch_id,
        operator_id="operator.owner",
        valid_from="2026-08-22T11:00:00+00:00",
        valid_until="2026-08-22T13:00:00+00:00",
    )
    with pytest.raises(ExternalQualificationError) as captured:
        verify_external_qualification_occurrence_authorization(
            plan, authorization, observed_at=OBSERVED_AT
        )
    assert captured.value.error_code == "blocked_identity"


def test_missing_occurrence_authority_fails_with_stable_pre_effect_code() -> None:
    with pytest.raises(ExternalQualificationError) as captured:
        verify_external_qualification_occurrence_authorization(
            _blocked_plan(), None, observed_at=OBSERVED_AT
        )
    assert captured.value.error_code == "blocked_live_authorization"


def test_identity_preparation_is_exact_but_does_not_promote_qualification() -> None:
    plan = _preparation_plan()
    verify_external_identity_preparation_plan(
        plan,
        expected_source_digest=DIGEST,
        expected_discovery_report_digest=OTHER_DIGEST,
        expected_gap_digests=tuple(item.gap_digest for item in plan.decisions),
    )
    assert plan.to_dict()["authorizable"] is True
    assert plan.live_effect_authorized is False
    assert _blocked_plan().authorizable is False


def test_identity_preparation_requires_separate_exact_occurrence_authorization() -> (
    None
):
    plan = _preparation_plan()
    with pytest.raises(ExternalQualificationError) as captured:
        verify_external_identity_preparation_occurrence_authorization(
            plan,
            None,
            observed_at=OBSERVED_AT,
        )
    assert captured.value.error_code == "blocked_preparation_authorization"

    authorization = ExternalIdentityPreparationOccurrenceAuthorization.create(
        authorization_id="authorization.preparation.batch-1",
        preparation_plan_digest=plan.preparation_plan_digest,
        batch_id=plan.batch_id,
        operator_id="operator.owner",
        authorized_at="2026-08-22T11:00:00+00:00",
    )
    verify_external_identity_preparation_occurrence_authorization(
        plan,
        authorization,
        observed_at="2036-08-22T12:00:00+00:00",
    )
    assert (
        ExternalIdentityPreparationOccurrenceAuthorization.from_dict(
            authorization.to_dict()
        )
        == authorization
    )

    revocation = ExternalIdentityPreparationAuthorizationRevocation.create(
        revocation_id="revocation.authorization.preparation.batch-1",
        authorization_digest=authorization.authorization_digest,
        operator_id=authorization.operator_id,
        revoked_at="2026-08-23T00:00:00+00:00",
        reason_code="operator_revoked",
    )
    with pytest.raises(ExternalQualificationError) as revoked:
        verify_external_identity_preparation_authorization_not_revoked(
            authorization,
            revocation,
        )
    assert revoked.value.error_code == (
        "qualification_preparation_authorization_revoked"
    )


class _ResponseLossOperationPort:
    def __init__(self) -> None:
        self.dispatch_calls = 0
        self.reconcile_calls = 0

    def dispatch(self, request):
        self.dispatch_calls += 1
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty="dispatch_in_doubt",
            terminal=False,
            succeeded=False,
            output_digest=None,
            receipt_digest=None,
            error_code="qualification_response_lost",
            external_effect_performed=True,
            credential_material_accessed=False,
        )

    def reconcile(self, request):
        self.reconcile_calls += 1
        return ExternalQualificationOperationObservation(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            operation=request.operation,
            effect_certainty="terminal_known",
            terminal=True,
            succeeded=True,
            output_digest=DIGEST,
            receipt_digest=OTHER_DIGEST,
            error_code=None,
            external_effect_performed=True,
            credential_material_accessed=False,
        )


def test_bound_owner_bridge_reconciles_same_attempt_without_redispatch() -> None:
    from openzyme_contracts import ExternalQualificationBridgeBinding

    binding = ExternalQualificationBridgeBinding.create(
        component_id="component.owner",
        operation="publish",
        route_id="route.publish@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
    )
    request = ExternalQualificationProbeRequest.create(
        attempt_id="attempt.publish",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=30,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id=None,
    )
    port = _ResponseLossOperationPort()
    bridge = BoundExternalQualificationOperationBridge(
        binding=binding,
        operation_port=port,
        allowed_operations=("publish",),
    )

    first = bridge.dispatch(request)
    terminal = bridge.reconcile(request)

    assert first.disposition.value == "reconcile_required"
    assert terminal.disposition.value == "succeeded"
    assert port.dispatch_calls == 1
    assert port.reconcile_calls == 1
    with pytest.raises(ExternalQualificationError) as captured:
        bridge.dispatch(request)
    assert captured.value.error_code == "qualification_probe_redispatch_forbidden"


def test_bridge_binding_rejects_credential_locator_drift_before_dispatch() -> None:
    from openzyme_contracts import ExternalQualificationBridgeBinding

    binding = ExternalQualificationBridgeBinding.create(
        component_id="component.owner",
        operation="publish",
        route_id="route.publish@1",
        plan_digest=DIGEST,
        unit_digest=OTHER_DIGEST,
        subject_digest=DIGEST,
        input_digest=OTHER_DIGEST,
        expected_result_schema_digest=DIGEST,
        authorization_digest=OTHER_DIGEST,
        credential_locator_id="credential.owner.qualification",
    )
    request = ExternalQualificationProbeRequest.create(
        attempt_id="attempt.publish.locator-drift",
        plan_digest=binding.plan_digest,
        unit_digest=binding.unit_digest,
        operation=binding.operation,
        timeout_seconds=30,
        input_digest=binding.input_digest,
        expected_result_schema_digest=binding.expected_result_schema_digest,
        credential_locator_id="credential.other.qualification",
    )

    with pytest.raises(ExternalQualificationError) as captured:
        BoundExternalQualificationOperationBridge(
            binding=binding,
            operation_port=_ResponseLossOperationPort(),
            allowed_operations=("publish",),
        ).dispatch(request)

    assert captured.value.error_code == "qualification_bridge_request_binding_mismatch"


def test_dry_plan_credential_locators_must_match_exact_unit_bindings() -> None:
    with pytest.raises(ExternalQualificationError) as captured:
        replace(
            _blocked_plan(),
            credential_locator_ids=("credential.unbound.qualification",),
        )

    assert captured.value.error_code == (
        "qualification_credential_locator_coverage_mismatch"
    )
