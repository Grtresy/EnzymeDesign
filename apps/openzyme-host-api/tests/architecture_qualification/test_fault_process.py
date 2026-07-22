from __future__ import annotations

from dataclasses import replace
from pathlib import Path
import signal

from openzyme_host_api.architecture_qualification import load_invariant_registry

from .external_ports import ExternalEffectLedger
from .fault_process import IdentityBoundFaultProcessRunner
from .safety import QualificationSafetyGuard


REPO_ROOT = Path(__file__).resolve().parents[4]


def _runner(
    guard: QualificationSafetyGuard,
    *,
    ledger: ExternalEffectLedger,
) -> IdentityBoundFaultProcessRunner:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    return IdentityBoundFaultProcessRunner(
        registry=registry.payload,
        ledger=ledger,
        safety_guard=guard,
        readiness_timeout_seconds=5.0,
        operator_grace_seconds=0.05,
        term_grace_seconds=0.05,
        kill_grace_seconds=0.5,
        deadline_seconds=0.05,
    )


def test_fault_process_deadline_uses_bounded_term_and_preserves_signal() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    ledger = ExternalEffectLedger()
    with QualificationSafetyGuard(registry=registry.payload) as guard:
        handle = _runner(guard, ledger=ledger).start("wait")
        evidence = handle.retire(operator_signal=None)

    payload = evidence.payload
    phases = {item["phase"]: item for item in payload["phases"]}  # type: ignore[index]
    assert payload["retirement_proven"] is True
    assert payload["raw_exit_code"] == -signal.SIGTERM
    assert payload["raw_signal"] == signal.SIGTERM
    assert phases["deadline"]["sent"] is False
    assert phases["sigterm"]["sent"] is True
    assert phases["sigkill"]["sent"] is False
    assert phases["descendant_emptiness"]["group_member_count"] == 0
    assert ledger.count(operation="spawn") == 1
    assert ledger.count_effects() == 0
    assert guard.blocked_invocations == ()


def test_fault_process_identity_mismatch_fails_closed_without_group_claim() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    ledger = ExternalEffectLedger()
    with QualificationSafetyGuard(registry=registry.payload) as guard:
        handle = _runner(guard, ledger=ledger).start("wait")
        drifted = replace(
            handle.identity,
            start_time_ticks=handle.identity.start_time_ticks + 1,
        )
        evidence = handle.retire(
            operator_signal=signal.SIGTERM,
            expected_identity=drifted,
        )

    payload = evidence.payload
    phases = {item["phase"]: item for item in payload["phases"]}  # type: ignore[index]
    assert payload["identity_exact"] is False
    assert payload["retirement_proven"] is False
    assert payload["quarantine_required"] is True
    assert phases["operator_signal"]["sent"] is False
    assert phases["sigterm"]["sent"] is True
    assert handle.process.poll() is not None


def test_fault_process_unretired_descendant_proof_stays_non_admissible() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    ledger = ExternalEffectLedger()
    with QualificationSafetyGuard(registry=registry.payload) as guard:
        handle = _runner(guard, ledger=ledger).start("descendant_residue")
        handle.process.wait(timeout=1.0)
        evidence = handle.retire(
            operator_signal=signal.SIGTERM,
            force_retirement_unproven=True,
        )

    payload = evidence.payload
    phases = {item["phase"]: item for item in payload["phases"]}  # type: ignore[index]
    assert payload["descendant_residue_observed"] is True
    assert phases["sigkill"]["sent"] is True
    assert phases["descendant_emptiness"]["group_member_count"] == 0
    assert payload["retirement_proven"] is False
    assert payload["quarantine_required"] is True
    assert payload["cutover_eligible"] is False


def test_fault_process_cleanup_preserves_unknown_outcome_and_no_closure_claims() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    ledger = ExternalEffectLedger()
    with QualificationSafetyGuard(registry=registry.payload) as guard:
        handle = _runner(guard, ledger=ledger).start("wait")
        first = handle.retire(operator_signal=signal.SIGINT)
        second = handle.retire(operator_signal=signal.SIGINT)

    assert first is second
    assert handle.retirement_calls == 2
    payload = first.payload
    assert payload["raw_exit_code"] == -signal.SIGINT
    assert payload["raw_signal"] == signal.SIGINT
    assert payload["external_outcome"] == "unknown"
    assert payload["remote_cancellation_claimed"] is False
    assert payload["normal_bundle_created"] is False
    assert payload["quiescence_claimed"] is False
    assert payload["exact_charge_claimed"] is False
    assert set(payload["cleanup_call_counts"].values()) == {0}  # type: ignore[union-attr]
