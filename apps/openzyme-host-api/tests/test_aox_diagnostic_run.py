from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import pytest

from openzyme_host_api import aox_diagnostic_run as diagnostic_module
from openzyme_host_api.aox_cutover_evidence import AttemptExecution
from openzyme_host_api.aox_cutover_evidence import AttemptRunRecord
from openzyme_host_api.aox_cutover_evidence import AoxCutoverCampaign
from openzyme_host_api.aox_cutover_evidence import BlankWorldRoots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import (
    DIAGNOSTIC_ROOT_MARKER_FILENAME,
)
from openzyme_host_api.aox_cutover_evidence import (
    DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_evidence import evaluate_campaign
from openzyme_host_api.aox_cutover_evidence import execute_aox_attempt
from openzyme_host_api.aox_cutover_evidence import VerificationResult
from openzyme_host_api.aox_cutover_evidence import verify_attempt_bundle
from openzyme_host_api.aox_cutover_live import LiveAoxAttemptRunner
from openzyme_host_api.aox_diagnostic_authority import (
    build_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    build_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    consume_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_authority import (
    diagnostic_authority_consumption_path,
)
from openzyme_host_api.aox_diagnostic_authority import (
    publish_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_run import (
    AOX_DIAGNOSTIC_DECISION_FILENAME,
)
from openzyme_host_api.aox_diagnostic_run import (
    AOX_DIAGNOSTIC_DECISION_SCHEMA_ID,
)
from openzyme_host_api.aox_diagnostic_run import AoxDiagnosticRun
from openzyme_host_api.aox_diagnostic_run import (
    seal_aox_diagnostic_decision,
)
from openzyme_host_api.aox_diagnostic_run import (
    validate_aox_diagnostic_decision,
)
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass


def _declarations() -> tuple[
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    return (
        {"git_commit": "a" * 40, "config_digest": "sha256:" + "b" * 64},
        {"provider_cache_mode": "bypass", "evidence_cache_reuse": False},
        {
            "schema_id": "aox_architecture_qualification_receipt@1",
            "report_payload_digest": "sha256:" + "c" * 64,
        },
    )


def _authority(
    tmp_path: Path,
) -> tuple[
    dict[str, object],
    dict[str, object],
    Path,
    dict[str, object],
    dict[str, object],
    dict[str, object],
]:
    identity, prerequisites, qualification = _declarations()
    plan = build_aox_diagnostic_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=10_000,
        max_cost_microunits=20_000,
        max_wall_time_seconds=3_600,
    )
    plan_path = tmp_path / "diagnostic-authority.json"
    publish_aox_diagnostic_authority_plan(plan, plan_path)
    consumption = consume_aox_diagnostic_authority_plan(
        plan,
        plan_path=plan_path,
        path=diagnostic_authority_consumption_path(plan_path),
    )
    return (
        plan,
        consumption,
        plan_path,
        identity,
        prerequisites,
        qualification,
    )


def _fake_execution(
    *,
    diagnostic_root: Path,
    plan: dict[str, object],
) -> AttemptExecution:
    slot = plan["slot"]
    assert isinstance(slot, dict)
    attempt_root = diagnostic_root / str(slot["attempt_id"])
    roots = BlankWorldRoots(
        attempt_id=str(slot["attempt_id"]),
        attempt_kind="positive",
        attempt_root=attempt_root,
        sqlite_path=attempt_root / "control-plane.sqlite3",
        artifact_root=attempt_root / "artifacts",
        blob_root=attempt_root / "blobs",
        sandbox_root=attempt_root / "sandboxes",
        hpc_root=attempt_root / "hpc-workspace",
        evidence_root=attempt_root / "evidence",
        hpc_workspace_label="aox-diagnostic-" + "d" * 32,
        proof={
            "schema_id": DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID,
            "root_identity": "sha256:" + "e" * 64,
        },
    )
    return AttemptExecution(
        roots=roots,
        ledger_before={"charged_tokens": 10},
        ledger_after={"charged_tokens": 20},
        evidence={
            "run_class": AoxLiveRunClass.DIAGNOSTIC.value,
            "acceptance_eligible": False,
            "diagnostic_observation": {
                "product_path_completed": True,
                "observed_scientific_status": "completed",
                "observed_report_status": "published",
            },
            "scientific_outcome": {
                "status": "completed",
                "cutover_eligible": False,
            },
            "report": {
                "status": "published",
                "cutover_eligible": False,
            },
            "approvals": [{"approval_id": "appr_diagnostic"}],
            "operations": [{"operation_id": "op_diagnostic"}],
            "artifacts": [{"artifact_id": "art_diagnostic"}],
            "scientific_attempt_control": {
                "attempt_authority": {
                    "envelope_id": slot["envelope_id"],
                    "root_ref": slot["authority_request"]["root_ref"],
                }
            },
        },
    )


def test_diagnostic_collector_emits_only_append_only_non_acceptance_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, consumption, plan_path, identity, prerequisites, qualification = (
        _authority(tmp_path)
    )
    diagnostic_root = tmp_path / str(plan["root_namespace"])
    captured: dict[str, object] = {}

    def fake_execute(**kwargs: object) -> AttemptExecution:
        captured.update(kwargs)
        return _fake_execution(
            diagnostic_root=diagnostic_root,
            plan=plan,
        )

    monkeypatch.setattr(
        diagnostic_module,
        "execute_aox_attempt",
        fake_execute,
    )
    run = AoxDiagnosticRun(
        diagnostic_root=diagnostic_root,
        identity=identity,
        ledger_path=tmp_path / "ledger.sqlite3",
        runner=lambda context: {},
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        authority_plan=plan,
        authority_consumption=consumption,
        authority_plan_path=plan_path,
    )

    decision = run.run()

    assert decision["schema_id"] == AOX_DIAGNOSTIC_DECISION_SCHEMA_ID
    assert decision["run_class"] == AoxLiveRunClass.DIAGNOSTIC.value
    assert decision["acceptance_eligible"] is False
    assert decision["status"] == "completed_product_path"
    assert decision["blocker"] is None
    assert decision["root"]["proof_schema_id"] == (
        DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID
    )
    assert captured["run_class"] is AoxLiveRunClass.DIAGNOSTIC
    assert captured["kind"] == "positive"
    assert captured["number"] == 1
    assert (
        captured["authority"]["run_class"]
        == AoxLiveRunClass.DIAGNOSTIC.value
    )
    decision_path = diagnostic_root / AOX_DIAGNOSTIC_DECISION_FILENAME
    assert decision_path.is_file()
    assert decision_path.stat().st_mode & 0o222 == 0
    assert (diagnostic_root / DIAGNOSTIC_ROOT_MARKER_FILENAME).is_file()
    assert not tuple(diagnostic_root.rglob("attempt-bundle.json"))
    assert not tuple(diagnostic_root.rglob("campaign-decision.json"))
    assert validate_aox_diagnostic_decision(decision) == decision

    with pytest.raises(CutoverEvidenceError) as append_only:
        seal_aox_diagnostic_decision(decision, decision_path)
    assert append_only.value.code == "diagnostic_decision_append_only"

    formal_verification = verify_attempt_bundle(
        decision_path,
        artifact_root=diagnostic_root,
    )
    assert formal_verification.passed is False
    formal_record = AttemptRunRecord(
        attempt_id=str(plan["slot"]["attempt_id"]),
        attempt_kind="positive",
        bundle_path=decision_path,
        artifact_root=diagnostic_root,
        bundle_digest=str(decision["decision_digest"]),
        verification=VerificationResult(
            passed=True,
            bundle_digest=str(decision["decision_digest"]),
            attempt_id=str(plan["slot"]["attempt_id"]),
            attempt_kind="positive",
            issues=(),
        ),
    )
    assert evaluate_campaign([formal_record])["decision"] == "NO-GO"

    for formal_root in (
        diagnostic_root,
        diagnostic_root / "nested-formal-campaign",
    ):
        formal_campaign = AoxCutoverCampaign.for_non_live_test(
            campaign_root=formal_root,
            identity=identity,
            ledger_path=tmp_path / "formal-ledger.sqlite3",
            positive_runner=lambda context: {},
            fault_runner=lambda context: {},
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
        with pytest.raises(CutoverEvidenceError) as diagnostic_root_reuse:
            formal_campaign.run()
        assert (
            diagnostic_root_reuse.value.code
            == "formal_campaign_diagnostic_root_forbidden"
        )


def test_diagnostic_execution_failure_seals_only_non_acceptance_decision(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    plan, consumption, plan_path, identity, prerequisites, qualification = (
        _authority(tmp_path)
    )
    diagnostic_root = tmp_path / str(plan["root_namespace"])

    def fail_execution(**kwargs: object) -> AttemptExecution:
        del kwargs
        raise CutoverEvidenceError(
            "attempt_child_timeout",
            "injected diagnostic child timeout",
        )

    monkeypatch.setattr(
        diagnostic_module,
        "execute_aox_attempt",
        fail_execution,
    )
    decision = AoxDiagnosticRun(
        diagnostic_root=diagnostic_root,
        identity=identity,
        ledger_path=tmp_path / "ledger.sqlite3",
        runner=lambda context: {},
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        authority_plan=plan,
        authority_consumption=consumption,
        authority_plan_path=plan_path,
    ).run()

    assert decision["status"] == "failed"
    assert decision["acceptance_eligible"] is False
    assert decision["blocker"] == {
        "code": "attempt_child_timeout",
        "identity": "diagnostic.runner",
    }
    assert decision["micu_ledger"] == {
        "status": "not_claimed",
        "reason": "diagnostic_runner_failed_before_settled_snapshot",
    }
    assert decision["root"]["proof_schema_id"] is None
    assert validate_aox_diagnostic_decision(decision) == decision
    assert (
        diagnostic_root / AOX_DIAGNOSTIC_DECISION_FILENAME
    ).is_file()
    assert not tuple(diagnostic_root.rglob("attempt-bundle.json"))
    assert not tuple(diagnostic_root.rglob("campaign-decision.json"))


def test_diagnostic_runner_projection_forces_all_eligibility_false() -> None:
    runner = object.__new__(LiveAoxAttemptRunner)
    runner.run_class = AoxLiveRunClass.DIAGNOSTIC
    projected = runner._project_run_class_evidence(
        {
            "scientific_outcome": {
                "status": "completed",
                "cutover_eligible": True,
            },
            "report": {
                "status": "published",
                "cutover_eligible": True,
            },
            "nested": {
                "acceptance_eligible": True,
                "items": [{"cutover_eligible": True}],
            },
        }
    )

    assert projected["acceptance_eligible"] is False
    assert projected["scientific_outcome"]["cutover_eligible"] is False
    assert projected["report"]["cutover_eligible"] is False
    assert projected["nested"]["acceptance_eligible"] is False
    assert projected["nested"]["items"][0]["cutover_eligible"] is False
    assert (
        projected["diagnostic_observation"]["product_path_completed"]
        is True
    )


def test_shared_execution_core_rejects_stripped_or_cross_mode_slot_before_root(
    tmp_path: Path,
) -> None:
    diagnostic, _, _, identity, prerequisites, qualification = _authority(
        tmp_path
    )
    diagnostic_slot = deepcopy(diagnostic["slot"])
    assert isinstance(diagnostic_slot, dict)
    diagnostic_slot.pop("run_class")
    formal = build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=10,
        max_cost_microunits_per_attempt=20,
        max_wall_time_seconds_per_attempt=30,
    )
    cases = (
        (
            diagnostic_slot,
            AoxLiveRunClass.FORMAL_ACCEPTANCE,
            tmp_path / "formal-from-diagnostic",
        ),
        (
            formal["slots"][0],
            AoxLiveRunClass.DIAGNOSTIC,
            tmp_path / "diagnostic-from-formal",
        ),
    )
    for authority, run_class, root in cases:
        with pytest.raises(CutoverEvidenceError) as rejected:
            execute_aox_attempt(
                campaign_root=root,
                identity=identity,
                ledger_path=tmp_path / "unused-ledger.sqlite3",
                runner=lambda context: (_ for _ in ()).throw(
                    AssertionError(context)
                ),
                allowed_prerequisites=prerequisites,
                architecture_qualification=qualification,
                number=1,
                kind="positive",
                authority=authority,
                run_class=run_class,
            )
        assert rejected.value.code == "attempt_authority_slot_identity_invalid"
        assert not root.exists()
