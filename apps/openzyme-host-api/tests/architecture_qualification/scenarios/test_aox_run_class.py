from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import openzyme_core
from openzyme_host_api import aox_attempt_preflight
from openzyme_host_api import aox_cutover_cli
from openzyme_host_api import aox_cutover_launch
from openzyme_host_api import aox_diagnostic_run
from openzyme_host_api import aox_host_supervision
from openzyme_host_api import aox_public_conductor_bundle
from openzyme_host_api.v3_service import V3HostApiService
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_cli import cli as host_cli
from openzyme_host_cli.client import HostApiClient

from ..composition import ProductionCompositionFactory
from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger


REPO_ROOT = Path(__file__).resolve().parents[5]


@pytest.mark.architecture_qualification_scenario(
    scenario_id="evidence-projection.aox-run-class-disjoint-closure",
    family="evidence-projection",
    selections=("full", "premerge_subset"),
)
def test_aox_automatic_run_surfaces_are_retired(tmp_path: Path) -> None:
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
    assert "inject-aox-reference-fault" in scientific_commands
    assert {"receipt_chain", "seal_response"}.issubset(global_options)
    assert hasattr(HostApiClient, "export_v3_closed_scientific_attempt_evidence")
    assert hasattr(V3HostApiService, "export_closed_aox_attempt_evidence")
    assert callable(aox_attempt_preflight.load_attempt_preflight_receipt)
    assert callable(aox_host_supervision.supervised_attempt_host)
    assert callable(
        aox_public_conductor_bundle.finalize_and_seal_public_conductor_bundle
    )
    assert callable(aox_public_conductor_bundle.verify_public_conductor_bundle)
    factory = ProductionCompositionFactory.create(tmp_path / "aox-composition")
    composition = factory.build()
    with composition as running:
        running.stop_durable_supervisor()
        client = running.client
        assert client is not None
        session_id = "sess_aox_production_composition"
        created = client.post(
            "/v3/sessions",
            json={
                "session_id": session_id,
                "project_id": "aox-blank-world-cutover",
                "objective": "Qualify public Host and SQLite composition",
                "title": "AOX composition qualification",
            },
        )
        posted = client.post(
            f"/v3/sessions/{session_id}/messages",
            headers={"Idempotency-Key": "aox-composition-message"},
            json={
                "message": "Qualify canonical public composition only.",
                "skill_keys": [],
            },
        )
        workspace = client.get(f"/v3/sessions/{session_id}/workspace")
        events = client.get(f"/v3/sessions/{session_id}/events?replay=1&after_cursor=0")
        fault_rejection = client.post(
            f"/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
            headers={"Idempotency-Key": "aox-composition-no-attempt"},
            json={
                "attempt_id": "fault-not-admitted",
                "artifact_id": "artifact-not-admitted",
            },
        )
        export_rejection = client.get(
            f"/v3/sessions/{session_id}/scientific-attempts/not-closed/"
            "selections/not-sealed/evidence"
        )
    assert created.status_code == 200
    assert posted.status_code == 200
    assert workspace.status_code == 200
    assert events.status_code == 200
    assert fault_rejection.status_code == 409
    assert export_rejection.status_code == 409
    with composition.repository_provider.read() as reader:
        persisted_session = reader.repositories.sessions.get(session_id)
        persisted_messages = reader.repositories.inbox.list_by_session(session_id)
        persisted_events = reader.repositories.durable_events.list_by_session(
            session_id,
            after_cursor=0,
            limit=1_000,
        )
    assert persisted_session is not None
    assert any(item.message_type == "user_message" for item in persisted_messages)
    assert persisted_events

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
            "exact_fault_capability": (
                "inject-aox-reference-fault" in scientific_commands
            ),
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
        "production_composition": {
            "file_backed_sqlite": composition.repository_provider.database_path.endswith(
                "aox-composition.sqlite3"
            ),
            "session_persisted": persisted_session is not None,
            "message_persisted": bool(persisted_messages),
            "events_persisted": bool(persisted_events),
            "fault_route_fail_closed": fault_rejection.status_code == 409,
            "export_route_fail_closed": export_rejection.status_code == 409,
        },
        "schema_id": "aox_post_r68_public_composition_qualification@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
