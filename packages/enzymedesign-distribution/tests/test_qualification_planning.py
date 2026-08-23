from dataclasses import replace
import json
from pathlib import Path

import pytest

from enzymedesign_distribution import OPTIONAL_PROFILES
from enzymedesign_distribution import PlanOnlyQualificationBackendFactory
from enzymedesign_distribution import PlanOnlyIdentityPreparationBackendFactory
from enzymedesign_distribution import QualificationBudgetLedger
from enzymedesign_distribution import build_enzymedesign_external_qualification_plan
from enzymedesign_distribution import load_safe_identity_snapshot
from enzymedesign_distribution import load_operator_identity_resolution_selections
from enzymedesign_distribution import qualification_plan_bundle
from openzyme_contracts import ExternalQualificationError
from openzyme_contracts import ExternalQualificationOperationObservation
from openzyme_contracts import ExternalSubjectIdentityStatus
from openzyme_contracts import ExternalIdentityPreparationResult
from openzyme_contracts import SafeIdentityField
from openzyme_contracts import canonical_sha256_digest
from openzyme_process_podman import load_qualification_image_manifest
from openzyme_process_podman import qualification_image_identity_field_ids


REPO_ROOT = Path(__file__).resolve().parents[3]
SNAPSHOT = (
    REPO_ROOT
    / "openspec/changes/qualify-enzymedesign-external-capability-routes/operator"
    / "safe-identity-snapshot-20260822.json"
)
SELECTIONS = (
    REPO_ROOT
    / "openspec/changes/qualify-enzymedesign-external-capability-routes/operator"
    / "approved-identity-resolution-selections-20260822.json"
)


def _bundle(*, with_selections: bool = True):
    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.current",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    return qualification_plan_bundle(
        readiness_plan=readiness,
        snapshot=snapshot,
        selection_set=(
            load_operator_identity_resolution_selections(SELECTIONS)
            if with_selections
            else None
        ),
    )


def test_current_safe_snapshot_covers_all_units_and_emits_two_blocked_plans() -> None:
    bundle = _bundle()
    assert bundle["claim"] == "plan_only"
    assert bundle["credential_material_accessed"] is False
    assert bundle["external_effect_performed"] is False
    summary = bundle["summary"]
    assert summary == {
        "observation_count": 16,
        "resolved_observation_count": 3,
        "gap_count": 13,
        "decision_count": 13,
        "batch_1_preparation_authorizable": True,
        "batch_2_preparation_authorizable": True,
        "batch_1_authorizable": False,
        "batch_2_authorizable": False,
    }
    plans = bundle["dry_plans"]
    assert len(plans[0]["unit_bindings"]) == 44
    assert len(plans[1]["unit_bindings"]) == 1
    assert plans[0]["live_effect_authorized"] is False
    assert plans[1]["live_effect_authorized"] is False
    preparation_plans = bundle["identity_preparation_plans"]
    assert len(preparation_plans) == 2
    assert preparation_plans[0]["authorizable"] is True
    assert preparation_plans[0]["live_effect_authorized"] is False
    assert preparation_plans[1]["authorizable"] is True
    assert bundle["external_effect_performed"] is False


def test_alphafold_batch_2_preparation_is_read_only_and_exact() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    original = load_operator_identity_resolution_selections(SELECTIONS)
    selections = replace(
        original,
        selection_set_id="operator-confirmed-alphafold-test",
        selections=tuple(
            replace(
                item,
                candidate_id="observe-existing-alphafold3-resource-closure",
            )
            if item.projection_id == "alphafold-hpc"
            else item
            for item in original.selections
        ),
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.alphafold-preparation",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selections,
        ),
        selection_set=selections,
        batch=ExternalQualificationBatch.BATCH_2_ALPHAFOLD,
    )

    assert plan.batch_id == "batch-2-alphafold"
    assert len(plan.actions) == 1
    action = plan.actions[0]
    assert action.effect_id == "hpc.alphafold3.resource-identity.observe"
    assert action.credential_locator_id == "credential.hpc.diannan.qualification"
    assert action.mutating is False
    assert action.cleanup_action_id is None
    assert action.cleanup_deadline_seconds is None
    assert "fixed_monomer_input_digest" in action.expected_identity_fields
    assert "alphafold_version" in action.expected_identity_fields


def test_alphafold_preparation_projects_version_and_resource_identity() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import apply_external_identity_preparation_results
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities
    from enzymedesign_distribution import project_external_identity_discovery_snapshot
    from openzyme_contracts import create_external_identity_preparation_success

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    original = load_operator_identity_resolution_selections(SELECTIONS)
    selections = replace(
        original,
        selection_set_id="operator-confirmed-alphafold-projection-test",
        selections=tuple(
            replace(
                item,
                candidate_id="observe-existing-alphafold3-resource-closure",
            )
            if item.projection_id == "alphafold-hpc"
            else item
            for item in original.selections
        ),
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.alphafold-projection",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selections,
        ),
        selection_set=selections,
        batch=ExternalQualificationBatch.BATCH_2_ALPHAFOLD,
    )
    action = plan.actions[0]
    values = {
        field_id: (
            "credential.hpc.diannan.qualification"
            if field_id == "credential_locator_id"
            else "3.0.1"
            if field_id == "alphafold_version"
            else "a" * 40
            if field_id == "alphafold_source_commit"
            else "sha256:" + "1" * 64
        )
        for field_id in action.expected_identity_fields
    }
    result = create_external_identity_preparation_success(
        occurrence_id="occurrence.preparation.alphafold-projection",
        preparation_plan_digest=plan.preparation_plan_digest,
        authorization_digest="sha256:" + "2" * 64,
        action_id=action.action_id,
        owner_component_id=action.owner_component_id,
        effect_id=action.effect_id,
        input_binding_digest=action.input_binding_digest,
        request_digest="sha256:" + "3" * 64,
        safe_identity_fields=tuple(
            SafeIdentityField(field_id, values[field_id])
            for field_id in action.expected_identity_fields
        ),
        receipt_payload={"action_id": action.action_id},
        external_effect_performed=True,
        credential_material_accessed=True,
    )
    prepared = apply_external_identity_preparation_results(
        snapshot=project_external_identity_discovery_snapshot(
            snapshot=snapshot,
            discovery=discovery,
        ),
        preparation_plan=plan,
        results=(result,),
        observed_at="2026-08-24T00:00:00+08:00",
    )
    projection = next(
        item for item in prepared.projections if item.projection_id == "alphafold-hpc"
    )
    fields = {item.field_id: item.value for item in projection.safe_fields}

    assert fields["alphafold_version"] == "3.0.1"
    assert fields["alphafold_wrapper_digest"] == "sha256:" + "1" * 64
    rediscovered = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=prepared,
    )
    observation = next(
        item
        for item in rediscovered.observations
        if item.observation_id == "observation.alphafold-hpc"
    )
    assert observation.status is ExternalSubjectIdentityStatus.RESOLVED
    assert observation.missing_fields == ()


def test_alphafold_config_reconciles_only_authority_fields(tmp_path: Path) -> None:
    from enzymedesign_distribution.qualification_preparation_runtime import (
        _persist_exact_alphafold_config,
    )

    parent = tmp_path / "alphafold-qualification"
    parent.mkdir(mode=0o700)
    path = parent / "config.json"

    def config(plan: str, authority: str, resource: str) -> dict[str, object]:
        payload: dict[str, object] = {
            "schema_version": "enzymedesign_alphafold_qualification_config@1",
            "image_digest": resource,
            "preparation_plan_digest": plan,
            "preparation_authorization_digest": authority,
        }
        payload["config_digest"] = canonical_sha256_digest(payload)
        return payload

    initial = config("sha256:" + "1" * 64, "sha256:" + "2" * 64, "resource-a")
    assert _persist_exact_alphafold_config(path, initial) is None
    assert path.stat().st_mode & 0o777 == 0o600

    rebound = config("sha256:" + "3" * 64, "sha256:" + "4" * 64, "resource-a")
    assert _persist_exact_alphafold_config(path, rebound) == initial["config_digest"]
    assert json.loads(path.read_text(encoding="utf-8")) == rebound

    drifted = config("sha256:" + "5" * 64, "sha256:" + "6" * 64, "resource-b")
    with pytest.raises(ExternalQualificationError) as captured:
        _persist_exact_alphafold_config(path, drifted)
    assert captured.value.error_code == "qualification_alphafold_config_subject_drift"
    assert json.loads(path.read_text(encoding="utf-8")) == rebound


def test_operator_decisions_preserve_local_only_git_and_two_phase_authority() -> None:
    bundle = _bundle()
    selection_set = bundle["operator_selection_set"]
    assert "git-local-only-no-hosted-sync" in selection_set["constraints"]
    git_selection = next(
        item
        for item in selection_set["selections"]
        if item["projection_id"] == "git-primary"
    )
    assert git_selection["candidate_id"] == ("create-local-isolated-git-lfs-repository")
    batch_1 = bundle["identity_preparation_plans"][0]
    git_action = next(
        item
        for item in batch_1["actions"]
        if item["logical_subject_id"] == "git.primary"
    )
    assert git_action["effect_id"] == "git-lfs.local-isolated-repository.create"
    assert batch_1["live_effect_authorized"] is False
    assert bundle["dry_plans"][0]["authorizable"] is False


def test_batch_1_preparation_has_one_hpc_effect_and_unique_image_effects() -> None:
    batch_1 = _bundle()["identity_preparation_plans"][0]
    actions = batch_1["actions"]
    assert len(actions) == 7
    assert all(item["owner_component_id"] for item in actions)
    assert all(item["input_schema_id"].endswith("@1") for item in actions)
    assert all(item["safe_input_fields"] for item in actions)
    assert all(item["input_binding_digest"].startswith("sha256:") for item in actions)
    assert {
        item["credential_locator_id"]
        for item in actions
        if item["credential_locator_id"] is not None
    } == set(batch_1["credential_locator_ids"])

    hpc_actions = [
        item
        for item in actions
        if item["effect_id"] == "hpc.executor-workspace-v2.identity-resolve"
    ]
    assert len(hpc_actions) == 1
    assert hpc_actions[0]["action_id"] == "prepare.batch-1.hpc-primary"
    assert len(hpc_actions[0]["gap_digests"]) == 4
    assert len(hpc_actions[0]["decision_digests"]) == 4
    assert "credential_locator_id" in hpc_actions[0]["expected_identity_fields"]

    image_actions = [
        item for item in actions if item["effect_id"].startswith("podman.")
    ]
    assert len(image_actions) == 3
    assert len({item["effect_id"] for item in image_actions}) == 3
    assert len({item["cleanup_action_id"] for item in image_actions}) == 3
    image_groups = {
        next(
            field["value"]
            for field in item["safe_input_fields"]
            if field["field_id"] == "image_group"
        )
        for item in image_actions
    }
    assert image_groups == {"base", "hmmer", "docking"}
    for action in image_actions:
        image_group = next(
            field["value"]
            for field in action["safe_input_fields"]
            if field["field_id"] == "image_group"
        )
        assert tuple(action["expected_identity_fields"]) == (
            qualification_image_identity_field_ids(image_group)
        )


def test_batch_without_identity_gaps_omits_noop_preparation_plan() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import discover_external_subject_identities
    from enzymedesign_distribution.qualification_planning import _batch_identity_gaps

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.current",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    gaps = build_external_identity_gaps(
        discover_external_subject_identities(
            readiness_plan=readiness,
            snapshot=snapshot,
        )
    )
    alphafold_gap = tuple(
        gap for gap in gaps if gap.logical_subject_id == "alphafold.hpc"
    )

    assert _batch_identity_gaps(
        readiness_plan=readiness,
        gaps=alphafold_gap,
        batch=ExternalQualificationBatch.BATCH_1,
    ) == ()
    assert _batch_identity_gaps(
        readiness_plan=readiness,
        gaps=alphafold_gap,
        batch=ExternalQualificationBatch.BATCH_2_ALPHAFOLD,
    ) == alphafold_gap


def test_llm_and_tavily_budgets_are_generous_circuit_breakers() -> None:
    batch_1 = _bundle()["dry_plans"][0]
    budgets = {item["budget_id"]: item for item in batch_1["budgets"]}
    assert budgets["budget.llm.cash"]["warning_limit"] == 50
    assert budgets["budget.llm.cash"]["hard_limit"] == 100
    assert budgets["budget.tavily.cash"]["warning_limit"] == 20
    assert budgets["budget.tavily.cash"]["hard_limit"] == 50
    assert budgets["budget.batch-1.cash"]["hard_limit"] == 250
    assert batch_1["max_retries"] == 0


def test_budget_warning_does_not_block_but_hard_limit_fails_before_dispatch() -> None:
    from openzyme_contracts import ExternalQualificationBudgetPolicy

    ledger = QualificationBudgetLedger(
        (
            ExternalQualificationBudgetPolicy(
                "budget.llm.cash", "llm", "cash", 5, 25, "usd"
            ),
        )
    )
    warning = ledger.reserve(
        reservation_id="occurrence.llm.1",
        budget_id="budget.llm.cash",
        amount=10,
    )
    assert warning.warning_crossed is True
    ledger.settle(reservation_id=warning.reservation_id, actual_amount=8)

    with pytest.raises(ExternalQualificationError) as captured:
        ledger.reserve(
            reservation_id="occurrence.llm.2",
            budget_id="budget.llm.cash",
            amount=18,
        )
    assert captured.value.error_code == "blocked_budget"


def test_safe_snapshot_parser_rejects_unallowlisted_secret_field(
    tmp_path: Path,
) -> None:
    payload = json.loads(SNAPSHOT.read_text(encoding="utf-8"))
    payload["api_key"] = "sk-secret-material-123456789"
    unsafe = tmp_path / "unsafe.json"
    unsafe.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ExternalQualificationError) as captured:
        load_safe_identity_snapshot(unsafe)
    assert captured.value.error_code == "qualification_safe_snapshot_field_forbidden"
    assert "secret-material" not in str(captured.value)


def test_resolved_subject_with_out_of_range_version_becomes_drifted_gap() -> None:
    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    generic_fields = next(
        projection.safe_fields
        for projection in snapshot.projections
        if projection.projection_id == "bio-uniprot-public"
    )
    vina = next(
        projection
        for projection in snapshot.projections
        if projection.projection_id == "vina-local"
    )
    drifted_vina = replace(
        vina,
        status=ExternalSubjectIdentityStatus.RESOLVED,
        safe_fields=(
            *generic_fields,
            SafeIdentityField(
                "docking_image_recipe_digest",
                load_qualification_image_manifest()
                .recipe("docking")
                .recipe_digest,
            ),
            SafeIdentityField("vina_image_digest", "sha256:" + "2" * 64),
            SafeIdentityField("vina_version", "1.1.2"),
        ),
        missing_fields=(),
    )
    snapshot = replace(
        snapshot,
        projections=tuple(
            drifted_vina
            if item.projection_id == drifted_vina.projection_id
            else item
            for item in snapshot.projections
        ),
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.version-drift",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    from enzymedesign_distribution import discover_external_subject_identities

    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    observation = next(
        item
        for item in discovery.observations
        if item.logical_subject_id == "local"
        and any(
            unit.component_id == "enzymedesign.vina.local"
            and unit.unit_digest in item.affected_unit_digests
            for unit in readiness.units
        )
    )

    assert observation.status is ExternalSubjectIdentityStatus.DRIFTED
    assert observation.missing_fields == (
        "vina_version_satisfies_declared_spec",
    )


@pytest.mark.parametrize(
    ("recipe_fields", "expected_missing_field"),
    (
        ((), "docking_image_recipe_digest"),
        (
            (
                SafeIdentityField(
                    "docking_image_recipe_digest",
                    "sha256:" + "0" * 64,
                ),
            ),
            "docking_image_recipe_digest_matches_current_source",
        ),
    ),
)
def test_resolved_local_image_requires_current_source_recipe_digest(
    recipe_fields: tuple[SafeIdentityField, ...],
    expected_missing_field: str,
) -> None:
    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    generic_fields = next(
        projection.safe_fields
        for projection in snapshot.projections
        if projection.projection_id == "bio-uniprot-public"
    )
    vina = next(
        projection
        for projection in snapshot.projections
        if projection.projection_id == "vina-local"
    )
    resolved_vina = replace(
        vina,
        status=ExternalSubjectIdentityStatus.RESOLVED,
        safe_fields=(
            *generic_fields,
            *recipe_fields,
            SafeIdentityField("vina_image_digest", "sha256:" + "2" * 64),
            SafeIdentityField("vina_version", "1.2.7"),
        ),
        missing_fields=(),
    )
    snapshot = replace(
        snapshot,
        projections=tuple(
            resolved_vina
            if item.projection_id == resolved_vina.projection_id
            else item
            for item in snapshot.projections
        ),
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.recipe-drift",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    from enzymedesign_distribution import discover_external_subject_identities

    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    observation = next(
        item
        for item in discovery.observations
        if item.logical_subject_id == "local"
        and any(
            unit.component_id == "enzymedesign.vina.local"
            and unit.unit_digest in item.affected_unit_digests
            for unit in readiness.units
        )
    )

    expected_status = (
        ExternalSubjectIdentityStatus.PARTIAL
        if not recipe_fields
        else ExternalSubjectIdentityStatus.DRIFTED
    )
    assert observation.status is expected_status
    assert observation.missing_fields == (expected_missing_field,)


def test_stale_image_recipe_predicate_prepares_the_observed_digest_field() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    generic_fields = next(
        projection.safe_fields
        for projection in snapshot.projections
        if projection.projection_id == "bio-uniprot-public"
    )
    vina = next(
        projection
        for projection in snapshot.projections
        if projection.projection_id == "vina-local"
    )
    snapshot = replace(
        snapshot,
        projections=tuple(
            replace(
                vina,
                status=ExternalSubjectIdentityStatus.RESOLVED,
                safe_fields=(
                    *generic_fields,
                    SafeIdentityField(
                        "docking_image_recipe_digest",
                        "sha256:" + "0" * 64,
                    ),
                    SafeIdentityField("vina_image_digest", "sha256:" + "2" * 64),
                    SafeIdentityField("vina_version", "1.2.7"),
                ),
                missing_fields=(),
            )
            if item.projection_id == vina.projection_id
            else item
            for item in snapshot.projections
        ),
    )
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.recipe-replacement",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    selection_set = load_operator_identity_resolution_selections(SELECTIONS)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selection_set,
        ),
        selection_set=selection_set,
        batch=ExternalQualificationBatch.BATCH_1,
    )

    docking = next(
        action
        for action in plan.actions
        if action.action_id == "prepare.batch-1.image-docking"
    )
    assert "docking_image_recipe_digest" in docking.expected_identity_fields
    assert (
        "docking_image_recipe_digest_matches_current_source"
        not in docking.expected_identity_fields
    )


def test_operator_selection_parser_rejects_secret_shaped_identity(
    tmp_path: Path,
) -> None:
    payload = json.loads(SELECTIONS.read_text(encoding="utf-8"))
    payload["operator_id"] = "api_key=sk-secret-material-123456789"
    unsafe = tmp_path / "unsafe-selections.json"
    unsafe.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError):
        load_operator_identity_resolution_selections(unsafe)


class _CountingResolver:
    def __init__(self) -> None:
        self.calls = 0

    def resolve(self, *, locator_id: str) -> object:
        self.calls += 1
        return object()


def test_plan_only_factory_blocks_before_credential_resolution() -> None:
    bundle = _bundle()
    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.current",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_qualification_dry_plan
    from enzymedesign_distribution import build_plan_only_probe_bridge_metadata
    from enzymedesign_distribution import discover_external_subject_identities
    from enzymedesign_distribution import ExternalQualificationBatch

    discovery = discover_external_subject_identities(
        readiness_plan=readiness, snapshot=snapshot
    )
    plan = build_external_qualification_dry_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=build_external_identity_gaps(discovery),
        batch=ExternalQualificationBatch.BATCH_1,
    )
    assert bundle["summary"]["batch_1_authorizable"] is False
    metadata = build_plan_only_probe_bridge_metadata(
        readiness_plan=readiness,
        dry_plan=plan,
    )
    assert len(metadata) == 44
    assert all(item.plan_only for item in metadata)
    assert all(item.selected_binding_digest.startswith("sha256:") for item in metadata)
    resolver = _CountingResolver()
    factory = PlanOnlyQualificationBackendFactory(credential_resolver=resolver)

    with pytest.raises(ExternalQualificationError) as captured:
        factory.build(
            plan=plan,
            authorization=None,
            observed_at="2026-08-22T12:00:00+00:00",
            operator_id="operator.owner",
            locator_id="credential.llm.primary",
        )
    assert captured.value.error_code == "blocked_live_authorization"
    assert resolver.calls == 0


def test_preparation_factory_blocks_before_credential_resolution_or_effect() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    selection_set = load_operator_identity_resolution_selections(SELECTIONS)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.current",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    decisions = build_external_identity_resolution_decisions(
        gaps=gaps,
        snapshot=snapshot,
        selection_set=selection_set,
    )
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=decisions,
        selection_set=selection_set,
        batch=ExternalQualificationBatch.BATCH_1,
    )
    action = next(item for item in plan.actions if item.requires_credential_material)
    resolver = _CountingResolver()
    factory = PlanOnlyIdentityPreparationBackendFactory(credential_resolver=resolver)

    with pytest.raises(ExternalQualificationError) as captured:
        factory.build(
            plan=plan,
            authorization=None,
            observed_at="2026-08-22T14:37:12+00:00",
            occurrence_id="occurrence.preparation.blocked",
            action_id=action.action_id,
            input_binding_digest=action.input_binding_digest,
            locator_id=plan.credential_locator_ids[0],
        )
    assert captured.value.error_code == "blocked_preparation_authorization"
    assert resolver.calls == 0


def test_preparation_factory_rejects_cross_action_credential_locator() -> None:
    from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization

    bundle = _bundle()
    plan_payload = bundle["identity_preparation_plans"][0]
    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    selection_set = load_operator_identity_resolution_selections(SELECTIONS)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.current",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities

    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selection_set,
        ),
        selection_set=selection_set,
        batch=ExternalQualificationBatch.BATCH_1,
    )
    action = next(
        item
        for item in plan.actions
        if item.credential_locator_id == "credential.llm.micuapi.qualification"
    )
    authorization = ExternalIdentityPreparationOccurrenceAuthorization.create(
        authorization_id="authorization.preparation.locator-test",
        preparation_plan_digest=plan.preparation_plan_digest,
        batch_id=plan.batch_id,
        operator_id="operator.owner",
        authorized_at="2026-08-22T14:00:00+00:00",
    )
    resolver = _CountingResolver()
    builder_calls = 0

    def live_builder(**kwargs: object) -> ExternalIdentityPreparationResult:
        nonlocal builder_calls
        builder_calls += 1
        owner_action = kwargs["action"]
        safe_fields = tuple(
            SafeIdentityField(field_id, f"safe-{index}")
            for index, field_id in enumerate(
                owner_action.expected_identity_fields  # type: ignore[union-attr]
            )
        )
        if str(kwargs["occurrence_id"]).endswith("coverage-test"):
            safe_fields = safe_fields[:-1]
        output_digest = canonical_sha256_digest(
            {
                "schema_version": "external_identity_preparation_safe_output@1",
                "action_id": owner_action.action_id,  # type: ignore[union-attr]
                "safe_identity_fields": [item.to_dict() for item in safe_fields],
            }
        )
        observation = ExternalQualificationOperationObservation(
            attempt_id=str(kwargs["occurrence_id"]),
            request_digest=str(kwargs["request_digest"]),
            operation=owner_action.effect_id,  # type: ignore[union-attr]
            effect_certainty="terminal_known",
            terminal=True,
            succeeded=True,
            output_digest=output_digest,
            receipt_digest="sha256:" + "8" * 64,
            error_code=None,
            external_effect_performed=True,
            credential_material_accessed=True,
            fallback_performed=False,
        )
        return ExternalIdentityPreparationResult.create(
            occurrence_id=str(kwargs["occurrence_id"]),
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=owner_action.action_id,  # type: ignore[union-attr]
            owner_component_id=owner_action.owner_component_id,  # type: ignore[union-attr]
            input_binding_digest=owner_action.input_binding_digest,  # type: ignore[union-attr]
            safe_identity_fields=safe_fields,
            observation=observation,
        )

    wrong_owner_factory = PlanOnlyIdentityPreparationBackendFactory(
        credential_resolver=resolver,
        owner_builders={"openzyme.other.owner": live_builder},
    )
    with pytest.raises(ExternalQualificationError) as owner_captured:
        wrong_owner_factory.build(
            plan=plan,
            authorization=authorization,
            observed_at="2026-08-22T14:37:12+00:00",
            occurrence_id="occurrence.preparation.owner-test",
            action_id=action.action_id,
            input_binding_digest=action.input_binding_digest,
            locator_id=action.credential_locator_id,
        )
    assert owner_captured.value.error_code == (
        "qualification_preparation_backend_not_implemented"
    )
    assert resolver.calls == 0
    assert builder_calls == 0

    factory = PlanOnlyIdentityPreparationBackendFactory(
        credential_resolver=resolver,
        owner_builders={action.owner_component_id: live_builder},
    )

    with pytest.raises(ExternalQualificationError) as input_captured:
        factory.build(
            plan=plan,
            authorization=authorization,
            observed_at="2026-08-22T14:37:12+00:00",
            occurrence_id="occurrence.preparation.input-test",
            action_id=action.action_id,
            input_binding_digest="sha256:" + "9" * 64,
            locator_id=action.credential_locator_id,
        )
    assert input_captured.value.error_code == (
        "qualification_preparation_input_binding_mismatch"
    )
    assert resolver.calls == 0
    assert builder_calls == 0

    with pytest.raises(ExternalQualificationError) as captured:
        factory.build(
            plan=plan,
            authorization=authorization,
            observed_at="2026-08-22T14:37:12+00:00",
            occurrence_id="occurrence.preparation.locator-test",
            action_id=action.action_id,
            input_binding_digest=action.input_binding_digest,
            locator_id="credential.tavily.qualification",
        )
    assert plan_payload["preparation_plan_digest"] == plan.preparation_plan_digest
    assert captured.value.error_code == (
        "qualification_preparation_credential_locator_mismatch"
    )
    assert resolver.calls == 0
    assert builder_calls == 0

    with pytest.raises(ExternalQualificationError) as coverage_captured:
        factory.build(
            plan=plan,
            authorization=authorization,
            observed_at="2026-08-22T14:37:12+00:00",
            occurrence_id="occurrence.preparation.coverage-test",
            action_id=action.action_id,
            input_binding_digest=action.input_binding_digest,
            locator_id=action.credential_locator_id,
        )
    assert coverage_captured.value.error_code == (
        "qualification_preparation_result_field_coverage_mismatch"
    )
    assert coverage_captured.value.mutation_applied is True
    assert coverage_captured.value.effect_certainty == "terminal_known"  # type: ignore[attr-defined]
    assert resolver.calls == 1
    assert builder_calls == 1

    result = factory.build(
        plan=plan,
        authorization=authorization,
        observed_at="2026-08-22T14:37:12+00:00",
        occurrence_id="occurrence.preparation.exact-test",
        action_id=action.action_id,
        input_binding_digest=action.input_binding_digest,
        locator_id=action.credential_locator_id,
    )
    assert isinstance(result, ExternalIdentityPreparationResult)
    assert result.observation.operation == action.effect_id
    assert resolver.calls == 2
    assert builder_calls == 2


def test_safe_preparation_without_target_versions_keeps_batch_1_blocked() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import apply_external_identity_preparation_results
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import build_external_qualification_dry_plan
    from enzymedesign_distribution import discover_external_subject_identities
    from enzymedesign_distribution import project_external_identity_discovery_snapshot
    from openzyme_contracts import create_external_identity_preparation_success

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    generic_fields = next(
        projection.safe_fields
        for projection in snapshot.projections
        if projection.projection_id == "bio-uniprot-public"
    )
    existing_docking_fields = {
        "vina-local": (
            SafeIdentityField("vina_image_digest", "sha256:" + "1" * 64),
            SafeIdentityField("vina_version", "1.2.7"),
        ),
        "fpocket-local": (
            SafeIdentityField("fpocket_image_digest", "sha256:" + "1" * 64),
            SafeIdentityField("fpocket_version", "4.2.3"),
        ),
        "preprocess-podman": (
            SafeIdentityField("meeko_version", "0.7.1"),
            SafeIdentityField("openbabel_version", "3.1.1.23"),
            SafeIdentityField("preprocess_image_digest", "sha256:" + "1" * 64),
            SafeIdentityField("rdkit_version", "2026.3.1"),
        ),
    }
    snapshot = replace(
        snapshot,
        projections=tuple(
            replace(
                projection,
                status=ExternalSubjectIdentityStatus.RESOLVED,
                safe_fields=(
                    *generic_fields,
                    *existing_docking_fields[projection.projection_id],
                ),
                missing_fields=(),
            )
            if projection.projection_id in existing_docking_fields
            else projection
            for projection in snapshot.projections
        ),
    )
    selection_set = load_operator_identity_resolution_selections(SELECTIONS)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.current",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    execution_snapshot = project_external_identity_discovery_snapshot(
        snapshot=snapshot,
        discovery=discovery,
    )
    gaps = build_external_identity_gaps(discovery)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selection_set,
        ),
        selection_set=selection_set,
        batch=ExternalQualificationBatch.BATCH_1,
    )
    results = []
    for index, action in enumerate(plan.actions):
        fields = tuple(
            SafeIdentityField(
                field_id,
                (
                    action.credential_locator_id
                    if field_id == "credential_locator_id"
                    else "sha256:" + f"{index + 1:x}" * 64
                    if field_id.endswith("digest")
                    or field_id.endswith("fact")
                    or field_id.endswith("profile")
                    else f"prepared-{field_id}"
                ),
            )
            for field_id in action.expected_identity_fields
        )
        results.append(
            create_external_identity_preparation_success(
                occurrence_id=f"occurrence.preparation.{index}",
                preparation_plan_digest=plan.preparation_plan_digest,
                authorization_digest="sha256:" + "a" * 64,
                action_id=action.action_id,
                owner_component_id=action.owner_component_id,
                effect_id=action.effect_id,
                input_binding_digest=action.input_binding_digest,
                request_digest="sha256:" + f"{index + 1:x}" * 64,
                safe_identity_fields=fields,
                receipt_payload={"action_id": action.action_id},
                external_effect_performed=True,
                credential_material_accessed=action.requires_credential_material,
            )
        )
    prepared_snapshot = apply_external_identity_preparation_results(
        snapshot=execution_snapshot,
        preparation_plan=plan,
        results=tuple(results),
        observed_at="2026-08-23T01:00:00+00:00",
    )
    docking_action = next(
        action
        for action in plan.actions
        if action.action_id == "prepare.batch-1.image-docking"
    )
    docking_result = next(
        result for result in results if result.action_id == docking_action.action_id
    )
    prepared_by_projection = {
        projection.projection_id: {
            field.field_id: field.value for field in projection.safe_fields
        }
        for projection in prepared_snapshot.projections
    }
    docking_result_fields = {
        field.field_id: field.value for field in docking_result.safe_identity_fields
    }
    for projection_id, field_ids in {
        "vina-local": (
            "docking_image_recipe_digest",
            "vina_image_digest",
            "vina_version",
        ),
        "fpocket-local": (
            "docking_image_recipe_digest",
            "fpocket_image_digest",
            "fpocket_version",
        ),
        "preprocess-podman": (
            "docking_image_recipe_digest",
            "meeko_version",
            "openbabel_version",
            "preprocess_image_digest",
            "rdkit_version",
        ),
    }.items():
        assert {
            field_id: prepared_by_projection[projection_id][field_id]
            for field_id in field_ids
        } == {
            field_id: docking_result_fields[field_id] for field_id in field_ids
        }
    exact_readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.batch-1.exact-readiness",
        created_at=prepared_snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
        credential_locator_ids={
            "llm.primary": "credential.llm.micuapi.qualification",
            "research.tavily.primary": "credential.tavily.qualification",
            "git.primary": None,
            "hpc.ssh.primary": "credential.hpc.diannan.qualification",
            "hpc.slurm.primary": "credential.hpc.diannan.qualification",
        },
    )
    rediscovery = discover_external_subject_identities(
        readiness_plan=exact_readiness,
        snapshot=prepared_snapshot,
    )
    remaining_gaps = build_external_identity_gaps(rediscovery)
    dry_plan = build_external_qualification_dry_plan(
        readiness_plan=exact_readiness,
        discovery=rediscovery,
        gaps=remaining_gaps,
        batch=ExternalQualificationBatch.BATCH_1,
    )

    assert dry_plan.authorizable is False
    hpc_science = {
        observation.observation_id: observation
        for observation in rediscovery.observations
        if observation.observation_id
        in {
            "observation.hmmer-hpc",
            "observation.vina-hpc",
            "observation.fpocket-hpc",
        }
    }
    assert set(hpc_science) == {
        "observation.hmmer-hpc",
        "observation.vina-hpc",
        "observation.fpocket-hpc",
    }
    assert all(
        observation.status is ExternalSubjectIdentityStatus.PARTIAL
        for observation in hpc_science.values()
    )
    assert {
        field
        for observation in hpc_science.values()
        for field in observation.missing_fields
    } == {"hmmer_version", "vina_version", "fpocket_version"}
    assert set(dry_plan.credential_locator_ids) == {
        "credential.llm.micuapi.qualification",
        "credential.tavily.qualification",
        "credential.hpc.diannan.qualification",
    }


def test_batch_executor_dispatches_each_exact_action_once_and_can_resume() -> None:
    from enzymedesign_distribution import ExternalQualificationBatch
    from enzymedesign_distribution import build_external_identity_gaps
    from enzymedesign_distribution import build_external_identity_preparation_plan
    from enzymedesign_distribution import build_external_identity_resolution_decisions
    from enzymedesign_distribution import discover_external_subject_identities
    from enzymedesign_distribution import (
        execute_enzymedesign_identity_preparation_batch,
    )
    from openzyme_contracts import ExternalIdentityPreparationOccurrenceAuthorization
    from openzyme_contracts import create_external_identity_preparation_success

    snapshot = load_safe_identity_snapshot(SNAPSHOT)
    selection_set = load_operator_identity_resolution_selections(SELECTIONS)
    readiness = build_enzymedesign_external_qualification_plan(
        plan_id="qualification.readiness.execution-test",
        created_at=snapshot.observed_at,
        enabled_optional_profiles=OPTIONAL_PROFILES,
    )
    discovery = discover_external_subject_identities(
        readiness_plan=readiness,
        snapshot=snapshot,
    )
    gaps = build_external_identity_gaps(discovery)
    plan = build_external_identity_preparation_plan(
        readiness_plan=readiness,
        discovery=discovery,
        gaps=gaps,
        decisions=build_external_identity_resolution_decisions(
            gaps=gaps,
            snapshot=snapshot,
            selection_set=selection_set,
        ),
        selection_set=selection_set,
        batch=ExternalQualificationBatch.BATCH_1,
    )
    authorization = ExternalIdentityPreparationOccurrenceAuthorization.create(
        authorization_id="authorization.preparation.execution-test",
        preparation_plan_digest=plan.preparation_plan_digest,
        batch_id="batch-1",
        operator_id="operator.owner",
        authorized_at="2026-08-23T00:00:00+00:00",
    )
    calls: list[str] = []
    recorded: list[ExternalIdentityPreparationResult] = []

    def owner_builder(**kwargs: object) -> ExternalIdentityPreparationResult:
        action = kwargs["action"]
        calls.append(action.action_id)  # type: ignore[union-attr]
        safe_fields = tuple(
            SafeIdentityField(
                field_id,
                (
                    action.credential_locator_id  # type: ignore[union-attr]
                    if field_id == "credential_locator_id"
                    else "sha256:" + "7" * 64
                    if field_id.endswith(("digest", "fact", "profile"))
                    else f"prepared-{field_id}"
                ),
            )
            for field_id in action.expected_identity_fields  # type: ignore[union-attr]
        )
        return create_external_identity_preparation_success(
            occurrence_id=str(kwargs["occurrence_id"]),
            preparation_plan_digest=plan.preparation_plan_digest,
            authorization_digest=authorization.authorization_digest,
            action_id=action.action_id,  # type: ignore[union-attr]
            owner_component_id=action.owner_component_id,  # type: ignore[union-attr]
            effect_id=action.effect_id,  # type: ignore[union-attr]
            input_binding_digest=action.input_binding_digest,  # type: ignore[union-attr]
            request_digest=str(kwargs["request_digest"]),
            safe_identity_fields=safe_fields,
            receipt_payload={"action_id": action.action_id},  # type: ignore[union-attr]
            external_effect_performed=True,
            credential_material_accessed=action.requires_credential_material,  # type: ignore[union-attr]
        )

    factory = PlanOnlyIdentityPreparationBackendFactory(
        credential_resolver=_CountingResolver(),
        owner_builders={
            action.owner_component_id: owner_builder for action in plan.actions
        },
        result_recorder=recorded.append,
    )
    execution = execute_enzymedesign_identity_preparation_batch(
        plan=plan,
        authorization=authorization,
        snapshot=snapshot,
        factory=factory,
        clock=lambda: "2026-08-23T01:00:00+00:00",
    )

    assert calls == [item.action_id for item in plan.actions]
    assert tuple(recorded) == execution.results
    assert not any(
        projection.missing_fields
        for projection in execution.prepared_snapshot.projections
        if projection.projection_id != "alphafold-hpc"
    )

    resumed = execute_enzymedesign_identity_preparation_batch(
        plan=plan,
        authorization=authorization,
        snapshot=snapshot,
        factory=factory,
        clock=lambda: "2026-08-23T01:00:00+00:00",
        existing_results=execution.results,
    )
    assert resumed.results == execution.results
    assert len(calls) == len(plan.actions)
