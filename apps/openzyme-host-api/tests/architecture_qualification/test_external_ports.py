from __future__ import annotations

from pathlib import Path

import pytest

from .composition import ProductionCompositionFactory
from .external_ports import ControlledExternalPort
from .external_ports import ControlledExternalPortError
from .external_ports import ControlledPortOutcome
from .external_ports import EffectAcceptance
from .external_ports import ExternalEffectLedger


def test_controlled_port_records_dispatch_poll_and_reconcile_canonically() -> None:
    ledger = ExternalEffectLedger()
    port = ControlledExternalPort(port_id="provider.http", ledger=ledger)
    port.queue(
        "dispatch",
        ControlledPortOutcome(
            acceptance=EffectAcceptance.NOT_ACCEPTED,
            error_code="provider_rejected_before_dispatch",
        ),
        ControlledPortOutcome(
            acceptance=EffectAcceptance.ACCEPTED,
            effect_attempted=True,
            response={"request_id": "req-1", "status": "accepted"},
        ),
    )
    port.queue(
        "poll",
        ControlledPortOutcome(acceptance=EffectAcceptance.IN_DOUBT),
    )
    port.queue(
        "reconcile",
        ControlledPortOutcome(
            acceptance=EffectAcceptance.TERMINAL,
            response={"request_id": "req-1", "status": "succeeded"},
        ),
    )

    with pytest.raises(ControlledExternalPortError) as not_accepted:
        port.invoke("dispatch", {"query": "qualification"})
    assert not_accepted.value.acceptance is EffectAcceptance.NOT_ACCEPTED
    assert port.invoke("dispatch", {"query": "qualification"})["status"] == (
        "accepted"
    )
    with pytest.raises(ControlledExternalPortError) as in_doubt:
        port.invoke("poll", {"request_id": "req-1"})
    assert in_doubt.value.acceptance is EffectAcceptance.IN_DOUBT
    assert port.invoke("reconcile", {"request_id": "req-1"})["status"] == (
        "succeeded"
    )

    snapshot = ledger.snapshot()
    assert snapshot["external_effects_real"] is False
    assert snapshot["fixture_mode"] == "qualification_fixture_non_cutover"
    assert str(snapshot["ledger_digest"]).startswith("sha256:")
    assert [entry.acceptance for entry in ledger.entries()] == list(EffectAcceptance)
    assert [entry.operation for entry in ledger.entries()] == [
        "dispatch",
        "dispatch",
        "poll",
        "reconcile",
    ]
    assert ledger.count(operation="dispatch") == 2
    assert ledger.count(operation="poll") == 1
    assert ledger.count(operation="reconcile") == 1
    assert ledger.count(acceptance=EffectAcceptance.ACCEPTED) == 1
    assert ledger.count(acceptance=EffectAcceptance.TERMINAL) == 1
    assert ledger.count_effects(port_id="provider.http") == 1


def test_unplanned_composition_ports_fail_closed_and_share_restart_ledger(
    tmp_path: Path,
) -> None:
    factory = ProductionCompositionFactory.create(tmp_path / "external-port-ledger")
    first = factory.build()

    with pytest.raises(ControlledExternalPortError) as runner_error:
        first.dependencies.foundation.execution_adapter.submit_execution(
            "sess_port_guard",
            {"command": "forbidden"},
        )
    assert runner_error.value.acceptance is EffectAcceptance.NOT_ACCEPTED
    with pytest.raises(ControlledExternalPortError):
        first.dependencies.v3_bio_adapter.ncbi_fetch_proteins(
            accessions=("ABC",),
            fields=("sequence",),
            retrieved_at="2026-07-22T00:00:00Z",
        )
    with pytest.raises(ControlledExternalPortError):
        first.dependencies.v3_pipeline_sandbox_runner.preflight()

    with first:
        pass
    restarted = factory.restart(first)
    assert restarted.external_effect_ledger is first.external_effect_ledger
    assert restarted.external_effect_ledger.count() == 3
    assert restarted.external_effect_ledger.count(
        acceptance=EffectAcceptance.NOT_ACCEPTED
    ) == 3
    assert restarted.external_effect_ledger.count(
        acceptance=EffectAcceptance.ACCEPTED
    ) == 0
