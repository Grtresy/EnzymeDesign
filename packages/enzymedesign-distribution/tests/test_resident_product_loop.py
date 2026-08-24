from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
import json
import sqlite3
from datetime import UTC
from datetime import datetime
from pathlib import Path

import httpx

import test_distribution as support
from enzymedesign_distribution import ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS
from enzymedesign_distribution import activate_enzymedesign_composition
from enzymedesign_distribution import build_enzymedesign_application_runtime
from enzymedesign_distribution import build_enzymedesign_fresh_install_seed
from enzymedesign_distribution import verify_enzymedesign_deployment_startup_read_only
from enzymedesign_distribution.launcher import EnzymeDesignHostLauncher
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import WorkspaceProvisionerPortError
from openzyme_host_api import HostSecurityPolicy
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_reporting import ReportingToolRuntime
from scripts.test_gate.no_live_effects import ExternalEffectDenyGuard
from openzyme_store_sqlite import ENZYMEDESIGN_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only


def _digest(label: str) -> str:
    return canonical_sha256_digest({"resident_e2e": label})


def _initialize_file_store(database_path: Path):  # noqa: ANN201
    connection = sqlite3.connect(database_path, check_same_thread=False)
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=ENZYMEDESIGN_OWNER_SCHEMA_PROFILE,
    )
    wheel_digest = _digest("installed-wheels")
    seed = build_enzymedesign_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=wheel_digest,
        host_build_digest=_digest("host-build"),
        client_build_digest=_digest("client-build"),
        epoch_id="enzymedesign-file-resident-e2e",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-22T00:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    return connection, seed, wheel_digest


def _build_launcher(
    connection,
    *,
    seed,
    wheel_digest,
    workspace_provisioner_factory=None,  # noqa: ANN001
):  # noqa: ANN001, ANN201
    clock = DeterministicClock(datetime(2026, 8, 22, tzinfo=UTC))
    startup = verify_enzymedesign_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=wheel_digest,
        verified_at="2026-08-22T00:01:00+00:00",
    )
    composition = activate_enzymedesign_composition()
    runtime_manifest = next(
        item.manifest
        for item in composition.adapters
        if item.selection.slot_id == "agent.turn"
    )
    runtime_adapter = support._ResidentRuntimeAdapter(
        runtime_manifest.identity.component_id,
        runtime_manifest.identity.contract_digest,
    )
    operational = support._operational_selection(runtime_adapter=runtime_adapter)
    adapters = support._adapter_runtime_set(
        operational,
        workspace_provisioner_factory=workspace_provisioner_factory,
    )
    runtime = build_enzymedesign_application_runtime(
        connection,
        startup=startup,
        surfaces=support._runtime_surface_set(),
        adapter_runtimes=adapters,
        inventories=support._EmptyInventoryRepository(),
        clock=clock,
        ids=DeterministicIdGenerator(),
        bootstrap_authority=support._BootstrapAuthority(),
        **support._bootstrap_runtime_kwargs(
            project_id="project-resident-e2e",
            adapters=adapters,
            created_by="user:local-dev",
        ),
    )
    workspace_runtime = adapters.require_binding(slot_id="workspace.backend").runtime
    provisioner = workspace_runtime.provisioner
    return (
        EnzymeDesignHostLauncher(
            runtime=runtime,
            security_policy=HostSecurityPolicy.from_settings(None),
        ),
        provisioner,
        runtime_adapter,
    )


def _base_headers() -> dict[str, str]:
    return {
        "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "OpenZyme-Workspace-Contract": "file_workspace_public@2",
        "X-Request-Id": "request-enzymedesign-resident-e2e",
    }


def _mutation_headers(response, idempotency_key: str) -> dict[str, str]:  # noqa: ANN001
    return {
        **_base_headers(),
        "Idempotency-Key": idempotency_key,
        **{
            name: response.headers[name]
            for name in (
                "OpenZyme-Release-Digest",
                "OpenZyme-Public-Contract-Digest",
                "OpenZyme-Projection-Digest",
                "OpenZyme-Capability-Binding-Digest",
                "OpenZyme-Affordance-Snapshot-Digest",
            )
        },
    }


@dataclass(slots=True)
class _DispatchInDoubtWorkspaceProvisioner:
    provider_id: str
    adapter_binding_digest: str
    requests: list[object] = field(default_factory=list)
    reconciliation_requests: list[object] = field(default_factory=list)

    def provision(self, request):  # noqa: ANN001, ANN201
        self.requests.append(request)
        raise WorkspaceProvisionerPortError(
            code="non_live_workspace_dispatch_response_lost",
            diagnostic_id="diagnostic-non-live-dispatch-response-lost",
            summary="The non-live dispatch response was intentionally lost",
        )

    def reconcile(self, request):  # noqa: ANN001, ANN201
        self.reconciliation_requests.append(request)
        raise WorkspacePortError(
            "non_live_reconciliation_observed_no_effect",
            "The non-live reconciliation proved that no mutation occurred",
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            mutation_applied=False,
            diagnostic_id="diagnostic-non-live-reconciliation-no-effect",
        )


def test_fresh_file_backed_resident_loop_is_async_exact_and_restartable(
    tmp_path: Path,
    deny_external_effects: ExternalEffectDenyGuard,
) -> None:
    database_path = tmp_path / "enzymedesign-resident.sqlite3"
    connection, seed, wheel_digest = _initialize_file_store(database_path)
    launcher, provisioner, runtime_adapter = _build_launcher(
        connection,
        seed=seed,
        wheel_digest=wheel_digest,
    )
    launcher.start(background=False)
    runtime = launcher.runtime

    async def exercise() -> str:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=launcher.app),
            base_url="http://enzymedesign.test",
        ) as client:
            health = await client.get("/healthz")
            created = await client.post(
                "/v3/sessions",
                headers={
                    **_base_headers(),
                    "Idempotency-Key": "bootstrap-resident-e2e",
                    "OpenZyme-Release-Digest": health.json()["release_digest"],
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                },
                json={
                    "session_id": "session-resident-e2e",
                    "project_id": "project-resident-e2e",
                    "title": "EnzymeDesign resident teammate",
                    "objective": "Prove the exact asynchronous resident loop",
                },
            )
            assert created.status_code == 202, created.text
            assert created.json()["result"]["workspace_readiness"] == "provisioning"
            assert provisioner.requests == []
            assert runtime_adapter.commands == []
            generations = runtime.store.list_for_session(
                entity_type="workspace_generation",
                session_id="session-resident-e2e",
                max_items=4,
            )
            leases = runtime.store.list_for_session(
                entity_type="agent_authority_lease",
                session_id="session-resident-e2e",
                max_items=4,
            )
            pins = runtime.store.list_for_session(
                entity_type="session_repository_binding_pin",
                session_id="session-resident-e2e",
                max_items=4,
            )
            assert len(generations) == len(leases) == len(pins) == 1
            assert generations[0].payload["status"] == "reserved"
            assert leases[0].payload["state"] == "pending"

            provisioning = await client.get(
                "/v3/sessions/session-resident-e2e/workspace",
                headers=_base_headers(),
            )
            assert provisioning.status_code == 200, provisioning.text
            assert (
                provisioning.json()["core"]["session"]["resident_readiness"][
                    "readiness"
                ]
                == "provisioning"
            )
            early_message = await client.post(
                "/v3/sessions/session-resident-e2e/messages",
                headers=_mutation_headers(provisioning, "early-message"),
                json={
                    "message_id": "early-message",
                    "message": "Do not run before the exact workspace is ready.",
                    "task_id": None,
                    "lane_id": None,
                    "workflow_refs": [],
                },
            )
            assert early_message.status_code == 409, early_message.text

            intent = runtime.store.list_for_session(
                entity_type="workspace_provisioning_intent",
                session_id="session-resident-e2e",
                max_items=4,
            )[0]
            assert intent.payload["status"] == "pending"
            provisioning_receipts = launcher.tick_workspace_provisioning(
                session_id="session-resident-e2e",
                maximum=1,
            )
            assert len(provisioning_receipts) == 1
            assert provisioning_receipts[0].result["readiness"] == "ready"

            ready = await client.get(
                "/v3/sessions/session-resident-e2e/workspace",
                headers=_base_headers(),
            )
            assert ready.status_code == 200, ready.text
            ready_projection = ready.json()
            core = ready_projection["core"]
            assert core["session"]["resident_readiness"]["readiness"] == "ready"
            assert set(ready_projection["extensions"]) == {
                section_id
                for section_id, _projection in runtime.mounted_surfaces.projections
            }
            assert len(ready_projection["extensions"]) == 5
            exposure = core["tool_reflection"]["tool_exposure"]
            assert "world.inspect" in exposure["direct_tool_names"]
            assert "report.publish" in exposure["deferred_tool_names"]
            assert "hpc.workspace.exec" not in json.dumps(
                core["tool_reflection"],
                sort_keys=True,
            )

            message = await client.post(
                "/v3/sessions/session-resident-e2e/messages",
                headers=_mutation_headers(ready, "message-resident-e2e"),
                json={
                    "message_id": "message-resident-e2e",
                    "message": "Inspect the exact world and answer without live effects.",
                    "task_id": None,
                    "lane_id": None,
                    "workflow_refs": list(ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS),
                },
            )
            assert message.status_code == 202, message.text
            assert message.json()["result"]["runtime_executed"] is False
            assert runtime_adapter.commands == []

            authorities = runtime.store.list_for_session(
                entity_type="workflow_authority_binding",
                session_id="session-resident-e2e",
                max_items=4,
            )
            assert len(authorities) == 1
            authority = WorkflowAuthorityBinding.from_dict(authorities[0].payload)
            assert authority.selected_workflow_refs == (
                ENZYMEDESIGN_ADOPTED_WORKFLOW_REFS
            )
            links = runtime.store.list_for_session(
                entity_type="runtime_signal_authority_link",
                session_id="session-resident-e2e",
                max_items=4,
            )
            assert len(links) == 1
            assert links[0].payload["authority_binding_digest"] == (
                authority.binding_digest
            )

            queued = await client.get(
                "/v3/sessions/session-resident-e2e/workspace",
                headers=_base_headers(),
            )
            drained = await client.post(
                "/v3/sessions/session-resident-e2e/runtime/drain",
                headers=_mutation_headers(queued, "drain-resident-e2e"),
                json={"max_signals": 1, "max_steps_per_agent": 4},
            )
            assert drained.status_code == 202, drained.text
            admitted = drained.json()["result"]
            assert admitted["runtime_executed"] is False
            assert admitted["task_transition_performed"] is False
            assert admitted["fallback_performed"] is False
            assert runtime_adapter.commands == []

            worker_receipts = launcher.tick_runtime_commands(
                session_id="session-resident-e2e",
                maximum=1,
            )
            assert len(worker_receipts) == 1
            assert worker_receipts[0].result["runtime_command_status"] == "completed", (
                worker_receipts[0].result,
            )
            assert len(runtime_adapter.commands) == 1
            assert runtime_adapter.world_result.ok
            assert runtime_adapter.inspection_result.ok, (
                runtime_adapter.inspection_result.to_dict()
            )
            assert "report_draft.get" in runtime_adapter.expanded_tool_names, (
                runtime_adapter.inspection_result.to_dict(),
                runtime_adapter.expanded_tool_names,
            )
            assert runtime_adapter.deferred_result.ok
            assert runtime_adapter.expansion_fences_after == (
                runtime_adapter.expansion_fences_before
            )
            report_draft_runtime = dict(runtime.mounted_tools.tools)["report_draft.get"]
            assert isinstance(report_draft_runtime, ReportingToolRuntime)
            qualification_matrix = {
                "mounted": {name for name, _runtime in runtime.mounted_tools.tools},
                "exercised": {
                    "world.inspect",
                    "capabilities.inspect",
                    "report_draft.get",
                },
                "substituted": {
                    "agent.turn": type(runtime_adapter).__name__,
                    "report_draft.get": type(report_draft_runtime.application).__name__,
                    "workspace.backend": type(provisioner).__name__,
                },
            }
            assert qualification_matrix["exercised"].issubset(
                qualification_matrix["mounted"]
            )
            assert qualification_matrix["substituted"] == {
                "agent.turn": "_ResidentRuntimeAdapter",
                "report_draft.get": "_NoopApplication",
                "workspace.backend": "_ReadyWorkspaceProvisioner",
            }

            settled = await client.get(
                "/v3/sessions/session-resident-e2e/workspace",
                headers=_base_headers(),
            )
            assert settled.status_code == 200, settled.text
            settled_core = settled.json()["core"]
            transcript = settled_core["conversation"]["transcript"]
            assert [item["role"] for item in transcript["messages"]] == [
                "user",
                "tool",
                "tool",
                "tool",
                "assistant",
            ]
            assert all(
                item["tool_call_id"] is not None
                for item in transcript["messages"]
                if item["role"] == "tool"
            )
            assert transcript["messages"][-1]["content"].startswith(
                "I inspected the exact resident world"
            )
            assert "hpc.workspace.exec" not in json.dumps(
                settled_core,
                sort_keys=True,
            )
            return transcript["transcript_digest"]

    transcript_digest = asyncio.run(exercise())
    assert len(provisioner.requests) == 1
    launcher.close()

    restarted_connection = sqlite3.connect(database_path, check_same_thread=False)
    restarted_connection.execute("PRAGMA foreign_keys = ON")
    restarted_launcher, restarted_provisioner, restarted_adapter = _build_launcher(
        restarted_connection,
        seed=seed,
        wheel_digest=wheel_digest,
    )
    restarted_launcher.start(background=False)

    async def inspect_restarted() -> None:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=restarted_launcher.app),
            base_url="http://enzymedesign.test",
        ) as client:
            response = await client.get(
                "/v3/sessions/session-resident-e2e/workspace",
                headers=_base_headers(),
            )
            assert response.status_code == 200, response.text
            core = response.json()["core"]
            assert core["session"]["resident_readiness"]["readiness"] == "ready"
            assert core["conversation"]["transcript"]["transcript_digest"] == (
                transcript_digest
            )
            assert core["runtime"]["commands"][0]["status"] == "completed"
            assert "hpc.workspace.exec" not in json.dumps(core, sort_keys=True)

    asyncio.run(inspect_restarted())
    assert restarted_provisioner.requests == []
    assert restarted_adapter.commands == []
    assert deny_external_effects.attempts == []
    restarted_launcher.close()


def test_file_backed_reconciliation_is_admission_only_and_successor_is_history(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "enzymedesign-reconciliation.sqlite3"
    connection, seed, wheel_digest = _initialize_file_store(database_path)
    provisioners: list[_DispatchInDoubtWorkspaceProvisioner] = []

    def provisioner_factory(
        provider_id: str,
        adapter_binding_digest: str,
    ) -> _DispatchInDoubtWorkspaceProvisioner:
        provisioner = _DispatchInDoubtWorkspaceProvisioner(
            provider_id=provider_id,
            adapter_binding_digest=adapter_binding_digest,
        )
        provisioners.append(provisioner)
        return provisioner

    launcher, provisioner, _runtime_adapter = _build_launcher(
        connection,
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_provisioner_factory=provisioner_factory,
    )
    assert provisioner is provisioners[0]
    launcher.start(background=False)
    runtime = launcher.runtime

    async def bootstrap_and_admit() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=launcher.app),
            base_url="http://enzymedesign.test",
        ) as client:
            health = await client.get("/healthz")
            created = await client.post(
                "/v3/sessions",
                headers={
                    **_base_headers(),
                    "Idempotency-Key": "bootstrap-reconciliation-e2e",
                    "OpenZyme-Release-Digest": health.json()["release_digest"],
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                },
                json={
                    "session_id": "session-reconciliation-e2e",
                    "project_id": "project-resident-e2e",
                    "title": "EnzymeDesign reconciliation",
                    "objective": "Keep HTTP admission separate from observation",
                },
            )
            assert created.status_code == 202, created.text
            failed = launcher.tick_workspace_provisioning(
                session_id="session-reconciliation-e2e",
                maximum=1,
            )
            assert len(failed) == 1
            assert failed[0].result["readiness"] == "blocked"

            blocked = await client.get(
                "/v3/sessions/session-reconciliation-e2e/workspace",
                headers=_base_headers(),
            )
            assert blocked.status_code == 200, blocked.text
            provisioning = blocked.json()["core"]["workspace"]["provisioning"]
            assert provisioning["effect_certainty"] == "dispatch_in_doubt"
            assert provisioning["reconcile_required"] is True
            admitted = await client.post(
                "/v3/sessions/session-reconciliation-e2e/"
                "workspace/provisioning/reconcile",
                headers=_mutation_headers(
                    blocked,
                    "reconcile-session-reconciliation-e2e",
                ),
                json={
                    "intent_id": provisioning["intent_id"],
                    "intent_digest": provisioning["intent_digest"],
                    "expected_intent_version": provisioning["intent_state_version"],
                    "claim_seconds": 43,
                },
            )
            assert admitted.status_code == 202, admitted.text
            receipt = admitted.json()
            assert receipt["operation"] == "admit_reconciliation"
            assert receipt["result"]["reconciliation_enqueued"] is True
            assert receipt["result"]["external_effect_performed"] is False
            assert receipt["result"]["runtime_executed"] is False
            assert receipt["result"]["task_transition_performed"] is False
            return provisioning

    failed_provisioning = asyncio.run(bootstrap_and_admit())
    assert len(provisioner.requests) == 1
    assert provisioner.reconciliation_requests == []
    admitted_occurrences = runtime.store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )
    assert len(admitted_occurrences) == 1
    assert admitted_occurrences[0].payload["status"] == "pending"
    assert admitted_occurrences[0].payload["requested_claim_seconds"] == 43

    diagnosed = launcher.tick_workspace_provisioning(
        session_id="session-reconciliation-e2e",
        maximum=1,
    )
    assert len(diagnosed) == 1
    assert len(provisioner.requests) == 1
    assert len(provisioner.reconciliation_requests) == 1
    reconciliation = runtime.store.list_for_session(
        entity_type="workspace_provisioning_reconciliation",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )[0]
    assert reconciliation.payload["status"] == "blocked"
    assert reconciliation.payload["effect_certainty"] == "no_effect"
    assert reconciliation.payload["reconcile_required"] is False
    failure_pairs = runtime.store.list_for_session(
        entity_type="failure_observation",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )
    private_diagnostics = runtime.store.list_for_session(
        entity_type="private_diagnostic",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )
    assert len(failure_pairs) == len(private_diagnostics) == 2
    private_by_id = {item.entity_id: item for item in private_diagnostics}
    for failure in failure_pairs:
        diagnostic_id = str(failure.payload["diagnostic_id"])
        assert (
            failure.payload["private_diagnostic_digest"]
            == (private_by_id[diagnostic_id].payload["record_digest"])
        )

    async def admit_successor() -> dict[str, object]:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=launcher.app),
            base_url="http://enzymedesign.test",
        ) as client:
            projection = await client.get(
                "/v3/sessions/session-reconciliation-e2e/workspace",
                headers=_base_headers(),
            )
            assert projection.status_code == 200, projection.text
            provisioning = projection.json()["core"]["workspace"]["provisioning"]
            assert provisioning["next_action"] == (
                "create_successor_workspace_generation"
            )
            response = await client.post(
                "/v3/sessions/session-reconciliation-e2e/"
                "workspace/provisioning/successor",
                headers=_mutation_headers(
                    projection,
                    "successor-session-reconciliation-e2e",
                ),
                json={
                    "failed_intent_id": failed_provisioning["intent_id"],
                    "failed_intent_digest": failed_provisioning["intent_digest"],
                    "expected_failed_intent_version": failed_provisioning[
                        "intent_state_version"
                    ],
                    "resolved_reconciliation_id": reconciliation.entity_id,
                },
            )
            assert response.status_code == 202, response.text
            receipt = response.json()
            assert receipt["operation"] == "replace_failed_generation"
            assert receipt["result"]["generation"] == 2
            assert receipt["result"]["readiness"] == "provisioning"
            return receipt

    successor_receipt = asyncio.run(admit_successor())
    assert successor_receipt["fallback_performed"] is False
    assert len(provisioner.requests) == 1
    assert len(provisioner.reconciliation_requests) == 1
    intents = runtime.store.list_for_session(
        entity_type="workspace_provisioning_intent",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )
    assert sorted(item.payload["generation"] for item in intents) == [1, 2]
    assert (
        next(item for item in intents if item.payload["generation"] == 1).payload[
            "status"
        ]
        == "blocked"
    )
    assert (
        next(item for item in intents if item.payload["generation"] == 2).payload[
            "status"
        ]
        == "pending"
    )
    generation_rows = connection.execute(
        """
        SELECT workspace_id, generation, workspace_state_version, status
        FROM workspace_generation_records
        WHERE session_id = ?
        ORDER BY generation
        """,
        ("session-reconciliation-e2e",),
    ).fetchall()
    assert len(generation_rows) == 2
    assert [row[1] for row in generation_rows] == [1, 2]
    assert generation_rows[0][0] == generation_rows[1][0]
    assert generation_rows[0][3] == "failed"
    assert generation_rows[1][3] == "reserved"
    assert generation_rows[1][2] == generation_rows[0][2] + 1
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    launcher.close()

    restarted_connection = sqlite3.connect(database_path, check_same_thread=False)
    restarted_connection.execute("PRAGMA foreign_keys = ON")
    restarted_provisioners: list[_DispatchInDoubtWorkspaceProvisioner] = []

    def restarted_factory(
        provider_id: str,
        adapter_binding_digest: str,
    ) -> _DispatchInDoubtWorkspaceProvisioner:
        restarted = _DispatchInDoubtWorkspaceProvisioner(
            provider_id=provider_id,
            adapter_binding_digest=adapter_binding_digest,
        )
        restarted_provisioners.append(restarted)
        return restarted

    restarted_launcher, restarted_provisioner, _adapter = _build_launcher(
        restarted_connection,
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_provisioner_factory=restarted_factory,
    )
    restarted_launcher.start(background=False)
    assert restarted_provisioner is restarted_provisioners[0]
    assert [
        row[0]
        for row in restarted_connection.execute(
            """
            SELECT generation
            FROM workspace_generation_records
            WHERE session_id = ?
            ORDER BY generation
            """,
            ("session-reconciliation-e2e",),
        ).fetchall()
    ] == [1, 2]
    assert (
        len(
            restarted_launcher.runtime.store.list_for_session(
                entity_type="workspace_provisioning_reconciliation",
                session_id="session-reconciliation-e2e",
                max_items=8,
            )
        )
        == 1
    )
    restarted_failures = restarted_launcher.runtime.store.list_for_session(
        entity_type="failure_observation",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )
    restarted_diagnostics = restarted_launcher.runtime.store.list_for_session(
        entity_type="private_diagnostic",
        session_id="session-reconciliation-e2e",
        max_items=8,
    )
    assert tuple(item.record_digest for item in restarted_failures) == tuple(
        item.record_digest for item in failure_pairs
    )
    assert tuple(item.record_digest for item in restarted_diagnostics) == tuple(
        item.record_digest for item in private_diagnostics
    )
    assert restarted_provisioner.requests == []
    assert restarted_provisioner.reconciliation_requests == []
    restarted_launcher.close()
