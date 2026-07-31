from __future__ import annotations

import hashlib
import inspect
from pathlib import Path

import pytest

import openzyme_core
from openzyme_host_api import aox_attempt_preflight
from openzyme_host_api import aox_cutover_cli
from openzyme_host_api import aox_cutover_launch
from openzyme_host_api import aox_diagnostic_run
from openzyme_host_api import aox_host_supervision
from openzyme_host_api import aox_public_conductor_bundle
from openzyme_host_api import app as host_app
from openzyme_host_api.v3_service import V3HostApiService
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_cli import cli as host_cli
from openzyme_host_cli.client import HostApiClient

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
    required_conductor_commands = {
        "preflight",
        "serve-attempt",
        "finalize-and-seal",
        "verify",
        "decide",
    }

    assert "run-live" not in subcommands
    assert "run-diagnostic-live" not in subcommands
    assert "browser-receipt" not in subcommands
    assert "consume-authority" in subcommands
    assert "consume-diagnostic-authority" in subcommands
    assert required_conductor_commands.issubset(subcommands)
    assert not hasattr(aox_diagnostic_run, "AoxDiagnosticRun")
    assert not hasattr(aox_cutover_launch, "AoxCutoverDriverConfig")
    assert not hasattr(openzyme_core, "RuntimeBarrierProjectionService")

    public_parser = host_cli._build_parser()
    public_resources = public_parser._subparsers._group_actions[0].choices
    session_commands = public_resources["sessions"]._subparsers._group_actions[
        0
    ].choices
    approval_commands = public_resources["approvals"]._subparsers._group_actions[
        0
    ].choices
    scientific_commands = public_resources[
        "scientific"
    ]._subparsers._group_actions[0].choices
    global_options = {action.dest for action in public_parser._actions}
    assert "events" in session_commands
    assert "pending" in approval_commands
    assert "export-evidence" in scientific_commands
    assert {"receipt_chain", "seal_response"}.issubset(global_options)
    assert hasattr(HostApiClient, "export_v3_closed_scientific_attempt_evidence")
    assert hasattr(V3HostApiService, "export_closed_aox_attempt_evidence")
    assert callable(aox_attempt_preflight.load_attempt_preflight_receipt)
    assert callable(aox_host_supervision.supervised_attempt_host)
    assert callable(
        aox_public_conductor_bundle.finalize_and_seal_public_conductor_bundle
    )
    assert callable(aox_public_conductor_bundle.verify_public_conductor_bundle)
    route_source = inspect.getsource(host_app.create_app)
    assert "selections/{selection_id}/evidence" in route_source
    assert "export_v3_closed_scientific_attempt_evidence" in route_source

    retired_paths = (
        "apps/openzyme-host-api/src/openzyme_host_api/aox_cutover_live.py",
        "apps/openzyme-host-api/src/openzyme_host_api/aox_runtime_observation.py",
        "apps/openzyme-host-api/src/openzyme_host_api/aox_attempt_supervision.py",
        "apps/openzyme-host-api/src/openzyme_host_api/aox_browser_observation.py",
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
        "public_conductor_commands_present": sorted(
            required_conductor_commands.intersection(subcommands)
        ),
        "public_host_cli_receipt_chain_present": {
            "events": "events" in session_commands,
            "pending_approvals": "pending" in approval_commands,
            "closed_attempt_export": "export-evidence" in scientific_commands,
            "receipt_chain": "receipt_chain" in global_options,
            "sealed_response": "seal_response" in global_options,
        },
        "public_host_evidence_export_present": (
            hasattr(V3HostApiService, "export_closed_aox_attempt_evidence")
            and hasattr(
                HostApiClient,
                "export_v3_closed_scientific_attempt_evidence",
            )
        ),
        "source_bound_finalizer_present": all(
            callable(item)
            for item in (
                aox_public_conductor_bundle.finalize_and_seal_public_conductor_bundle,
                aox_public_conductor_bundle.verify_public_conductor_bundle,
            )
        ),
        "policy_free_host_supervision_present": callable(
            aox_host_supervision.supervised_attempt_host
        ),
        "diagnostic_runner_absent": not hasattr(aox_diagnostic_run, "AoxDiagnosticRun"),
        "legacy_driver_absent": not hasattr(
            aox_cutover_launch,
            "AoxCutoverDriverConfig",
        ),
        "retired_paths_absent": [
            relative_path
            for relative_path in retired_paths
            if not (REPO_ROOT / relative_path).exists()
        ],
        "runtime_barrier_absent": not hasattr(
            openzyme_core,
            "RuntimeBarrierProjectionService",
        ),
        "schema_id": "aox_r68_public_conductor_reachability@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
