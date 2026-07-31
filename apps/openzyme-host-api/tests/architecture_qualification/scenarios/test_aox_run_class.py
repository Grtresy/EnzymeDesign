from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import openzyme_core
from openzyme_host_api import aox_cutover_cli
from openzyme_host_api import aox_diagnostic_run
from openzyme_host_api.architecture_qualification import canonical_json_bytes

from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger


REPO_ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.aox-run-class-disjoint-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_aox_automatic_run_surfaces_are_retired() -> None:
    parser = aox_cutover_cli.build_parser()
    subcommands = parser._subparsers._group_actions[0].choices

    assert "run-live" not in subcommands
    assert "run-diagnostic-live" not in subcommands
    assert "consume-authority" in subcommands
    assert "consume-diagnostic-authority" in subcommands
    assert not hasattr(aox_diagnostic_run, "AoxDiagnosticRun")
    assert not hasattr(openzyme_core, "RuntimeBarrierProjectionService")

    retired_paths = (
        "apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_live.py",
        "apps/openzyme-host-api/src/openzyme_host_api/aox_runtime_observation.py",
        "packages/openzyme-core/src/openzyme_core/runtime_barrier.py",
    )
    for relative_path in retired_paths:
        assert not (REPO_ROOT / relative_path).exists()

    observation = {
        "automatic_commands_absent": all(
            command not in subcommands
            for command in ("run-live", "run-diagnostic-live")
        ),
        "authority_consumption_commands_present": all(
            command in subcommands
            for command in ("consume-authority", "consume-diagnostic-authority")
        ),
        "diagnostic_runner_absent": not hasattr(aox_diagnostic_run, "AoxDiagnosticRun"),
        "retired_paths_absent": [
            relative_path
            for relative_path in retired_paths
            if not (REPO_ROOT / relative_path).exists()
        ],
        "runtime_barrier_absent": not hasattr(
            openzyme_core,
            "RuntimeBarrierProjectionService",
        ),
        "schema_id": "aox_r67_deletion_first_observation@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
