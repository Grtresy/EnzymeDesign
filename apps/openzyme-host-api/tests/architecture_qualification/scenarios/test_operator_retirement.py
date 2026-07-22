from __future__ import annotations

import hashlib
from pathlib import Path
import signal

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import load_invariant_registry

from ..composition import ProductionCompositionFactory
from ..driver import AdmittedOperation
from ..driver import QualificationDriver
from ..external_ports import ExternalEffectLedger
from ..execution_evidence import record_effect_ledger_snapshot
from ..fault_process import FaultProcessEvidence
from ..fault_process import IdentityBoundFaultProcessRunner
from ..observation import collect_observation
from ..safety import QualificationSafetyGuard


REPO_ROOT = Path(__file__).resolve().parents[5]


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


def _assert_non_cutover_cleanup(evidence: FaultProcessEvidence) -> None:
    payload = evidence.payload
    assert payload["outcome"] == "fatal"
    assert payload["external_outcome"] == "unknown"
    assert payload["cutover_eligible"] is False
    assert payload["remote_cancellation_claimed"] is False
    assert payload["normal_bundle_created"] is False
    assert payload["quiescence_claimed"] is False
    assert payload["exact_charge_claimed"] is False
    assert set(payload["cleanup_call_counts"].values()) == {0}  # type: ignore[union-attr]


@pytest.mark.architecture_qualification_scenario(
    scenario_id="operator-retirement.idempotent-in-doubt-stop",
    family="operator-retirement",
    selections=("full", "premerge_subset"),
)
def test_operator_signals_retire_exact_groups_without_inventing_product_facts(
    tmp_path: Path,
) -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    fault_ledger = ExternalEffectLedger()
    host_root = tmp_path / "operator-host-child"

    with QualificationSafetyGuard(registry=registry.payload) as guard:
        runner = IdentityBoundFaultProcessRunner(
            registry=registry.payload,
            ledger=fault_ledger,
            safety_guard=guard,
            readiness_timeout_seconds=10.0,
            operator_grace_seconds=0.1,
            term_grace_seconds=0.1,
            kill_grace_seconds=0.75,
            deadline_seconds=0.1,
        )

        sigint_handle = runner.start("wait")
        sigint_evidence = sigint_handle.retire(operator_signal=signal.SIGINT)

        host_handle = runner.start(
            "host_dispatch_in_doubt",
            scenario_root=host_root,
        )
        host_ready = host_handle.ready_payload
        host_evidence = host_handle.retire(operator_signal=signal.SIGTERM)
        repeated_host_evidence = host_handle.retire(operator_signal=signal.SIGTERM)

        early_exit_handle = runner.start("early_exit")
        early_exit_handle.process.wait(timeout=1.0)
        early_exit_evidence = early_exit_handle.retire(
            operator_signal=signal.SIGTERM
        )

        descendant_handle = runner.start("descendant_residue")
        descendant_handle.process.wait(timeout=1.0)
        descendant_evidence = descendant_handle.retire(
            operator_signal=signal.SIGTERM
        )

        kill_handle = runner.start("ignore_term")
        kill_evidence = kill_handle.retire(operator_signal=signal.SIGTERM)

        restarted_factory = ProductionCompositionFactory.open_existing(host_root)
        restarted = restarted_factory.build()
        with restarted as running:
            running.stop_durable_supervisor()
            ids_payload = host_ready["ids"]
            assert isinstance(ids_payload, dict)
            ids = AdmittedOperation(
                **{key: str(value) for key, value in ids_payload.items()}
            )
            driver = QualificationDriver(running)
            after_restart = driver.canonical_records(ids)
            observation = collect_observation(
                running,
                session_ids=(ids.session_id,),
            )

    for evidence in (
        sigint_evidence,
        host_evidence,
        early_exit_evidence,
        descendant_evidence,
        kill_evidence,
    ):
        _assert_non_cutover_cleanup(evidence)
        assert evidence.payload["retirement_proven"] is True
        assert evidence.payload["quarantine_required"] is False

    assert sigint_evidence.payload["raw_exit_code"] == -signal.SIGINT
    assert sigint_evidence.payload["raw_signal"] == signal.SIGINT
    assert host_evidence.payload["raw_exit_code"] == -signal.SIGTERM
    assert host_evidence.payload["raw_signal"] == signal.SIGTERM
    assert repeated_host_evidence is host_evidence
    assert host_handle.retirement_calls == 2

    assert early_exit_evidence.payload["raw_exit_code"] == 23
    assert early_exit_evidence.payload["raw_signal"] is None
    assert descendant_evidence.payload["raw_exit_code"] == 0
    assert descendant_evidence.payload["descendant_residue_observed"] is True
    descendant_phases = {
        item["phase"]: item
        for item in descendant_evidence.payload["phases"]  # type: ignore[union-attr]
    }
    assert descendant_phases["sigkill"]["sent"] is True
    assert descendant_phases["descendant_emptiness"]["group_member_count"] == 0
    assert kill_evidence.payload["raw_exit_code"] == -signal.SIGKILL
    kill_phases = {
        item["phase"]: item
        for item in kill_evidence.payload["phases"]  # type: ignore[union-attr]
    }
    assert kill_phases["operator_signal"]["sent"] is True
    assert kill_phases["sigkill"]["sent"] is True

    assert host_ready["before_signal"] == {
        "approval_count": 1,
        "approval_status": "approved",
        "lifecycle_state": "reconcile_required",
        "result_present": False,
        "task_count": 0,
        "terminal_outcome": None,
    }
    child_effect_ledger = host_ready["effect_ledger"]
    assert isinstance(child_effect_ledger, dict)
    record_effect_ledger_snapshot(child_effect_ledger)
    child_ledger_payload = {
        key: value
        for key, value in child_effect_ledger.items()
        if key != "ledger_digest"
    }
    assert child_effect_ledger["ledger_digest"] == _digest(child_ledger_payload)
    child_entries = child_effect_ledger["entries"]
    assert isinstance(child_entries, list) and len(child_entries) == 1
    assert child_entries[0]["port_id"] == "bio.provider_http"
    assert child_entries[0]["operation"] == "dispatch"
    assert child_entries[0]["acceptance"] == "accepted"
    assert child_entries[0]["effect_attempted"] is True

    assert after_restart["approval"]["status"] == "approved"  # type: ignore[index]
    assert len(after_restart["approvals"]) == 1
    assert after_restart["execution"]["lifecycle_state"] == (  # type: ignore[index]
        "reconcile_required"
    )
    assert after_restart["execution"]["terminal_outcome"] is None  # type: ignore[index]
    assert after_restart["result"] is None
    assert after_restart["tasks"] == []
    assert restarted_factory.external_effect_ledger.entries() == ()
    assert observation.counts.effect_count == 0
    assert observation.payload["public_projection"]

    assert fault_ledger.count(
        port_id="qualification.fault_process",
        operation="spawn",
    ) == 5
    assert fault_ledger.count_effects() == 0
    assert guard.blocked_invocations == ()
    forbidden_evidence_names = {
        "attempt-bundle.json",
        "exact-charge.json",
        "normal-evidence.json",
        "quiescence-receipt.json",
    }
    assert not [
        path
        for path in host_root.rglob("*")
        if path.is_file() and path.name in forbidden_evidence_names
    ]
