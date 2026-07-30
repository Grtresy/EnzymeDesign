from __future__ import annotations

from copy import deepcopy
import hashlib
from pathlib import Path

import pytest

from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_host_api import aox_diagnostic_run as diagnostic_module
from openzyme_host_api.aox_attempt_authority import (
    build_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    consume_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_attempt_authority import (
    validate_aox_attempt_authority_plan,
)
from openzyme_host_api.aox_cutover_evidence import AttemptExecution
from openzyme_host_api.aox_cutover_evidence import BlankWorldRoots
from openzyme_host_api.aox_cutover_evidence import CutoverEvidenceError
from openzyme_host_api.aox_cutover_evidence import (
    DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID,
)
from openzyme_host_api.aox_cutover_evidence import assert_formal_campaign_root
from openzyme_host_api.aox_cutover_evidence import create_blank_world_roots
from openzyme_host_api.aox_cutover_evidence import execute_aox_attempt
from openzyme_host_api.aox_cutover_evidence import verify_attempt_bundle
from openzyme_host_api.aox_diagnostic_authority import (
    build_aox_diagnostic_authority_plan,
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
from openzyme_host_api.aox_diagnostic_authority import (
    validate_aox_diagnostic_authority_plan,
)
from openzyme_host_api.aox_diagnostic_run import (
    AOX_DIAGNOSTIC_DECISION_FILENAME,
)
from openzyme_host_api.aox_diagnostic_run import AoxDiagnosticRun
from openzyme_host_api.aox_live_run_class import AoxLiveRunClass
from openzyme_host_api.architecture_qualification import canonical_json_bytes

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger


def _digest(digit: str) -> str:
    return "sha256:" + digit * 64


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.aox-run-class-disjoint-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_aox_diagnostic_and_formal_run_classes_remain_disjoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    identity = {
        "git_commit": "a" * 40,
        "config_digest": _digest("1"),
    }
    prerequisites = {
        "provider_cache_mode": "bypass",
        "evidence_cache_reuse": False,
    }
    qualification = {
        "schema_id": "aox_architecture_qualification_receipt@1",
        "report_payload_digest": _digest("2"),
    }
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
    diagnostic = build_aox_diagnostic_authority_plan(
        identity=identity,
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        issued_at="2026-07-23T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu=10,
        max_cost_microunits=20,
        max_wall_time_seconds=30,
    )
    with pytest.raises(CutoverEvidenceError) as formal_plan_rejection:
        validate_aox_attempt_authority_plan(
            diagnostic,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    with pytest.raises(CutoverEvidenceError) as diagnostic_plan_rejection:
        validate_aox_diagnostic_authority_plan(
            formal,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    closure_plan = {
        "schema_id": "aox_closure_stage_diagnostic_authority_plan@1",
        "run_class": "closure_stage_diagnostic",
        "acceptance_eligible": False,
        "diagnostic_id": "aox_closure_stage_" + "b" * 24,
        "slot": {"attempt_id": "closure-stage-" + "c" * 32},
        "plan_digest": _digest("3"),
    }
    with pytest.raises(CutoverEvidenceError) as closure_formal_rejection:
        validate_aox_attempt_authority_plan(
            closure_plan,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    with pytest.raises(CutoverEvidenceError) as closure_diagnostic_rejection:
        validate_aox_diagnostic_authority_plan(
            closure_plan,
            identity=identity,
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    with pytest.raises(CutoverEvidenceError) as closure_blank_rejection:
        create_blank_world_roots(
            tmp_path / "aox-closure-stage-" / ("d" * 24),
            attempt_kind="positive",
            attempt_id="closure-stage-" + "c" * 32,
            run_class="closure_stage_diagnostic",  # type: ignore[arg-type]
            allowed_prerequisites=prerequisites,
            architecture_qualification=qualification,
        )
    equal_digest_diagnostic = deepcopy(diagnostic)
    equal_digest_diagnostic["plan_digest"] = formal["plan_digest"]
    with pytest.raises(CutoverEvidenceError) as cross_consumption:
        consume_aox_attempt_authority_plan(
            equal_digest_diagnostic,
            plan_path=tmp_path / "diagnostic.json",
            path=tmp_path / "diagnostic.json.consumed.json",
        )
    stripped_diagnostic_slot = deepcopy(diagnostic["slot"])
    assert isinstance(stripped_diagnostic_slot, dict)
    stripped_diagnostic_slot.pop("run_class")
    cross_mode_execution_errors: list[str] = []
    for authority, run_class, target in (
        (
            stripped_diagnostic_slot,
            AoxLiveRunClass.FORMAL_ACCEPTANCE,
            tmp_path / "formal-from-stripped-diagnostic",
        ),
        (
            formal["slots"][0],
            AoxLiveRunClass.DIAGNOSTIC,
            tmp_path / "diagnostic-from-formal",
        ),
    ):
        with pytest.raises(CutoverEvidenceError) as cross_execution:
            execute_aox_attempt(
                campaign_root=target,
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
        cross_mode_execution_errors.append(cross_execution.value.code)
        assert not target.exists()

    plan_path = tmp_path / "diagnostic-authority.json"
    publish_aox_diagnostic_authority_plan(diagnostic, plan_path)
    consumption = consume_aox_diagnostic_authority_plan(
        diagnostic,
        plan_path=plan_path,
        path=diagnostic_authority_consumption_path(plan_path),
    )
    diagnostic_root = tmp_path / str(diagnostic["root_namespace"])
    slot = diagnostic["slot"]
    assert isinstance(slot, dict)

    def execute(**kwargs: object) -> AttemptExecution:
        assert kwargs["run_class"] is AoxLiveRunClass.DIAGNOSTIC
        assert kwargs["authority"] == slot
        attempt_root = diagnostic_root / str(slot["attempt_id"])
        roots_by_name = {
            "artifact": attempt_root / "artifacts",
            "blob": attempt_root / "blobs",
            "sandbox": attempt_root / "sandboxes",
            "hpc": attempt_root / "hpc-workspace",
            "evidence": attempt_root / "evidence",
        }
        for path in roots_by_name.values():
            path.mkdir(parents=True, exist_ok=False)
        sqlite_path = attempt_root / "control-plane.sqlite3"
        connection = connect_sqlite(str(sqlite_path))
        try:
            apply_sqlite_migrations(connection)
        finally:
            connection.close()
        roots = BlankWorldRoots(
            attempt_id=str(slot["attempt_id"]),
            attempt_kind="positive",
            attempt_root=attempt_root,
            sqlite_path=sqlite_path,
            artifact_root=roots_by_name["artifact"],
            blob_root=roots_by_name["blob"],
            sandbox_root=roots_by_name["sandbox"],
            hpc_root=roots_by_name["hpc"],
            evidence_root=roots_by_name["evidence"],
            hpc_workspace_label="aox-diagnostic-" + "3" * 32,
            proof={
                "schema_id": DIAGNOSTIC_ROOT_PROOF_SCHEMA_ID,
                "root_identity": _digest("4"),
            },
        )
        return AttemptExecution(
            roots=roots,
            ledger_before={"charged_tokens": 0},
            ledger_after={"charged_tokens": 0},
            evidence={
                "run_class": AoxLiveRunClass.DIAGNOSTIC.value,
                "acceptance_eligible": False,
                "diagnostic_observation": {
                    "product_path_completed": True,
                },
                "scientific_outcome": {
                    "status": "completed",
                    "cutover_eligible": False,
                },
                "report": {
                    "status": "published",
                    "cutover_eligible": False,
                },
                "approvals": [],
                "operations": [],
                "artifacts": [],
            },
        )

    monkeypatch.setattr(
        diagnostic_module,
        "execute_aox_attempt",
        execute,
    )
    decision = AoxDiagnosticRun(
        diagnostic_root=diagnostic_root,
        identity=identity,
        ledger_path=tmp_path / "ledger.sqlite3",
        runner=lambda context: {},
        allowed_prerequisites=prerequisites,
        architecture_qualification=qualification,
        authority_plan=diagnostic,
        authority_consumption=consumption,
        authority_plan_path=plan_path,
    ).run()

    decision_path = diagnostic_root / AOX_DIAGNOSTIC_DECISION_FILENAME
    verification = verify_attempt_bundle(
        decision_path,
        artifact_root=diagnostic_root,
    )
    with pytest.raises(CutoverEvidenceError) as root_rejection:
        assert_formal_campaign_root(diagnostic_root)
    assert (diagnostic_root / str(slot["attempt_id"]) / "control-plane.sqlite3").is_file()
    assert decision["acceptance_eligible"] is False
    assert verification.passed is False
    assert not tuple(diagnostic_root.rglob("attempt-bundle.json"))
    assert not tuple(diagnostic_root.rglob("campaign-decision.json"))

    observation = {
        "cross_consumption_error": cross_consumption.value.code,
        "cross_mode_execution_errors": cross_mode_execution_errors,
        "diagnostic_decision_schema": decision["schema_id"],
        "diagnostic_plan_error": diagnostic_plan_rejection.value.code,
        "closure_blank_error": closure_blank_rejection.value.code,
        "closure_diagnostic_error": closure_diagnostic_rejection.value.code,
        "closure_formal_error": closure_formal_rejection.value.code,
        "closure_run_class": closure_plan["run_class"],
        "formal_plan_error": formal_plan_rejection.value.code,
        "formal_root_error": root_rejection.value.code,
        "formal_verification_passed": verification.passed,
        "run_class": decision["run_class"],
        "schema_id": "aox_run_class_qualification_observation@1",
        "sqlite_file_backed": True,
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
