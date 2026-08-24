from __future__ import annotations

from datetime import UTC
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from enzymedesign_distribution import CutoverQuiescenceSeal
from enzymedesign_distribution import CutoverMonitoringSnapshot
from enzymedesign_distribution import CutoverRollbackReceipt
from enzymedesign_distribution import CutoverStartupProof
from enzymedesign_distribution import FirstLiveBoundaryReceipt
from enzymedesign_distribution import PostCutoverSmokeAuthority
from enzymedesign_distribution import PostCutoverSmokePlan
from enzymedesign_distribution import PostCutoverSmokeReceipt
from enzymedesign_distribution import ProtectedQualifiedRuntimeState
from enzymedesign_distribution import QualificationSourceCompatibilityProof
from enzymedesign_distribution import QualifiedRuntimeAdoptionLedger
from enzymedesign_distribution import QualifiedRuntimeCutoverAuthority
from enzymedesign_distribution import QualifiedRuntimeCutoverError
from enzymedesign_distribution import QualifiedRuntimeCutoverPlan
from enzymedesign_distribution import QualifiedRuntimeCutoverReceipt
from enzymedesign_distribution import backup_manifest_payload
from enzymedesign_distribution import load_adoption_ledger
from enzymedesign_distribution import validate_cutover_startup_admission
from openzyme_contracts import ExternalQualificationSubjectKind
from openzyme_contracts import QualifiedExternalCapabilityFact
from openzyme_contracts import canonical_sha256_digest


_D0 = "sha256:" + "0" * 64
_D1 = "sha256:" + "1" * 64
_NOW = "2026-08-24T10:00:00+08:00"


def _proof(*, drift: bool = False) -> QualificationSourceCompatibilityProof:
    return QualificationSourceCompatibilityProof.create(
        qualification_commit="a" * 40,
        qualification_source_identity_digest=_D0,
        deployment_commit="b" * 40,
        deployment_source_identity_digest=_D1,
        qualification_owner_closure_digest=_D0,
        deployment_owner_closure_digest=_D1 if drift else _D0,
        allowed_cutover_path_set_digest=_D1,
        diff_digest=canonical_sha256_digest({"paths": ["cutover.py"]}),
    )


def _quiescence() -> CutoverQuiescenceSeal:
    return CutoverQuiescenceSeal.create(
        observations=(
            ("host.enzymedesign", "not_installed"),
            ("writer.sqlite", "isolated"),
        ),
        unsettled_effect_count=0,
        unknown_effect_count=0,
        sealed_at=_NOW,
    )


def _plan() -> QualifiedRuntimeCutoverPlan:
    return QualifiedRuntimeCutoverPlan.create(
        plan_id="cutover.enzymedesign.batch-1",
        operator_id="operator.enzymedesign-owner",
        source_compatibility=_proof(),
        dry_plan_digest=_D0,
        qualification_report_digest=_D1,
        receipt_set_report_digest=canonical_sha256_digest({"set": 1}),
        receipt_digests=tuple(
            canonical_sha256_digest({"receipt": index}) for index in range(44)
        ),
        deployment_inventory=(
            ("distribution", _D0),
            ("wheel-lock", _D1),
        ),
        backup_sources=(
            ("adoption-ledger", "/state/adoption.json"),
            ("configuration", "/state/config.json"),
            ("qualification-receipts", "/state/receipts.json"),
            ("sqlite", "/state/openzyme.sqlite3"),
            ("target-inventory", "/state/target.json"),
            ("wheel-lock", "/state/uv.lock"),
        ),
        quiescence=_quiescence(),
        runtime_root=(
            "/home/grtresy/.local/state/openzyme/deployments/"
            "enzymedesign-qualified-runtime"
        ),
        created_at=_NOW,
    )


def _authority(plan: QualifiedRuntimeCutoverPlan) -> QualifiedRuntimeCutoverAuthority:
    return QualifiedRuntimeCutoverAuthority.create(
        authority_id="authority.cutover.enzymedesign.batch-1",
        plan_digest=plan.plan_digest,
        deployment_source_identity_digest=(
            plan.source_compatibility.deployment_source_identity_digest
        ),
        operator_id=plan.operator_id,
        occurrence_id="cutover.enzymedesign.20260824",
        authorized_at=_NOW,
    )


def _facts() -> tuple[QualifiedExternalCapabilityFact, ...]:
    return tuple(
        QualifiedExternalCapabilityFact.create(
            capability_id=f"capability.test-{index}",
            operation="observe",
            route_id=f"route.test-{index}",
            subject_kind=ExternalQualificationSubjectKind.TARGET,
            subject_id=f"subject.test-{index}",
            source_digest=_D0,
            build_digest=_D0,
            configuration_digest=_D0,
            validator_id=f"validator.test-{index}",
            qualification_receipt_digest=canonical_sha256_digest(
                {"receipt": index}
            ),
            valid_until="2026-08-25T10:00:00+08:00",
            unit_digest=canonical_sha256_digest({"unit": index}),
        )
        for index in range(44)
    )


def test_source_compatibility_rejects_qualified_owner_drift() -> None:
    with pytest.raises(
        QualifiedRuntimeCutoverError,
        match="qualified owner closure",
    ):
        _proof(drift=True)


def test_plan_closes_batch_1_and_explicitly_omits_alphafold() -> None:
    plan = _plan()

    assert len(plan.receipt_digests) == 44
    assert plan.to_dict()["alphafold"] == {
        "state": "deferred_optional_profile_capacity_unavailable",
        "qualified": False,
        "adopted": False,
        "cutover": False,
        "advertised": False,
    }
    assert plan.to_dict()["fallback_performed"] is False


def test_quiescence_rejects_unknown_effect() -> None:
    with pytest.raises(QualifiedRuntimeCutoverError, match="zero unsettled"):
        CutoverQuiescenceSeal.create(
            observations=(("host.enzymedesign", "stopped"),),
            unsettled_effect_count=0,
            unknown_effect_count=1,
            sealed_at=_NOW,
        )


def test_protected_state_is_create_once_and_rejects_symlink(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    state = ProtectedQualifiedRuntimeState(root)
    state.write_once("plan", {"value": 1})

    assert state.read("plan") == {"value": 1}
    state.write_once("plan", {"value": 1})
    with pytest.raises(QualifiedRuntimeCutoverError, match="differs"):
        state.write_once("plan", {"value": 2})

    unsafe = tmp_path / "unsafe"
    unsafe.symlink_to(root, target_is_directory=True)
    with pytest.raises(QualifiedRuntimeCutoverError, match="unsafe"):
        ProtectedQualifiedRuntimeState(unsafe).bootstrap()


def test_activation_replace_requires_exact_prior_digest(tmp_path: Path) -> None:
    root = tmp_path / "runtime"
    root.mkdir(mode=0o700)
    state = ProtectedQualifiedRuntimeState(root)
    state.replace_exact("activation", {"epoch": 1}, expected_prior_digest=None)
    prior = canonical_sha256_digest({"epoch": 1})

    state.replace_exact(
        "activation",
        {"epoch": 2},
        expected_prior_digest=prior,
    )
    with pytest.raises(QualifiedRuntimeCutoverError, match="prior deployment"):
        state.replace_exact(
            "activation",
            {"epoch": 3},
            expected_prior_digest=prior,
        )


def test_adoption_startup_cutover_and_first_live_are_distinct() -> None:
    plan = _plan()
    authority = _authority(plan)
    ledger = QualifiedRuntimeAdoptionLedger.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        source_compatibility_digest=plan.source_compatibility.proof_digest,
        facts=_facts(),
        adopted_at=_NOW,
    )
    startup = CutoverStartupProof.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        adoption_ledger_digest=ledger.ledger_digest,
        distribution_digest=_D0,
        mounted_component_count=30,
        admitted_fact_count=44,
        verified_at=_NOW,
    )
    cutover = QualifiedRuntimeCutoverReceipt.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        adoption_ledger_digest=ledger.ledger_digest,
        startup_proof_digest=startup.proof_digest,
        backup_manifest_digest=_D1,
        activated_at=_NOW,
    )
    first_live = FirstLiveBoundaryReceipt.create(
        cutover_receipt_digest=cutover.receipt_digest,
        occurrence_id="smoke.enzymedesign.20260824",
        occurrence_authority_digest=_D0,
        effect_certainty="terminal_known",
        accepted_at=_NOW,
    )

    assert cutover.to_dict()["cutover"] is True
    assert cutover.to_dict()["live_occurrence"] is False
    assert first_live.to_dict()["recovery_boundary"] == (
        "forward_only_preserve_evidence"
    )

    restored = load_adoption_ledger(
        payload=ledger.to_dict(),
        plan=plan,
        authority=authority,
    )
    assert restored.ledger_digest == ledger.ledger_digest


def test_adoption_readback_rejects_tampered_fact() -> None:
    plan = _plan()
    authority = _authority(plan)
    ledger = QualifiedRuntimeAdoptionLedger.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        source_compatibility_digest=plan.source_compatibility.proof_digest,
        facts=_facts(),
        adopted_at=_NOW,
    )
    payload = ledger.to_dict()
    payload["facts"][0]["route_id"] = "route.tampered"

    with pytest.raises(QualifiedRuntimeCutoverError, match="not canonical"):
        load_adoption_ledger(payload=payload, plan=plan, authority=authority)


def test_backup_manifest_closes_present_and_absent_sources(tmp_path: Path) -> None:
    paths = []
    for index, scope in enumerate(
        (
            "adoption-ledger",
            "configuration",
            "qualification-receipts",
            "sqlite",
            "target-inventory",
            "wheel-lock",
        )
    ):
        path = tmp_path / scope
        if index:
            path.write_bytes(scope.encode())
        paths.append((scope, path))

    manifest = backup_manifest_payload(paths)

    assert len(manifest["entries"]) == 6
    assert manifest["entries"][0]["pre_state"] == "absent"
    assert manifest["independently_recoverable"] is True


def test_first_live_rejects_no_effect_boundary() -> None:
    with pytest.raises(QualifiedRuntimeCutoverError, match="accepted or unknown"):
        FirstLiveBoundaryReceipt.create(
            cutover_receipt_digest=_D0,
            occurrence_id="smoke.enzymedesign.no-effect",
            occurrence_authority_digest=_D1,
            effect_certainty="no_effect",
            accepted_at=datetime.now(UTC).isoformat(),
        )


def test_protected_state_bootstraps_only_one_safe_parent(tmp_path: Path) -> None:
    root = tmp_path / "deployments" / "runtime"
    state = ProtectedQualifiedRuntimeState(root)

    state.bootstrap()

    assert root.stat().st_mode & 0o777 == 0o700
    assert root.parent.stat().st_mode & 0o777 == 0o700


def test_monitoring_requires_healthy_complete_adoption() -> None:
    with pytest.raises(QualifiedRuntimeCutoverError, match="healthy 44-fact"):
        CutoverMonitoringSnapshot.create(
            cutover_receipt_digest=_D0,
            activation_digest=_D1,
            adoption_ledger_digest=_D0,
            admitted_fact_count=43,
            status="degraded",
            diagnostic_ids=("diagnostic.cutover.test",),
            observed_at=_NOW,
        )


def test_startup_accepts_only_one_explicitly_blocked_alphafold_unit() -> None:
    alpha_digest = canonical_sha256_digest({"unit": "alphafold"})
    readiness = SimpleNamespace(
        units=(
            SimpleNamespace(
                unit_digest=alpha_digest,
                component_id="enzymedesign.alphafold.hpc",
            ),
        )
    )
    admission = SimpleNamespace(
        qualified_facts=tuple(object() for _ in range(44)),
        blockers=(
            SimpleNamespace(
                unit_digest=alpha_digest,
                error_code="blocked_qualification_missing",
            ),
        ),
    )

    validate_cutover_startup_admission(
        readiness_plan=readiness,
        admission=admission,
    )

    with pytest.raises(QualifiedRuntimeCutoverError, match="44 admitted"):
        validate_cutover_startup_admission(
            readiness_plan=readiness,
            admission=SimpleNamespace(
                qualified_facts=admission.qualified_facts,
                blockers=(),
            ),
        )


def test_rollback_and_smoke_authorities_remain_distinct() -> None:
    plan = PostCutoverSmokePlan.create(
        plan_id="smoke.enzymedesign.uniprot.batch-1",
        cutover_receipt_digest=_D0,
        adoption_ledger_digest=_D1,
        unit_digest=canonical_sha256_digest({"unit": "uniprot"}),
        route_id="enzymedesign.bio-provider-http.uniprot.read@1",
        subject_id="provider.uniprot.public",
        created_at=_NOW,
    )
    authority = PostCutoverSmokeAuthority.create(
        authority_id="authority.smoke.enzymedesign.uniprot.batch-1",
        plan_digest=plan.plan_digest,
        operator_id="operator.enzymedesign-owner",
        occurrence_id="occurrence.smoke.enzymedesign.uniprot.batch-1",
        authorized_at=_NOW,
    )
    smoke = PostCutoverSmokeReceipt.create(
        plan_digest=plan.plan_digest,
        authority_digest=authority.authority_digest,
        occurrence_id=authority.occurrence_id,
        unit_digest=plan.unit_digest,
        backend_receipt_digest=canonical_sha256_digest({"provider": "uniprot"}),
        effect_certainty="terminal_known",
        completed_at=_NOW,
    )
    rollback = CutoverRollbackReceipt.create(
        plan_digest=_D0,
        authority_digest=_D1,
        restored_backup_manifest_digest=_D0,
        prior_activation_digest=_D1,
        reason_code="startup_readback_failed",
        rolled_back_at=_NOW,
    )

    assert smoke.to_dict()["retry_count"] == 0
    assert smoke.to_dict()["fallback_performed"] is False
    assert rollback.to_dict()["before_first_live_only"] is True
