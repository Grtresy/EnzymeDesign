from __future__ import annotations

import pytest

from openzyme_host_api import aox_diagnostic_run
from openzyme_host_api.aox_cutover_evidence import canonical_digest
from openzyme_host_api.aox_diagnostic_run import (
    AOX_DIAGNOSTIC_DECISION_SCHEMA_ID,
)
from openzyme_host_api.aox_diagnostic_run import validate_aox_diagnostic_decision


def _sealed_no_go_decision() -> dict[str, object]:
    diagnostic_id = "aox_diagnostic_8c2ce426355c001253b86c1c"
    payload: dict[str, object] = {
        "schema_id": AOX_DIAGNOSTIC_DECISION_SCHEMA_ID,
        "run_class": "diagnostic",
        "acceptance_eligible": False,
        "diagnostic_id": diagnostic_id,
        "attempt_id": "diagnostic-positive-5dfdd0686e9174a975ff85b18404e85d",
        "attempt_kind": "positive",
        "decided_at": "2026-07-31T12:00:00+00:00",
        "status": "blocked",
        "blocker": {
            "code": "sandbox_run_failure_binding_invalid",
            "identity": "diagnostic.runner",
        },
        "authority": {
            "plan_schema_id": "aox_diagnostic_attempt_authority_plan@1",
            "consumption_schema_id": ("aox_diagnostic_attempt_authority_consumption@1"),
            "plan_digest": "sha256:" + "1" * 64,
            "consumption_digest": "sha256:" + "2" * 64,
            "envelope_id": "attempt_authority_r67",
            "request_digest": "sha256:" + "3" * 64,
        },
        "root": {
            "proof_schema_id": "aox_diagnostic_root_proof@1",
            "root_namespace": diagnostic_id.replace("_", "-"),
            "root_marker_digest": "sha256:" + "4" * 64,
            "root_identity": "sha256:" + "5" * 64,
        },
        "micu_ledger": {"before": {}, "after": {}},
        "observations": {
            "product_path_completed": False,
            "scientific_status": "failed",
            "report_status": "failed_evidence",
            "approval_count": 6,
            "operation_count": 7,
            "artifact_count": 13,
            "evidence_digest": "sha256:" + "6" * 64,
            "scientific_attempt_control_digest": None,
            "raw_facts": {"active_writer_count": 0},
        },
    }
    return {**payload, "decision_digest": canonical_digest(payload)}


def test_historical_diagnostic_decision_remains_read_only_non_acceptance() -> None:
    decision = _sealed_no_go_decision()

    assert validate_aox_diagnostic_decision(decision) == decision
    assert not hasattr(aox_diagnostic_run, "seal_aox_diagnostic_decision")


def test_automatic_diagnostic_runner_is_retired() -> None:
    assert not hasattr(aox_diagnostic_run, "AoxDiagnosticRun")


def test_diagnostic_decision_cannot_embed_formal_slot_failure_decision() -> None:
    decision = _sealed_no_go_decision()
    observations = dict(decision["observations"])
    observations["raw_facts"] = {
        "forbidden": "aox_blank_world_campaign_failure_decision@1"
    }
    decision["observations"] = observations
    payload = {
        key: value for key, value in decision.items() if key != "decision_digest"
    }
    decision["decision_digest"] = canonical_digest(payload)

    with pytest.raises(aox_diagnostic_run.CutoverEvidenceError) as error:
        validate_aox_diagnostic_decision(decision)

    assert error.value.code == "diagnostic_decision_formal_evidence_forbidden"
