from dataclasses import dataclass

import pytest

from enzymedesign_distribution import SelectedQualificationProbeRouter
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import build_external_qualification_probe_request
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationBridgeBinding
from openzyme_contracts import ExternalQualificationBudgetPolicy
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationEffectPolicy
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationFaultPolicy
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProbeRequest
from openzyme_contracts import ExternalQualificationStoragePolicy
from openzyme_contracts import ExternalQualificationTtlPolicy
from openzyme_contracts import ExternalQualificationUnitSubjectBinding
from openzyme_contracts import ExternalRealSubjectIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import verify_external_qualification_probe_request_binding


OBSERVED_AT = "2026-08-22T12:00:00+00:00"
VALID_UNTIL = "2026-08-23T12:00:00+00:00"
DIGEST = "sha256:" + "1" * 64


def _plans():
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.router.test",
        created_at=OBSERVED_AT,
    )
    unit = next(
        item
        for item in readiness.units
        if item.component_id == "enzymedesign.bio-provider-http"
    )
    subject = ExternalRealSubjectIdentity.create(
        identity_id="identity.bio.router.test",
        logical_subject_id=unit.subject_id,
        subject_kind=unit.subject_kind,
        endpoint_or_runtime_id="https.public.provider.test",
        account_or_deployment_digest=DIGEST,
        api_or_route_variant="read-v1",
        environment_or_inventory_digest=DIGEST,
        policy_digest=DIGEST,
        source_observation_digest=DIGEST,
    )
    dry_plan = ExternalQualificationDryPlan.create(
        plan_id="qualification.router.dry-plan",
        batch_id="batch-1",
        source_digest=DIGEST,
        readiness_plan_digest=readiness.plan_digest,
        discovery_report_digest=DIGEST,
        unit_bindings=(
            ExternalQualificationUnitSubjectBinding(
                unit_digest=unit.unit_digest,
                profile_id="base",
                subject_digest=subject.subject_digest,
            ),
        ),
        subjects=(subject,),
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
    authorization = ExternalQualificationOccurrenceAuthorization.create(
        authorization_id="authorization.router.test",
        dry_plan_digest=dry_plan.dry_plan_digest,
        batch_id=dry_plan.batch_id,
        operator_id="operator.owner",
        valid_from=OBSERVED_AT,
        valid_until=VALID_UNTIL,
    )
    return readiness, unit, dry_plan, authorization


@dataclass
class _Bridge:
    binding: ExternalQualificationBridgeBinding
    calls: int = 0

    def dispatch(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        verify_external_qualification_probe_request_binding(self.binding, request)
        self.calls += 1
        return ExternalQualificationProbeOutcome(
            attempt_id=request.attempt_id,
            request_digest=request.request_digest,
            disposition=ExternalQualificationProbeDisposition.SUCCEEDED,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            observed_operation=request.operation,
            output_digest=DIGEST,
            observed_result_schema_digest=request.expected_result_schema_digest,
            backend_receipt_digest=canonical_sha256_digest(
                {"attempt_id": request.attempt_id}
            ),
            external_effect_performed=True,
            credential_material_accessed=False,
            fallback_performed=False,
        )

    def reconcile(
        self, request: ExternalQualificationProbeRequest
    ) -> ExternalQualificationProbeOutcome:
        raise AssertionError("terminal fake bridge must not reconcile")


def test_authorized_router_builds_and_dispatches_only_the_exact_unit() -> None:
    readiness, unit, dry_plan, authorization = _plans()
    built: list[_Bridge] = []

    def builder(binding: ExternalQualificationBridgeBinding) -> _Bridge:
        bridge = _Bridge(binding)
        built.append(bridge)
        return bridge

    router = SelectedQualificationProbeRouter(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        observed_at="2026-08-22T13:00:00+00:00",
        bridge_builders={unit.component_id: builder},
    )
    request = build_external_qualification_probe_request(
        dry_plan=dry_plan,
        readiness_unit=unit,
        attempt_id="attempt.router.test",
        timeout_seconds=30,
    )

    outcome = router.dispatch(request)

    assert outcome.disposition is ExternalQualificationProbeDisposition.SUCCEEDED
    assert outcome.fallback_performed is False
    assert built[0].binding.authorization_digest == authorization.authorization_digest
    assert built[0].binding.subject_digest == dry_plan.unit_bindings[0].subject_digest
    assert built[0].calls == 1
    with pytest.raises(ExternalQualificationError) as captured:
        router.dispatch(request)
    assert captured.value.error_code == "qualification_probe_redispatch_forbidden"


def test_router_blocks_before_builder_without_exact_occurrence_authority() -> None:
    readiness, unit, dry_plan, _authorization = _plans()
    builder_calls = 0

    def builder(binding: ExternalQualificationBridgeBinding) -> _Bridge:
        nonlocal builder_calls
        builder_calls += 1
        return _Bridge(binding)

    with pytest.raises(ExternalQualificationError) as captured:
        SelectedQualificationProbeRouter(
            dry_plan=dry_plan,
            readiness_plan=readiness,
            authorization=None,  # type: ignore[arg-type]
            observed_at="2026-08-22T13:00:00+00:00",
            bridge_builders={unit.component_id: builder},
        )

    assert captured.value.error_code == "blocked_live_authorization"
    assert builder_calls == 0


def test_router_rejects_owner_bridge_that_changes_exact_binding() -> None:
    readiness, unit, dry_plan, authorization = _plans()

    def builder(binding: ExternalQualificationBridgeBinding) -> _Bridge:
        payload = dict(binding.identity_payload)
        payload.pop("schema_version")
        payload["route_id"] = "enzymedesign.bio-provider-http.other.read@1"
        return _Bridge(ExternalQualificationBridgeBinding.create(**payload))

    with pytest.raises(ExternalQualificationError) as captured:
        SelectedQualificationProbeRouter(
            dry_plan=dry_plan,
            readiness_plan=readiness,
            authorization=authorization,
            observed_at="2026-08-22T13:00:00+00:00",
            bridge_builders={unit.component_id: builder},
        )

    assert captured.value.error_code == "qualification_live_bridge_binding_mismatch"
