from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
import json
from pathlib import Path
import threading

import pytest

from openzyme_core import AttachedProcessDelivery
from openzyme_core import AttachedProcessIdentity
from openzyme_core import ContinuationDeliveryWorker
from ..composition import ProductionCompositionFactory
from ..driver import AdmittedOperation
from ..driver import QualificationDriver
from ..driver import materialized_observation_response
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..execution_evidence import record_observed_p0_trigger
from ..observation import QualificationObservation
from ..observation import collect_observation
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent
from ..probes import prepare_backend_handle_for_probe
from ..probes import probe_supervisor_database_busy


@dataclass(slots=True)
class _QualificationProcessHandle:
    alive: bool = True
    bound_identity: AttachedProcessIdentity | None = None
    deliveries: list[AttachedProcessDelivery] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.alive

    def bind_identity(self, identity: AttachedProcessIdentity) -> None:
        self.bound_identity = identity

    def deliver(
        self,
        identity: AttachedProcessIdentity,
        delivery: AttachedProcessDelivery,
    ) -> None:
        if identity != self.bound_identity:
            raise AssertionError("qualification delivery identity drifted")
        self.deliveries.append(delivery)

    def request_stop(self, *, reason: str) -> None:
        del reason
        self.alive = False

    def wait_stopped(self, *, timeout_seconds: float) -> bool:
        del timeout_seconds
        return not self.alive


def _envelope(case_id: str) -> dict[str, object]:
    return {
        "bounded_summary": {"case_id": case_id, "status": "completed"},
        "output_artifact_ids": [],
        "registered_artifact_ids": [],
        "status": "succeeded",
    }


def _admit(
    driver: QualificationDriver,
    *,
    case_id: str,
    attached_process: bool = False,
) -> AdmittedOperation:
    session_id = f"sess_supervisor_progress_{case_id}"
    driver.create_session(session_id)
    ids = driver.admit_durable_operation(
        session_id=session_id,
        scenario_key=f"supervisor_{case_id}",
        route_policy_id="qualification.provider:v1",
        selected_backend="qualification_provider",
        adapter_policy_id="qualification_provider_adapter:v1",
        attached_process=attached_process,
    )
    driver.resolve_approval(ids.approval_id)
    return ids


def _queue_success(
    driver: QualificationDriver,
    *,
    operation: str,
    envelope: dict[str, object],
) -> None:
    driver.queue_external(
        "bio.provider_http",
        operation,
        ControlledPortOutcome(
            acceptance=EffectAcceptance.TERMINAL,
            effect_attempted=operation == "dispatch",
            response=materialized_observation_response(
                bounded_result_envelope=envelope,
                backend_handle_ref=None,
            ),
        ),
    )


def _waiting_response(backend_handle_ref: str) -> dict[str, object]:
    return {
        "backend_handle_ref": backend_handle_ref,
        "effect_certainty": "effect_known",
        "error_code": None,
        "kind": "waiting_external",
        "materialized_result": None,
        "retry_eligibility": "verify_then_retry",
        "safe_receipt_digest": None,
        "safe_summary": "controlled external work remains pending",
        "terminal_outcome": None,
    }


def _delta(before: QualificationObservation, after: QualificationObservation) -> dict[str, int]:
    return {
        "effects": after.counts.effect_count - before.counts.effect_count,
        "events": after.counts.event_count - before.counts.event_count,
        "state_versions": (
            after.counts.state_version_total - before.counts.state_version_total
        ),
    }


@pytest.mark.architecture_qualification_scenario(
    scenario_id="supervisor-progress.semantic-progress-only",
    family="supervisor-progress",
    selections=("full", "premerge_subset"),
)
def test_supervisor_does_not_self_wake_after_terminal_or_idle_ticks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "supervisor-progress")
    composition = factory.build()
    records: dict[str, dict[str, object]] = {}
    envelopes: dict[str, dict[str, object]] = {}
    no_progress_evidence: dict[str, dict[str, int]] = {}
    with composition as running:
        running.stop_durable_supervisor()
        supervisor = running.build_manual_durable_supervisor()

        initial = running.run_manual_durable_tick(supervisor)
        assert initial == ()
        assert supervisor.status()["tick_count"] == 1
        assert supervisor.notifier.notify_count == 0

        driver = QualificationDriver(running)
        actual_ids = _admit(driver, case_id="actual_transition")

        notify_before_busy = supervisor.notifier.notify_count
        busy, original_restored = probe_supervisor_database_busy(
            running,
            supervisor=supervisor,
            monkeypatch=monkeypatch,
        )
        assert original_restored is True
        assert len(busy) == 2
        assert {item["action"] for item in busy} == {"database_busy"}
        assert supervisor.notifier.notify_count == notify_before_busy
        assert supervisor.status()["database_busy_count"] == 2

        envelopes["actual_transition"] = _envelope("actual_transition")
        _queue_success(
            driver,
            operation="dispatch",
            envelope=envelopes["actual_transition"],
        )
        semantic_actions: list[str] = []
        for _ in range(2):
            outcomes = running.run_manual_durable_tick(supervisor)
            semantic_actions.extend(str(item["action"]) for item in outcomes)
            current = driver.canonical_records(actual_ids)
            if current["execution"]["lifecycle_state"] == "terminal":  # type: ignore[index]
                break
        else:  # pragma: no cover - explicit bounded convergence failure
            raise AssertionError("manual production supervisor did not converge")
        assert "dispatch" in semantic_actions
        assert "terminalize_result" in semantic_actions
        assert driver.run_execution_once(
            actual_ids.execution_id,
            worker_id="qualification:supervisor:not-claimable",
        )["action"] == "not_claimable"
        records["actual_transition"] = driver.canonical_records(actual_ids)

        claim_race_ids = _admit(
            driver,
            case_id="claim_raced",
            attached_process=True,
        )
        envelopes["claim_raced"] = _envelope("claim_raced")
        _queue_success(
            driver,
            operation="dispatch",
            envelope=envelopes["claim_raced"],
        )
        assert driver.run_execution_once(
            claim_race_ids.execution_id,
            worker_id="qualification:claim-raced:result",
        )["lifecycle_state"] == "result_ready"
        continuation = driver.continuation_state(claim_race_ids.continuation_id)
        process_handle = _QualificationProcessHandle()
        running.dependencies.v3_live_process_registry.register(
            AttachedProcessIdentity.from_continuation(
                continuation,
                execution_id=claim_race_ids.execution_id,
            ),
            process_handle,
        )
        workers: list[ContinuationDeliveryWorker] = []
        for label in ("first", "second"):
            coordinator = running.durable_supervisor.worker_factory(
                f"qualification:claim-raced:{label}"
            )
            workers.append(
                next(
                    worker
                    for worker in coordinator.workers
                    if isinstance(worker, ContinuationDeliveryWorker)
                )
            )
        original_claim_and_deliver = ContinuationDeliveryWorker._claim_and_deliver
        claim_barrier = threading.Barrier(2)

        def synchronized_claim(self, candidate, *, now_iso):  # type: ignore[no-untyped-def]
            claim_barrier.wait(timeout=3.0)
            return original_claim_and_deliver(
                self,
                candidate,
                now_iso=now_iso,
            )

        delivery_outcomes: list[object] = []
        delivery_failures: list[BaseException] = []

        def run_delivery(worker: ContinuationDeliveryWorker) -> None:
            try:
                delivery_outcomes.append(worker.run_once())
            except BaseException as exc:  # pragma: no cover - surfaced below
                delivery_failures.append(exc)

        with monkeypatch.context() as scoped:
            scoped.setattr(
                ContinuationDeliveryWorker,
                "_claim_and_deliver",
                synchronized_claim,
            )
            delivery_threads = [
                threading.Thread(target=run_delivery, args=(worker,))
                for worker in workers
            ]
            for thread in delivery_threads:
                thread.start()
            for thread in delivery_threads:
                thread.join(timeout=4.0)
                assert thread.is_alive() is False
        if delivery_failures:
            raise AssertionError("continuation claim race failed") from delivery_failures[0]
        assert {getattr(item, "action") for item in delivery_outcomes} == {
            "claim_raced",
            "delivered",
        }
        assert len(process_handle.deliveries) == 1
        assert driver.run_execution_once(
            claim_race_ids.execution_id,
            worker_id="qualification:claim-raced:terminal",
        )["lifecycle_state"] == "terminal"
        records["claim_raced"] = driver.canonical_records(claim_race_ids)

        reconcile_ids = tuple(
            _admit(driver, case_id=f"unchanged_reconcile_{index}")
            for index in range(2)
        )
        for ids in reconcile_ids:
            case_id = ids.session_id.removeprefix("sess_supervisor_progress_")
            envelopes[case_id] = _envelope(case_id)
            driver.queue_external(
                "bio.provider_http",
                "dispatch",
                ControlledPortOutcome(
                    acceptance=EffectAcceptance.IN_DOUBT,
                    effect_attempted=True,
                ),
            )
            assert driver.run_execution_once(
                ids.execution_id,
                worker_id=f"qualification:{case_id}:dispatch",
            )["lifecycle_state"] == "reconcile_required"
        for _ in range(1):
            driver.queue_external(
                "bio.provider_http",
                "reconcile",
                ControlledPortOutcome(
                    acceptance=EffectAcceptance.NOT_ACCEPTED,
                    error_code="qualification_reconcile_unchanged",
                ),
            )
        reconcile_before = collect_observation(
            running,
            session_ids=tuple(ids.session_id for ids in reconcile_ids),
        )
        reconcile_notify_before = supervisor.notifier.notify_count
        reconcile_actions: list[str] = []
        outcomes = running.run_manual_durable_tick(supervisor)
        reconcile_actions.extend(str(item["action"]) for item in outcomes)
        reconcile_after = collect_observation(
            running,
            session_ids=tuple(ids.session_id for ids in reconcile_ids),
        )
        assert len(reconcile_actions) == 2
        assert set(reconcile_actions) <= {"not_claimable", "reconcile"}
        assert "reconcile" in reconcile_actions
        no_progress_evidence["unchanged_reconcile"] = {
            **_delta(reconcile_before, reconcile_after),
            "immediate_notifications": (
                supervisor.notifier.notify_count - reconcile_notify_before
            ),
            "ticks": 1,
        }
        for ids in reconcile_ids:
            case_id = ids.session_id.removeprefix("sess_supervisor_progress_")
            _queue_success(
                driver,
                operation="reconcile",
                envelope=envelopes[case_id],
            )
            assert driver.run_execution_once(
                ids.execution_id,
                worker_id=f"qualification:{case_id}:result",
            )["lifecycle_state"] == "result_ready"
            assert driver.run_execution_once(
                ids.execution_id,
                worker_id=f"qualification:{case_id}:terminal",
            )["lifecycle_state"] == "terminal"
            records[case_id] = driver.canonical_records(ids)

        poll_ids = tuple(
            _admit(driver, case_id=f"unchanged_poll_{index}") for index in range(2)
        )
        for ids in poll_ids:
            case_id = ids.session_id.removeprefix("sess_supervisor_progress_")
            envelopes[case_id] = _envelope(case_id)
            backend_handle_ref = prepare_backend_handle_for_probe(
                running,
                execution_id=ids.execution_id,
            )
            driver.queue_external(
                "bio.provider_http",
                "dispatch",
                ControlledPortOutcome(
                    acceptance=EffectAcceptance.ACCEPTED,
                    effect_attempted=True,
                    response=_waiting_response(backend_handle_ref),
                ),
            )
            assert driver.run_execution_once(
                ids.execution_id,
                worker_id=f"qualification:{case_id}:dispatch",
            )["lifecycle_state"] == "waiting_external"
        for _ in range(1):
            driver.queue_external(
                "bio.provider_http",
                "poll",
                ControlledPortOutcome(
                    acceptance=EffectAcceptance.NOT_ACCEPTED,
                    error_code="qualification_poll_unchanged",
                ),
            )
        poll_before = collect_observation(
            running,
            session_ids=tuple(ids.session_id for ids in poll_ids),
        )
        poll_notify_before = supervisor.notifier.notify_count
        poll_actions: list[str] = []
        outcomes = running.run_manual_durable_tick(supervisor)
        poll_actions.extend(str(item["action"]) for item in outcomes)
        poll_after = collect_observation(
            running,
            session_ids=tuple(ids.session_id for ids in poll_ids),
        )
        assert len(poll_actions) == 2
        assert set(poll_actions) <= {"not_claimable", "poll"}
        assert "poll" in poll_actions
        no_progress_evidence["unchanged_poll"] = {
            **_delta(poll_before, poll_after),
            "immediate_notifications": (
                supervisor.notifier.notify_count - poll_notify_before
            ),
            "ticks": 1,
        }
        for ids in poll_ids:
            case_id = ids.session_id.removeprefix("sess_supervisor_progress_")
            _queue_success(
                driver,
                operation="poll",
                envelope=envelopes[case_id],
            )
            assert driver.run_execution_once(
                ids.execution_id,
                worker_id=f"qualification:{case_id}:result",
            )["lifecycle_state"] == "result_ready"
            assert driver.run_execution_once(
                ids.execution_id,
                worker_id=f"qualification:{case_id}:terminal",
            )["lifecycle_state"] == "terminal"
            records[case_id] = driver.canonical_records(ids)

        notify_count_at_terminal = supervisor.notifier.notify_count
        processed_at_terminal = int(supervisor.status()["processed_count"])
        for _ in range(3):
            assert running.run_manual_durable_tick(supervisor) == ()
        final_status = supervisor.status()
        running.stop_manual_durable_supervisor(supervisor)
        observation = collect_observation(
            running,
            session_ids=tuple(
                ids.session_id
                for ids in (
                    actual_ids,
                    claim_race_ids,
                    *reconcile_ids,
                    *poll_ids,
                )
            ),
        )

    assert supervisor.notifier.notify_count == notify_count_at_terminal
    assert int(final_status["processed_count"]) == processed_at_terminal
    assert final_status["database_busy_count"] == 2
    assert final_status["last_error"] is None
    for case_id, case_records in records.items():
        assert_operation_oracle(
            case_records,
            expected_lifecycle="terminal",
            expected_terminal_outcome="succeeded",
            expected_envelope=envelopes[case_id],
            expected_result_ready_transitions=1,
            expected_terminal_transitions=1,
        )
    poll_call_count = factory.external_effect_ledger.count(operation="poll")
    reconcile_call_count = factory.external_effect_ledger.count(
        operation="reconcile"
    )
    assert poll_call_count in {3, 4}
    assert reconcile_call_count in {3, 4}
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={
            ("bio.provider_http", "dispatch"): 6,
            ("bio.provider_http", "poll"): poll_call_count,
            ("bio.provider_http", "reconcile"): reconcile_call_count,
        },
        expected_effect_count=6,
    )
    assert_public_authority_absent(observation.payload["public_projection"])

    no_progress_budget = {
        "max_effect_delta": 0,
        "max_event_delta": 16,
        "max_immediate_notifications": 0,
        "max_state_version_delta": 32,
    }
    violations = {
        family: {
            name: value
            for name, value in evidence.items()
            if (
                name == "effects"
                and value > no_progress_budget["max_effect_delta"]
            )
            or (
                name == "events"
                and value > no_progress_budget["max_event_delta"]
            )
            or (
                name == "immediate_notifications"
                and value
                > no_progress_budget["max_immediate_notifications"]
            )
            or (
                name == "state_versions"
                and value > no_progress_budget["max_state_version_delta"]
            )
        }
        for family, evidence in no_progress_evidence.items()
    }
    violations = {family: values for family, values in violations.items() if values}
    if violations:
        record_observed_p0_trigger("unbounded-progress")
    assert not violations, (
        "supervisor counted unchanged external observations as semantic progress: "
        + json.dumps(
            {
                "budget": no_progress_budget,
                "evidence": no_progress_evidence,
                "violations": violations,
            },
            sort_keys=True,
        )
    )
