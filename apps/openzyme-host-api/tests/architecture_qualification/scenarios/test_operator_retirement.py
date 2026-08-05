from __future__ import annotations

import hashlib
from pathlib import Path
import signal

import pytest

from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_api.architecture_qualification import load_invariant_registry

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger
from ..fault_process import IdentityBoundFaultProcessRunner
from ..fault_process import evaluate_retirement_semantics
from ..safety import QualificationSafetyGuard


REPO_ROOT = Path(__file__).resolve().parents[5]


def _digest(value: object) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


@pytest.mark.architecture_qualification_scenario(
    scenario_id="operator-retirement.idempotent-in-doubt-stop",
    family="operator-retirement",
    selections=("full", "premerge_subset"),
)
def test_operator_retirement_semantics_and_process_containment() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    ledger = ExternalEffectLedger()

    with QualificationSafetyGuard(registry=registry.payload) as guard:
        runner = IdentityBoundFaultProcessRunner(
            registry=registry.payload,
            ledger=ledger,
            safety_guard=guard,
            readiness_timeout_seconds=10.0,
            operator_grace_seconds=1.0,
            term_grace_seconds=1.0,
            kill_grace_seconds=5.0,
            deadline_seconds=2.0,
        )
        handle = runner.start("ignore_term")
        evidence = handle.retire(operator_signal=signal.SIGTERM)
        repeated = handle.retire(operator_signal=signal.SIGTERM)

    assert repeated is evidence
    assert handle.retirement_calls == 2
    assert evidence.payload["raw_exit_code"] == -signal.SIGKILL
    assert evidence.payload["raw_signal"] == signal.SIGKILL
    assert evidence.payload["retirement_proven"] is True
    assert evidence.payload["quarantine_required"] is False
    assert evidence.payload["external_outcome"] == "unknown"
    assert evidence.payload["cutover_eligible"] is False
    assert evidence.payload["remote_cancellation_claimed"] is False
    assert evidence.payload["normal_bundle_created"] is False
    assert evidence.payload["quiescence_claimed"] is False
    assert evidence.payload["exact_charge_claimed"] is False
    assert set(evidence.payload["cleanup_call_counts"].values()) == {0}  # type: ignore[union-attr]
    phases = {item["phase"]: item for item in evidence.payload["phases"]}  # type: ignore[index]
    assert phases["operator_signal"]["sent"] is True
    assert phases["sigkill"]["sent"] is True
    assert phases["descendant_emptiness"]["group_member_count"] == 0

    unproven = evaluate_retirement_semantics(
        identity_exact=False,
        raw_exit_code=-signal.SIGTERM,
        final_group_member_count=0,
    )
    assert unproven.retirement_proven is False
    assert unproven.quarantine_required is True
    assert unproven.external_outcome == "unknown"
    assert unproven.cutover_eligible is False

    ledger_snapshot = ledger.snapshot()
    assert ledger.count(operation="spawn") == 1
    assert ledger.count_effects() == 0
    assert guard.blocked_invocations == ()
    record_effect_ledger_snapshot(ledger_snapshot)
    record_execution_observation_digest(_digest(evidence.to_dict()))
