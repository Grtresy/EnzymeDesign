from dataclasses import dataclass

from enzymedesign_distribution import ExternalLiveQualificationCoordinator
from enzymedesign_distribution import SelectedQualificationProbeRouter
from enzymedesign_distribution import verify_live_qualification_receipt_set
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import ExternalQualificationBudgetPolicy
from openzyme_contracts import ExternalQualificationDryPlan
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationEffectPolicy
from openzyme_contracts import ExternalQualificationFaultPolicy
from openzyme_contracts import ExternalQualificationOccurrenceAuthorization
from openzyme_contracts import ExternalQualificationPlan
from openzyme_contracts import ExternalQualificationProbeDisposition
from openzyme_contracts import ExternalQualificationProbeOutcome
from openzyme_contracts import ExternalQualificationProfileRef
from openzyme_contracts import ExternalQualificationStoragePolicy
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import ExternalQualificationTtlPolicy
from openzyme_contracts import ExternalQualificationUnit
from openzyme_contracts import ExternalQualificationUnitSubjectBinding
from openzyme_contracts import ExternalRealSubjectIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_store_sqlite import SQLiteProtectedQualificationLedger
from enzymedesign_distribution.qualification_live_runtime import _unit_cleanup_ok
from enzymedesign_distribution.qualification_live_runtime import (
    exercise_live_qualification_negative_gate,
)


DIGEST = "sha256:" + "1" * 64
OBSERVED_AT = "2026-08-23T18:00:00+08:00"


def _unit(component: str, operation: str, route: str, subject: str):
    return ExternalQualificationUnit.create(
        component_id=component,
        capability_id=f"capability.{component}",
        operation=operation,
        route_id=route,
        subject_kind=ExternalQualificationSubjectKind.TARGET,
        subject_id=subject,
        source_digest=DIGEST,
        build_digest=DIGEST,
        configuration_digest=DIGEST,
        contract_digest=DIGEST,
        qualification_spec_id=f"qualification.{component}@1",
        qualification_spec_digest=DIGEST,
        validator_id=f"validator.{component}",
        expected_result_schema_digest=DIGEST,
    )


def _plans():
    first = _unit(
        "enzymedesign.bio-provider-http",
        "read-smoke",
        "enzymedesign.bio-provider-http.uniprot.read@1",
        "provider.uniprot.public",
    )
    response = _unit(
        "openzyme.workspace.git.lfs",
        "response-loss-reconcile",
        "openzyme.workspace.git.lfs.response-loss-reconcile@1",
        "git.primary",
    )
    units = (first, response)
    readiness = ExternalQualificationPlan.create(
        plan_id="qualification.live-runtime.test",
        distribution_id="enzymedesign",
        distribution_digest=DIGEST,
        enabled_profiles=("base",),
        profiles=(
            ExternalQualificationProfileRef(
                profile_id="base",
                required=True,
                unit_digests=tuple(item.unit_digest for item in units),
                required_negative_tests=(
                    "auth.failure",
                    "operation.mismatch",
                    "response.loss",
                    "schema.mismatch",
                    "timeout.before.effect",
                ),
            ),
        ),
        units=units,
        created_at=OBSERVED_AT,
        live_allowed=False,
    )
    subjects = tuple(
        ExternalRealSubjectIdentity.create(
            identity_id=f"identity.{unit.subject_id}",
            logical_subject_id=unit.subject_id,
            subject_kind=unit.subject_kind,
            endpoint_or_runtime_id=f"runtime.{unit.subject_id}",
            account_or_deployment_digest=DIGEST,
            api_or_route_variant="qualification-v1",
            environment_or_inventory_digest=DIGEST,
            policy_digest=DIGEST,
            source_observation_digest=DIGEST,
        )
        for unit in units
    )
    dry_plan = ExternalQualificationDryPlan.create(
        plan_id="qualification.live-runtime.dry-plan",
        batch_id="batch-1",
        source_digest=DIGEST,
        readiness_plan_digest=readiness.plan_digest,
        discovery_report_digest=DIGEST,
        unit_bindings=tuple(
            ExternalQualificationUnitSubjectBinding(
                unit_digest=unit.unit_digest,
                profile_id="base",
                subject_digest=subject.subject_digest,
            )
            for unit, subject in zip(units, subjects, strict=True)
        ),
        subjects=subjects,
        budgets=(
            ExternalQualificationBudgetPolicy(
                "budget.batch-1.cash", "batch-1", "cash", 100, 250, "usd"
            ),
        ),
        credential_locator_ids=(),
        effect_policies=(
            ExternalQualificationEffectPolicy(
                "qualification.fixed-smoke", "batch-1", False, None, None
            ),
        ),
        fault_policies=(
            ExternalQualificationFaultPolicy(
                "response.loss", "adapter.dispatch", True
            ),
        ),
        ttl_policies=(
            ExternalQualificationTtlPolicy("ttl.provider", "provider", 86_400),
        ),
        storage_policy=ExternalQualificationStoragePolicy(
            ledger_id="qualification.ledger.sqlite",
            private_evidence_root_id="qualification.evidence.private",
            public_export_secret_safe=True,
            credential_material_persisted=False,
        ),
        max_retries=0,
        created_at=OBSERVED_AT,
        live_effect_authorized=False,
    )
    authorization = ExternalQualificationOccurrenceAuthorization.create(
        authorization_id="authorization.live-runtime.test",
        dry_plan_digest=dry_plan.dry_plan_digest,
        batch_id="batch-1",
        operator_id="operator.enzymedesign-owner",
        authorized_at=OBSERVED_AT,
    )
    return readiness, dry_plan, authorization


def _alphafold_plans():
    unit = _unit(
        "enzymedesign.alphafold.hpc",
        "predict",
        "enzymedesign.alphafold.hpc-primary@1",
        "hpc-primary",
    )
    readiness = ExternalQualificationPlan.create(
        plan_id="qualification.alphafold.live-runtime.test",
        distribution_id="enzymedesign",
        distribution_digest=DIGEST,
        enabled_profiles=("alphafold",),
        profiles=(
            ExternalQualificationProfileRef(
                profile_id="alphafold",
                required=False,
                unit_digests=(unit.unit_digest,),
                required_negative_tests=(
                    "auth.failure",
                    "operation.mismatch",
                    "response.loss",
                    "schema.mismatch",
                    "timeout.before.effect",
                ),
            ),
        ),
        units=(unit,),
        created_at=OBSERVED_AT,
        live_allowed=False,
    )
    subject = ExternalRealSubjectIdentity.create(
        identity_id="identity.alphafold.diannan-3090",
        logical_subject_id="hpc-primary",
        subject_kind=unit.subject_kind,
        endpoint_or_runtime_id="runtime.diannan-3090.alphafold3",
        account_or_deployment_digest=DIGEST,
        api_or_route_variant="qualification-v1",
        environment_or_inventory_digest=DIGEST,
        policy_digest=DIGEST,
        source_observation_digest=DIGEST,
    )
    dry_plan = ExternalQualificationDryPlan.create(
        plan_id="qualification.alphafold.live-runtime.dry-plan",
        batch_id="batch-2-alphafold",
        source_digest=DIGEST,
        readiness_plan_digest=readiness.plan_digest,
        discovery_report_digest=DIGEST,
        unit_bindings=(
            ExternalQualificationUnitSubjectBinding(
                unit_digest=unit.unit_digest,
                profile_id="alphafold",
                subject_digest=subject.subject_digest,
            ),
        ),
        subjects=(subject,),
        budgets=(
            ExternalQualificationBudgetPolicy(
                "budget.batch-2.cash",
                "batch-2-alphafold",
                "cash",
                25,
                100,
                "usd",
            ),
        ),
        credential_locator_ids=(),
        effect_policies=(
            ExternalQualificationEffectPolicy(
                "qualification.alphafold.fixed-inference",
                "batch-2-alphafold",
                True,
                "cleanup.alphafold.workspace",
                1_800,
            ),
        ),
        fault_policies=(
            ExternalQualificationFaultPolicy(
                "response.loss",
                "scientific-route.terminal",
                True,
            ),
        ),
        ttl_policies=(
            ExternalQualificationTtlPolicy("ttl.alphafold", "alphafold", 604_800),
        ),
        storage_policy=ExternalQualificationStoragePolicy(
            ledger_id="qualification.ledger.sqlite",
            private_evidence_root_id="qualification.evidence.private",
            public_export_secret_safe=True,
            credential_material_persisted=False,
        ),
        max_retries=0,
        created_at=OBSERVED_AT,
        live_effect_authorized=False,
    )
    authorization = ExternalQualificationOccurrenceAuthorization.create(
        authorization_id="authorization.alphafold.live-runtime.test",
        dry_plan_digest=dry_plan.dry_plan_digest,
        batch_id="batch-2-alphafold",
        operator_id="operator.enzymedesign-owner",
        authorized_at=OBSERVED_AT,
    )
    return readiness, dry_plan, authorization


def test_alphafold_negative_gate_uses_terminal_no_redispatch_policy() -> None:
    readiness, dry_plan, authorization = _alphafold_plans()

    digest = exercise_live_qualification_negative_gate(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        observed_at=OBSERVED_AT,
    )

    assert digest.startswith("sha256:")


@dataclass
class _Bridge:
    binding: object
    calls: dict[str, int]

    def dispatch(self, request):
        self.calls["dispatch"] += 1
        if request.operation == "response-loss-reconcile":
            return ExternalQualificationProbeOutcome(
                attempt_id=request.attempt_id,
                request_digest=request.request_digest,
                disposition=ExternalQualificationProbeDisposition.RECONCILE_REQUIRED,
                effect_certainty=ExternalEffectCertainty.DISPATCH_IN_DOUBT,
                observed_operation=None,
                output_digest=None,
                observed_result_schema_digest=None,
                backend_receipt_digest=DIGEST,
                error_code="qualification_response_lost",
                external_effect_performed=True,
                credential_material_accessed=False,
                fallback_performed=False,
            )
        return self._success(request)

    def reconcile(self, request):
        self.calls["reconcile"] += 1
        return self._success(request)

    def restore_dispatched_attempt(self, request):
        self.calls["restore"] += 1

    @staticmethod
    def _success(request):
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


@dataclass
class _Cleanup:
    calls: int = 0

    def cleanup(self):
        self.calls += 1
        return {
            "openzyme.workspace.git.lfs": {
                "workspace_removed": True,
                "repository_preserved": True,
            }
        }


def _router(
    readiness,
    dry_plan,
    authorization,
    calls,
    *,
    selected_unit_digests=None,
    built_unit_digests=None,
):
    def builder(binding):
        if built_unit_digests is not None:
            built_unit_digests.append(binding.unit_digest)
        return _Bridge(binding, calls)

    return SelectedQualificationProbeRouter(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        observed_at=OBSERVED_AT,
        bridge_builders={
            "enzymedesign.bio-provider-http": builder,
            "openzyme.workspace.git.lfs": builder,
        },
        selected_unit_digests=selected_unit_digests,
    )


def test_live_coordinator_records_reconcile_terminal_receipts_and_restores_without_redispatch(
    tmp_path,
) -> None:
    readiness, dry_plan, authorization = _plans()
    ledger = SQLiteProtectedQualificationLedger(tmp_path / "qualification.sqlite3")
    calls = {"dispatch": 0, "reconcile": 0, "restore": 0}
    cleanup = _Cleanup()
    first = ExternalLiveQualificationCoordinator(
        source_identity_digest=DIGEST,
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        router=_router(readiness, dry_plan, authorization, calls),
        ledger=ledger,
        cleanup_port=cleanup,
    ).execute(observed_at=OBSERVED_AT)

    assert first.qualified is True
    assert len(first.receipts) == 2
    assert first.cleanup_resources["openzyme.workspace.git.lfs"] == {
        "workspace_removed": True,
        "repository_preserved": True,
    }
    assert set(first.budget_settlements) == {
        unit.unit_digest for unit in readiness.units
    }
    assert calls == {"dispatch": 2, "reconcile": 1, "restore": 0}

    restored_calls = {"dispatch": 0, "reconcile": 0, "restore": 0}
    restored = ExternalLiveQualificationCoordinator(
        source_identity_digest=DIGEST,
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        router=_router(readiness, dry_plan, authorization, restored_calls),
        ledger=ledger,
        cleanup_port=cleanup,
    ).execute(observed_at=OBSERVED_AT)

    assert restored.qualified is True
    assert restored.report_digest == first.report_digest
    assert restored.cleanup_resources == first.cleanup_resources
    assert restored.budget_settlements == first.budget_settlements
    assert restored_calls == {"dispatch": 0, "reconcile": 0, "restore": 0}


def test_live_coordinator_restores_cleanup_context_after_outcome_only_crash(
    tmp_path,
) -> None:
    readiness, dry_plan, authorization = _plans()
    first_ledger = SQLiteProtectedQualificationLedger(tmp_path / "first.sqlite3")
    first = ExternalLiveQualificationCoordinator(
        source_identity_digest=DIGEST,
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        router=_router(
            readiness,
            dry_plan,
            authorization,
            {"dispatch": 0, "reconcile": 0, "restore": 0},
        ),
        ledger=first_ledger,
        cleanup_port=_Cleanup(),
    ).execute(observed_at=OBSERVED_AT)
    outcome_only_ledger = SQLiteProtectedQualificationLedger(
        tmp_path / "outcome-only.sqlite3"
    )
    for unit_digest, outcome in first.outcomes:
        outcome_only_ledger.record_probe_outcome(
            dry_plan_digest=dry_plan.dry_plan_digest,
            authorization_digest=authorization.authorization_digest,
            unit_digest=unit_digest,
            outcome=outcome,
        )
    calls = {"dispatch": 0, "reconcile": 0, "restore": 0}

    restored = ExternalLiveQualificationCoordinator(
        source_identity_digest=DIGEST,
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=authorization,
        operator_id="operator.enzymedesign-owner",
        router=_router(readiness, dry_plan, authorization, calls),
        ledger=outcome_only_ledger,
        cleanup_port=_Cleanup(),
    ).execute(observed_at=OBSERVED_AT)

    assert restored.qualified is True
    assert calls == {"dispatch": 0, "reconcile": 0, "restore": 1}


def test_followup_occurrences_bind_exact_subsets_and_aggregate_receipts(
    tmp_path,
) -> None:
    readiness, dry_plan, first_authorization = _plans()
    first_unit, response_unit = readiness.units
    ledger = SQLiteProtectedQualificationLedger(tmp_path / "qualification.sqlite3")
    first_calls = {"dispatch": 0, "reconcile": 0, "restore": 0}
    first_built: list[str] = []
    first = ExternalLiveQualificationCoordinator(
        source_identity_digest=DIGEST,
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=first_authorization,
        operator_id="operator.enzymedesign-owner",
        router=_router(
            readiness,
            dry_plan,
            first_authorization,
            first_calls,
            selected_unit_digests=(first_unit.unit_digest,),
            built_unit_digests=first_built,
        ),
        ledger=ledger,
        cleanup_port=_Cleanup(),
    ).execute(
        observed_at=OBSERVED_AT,
        selected_unit_digests=(first_unit.unit_digest,),
    )

    assert first.occurrence_qualified is True
    assert first.qualified is False
    assert first.selected_unit_digests == (first_unit.unit_digest,)
    assert first_calls == {"dispatch": 1, "reconcile": 0, "restore": 0}
    assert first_built == [first_unit.unit_digest]

    try:
        ExternalLiveQualificationCoordinator(
            source_identity_digest=DIGEST,
            dry_plan=dry_plan,
            readiness_plan=readiness,
            authorization=first_authorization,
            operator_id="operator.enzymedesign-owner",
            router=_router(
                readiness,
                dry_plan,
                first_authorization,
                first_calls,
                selected_unit_digests=(first_unit.unit_digest,),
            ),
            ledger=ledger,
            cleanup_port=_Cleanup(),
        ).execute(observed_at=OBSERVED_AT)
    except ExternalQualificationError as exc:
        assert exc.error_code == "qualification_occurrence_scope_drift"
    else:
        raise AssertionError("same authority accepted a broader occurrence scope")

    partial = verify_live_qualification_receipt_set(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        source_identity_digest=DIGEST,
        operator_id="operator.enzymedesign-owner",
        authorizations=(first_authorization,),
        ledger=ledger,
        verified_at=OBSERVED_AT,
    )
    assert partial.qualified is False
    assert partial.missing_unit_digests == (response_unit.unit_digest,)
    source_drifted = verify_live_qualification_receipt_set(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        source_identity_digest="sha256:" + "2" * 64,
        operator_id="operator.enzymedesign-owner",
        authorizations=(first_authorization,),
        ledger=ledger,
        verified_at=OBSERVED_AT,
    )
    assert source_drifted.qualified is False
    assert source_drifted.missing_unit_digests == tuple(
        sorted((first_unit.unit_digest, response_unit.unit_digest))
    )
    assert source_drifted.rejected_receipts == (
        (
            first.receipts[0].receipt_digest,
            "qualification_receipt_set_source_identity_drift",
        ),
    )

    second_authorization = ExternalQualificationOccurrenceAuthorization.create(
        authorization_id="authorization.live-runtime.followup",
        dry_plan_digest=dry_plan.dry_plan_digest,
        batch_id="batch-1",
        operator_id="operator.enzymedesign-owner",
        authorized_at=OBSERVED_AT,
    )
    second_calls = {"dispatch": 0, "reconcile": 0, "restore": 0}
    second = ExternalLiveQualificationCoordinator(
        source_identity_digest=DIGEST,
        dry_plan=dry_plan,
        readiness_plan=readiness,
        authorization=second_authorization,
        operator_id="operator.enzymedesign-owner",
        router=_router(
            readiness,
            dry_plan,
            second_authorization,
            second_calls,
            selected_unit_digests=(response_unit.unit_digest,),
        ),
        ledger=ledger,
        cleanup_port=_Cleanup(),
    ).execute(
        observed_at=OBSERVED_AT,
        selected_unit_digests=(response_unit.unit_digest,),
    )

    assert second.occurrence_qualified is True
    assert second.qualified is False
    assert second_calls == {"dispatch": 1, "reconcile": 1, "restore": 0}
    complete = verify_live_qualification_receipt_set(
        dry_plan=dry_plan,
        readiness_plan=readiness,
        source_identity_digest=DIGEST,
        operator_id="operator.enzymedesign-owner",
        authorizations=(first_authorization, second_authorization),
        ledger=ledger,
        verified_at=OBSERVED_AT,
    )

    assert complete.qualified is True
    assert len(complete.selected_receipts) == 2
    assert complete.missing_unit_digests == ()
    assert complete.authorization_digests == tuple(
        sorted(
            (
                first_authorization.authorization_digest,
                second_authorization.authorization_digest,
            )
        )
    )


def test_scientific_receipts_require_their_route_cleanup_closure() -> None:
    local = _unit(
        "enzymedesign.vina.local",
        "dock",
        "enzymedesign.vina.local.dock@1",
        "podman.local",
    )
    hpc = _unit(
        "enzymedesign.hmmer.hpc",
        "hmmbuild",
        "enzymedesign.hmmer.hpc.hmmbuild@1",
        "hpc.diannan",
    )

    assert _unit_cleanup_ok(local, {}) is False
    assert _unit_cleanup_ok(
        local,
        {"openzyme.process.podman": {"container_absent": True}},
    ) is True
    assert _unit_cleanup_ok(
        hpc,
        {
            "openzyme.hpc.ssh": {
                "workspace_removed": True,
                "control_master_closed": True,
            },
            "openzyme.hpc.slurm": {
                "scheduler_cleanup_attempted": True,
                "command_accepted": False,
            },
        },
    ) is False
    assert _unit_cleanup_ok(
        hpc,
        {
            "openzyme.hpc.ssh": {
                "workspace_removed": True,
                "control_master_closed": True,
            },
            "openzyme.hpc.slurm": {
                "scheduler_cleanup_attempted": True,
                "command_accepted": True,
            },
        },
    ) is True
