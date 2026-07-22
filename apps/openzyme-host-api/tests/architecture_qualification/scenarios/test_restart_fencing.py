from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import threading

import pytest

from openzyme_core import AttachedProcessDelivery
from openzyme_core import AttachedProcessIdentity
from ..composition import ProductionCompositionFactory
from ..driver import AdmittedOperation
from ..driver import QualificationDriver
from ..driver import materialized_observation_response
from ..external_ports import ControlledPortOutcome
from ..external_ports import EffectAcceptance
from ..observation import collect_observation
from ..oracles import assert_effect_ledger_oracle
from ..oracles import assert_operation_oracle
from ..oracles import assert_public_authority_absent
from ..probes import probe_stale_execution_lease_release


@dataclass(slots=True)
class _QualificationProcessHandle:
    alive: bool = True
    bound_identity: AttachedProcessIdentity | None = None
    deliveries: list[AttachedProcessDelivery] = field(default_factory=list)
    stop_reasons: list[str] = field(default_factory=list)

    def is_alive(self) -> bool:
        return self.alive

    def bind_identity(self, identity: AttachedProcessIdentity) -> None:
        self.bound_identity = identity

    def deliver(
        self,
        identity: AttachedProcessIdentity,
        delivery: AttachedProcessDelivery,
    ) -> None:
        del identity
        self.deliveries.append(delivery)

    def request_stop(self, *, reason: str) -> None:
        self.stop_reasons.append(reason)
        self.alive = False

    def wait_stopped(self, *, timeout_seconds: float) -> bool:
        del timeout_seconds
        return not self.alive


def _envelope(case_id: str) -> dict[str, object]:
    return {
        "bounded_summary": {"case_id": case_id, "status": "completed"},
        "output_artifact_ids": [],
        "provider_request_id": f"provider_{case_id}",
        "registered_artifact_ids": [],
        "status": "succeeded",
    }


def _admit(
    driver: QualificationDriver,
    *,
    case_id: str,
    attached_process: bool = False,
) -> AdmittedOperation:
    session_id = f"sess_restart_fencing_{case_id}"
    driver.create_session(session_id)
    ids = driver.admit_durable_operation(
        session_id=session_id,
        scenario_key=case_id,
        route_policy_id="qualification.provider:v1",
        selected_backend="qualification_provider",
        adapter_policy_id="qualification_provider_adapter:v1",
        attached_process=attached_process,
    )
    driver.resolve_approval(ids.approval_id)
    return ids


def _queue_materialized(
    driver: QualificationDriver,
    *,
    case_id: str,
    acceptance: EffectAcceptance = EffectAcceptance.TERMINAL,
    error_code: str | None = None,
) -> dict[str, object]:
    envelope = _envelope(case_id)
    driver.queue_external(
        "bio.provider_http",
        "dispatch",
        ControlledPortOutcome(
            acceptance=acceptance,
            effect_attempted=True,
            response=materialized_observation_response(
                bounded_result_envelope=envelope,
                backend_handle_ref=None,
            ),
            error_code=error_code,
        ),
    )
    return envelope


@pytest.mark.architecture_qualification_scenario(
    scenario_id="restart-fencing.concurrent-claim-single-effect",
    family="restart-fencing",
    selections=("full", "premerge_subset"),
)
def test_concurrent_claim_has_one_dispatch_and_survives_full_host_restart(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "restart-fencing")
    first = factory.build()
    records: dict[str, dict[str, object]] = {}
    envelopes: dict[str, dict[str, object]] = {}
    with first as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)

        predispatch_ids = _admit(driver, case_id="pre_dispatch_loss")
        expired_start = (datetime.now(tz=UTC) - timedelta(minutes=2)).isoformat()
        stale_claim = driver.claim_execution(
            predispatch_ids.execution_id,
            worker_id="qualification:pre-dispatch-lost-owner",
            lease_seconds=1,
            now_iso=expired_start,
        )
        assert stale_claim["lifecycle_state"] == "claimed"
        assert stale_claim["effect_certainty"] == "no_effect"
        assert factory.external_effect_ledger.count_effects() == 0

        in_doubt_ids = _admit(driver, case_id="dispatch_in_doubt")
        envelopes["dispatch_in_doubt"] = _queue_materialized(
            driver,
            case_id="dispatch_in_doubt",
            acceptance=EffectAcceptance.ACCEPTED,
            error_code="simulated_lost_callback",
        )
        driver.queue_external(
            "bio.provider_http",
            "reconcile",
            ControlledPortOutcome(
                acceptance=EffectAcceptance.TERMINAL,
                response=materialized_observation_response(
                    bounded_result_envelope=envelopes["dispatch_in_doubt"],
                    backend_handle_ref=None,
                ),
            ),
        )
        in_doubt = driver.run_execution_once(
            in_doubt_ids.execution_id,
            worker_id="qualification:dispatch-in-doubt:before-restart",
        )
        assert in_doubt["lifecycle_state"] == "reconcile_required"

        stale_epoch_ids = _admit(
            driver,
            case_id="stale_process_epoch",
            attached_process=True,
        )
        envelopes["stale_process_epoch"] = _queue_materialized(
            driver,
            case_id="stale_process_epoch",
        )
        assert driver.run_execution_once(
            stale_epoch_ids.execution_id,
            worker_id="qualification:stale-process-epoch:result",
        )["lifecycle_state"] == "result_ready"
        stale_continuation = driver.continuation_state(
            stale_epoch_ids.continuation_id
        )
        correct_identity = AttachedProcessIdentity.from_continuation(
            stale_continuation,
            execution_id=stale_epoch_ids.execution_id,
        )
        stale_handle = _QualificationProcessHandle()
        running.dependencies.v3_live_process_registry.register(
            replace(
                correct_identity,
                process_epoch=correct_identity.process_epoch + 1,
            ),
            stale_handle,
        )
        stale_delivery = driver.run_continuation_once(
            worker_id="qualification:stale-process-epoch:delivery"
        )
        assert stale_delivery["action"] == "recovery_failed"
        stale_delivery_state = driver.continuation_state(
            stale_epoch_ids.continuation_id
        )
        assert stale_delivery_state.error_code == "attached_process_identity_mismatch"
        assert stale_handle.deliveries == []
        assert driver.run_execution_once(
            stale_epoch_ids.execution_id,
            worker_id="qualification:stale-process-epoch:terminal",
        )["lifecycle_state"] == "terminal"
        records["stale_process_epoch"] = driver.canonical_records(stale_epoch_ids)

        before_delivery_ids = _admit(
            driver,
            case_id="result_before_delivery",
            attached_process=True,
        )
        envelopes["result_before_delivery"] = _queue_materialized(
            driver,
            case_id="result_before_delivery",
        )
        assert driver.run_execution_once(
            before_delivery_ids.execution_id,
            worker_id="qualification:result-before-delivery:result",
        )["lifecycle_state"] == "result_ready"
        result_before_restart = driver.canonical_records(before_delivery_ids)
        continuation_before_restart = driver.continuation_state(
            before_delivery_ids.continuation_id
        )
        assert continuation_before_restart.delivery_state.value == "ready"

        concurrent_ids = _admit(driver, case_id="concurrent_claim")
        envelopes["concurrent_claim"] = _queue_materialized(
            driver,
            case_id="concurrent_claim",
        )
        entered = threading.Event()
        release = threading.Event()
        factory.external_ports["bio.provider_http"].install_one_shot_barrier(
            "dispatch",
            entered=entered,
            release=release,
        )
        outcomes: dict[str, dict[str, object]] = {}
        failures: list[BaseException] = []

        def run_worker(label: str) -> None:
            try:
                outcomes[label] = driver.run_execution_once(
                    concurrent_ids.execution_id,
                    worker_id=f"qualification:concurrent:{label}",
                )
            except BaseException as exc:  # pragma: no cover - surfaced below
                failures.append(exc)

        first_worker = threading.Thread(target=run_worker, args=("first",))
        first_worker.start()
        assert entered.wait(timeout=3.0), "first worker did not cross dispatch boundary"
        second_worker = threading.Thread(target=run_worker, args=("second",))
        second_worker.start()
        second_worker.join(timeout=3.0)
        assert second_worker.is_alive() is False
        release.set()
        first_worker.join(timeout=3.0)
        assert first_worker.is_alive() is False
        if failures:
            raise AssertionError("concurrent qualification worker failed") from failures[0]
        assert {item["action"] for item in outcomes.values()} == {
            "dispatch",
            "not_claimable",
        }
        assert driver.run_execution_once(
            concurrent_ids.execution_id,
            worker_id="qualification:concurrent:terminalize",
        )["lifecycle_state"] == "terminal"
        concurrent_before_restart = driver.canonical_records(concurrent_ids)

    assert stale_handle.alive is False
    assert stale_handle.stop_reasons == ["host_lifespan_stopping"]

    restarted = factory.restart(first)
    with restarted as running:
        running.stop_durable_supervisor()
        driver = QualificationDriver(running)

        envelopes["pre_dispatch_loss"] = _queue_materialized(
            driver,
            case_id="pre_dispatch_loss",
        )
        assert driver.run_execution_once(
            predispatch_ids.execution_id,
            worker_id="qualification:pre-dispatch-replacement",
        )["lifecycle_state"] == "result_ready"
        assert driver.run_execution_once(
            predispatch_ids.execution_id,
            worker_id="qualification:pre-dispatch-replacement",
        )["lifecycle_state"] == "terminal"
        records["pre_dispatch_loss"] = driver.canonical_records(predispatch_ids)

        assert probe_stale_execution_lease_release(
            running,
            execution_id=predispatch_ids.execution_id,
            session_id=predispatch_ids.session_id,
            stale_claim=stale_claim,
        )

        assert driver.run_execution_once(
            in_doubt_ids.execution_id,
            worker_id="qualification:dispatch-in-doubt:after-restart",
        )["lifecycle_state"] == "result_ready"
        assert driver.run_execution_once(
            in_doubt_ids.execution_id,
            worker_id="qualification:dispatch-in-doubt:after-restart",
        )["lifecycle_state"] == "terminal"
        records["dispatch_in_doubt"] = driver.canonical_records(in_doubt_ids)

        continuation_after_restart = driver.continuation_state(
            before_delivery_ids.continuation_id
        )
        assert continuation_after_restart.delivery_state.value == "recovery_failed"
        assert continuation_after_restart.error_code == (
            "attached_process_missing_after_restart"
        )
        assert driver.run_execution_once(
            before_delivery_ids.execution_id,
            worker_id="qualification:result-before-delivery:terminal",
        )["lifecycle_state"] == "terminal"
        records["result_before_delivery"] = driver.canonical_records(
            before_delivery_ids
        )
        assert records["result_before_delivery"]["result"] == (
            result_before_restart["result"]
        )

        records["concurrent_claim"] = driver.canonical_records(concurrent_ids)
        assert records["concurrent_claim"] == concurrent_before_restart
        assert driver.run_execution_once(
            concurrent_ids.execution_id,
            worker_id="qualification:concurrent:after-restart",
        )["action"] == "not_claimable"

        observation = collect_observation(
            running,
            session_ids=tuple(
                ids.session_id
                for ids in (
                    predispatch_ids,
                    in_doubt_ids,
                    stale_epoch_ids,
                    before_delivery_ids,
                    concurrent_ids,
                )
            ),
        )

    for case_id, case_records in records.items():
        assert_operation_oracle(
            case_records,
            expected_lifecycle="terminal",
            expected_terminal_outcome="succeeded",
            expected_envelope=envelopes[case_id],
            expected_result_ready_transitions=1,
            expected_terminal_transitions=1,
        )
    assert_effect_ledger_oracle(
        factory.external_effect_ledger,
        allowed_calls={
            ("bio.provider_http", "dispatch"): 5,
            ("bio.provider_http", "reconcile"): 1,
        },
        expected_effect_count=5,
    )
    assert_public_authority_absent(observation.payload["public_projection"])
