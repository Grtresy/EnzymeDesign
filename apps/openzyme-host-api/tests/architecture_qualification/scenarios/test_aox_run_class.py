from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

import openzyme_core
from openzyme_domain import MutationWriterKind
from openzyme_host_api import aox_attempt_authority
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
    assert "authorize-diagnostic" not in subcommands
    assert "consume-diagnostic-authority" not in subcommands
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
    assert "command" not in scientific_commands
    assert "finalize-admission" not in scientific_commands
    assert "finalize" not in scientific_commands
    assert {"receipt_chain", "seal_response"}.issubset(global_options)
    assert hasattr(HostApiClient, "export_v3_closed_scientific_attempt_evidence")
    assert hasattr(V3HostApiService, "export_closed_aox_attempt_evidence")
    assert not hasattr(HostApiClient, "execute_v3_scientific_attempt_command")
    assert not hasattr(HostApiClient, "finalize_v3_scientific_attempt_admission")
    assert not hasattr(HostApiClient, "finalize_v3_scientific_attempt_closure")
    assert not hasattr(V3HostApiService, "execute_scientific_attempt_command")
    assert not hasattr(V3HostApiService, "finalize_scientific_attempt_admission")
    assert not hasattr(V3HostApiService, "finalize_scientific_attempt_closure")
    assert not hasattr(openzyme_core.ScientificAttemptService, "create_attempt")
    assert not hasattr(aox_attempt_authority, "attempt_admission_arguments")
    assert callable(aox_attempt_preflight.load_attempt_preflight_receipt)
    assert callable(aox_host_supervision.supervised_attempt_host)
    assert callable(
        aox_public_conductor_bundle.finalize_and_seal_public_conductor_bundle
    )
    assert callable(aox_public_conductor_bundle.verify_public_conductor_bundle)
    factory = ProductionCompositionFactory.create(tmp_path / "aox-composition")
    composition = factory.build()
    public_routes = {
        (method, route.path)
        for route in composition.app.routes
        for method in (getattr(route, "methods", None) or ())
    }
    assert {
        ("POST", "/v3/sessions"),
        (
            "POST",
            "/v3/sessions/{session_id}/scientific-attempt-authorizations",
        ),
        ("GET", "/v3/sessions/{session_id}/scientific-attempts"),
        (
            "GET",
            "/v3/sessions/{session_id}/scientific-attempts/{attempt_id}/"
            "selections/{selection_id}/evidence",
        ),
        (
            "POST",
            "/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
        ),
    }.issubset(public_routes)
    retired_route_paths = {
        "/v3/sessions/{session_id}/scientific-attempt-commands",
        "/v3/sessions/{session_id}/scientific-attempt-admissions/finalize",
        "/v3/sessions/{session_id}/scientific-attempt-closures/finalize",
    }
    assert not retired_route_paths.intersection(
        path for _, path in public_routes
    )

    session_id = "sess_aox_production_composition"
    with composition.dependencies.v3_service_scope(mode="write") as service:
        created = service.create_session(
            session_id=session_id,
            project_id="aox-blank-world-cutover",
            objective="Qualify public Host and SQLite composition",
            title="AOX composition qualification",
        )
        posted = service.post_message(
            session_id=session_id,
            message="Qualify canonical public composition only.",
            skill_keys=(),
        )
    lane_id = "lane_aox_executor"
    task_id = "task_aox_execution"
    actor_ref = "agent:aox-executor"
    with composition.dependencies.v3_service_scope(mode="write") as service:
        registry = openzyme_core.ToolRegistry()
        openzyme_core.register_lane_tools(registry)
        openzyme_core.register_task_board_tools(registry)
        context = openzyme_core.SessionRuntimeContext(
            repositories=service.repositories,
            event_sink=openzyme_core.MemoryEventBus(),
            snapshot=openzyme_core.SessionRuntimeSnapshot.load(
                service.repositories,
                session_id,
            ),
            tool_registry=registry,
            restore_focus=openzyme_core.RestoreFocus(),
            agent_id=actor_ref,
            actor_kind="teammate",
            actor_role="executor",
        )
        with openzyme_core.MutationScopeService(service.repositories).writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.AGENT_TURN,
            owner_ref="qualification:executor-lane-setup",
        ):
            lane_result = registry.dispatch(
                context,
                openzyme_core.ToolInvocation(
                    call_id="call_aox_lane_create",
                    tool_name="lane.create",
                    arguments={
                        "lane_id": lane_id,
                        "name": "AOX executor",
                        "cwd": ".",
                    },
                ),
            )
            task_result = registry.dispatch(
                context,
                openzyme_core.ToolInvocation(
                    call_id="call_aox_task_create",
                    tool_name="task.create",
                    arguments={
                        "task_id": task_id,
                        "subject": "Execute AOX formal slot",
                        "description": "Qualification-only canonical task.",
                        "kind": "execution",
                        "assigned_ref": actor_ref,
                    },
                ),
            )
            bind_result = registry.dispatch(
                context,
                openzyme_core.ToolInvocation(
                    call_id="call_aox_lane_bind",
                    tool_name="lane.bind_task",
                    arguments={"lane_id": lane_id, "task_id": task_id},
                ),
            )
            openzyme_core.ProtocolService(service.repositories).delegate(
                session_id=session_id,
                agent_id=actor_ref,
                name="AOX Executor",
                role="executor",
                payload_ref=None,
                task_id=task_id,
                lane_id=lane_id,
                parent_agent_id="agent:master",
                correlation_id="corr_aox_executor_qualification",
            )
    assert lane_result.ok is True
    assert task_result.ok is True
    assert bind_result.ok is True

    with composition.dependencies.v3_service_scope(mode="write") as service:
        authority = service.grant_scientific_attempt_authorization(
            {
                "task_id": task_id,
                "campaign_id": "aox_campaign_composition",
                "workflow_id": "aox_blank_world",
                "root_ref": "formal-slots/aox_campaign_composition/1/composition",
                "grantor_kind": "operator",
                "allowed_scopes": ["formal"],
                "allowed_effect_classes": ["provider"],
                "allowed_providers": ["qualification.provider:v1"],
                "allowed_hpc_targets": [],
                "max_attempts": 1,
                "max_micu": 1,
                "max_cost_microunits": 0,
                "max_wall_time_seconds": 1,
                "expires_at": "2099-01-01T00:00:00+00:00",
            },
            session_id=session_id,
            grantor_ref="user:local-dev",
            idempotency_key="aox-composition-authority",
        )
    envelope_id = authority["record"]["envelope_id"]

    with composition.dependencies.v3_service_scope(mode="write") as service:
        registry = openzyme_core.ToolRegistry()
        openzyme_core.register_scientific_attempt_tools(registry)

        def attempt_context(agent_id: str) -> openzyme_core.SessionRuntimeContext:
            return openzyme_core.SessionRuntimeContext(
                repositories=service.repositories,
                event_sink=openzyme_core.MemoryEventBus(),
                snapshot=openzyme_core.SessionRuntimeSnapshot.load(
                    service.repositories,
                    session_id,
                ),
                tool_registry=registry,
                restore_focus=openzyme_core.RestoreFocus(
                    task_id=task_id,
                    lane_id=lane_id,
                ),
                scientific_workflow_contract_registry=(
                    service.scientific_workflow_contract_registry
                ),
                agent_id=agent_id,
                actor_kind="teammate",
                actor_role="executor",
            )

        mutation_scopes = openzyme_core.MutationScopeService(service.repositories)
        with mutation_scopes.writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.AGENT_TURN,
            owner_ref="qualification:wrong-actor",
        ):
            wrong_actor = registry.dispatch(
                attempt_context("agent:not-owner"),
                openzyme_core.ToolInvocation(
                    call_id="call_aox_attempt_wrong_actor",
                    tool_name="attempt.create",
                    arguments={
                        "envelope_id": envelope_id,
                        "idempotency_key": "wrong-actor-attempt",
                    },
                    task_id=task_id,
                    lane_id=lane_id,
                ),
            )
        assert wrong_actor.ok is False
        assert wrong_actor.error_code == "attempt_admission_actor_not_owner"
        assert not service.repositories.scientific_attempt_admission_requests.list_by_session(
            session_id
        )

        with mutation_scopes.writer_turn(
            session_id=session_id,
            owner_kind=MutationWriterKind.AGENT_TURN,
            owner_ref="qualification:executor-attempt-create",
        ):
            requested = registry.dispatch(
                attempt_context(actor_ref),
                openzyme_core.ToolInvocation(
                    call_id="call_aox_attempt_create",
                    tool_name="attempt.create",
                    arguments={
                        "envelope_id": envelope_id,
                        "idempotency_key": "executor-chosen-attempt-key",
                    },
                    task_id=task_id,
                    lane_id=lane_id,
                ),
            )
            assert requested.ok is True, requested.content
            assert not service.repositories.scientific_attempts.list_by_session(
                session_id
            )
        service.finalize_pending_scientific_transitions(session_id=session_id)
        admitted_attempts = service.repositories.scientific_attempts.list_by_session(
            session_id
        )
        assert len(admitted_attempts) == 1
        admitted_attempt = admitted_attempts[0]
        assert admitted_attempt.created_by == actor_ref
        assert admitted_attempt.lane_id == lane_id
        assert admitted_attempt.root_ref == (
            "formal-slots/aox_campaign_composition/1/composition"
        )
        assert admitted_attempt.attempt_id not in {
            envelope_id,
            "aox_campaign_composition",
            lane_id,
        }

        inspection = service.scientific_attempt_control().project_session(session_id)
        workspace = service.workspace(session_id)
        with pytest.raises(openzyme_core.ScientificAttemptError) as fault_rejection:
            service.inject_aox_reference_fault(
                session_id=session_id,
                attempt_id="fault-not-admitted",
                artifact_id="artifact-not-admitted",
                actor_ref="user:local-dev",
                idempotency_key="aox-composition-no-attempt",
            )
        with pytest.raises(openzyme_core.ScientificAttemptError) as export_rejection:
            service.export_closed_aox_attempt_evidence(
                session_id=session_id,
                attempt_id="not-closed",
                selection_id="not-sealed",
            )

    assert created["session_id"] == session_id
    assert posted.session_id == session_id
    assert inspection["attempt_count"] == 1
    assert inspection["attempts"][0]["attempt_id"] == admitted_attempt.attempt_id
    assert workspace["session"]["session_id"] == session_id
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
        "apps/openzyme-host-api/src/openzyme_host_api/aox_diagnostic_authority.py",
    )
    for relative_path in retired_paths:
        assert not (REPO_ROOT / relative_path).exists()

    observation = {
        "automatic_commands_absent": all(
            command not in subcommands
            for command in ("run-live", "run-diagnostic-live")
        ),
        "formal_authority_consumption_present": "consume-authority" in subcommands,
        "diagnostic_authority_commands_absent": all(
            command not in subcommands
            for command in ("authorize-diagnostic", "consume-diagnostic-authority")
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
            "scientific_mutation_absent": "command" not in scientific_commands,
            "scientific_finalizers_absent": all(
                command not in scientific_commands
                for command in ("finalize-admission", "finalize")
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
            "canonical_lane_id": admitted_attempt.lane_id,
            "late_bound_attempt_id": admitted_attempt.attempt_id,
            "assignee_bound_actor": admitted_attempt.created_by,
            "wrong_actor_rejected": (
                wrong_actor.error_code == "attempt_admission_actor_not_owner"
            ),
            "public_route_registry_composed": bool(public_routes),
            "legacy_public_routes_absent": not retired_route_paths.intersection(
                path for _, path in public_routes
            ),
            "fault_route_fail_closed": bool(fault_rejection.value.error_code),
            "export_route_fail_closed": bool(export_rejection.value.error_code),
        },
        "schema_id": "aox_post_r69_late_bound_composition_qualification@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
