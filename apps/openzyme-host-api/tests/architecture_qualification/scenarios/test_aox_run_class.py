from __future__ import annotations

import argparse
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import time

import pytest

import openzyme_core
from openzyme_host_api import aox_attempt_authority
from openzyme_host_api import aox_attempt_preflight
from openzyme_host_api import aox_conductor_execution
from openzyme_host_api import aox_cutover_cli
from openzyme_host_api import aox_cutover_launch
from openzyme_host_api import aox_diagnostic_run
from openzyme_host_api import aox_formal_slot_failure
from openzyme_host_api import aox_host_supervision
from openzyme_host_api import aox_public_conductor_bundle
from openzyme_host_api.aox_launch_profile import build_aox_cutover_launch_profile
from openzyme_host_api.v3_service import V3HostApiService
from openzyme_host_api.architecture_qualification import canonical_json_bytes
from openzyme_host_cli import cli as host_cli
from openzyme_host_cli.client import HostApiClient
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime.reliability import ControlledOperationOwnerPolicy

from ..composition import ProductionCompositionFactory
from ..composition import QUALIFICATION_SANDBOX_IMAGE_DIGEST
from ..composition import QUALIFICATION_SANDBOX_SDK_DIGEST
from ..execution_evidence import record_effect_ledger_snapshot
from ..execution_evidence import record_execution_observation_digest
from ..external_ports import ExternalEffectLedger


REPO_ROOT = Path(__file__).resolve().parents[5]


def _tool_message_payload(
    messages: list[object], *, tool_name: str
) -> dict[str, object]:
    for message in reversed(messages):
        name = (
            message.get("name")
            if isinstance(message, dict)
            else getattr(message, "name", None)
        )
        if name != tool_name:
            continue
        content = (
            message.get("content")
            if isinstance(message, dict)
            else getattr(message, "content", "")
        )
        try:
            envelope = json.loads(str(content or ""))
        except json.JSONDecodeError:
            continue
        payload = envelope.get("payload")
        if isinstance(payload, dict):
            return dict(payload)
    return {}


class _AoxPublicCompositionInvoker:
    def __init__(self, purpose: str) -> None:
        self.purpose = purpose
        self.calls = 0

    def invoke_with_tools(
        self,
        *,
        system_prompt: str,
        messages: list[object],
        tools: list[object],
    ) -> dict[str, object]:
        del system_prompt, tools
        self.calls += 1
        if self.purpose == "v3_harness_loop":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"create_{kind}",
                            "name": "task.create",
                            "args": {
                                "task_id": task_id,
                                "subject": f"AOX {kind} task",
                                "description": "Model-selected public composition task.",
                                "kind": kind,
                            },
                        }
                        for task_id, kind in (
                            ("model_execution_task", "execution"),
                            ("model_research_task", "research"),
                            ("model_reporting_task", "reporting"),
                        )
                    ],
                }
            if self.calls == 2:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": f"delegate_{role}",
                            "name": "task.delegate",
                            "args": {
                                "task_id": task_id,
                                "agent_role": role,
                                "instructions": "Exercise the canonical public runtime path.",
                            },
                        }
                        for task_id, role in (
                            ("model_execution_task", "executor"),
                            ("model_research_task", "researcher"),
                            ("model_reporting_task", "reporter"),
                        )
                    ],
                }
            return {"content": "Canonical task graph is ready.", "tool_calls": []}
        if self.purpose == "v3_teammate_loop:executor":
            if self.calls == 1:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "inspect_sandbox_workspace",
                            "name": "sandbox.workspace.status",
                            "args": {},
                        }
                    ],
                }
            if self.calls == 2:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "inspect_scientific_authority",
                            "name": "scientific.attempt.inspect",
                            "args": {"limit": 10},
                        }
                    ],
                }
            if self.calls == 3:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "create_executor_lane",
                            "name": "lane.create",
                            "args": {
                                "lane_id": "model_executor_lane",
                                "name": "Model-selected executor lane",
                                "cwd": ".",
                            },
                        }
                    ],
                }
            if self.calls == 4:
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "bind_executor_lane",
                            "name": "lane.bind_task",
                            "args": {
                                "lane_id": "model_executor_lane",
                                "task_id": "model_execution_task",
                            },
                        }
                    ],
                }
            if self.calls == 5:
                inspection = _tool_message_payload(
                    messages,
                    tool_name="scientific.attempt.inspect",
                )
                authorizations = inspection.get("authorizations")
                assert isinstance(authorizations, list) and len(authorizations) == 1
                envelope_id = str(dict(authorizations[0])["envelope_id"])
                return {
                    "content": "",
                    "tool_calls": [
                        {
                            "id": "create_late_bound_attempt",
                            "name": "attempt.create",
                            "args": {
                                "envelope_id": envelope_id,
                                "idempotency_key": "model-selected-attempt-create",
                            },
                        }
                    ],
                }
            return {"content": "Scientific attempt admitted.", "tool_calls": []}
        return {"content": "No qualification work requested.", "tool_calls": []}


class _AoxPublicCompositionModelFactory:
    def __init__(self) -> None:
        self.invokers: dict[str, _AoxPublicCompositionInvoker] = {}

    def create_tool_calling_invoker(self, *, purpose: str) -> _AoxPublicCompositionInvoker:
        if purpose not in self.invokers:
            self.invokers[purpose] = _AoxPublicCompositionInvoker(purpose)
        return self.invokers[purpose]


def _wait_for_terminal_command(
    client: HostApiClient,
    *,
    session_id: str,
    command_id: str,
) -> dict[str, object]:
    deadline = time.monotonic() + 15.0
    while True:
        status = client.get_v3_runtime_command(session_id, command_id)
        if status["status"] in {"completed", "failed", "locked", "cancelled"}:
            return status
        if time.monotonic() >= deadline:
            raise AssertionError(
                f"public runtime command did not reach a bounded terminal: {status}"
            )
        time.sleep(0.01)


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
        "public-host",
        "seal-conductor-state",
        "finalize-and-seal",
        "seal-slot-failure",
        "verify",
        "verify-slot-failure",
        "verify-preflight-failure",
        "decide",
    }

    assert "run-live" not in subcommands
    assert "run-diagnostic-live" not in subcommands
    assert "browser-receipt" not in subcommands
    assert "consume-authority" in subcommands
    assert "authorize-diagnostic" not in subcommands
    assert "consume-diagnostic-authority" not in subcommands
    assert required_conductor_commands.issubset(subcommands)
    public_host_arguments = {
        action.dest: action
        for action in subcommands["public-host"]._actions
    }
    assert public_host_arguments["host_cli_args"].nargs == argparse.REMAINDER
    attempt_finalizer_arguments = {
        action.dest for action in subcommands["finalize-and-seal"]._actions
    }
    assert "retirement_readiness" in attempt_finalizer_arguments
    slot_failure_arguments = {
        action.dest for action in subcommands["seal-slot-failure"]._actions
    }
    assert {"retirement_readiness", "pre_ready_failure"}.issubset(
        slot_failure_arguments
    )
    for finalizer_arguments in (
        attempt_finalizer_arguments,
        slot_failure_arguments,
    ):
        assert not {
            "receipt_chain",
            "workspace_response",
            "event_response",
            "evidence_response",
            "handoff_response",
        }.intersection(finalizer_arguments)
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
    assert callable(aox_conductor_execution.publish_conductor_execution_contract)
    assert callable(aox_conductor_execution.seal_conductor_retirement_readiness)
    assert callable(aox_conductor_execution.load_conductor_retirement_readiness)
    assert callable(aox_host_supervision.supervised_attempt_host)
    assert callable(
        aox_public_conductor_bundle.finalize_and_seal_public_conductor_bundle
    )
    assert callable(aox_public_conductor_bundle.verify_public_conductor_bundle)
    assert callable(aox_formal_slot_failure.finalize_and_seal_formal_slot_failure)
    assert callable(
        aox_formal_slot_failure.finalize_and_seal_pre_ready_formal_slot_failure
    )
    assert callable(aox_formal_slot_failure.verify_formal_slot_failure)
    assert callable(aox_formal_slot_failure.evaluate_formal_slot_failure)
    assert callable(
        aox_host_supervision.validate_supervised_host_pre_ready_failure
    )
    assert aox_formal_slot_failure.FORMAL_SLOT_FAILURE_SCHEMA_ID == (
        "aox_formal_slot_failure@2"
    )
    assert aox_formal_slot_failure.LEGACY_FORMAL_SLOT_FAILURE_SCHEMA_ID == (
        "aox_formal_slot_failure@1"
    )
    assert aox_host_supervision.HOST_PRE_READY_FAILURE_SCHEMA_ID == (
        "aox_supervised_host_pre_ready_failure@1"
    )
    factory = ProductionCompositionFactory.create(tmp_path / "aox-composition")
    model_factory = _AoxPublicCompositionModelFactory()
    composition = factory.build(
        model_factory=model_factory,
        bootstrap_supervised_sandbox=True,
    )
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

    identity = {
        "git_commit": "a" * 40,
        "config_digest": "sha256:" + "b" * 64,
    }
    settings = OpenZymeSettings.from_env()
    settings = replace(
        settings,
        reliability=replace(
            settings.reliability,
            controlled_operation_owner_policy=(
                ControlledOperationOwnerPolicy.ROUTE_ALLOWLIST_V1
            ),
        ),
    )
    qualification_launch_profile = build_aox_cutover_launch_profile(
        settings=settings,
        ledger_path=tmp_path / "micu-ledger.json",
        source_commit=str(identity["git_commit"]),
        config_digest=str(identity["config_digest"]),
        created_at="2026-08-04T00:00:00+00:00",
    )
    plan = aox_attempt_authority.build_aox_attempt_authority_plan(
        identity=identity,
        allowed_prerequisites={"provider_cache_mode": "bypass"},
        architecture_qualification={"schema_id": "qualification@1"},
        launch_profile=qualification_launch_profile,
        issued_at="2026-08-04T00:00:00+00:00",
        expires_at="2099-01-01T00:00:00+00:00",
        max_micu_per_attempt=1,
        max_cost_microunits_per_attempt=0,
        max_wall_time_seconds_per_attempt=60,
    )
    slot = dict(plan["slots"][0])
    session_id = str(slot["session_id"])

    with composition:
        assert composition.client is not None
        public = HostApiClient("http://testserver", session=composition.client)
        runtime_health = public.get_v3_runtime_health()
        sandbox_health = dict(dict(runtime_health["components"])["sandbox"])
        sandbox_details = dict(sandbox_health["details"])
        assert sandbox_health["status"] == "ready"
        assert sandbox_details["image_digest"] == QUALIFICATION_SANDBOX_IMAGE_DIGEST
        assert (
            sandbox_details["pipeline_sdk_digest"]
            == QUALIFICATION_SANDBOX_SDK_DIGEST
        )
        with composition.repository_provider.read() as reader:
            bootstrap_image = reader.repositories.sandbox_images.get_default()
            preexisting_session = reader.repositories.sessions.get(session_id)
            preexisting_workspaces = (
                reader.repositories.sandbox_workspaces.list_by_session(session_id)
            )
        assert bootstrap_image is not None
        assert bootstrap_image.image_ref.endswith(
            "@" + QUALIFICATION_SANDBOX_IMAGE_DIGEST
        )
        assert preexisting_session is None
        assert not preexisting_workspaces
        created = public.create_v3_session(
            session_id=session_id,
            project_id="aox-blank-world-cutover",
            objective="Qualify public Host and SQLite composition",
            title="AOX composition qualification",
        )
        posted = public.post_v3_message(
            session_id,
            message="Create and delegate the canonical AOX task graph.",
        )
        first = public.drain_v3_runtime(
            session_id,
            max_signals=1,
            max_steps_per_agent=8,
            idempotency_key="qualification:first-drain",
        )
        first_terminal = _wait_for_terminal_command(
            public,
            session_id=session_id,
            command_id=str(first["command_id"]),
        )
        workspace = public.get_v3_workspace(session_id)
        tasks = [
            dict(item["task"])
            for item in dict(workspace["task_board"])["items"]
        ]
        execution_tasks = [task for task in tasks if task.get("kind") == "execution"]
        assert len(tasks) == 3
        assert len(execution_tasks) == 1
        execution_task = execution_tasks[0]
        task_id = str(execution_task["task_id"])
        actor_ref = str(execution_task["assigned_ref"])

        invalid_grant = composition.client.post(
            f"/v3/sessions/{session_id}/scientific-attempt-authorizations",
            json=aox_attempt_authority.authority_grant_payload(
                slot,
                campaign_id=str(plan["campaign_id"]),
                task_id="not-a-canonical-task",
            ),
            headers={"Idempotency-Key": "qualification:invalid-task-grant"},
        )
        assert invalid_grant.status_code >= 400
        authority = public.grant_v3_scientific_attempt_authorization(
            session_id,
            aox_attempt_authority.authority_grant_payload(
                slot,
                campaign_id=str(plan["campaign_id"]),
                task_id=task_id,
            ),
            idempotency_key=str(dict(slot["authority_policy"])["idempotency_key"]),
        )
        envelope_id = str(dict(authority["record"])["envelope_id"])
        post_authority_terminals: list[dict[str, object]] = []
        inspection: dict[str, object] = {}
        for ordinal in range(1, 9):
            command = public.drain_v3_runtime(
                session_id,
                max_signals=1,
                max_steps_per_agent=8,
                idempotency_key=f"qualification:post-authority-drain:{ordinal}",
            )
            terminal = _wait_for_terminal_command(
                public,
                session_id=session_id,
                command_id=str(command["command_id"]),
            )
            post_authority_terminals.append(terminal)
            inspection = public.get_v3_scientific_attempts(session_id)
            if inspection["attempt_count"] == 1:
                break
        final_workspace = public.get_v3_workspace(session_id)
        final_execution_task = next(
            dict(item["task"])
            for item in dict(final_workspace["task_board"])["items"]
            if dict(item["task"]).get("kind") == "execution"
        )
        lane_id = str(final_execution_task["lane_id"])
        public_events = public.get_v3_events(session_id, after_cursor=0)
        fault_rejection = composition.client.post(
            f"/v3/sessions/{session_id}/aox-fault-injections/reference-byte-flip",
            json={"attempt_id": "not-admitted", "artifact_id": "not-admitted"},
            headers={"Idempotency-Key": "qualification:invalid-fault"},
        )
        export_rejection = composition.client.get(
            f"/v3/sessions/{session_id}/scientific-attempts/not-closed/"
            "selections/not-sealed/evidence"
        )

    assert created["session_id"] == session_id
    assert posted["session_id"] == session_id
    assert first_terminal["status"] == "completed"
    assert all(item["status"] == "completed" for item in post_authority_terminals)
    assert inspection["attempt_count"] == 1, {
        "inspection": inspection,
        "events": public_events,
        "terminals": post_authority_terminals,
    }
    admitted_attempt = dict(inspection["attempts"][0])
    admission = next(
        dict(item)
        for item in inspection["admission_requests"]
        if item.get("finalized_attempt_id") == admitted_attempt["attempt_id"]
    )
    assert admitted_attempt["task_id"] == task_id
    assert admitted_attempt["lane_id"] == lane_id
    assert admission["task_id"] == task_id
    assert admission["lane_id"] == lane_id
    assert admission["actor_ref"] == actor_ref
    assert authority["record"]["root_ref"] == slot["root_ref"]
    assert admitted_attempt["attempt_id"] not in {
        envelope_id,
        str(plan["campaign_id"]),
        lane_id,
    }
    assert workspace["session"]["session_id"] == session_id
    assert any(event["event_type"] == "runtime.command.finished" for event in public_events)
    assert fault_rejection.status_code >= 400
    assert export_rejection.status_code >= 400
    with composition.repository_provider.read() as reader:
        persisted_session = reader.repositories.sessions.get(session_id)
        persisted_messages = reader.repositories.inbox.list_by_session(session_id)
        persisted_events = reader.repositories.durable_events.list_by_session(
            session_id,
            after_cursor=0,
            limit=1_000,
        )
        sandbox_workspaces = reader.repositories.sandbox_workspaces.list_by_session(
            session_id
        )
    assert persisted_session is not None
    assert any(item.message_type == "user_message" for item in persisted_messages)
    assert persisted_events
    assert len(sandbox_workspaces) == 1
    assert sandbox_workspaces[0].status.value == "ready"
    assert sandbox_workspaces[0].image_digest == QUALIFICATION_SANDBOX_IMAGE_DIGEST
    assert not hasattr(model_factory, "authority_envelope_id")

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
        "public_conductor_execution_contract_present": all(
            callable(item)
            for item in (
                aox_conductor_execution.publish_conductor_execution_contract,
                aox_conductor_execution.seal_conductor_retirement_readiness,
                aox_conductor_execution.load_conductor_retirement_readiness,
            )
        ),
        "public_conductor_strategy_preserved": (
            public_host_arguments["host_cli_args"].nargs == argparse.REMAINDER
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
            "file_backed_sqlite": Path(
                composition.repository_provider.database_path
            ).name
            == "control-plane.sqlite3",
            "sandbox_bootstrap_receipt": bool(
                composition.sandbox_bootstrap_receipt
            ),
            "sandbox_runtime_health": sandbox_health["status"],
            "sandbox_workspace_status": sandbox_workspaces[0].status.value,
            "executor_inspect_and_lane_calls": model_factory.invokers[
                "v3_teammate_loop:executor"
            ].calls,
            "session_persisted": persisted_session is not None,
            "message_persisted": bool(persisted_messages),
            "events_persisted": bool(persisted_events),
            "canonical_lane_id": admitted_attempt["lane_id"],
            "late_bound_task_id": admitted_attempt["task_id"],
            "late_bound_attempt_id": admitted_attempt["attempt_id"],
            "assignee_bound_actor": admission["actor_ref"],
            "speculative_task_grant_rejected": invalid_grant.status_code >= 400,
            "first_runtime_command_terminal": first_terminal["status"],
            "post_authority_runtime_command_terminals": [
                item["status"] for item in post_authority_terminals
            ],
            "public_route_registry_composed": bool(public_routes),
            "legacy_public_routes_absent": not retired_route_paths.intersection(
                path for _, path in public_routes
            ),
            "fault_route_fail_closed": fault_rejection.status_code >= 400,
            "export_route_fail_closed": export_rejection.status_code >= 400,
        },
        "schema_id": "aox_post_r71_fresh_host_composition_qualification@1",
    }
    record_execution_observation_digest(
        "sha256:" + hashlib.sha256(canonical_json_bytes(observation)).hexdigest()
    )
    record_effect_ledger_snapshot(ExternalEffectLedger().snapshot())
