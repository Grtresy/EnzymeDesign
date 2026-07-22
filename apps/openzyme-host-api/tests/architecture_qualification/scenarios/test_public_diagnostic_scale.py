from __future__ import annotations

import json
from pathlib import Path

import pytest

from openzyme_host_api.architecture_qualification import load_invariant_registry

from ..boundary_probes import probe_public_diagnostic_bounded_work
from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..execution_evidence import record_observed_p0_trigger


REPO_ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.architecture_qualification_scenario(
    scenario_id="boundary-scale.public-diagnostic-bounded-work",
    family="boundary-scale",
    selections=("full", "premerge_subset"),
)
def test_public_diagnostic_sanitizer_has_bounded_work() -> None:
    registry = load_invariant_registry(repo_root=REPO_ROOT)
    probe = probe_public_diagnostic_bounded_work(registry=registry.payload)
    record_effect_ledger_snapshot(probe.effect_ledger)
    record_execution_observation_digest(probe.evidence_digest)
    if not probe.completed_within_deadline:
        record_observed_p0_trigger("unbounded-progress")

    assert probe.retirement_proven is True
    assert probe.effect_ledger["external_effects_real"] is False
    assert probe.completed_within_deadline, (
        "public diagnostic sanitizer exceeded bounded-work deadline: "
        + json.dumps(
            {
                "deadline_milliseconds": probe.deadline_milliseconds,
                "input_byte_length": probe.input_byte_length,
                "raw_exit_code": probe.raw_exit_code,
            },
            sort_keys=True,
        )
    )
