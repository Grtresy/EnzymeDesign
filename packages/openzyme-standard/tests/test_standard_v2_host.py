from __future__ import annotations

import sqlite3
import asyncio
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from httpx import ASGITransport
from httpx import AsyncClient
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ControlledOperationApplicationCommand
from openzyme_extension_spi import ControlledOperationCommandKind
from openzyme_extension_spi import KernelCommandContext
from openzyme_host_api import HostSecurityPolicy
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel import AgentAuthorityLeaseKernelApplicationService
from openzyme_kernel import AuthorityLeaseIssueCommand
from openzyme_kernel import ControlledOperationKernelApplicationService
from openzyme_kernel import WorkspaceGenerationTransitionCommand
from openzyme_kernel import WorkspaceIdentityKernelApplicationService
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_standard import build_standard_fresh_install_seed
from openzyme_standard import build_standard_v2_host_app
from openzyme_standard import StandardOperationalAdapterSelection
from openzyme_standard import verify_standard_deployment_startup_read_only
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only


@dataclass(slots=True)
class _BootstrapAuthority:
    def issue(self, **facts: str) -> SessionBootstrapAuthorization:
        issued_at = datetime(2026, 8, 21, 10, tzinfo=UTC)
        return SessionBootstrapAuthorization.create(
            authorization_id="bootstrap-authorization-1",
            operator_actor_id=facts["actor_id"],
            project_id=facts["project_id"],
            session_id=facts["session_id"],
            root_authority_lease_digest=facts["root_authority_lease_digest"],
            session_composition_pin_digest=facts[
                "session_composition_pin_digest"
            ],
            extension_bundle_digest=facts["extension_bundle_digest"],
            capability_binding_digest=facts["capability_binding_digest"],
            generation=1,
            fence=1,
            issued_at=issued_at.isoformat(),
            expires_at=(issued_at + timedelta(minutes=5)).isoformat(),
        )

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision:
        del now_iso
        return SessionBootstrapAuthorityDecision(
            allowed=True,
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.authorization_digest,
        )


@dataclass(frozen=True, slots=True)
class _IdleRuntimeAdapter:
    adapter_id = "test.runtime.idle"
    adapter_contract_digest = "sha256:" + "4" * 64
    commands: list[object] = field(default_factory=list)

    def run_turn(self, command, capability_gateway):  # noqa: ANN001, ANN201
        capability_gateway.list_tools(
            command_id=command.command_id,
            affordance_snapshot_digest=command.affordance_snapshot_digest,
        )
        self.commands.append(command)
        return RuntimeTurnOutcome(
            outcome_id=f"outcome-{command.command_id}",
            command_id=command.command_id,
            command_digest=command.command_digest,
            turn_id=command.turn_id,
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=command.signal_attempt,
            runtime_lease_generation=command.runtime_lease_generation,
            runtime_fence=command.runtime_fence,
            process_epoch=command.process_epoch,
            disposition=RuntimeTurnDisposition.IDLE,
            summary="bounded idle",
        )


def _app():  # noqa: ANN201 - concrete FastAPI return is not part of the assertion
    connection = sqlite3.connect(":memory:", check_same_thread=False)
    connection.execute("PRAGMA foreign_keys = ON")
    install_owner_partitioned_schema_for_offline_migration(
        connection,
        profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    install_store_schema_for_offline_migration(connection)
    schema = verify_composite_store_schema_read_only(
        connection,
        owner_schema_profile=OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE,
    )
    wheel_digest = "sha256:" + "1" * 64
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=wheel_digest,
        host_build_digest="sha256:" + "2" * 64,
        client_build_digest="sha256:" + "3" * 64,
        epoch_id="standard-real-host",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-21T10:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    startup = verify_standard_deployment_startup_read_only(
        connection,
        seed=seed,
        observed_installed_wheel_set_digest=wheel_digest,
        verified_at="2026-08-21T10:00:00+00:00",
    )
    clock = DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    runtime_adapter = _IdleRuntimeAdapter()
    operational_selection = StandardOperationalAdapterSelection(
        runtime_adapter=runtime_adapter,
        workspace_mounts=object(),  # type: ignore[arg-type]
        process_isolation=object(),  # type: ignore[arg-type]
        revision_backend=object(),  # type: ignore[arg-type]
    )
    app = build_standard_v2_host_app(
        connection,
        startup=startup,
        clock=clock,
        ids=ids,
        bootstrap_authority=_BootstrapAuthority(),
        security_policy=HostSecurityPolicy.from_settings(None),
        operational_selection=operational_selection,
    )
    store = app.state.openzyme_standard_runtime.store
    return app, connection, store, clock, ids, runtime_adapter


def _base_headers() -> dict[str, str]:
    return {
        "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "OpenZyme-Workspace-Contract": "file_workspace_public@2",
        "X-Request-Id": "request-standard-host",
    }


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _kernel_context(
    store,
    *,
    lease: AgentAuthorityLease,
    command_id: str,
    idempotency_key: str,
    workspace_generation: int | None = None,
) -> KernelCommandContext:
    session = store.read(entity_type="session", entity_id="session-1")
    bindings = store.list_for_session(
        entity_type="session_capability_binding_revision",
        session_id="session-1",
        max_items=8,
    )
    assert session is not None and len(bindings) == 1
    return KernelCommandContext(
        command_id=command_id,
        session_id="session-1",
        actor_id=lease.agent_member_id,
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=lease.generation,
        authority_fence=lease.fence,
        expected_session_version=session.state_version,
        extension_bundle_digest=str(bindings[0].payload["extension_bundle_digest"]),
        capability_binding_digest=str(bindings[0].payload["binding_digest"]),
        idempotency_key=idempotency_key,
        correlation_id="request-provision-workspace",
        workspace_generation=workspace_generation,
        route_id="openzyme.workspace.git-lfs",
    )


def _provision_ready_workspace(store, *, clock, ids) -> AgentAuthorityLease:
    leases = store.list_for_session(
        entity_type="agent_authority_lease",
        session_id="session-1",
        max_items=8,
    )
    assert len(leases) == 1
    root = AgentAuthorityLease.from_dict(leases[0].payload)
    identities = WorkspaceIdentityKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    created_at = clock.now_iso()

    def generation(
        status: WorkspaceGenerationStatus,
        state_version: int,
        *,
        root_digest: str | None = None,
        operation_id: str | None = None,
        receipt_digest: str | None = None,
    ) -> WorkspaceGeneration:
        return WorkspaceGeneration(
            workspace_id="workspace-1",
            workspace_kind=WorkspaceKind.AGENT_LOCAL,
            session_id="session-1",
            owner_member_id=root.agent_member_id,
            generation=1,
            state_version=state_version,
            status=status,
            provider_id="openzyme.workspace.git-lfs",
            target_id="local:host",
            created_at=created_at,
            updated_at=clock.now_iso(),
            root_identity_digest=root_digest,
            transition_receipt_digest=receipt_digest,
            controlled_operation_id=operation_id,
        )

    for status, state_version, expected_record_version in (
        (WorkspaceGenerationStatus.RESERVED, 1, None),
        (WorkspaceGenerationStatus.PROVISIONING, 2, 1),
    ):
        identities.transition_workspace_generation(
            WorkspaceGenerationTransitionCommand(
                context=_kernel_context(
                    store,
                    lease=root,
                    command_id=f"workspace-command-{state_version}",
                    idempotency_key=f"workspace-transition-{state_version}",
                ),
                generation=generation(status, state_version),
                expected_record_version=expected_record_version,
            )
        )

    operation_id = "workspace-provision-1"
    intent_digest = _digest("workspace-provision-intent")
    receipt_digest = _digest("workspace-provision-terminal-receipt")
    operations = ControlledOperationKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    for kind, phase, payload in (
        (
            ControlledOperationCommandKind.ADMIT,
            "admit",
            {
                "workspace_id": "workspace-1",
                "scope_id": "workspace-1",
                "authority_operation": "workspace.generation.transition",
                "fallback_performed": False,
            },
        ),
        (
            ControlledOperationCommandKind.OBSERVE,
            "settle",
            {
                "effect_certainty": ExternalEffectCertainty.TERMINAL_KNOWN.value,
                "mutation_applied": True,
                "terminal_receipt_digest": receipt_digest,
                "fallback_performed": False,
            },
        ),
    ):
        operations.execute(
            ControlledOperationApplicationCommand(
                context=_kernel_context(
                    store,
                    lease=root,
                    command_id=f"workspace-operation-{phase}",
                    idempotency_key=f"workspace-operation-{phase}",
                ),
                operation=kind,
                operation_id=operation_id,
                intent_digest=intent_digest,
                payload=payload,
            )
        )
    identities.transition_workspace_generation(
        WorkspaceGenerationTransitionCommand(
            context=_kernel_context(
                store,
                lease=root,
                command_id="workspace-command-ready",
                idempotency_key="workspace-transition-ready",
            ),
            generation=generation(
                WorkspaceGenerationStatus.READY,
                3,
                root_digest=_digest("workspace-root"),
                operation_id=operation_id,
                receipt_digest=receipt_digest,
            ),
            expected_record_version=2,
        )
    )

    child_grant = AuthorityGrant.create(
        grant_id="authority-grant-workspace-1",
        scope_id="session-1",
        operations=root.operations,
        generation=root.generation + 1,
        fence=root.fence + 1,
    )
    child = AgentAuthorityLease.create(
        lease_id="authority-lease-workspace-1",
        session_id="session-1",
        agent_member_id=root.agent_member_id,
        grants=(child_grant,),
        generation=root.generation + 1,
        fence=root.fence + 1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=clock.now_iso(),
        expires_at=None,
        agent_id=root.agent_id,
        workspace_generation=1,
        parent_lease_id=root.lease_id,
        policy_digest=root.policy_digest,
        idempotency_key="authority-workspace-1",
        updated_at=clock.now_iso(),
    )
    AgentAuthorityLeaseKernelApplicationService(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    ).issue(
        AuthorityLeaseIssueCommand(
            context=_kernel_context(
                store,
                lease=root,
                command_id="authority-command-workspace-1",
                idempotency_key="authority-workspace-1",
            ),
            lease=child,
            expected_parent_version=leases[0].state_version,
        )
    )
    return child


def test_real_standard_host_bootstraps_inspects_and_mutates_kernel_sqlite() -> None:
    app, connection, _, _, _, _ = _app()

    async def exercise() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/healthz")
            bootstrap_headers = {
                **_base_headers(),
                "Idempotency-Key": "bootstrap-session-1",
                "OpenZyme-Release-Digest": health.json()["release_digest"],
            }
            bootstrap_headers["OpenZyme-Public-Contract-Digest"] = (
                FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
            )
            created = await client.post(
                "/v3/sessions",
                headers=bootstrap_headers,
                json={
                    "session_id": "session-1",
                    "project_id": "project-1",
                    "title": "Plugin-free Standard",
                    "objective": "Prove real Host to Kernel to SQLite",
                },
            )
            assert created.status_code == 200, created.text

            inspected = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert inspected.status_code == 200, inspected.text
            projection = inspected.json()
            assert projection["core"]["session"]["session_id"] == "session-1"
            assert projection["extensions"] == {}

            mutation_headers = {
                **_base_headers(),
                "Idempotency-Key": "create-task-1",
            }
            for name in (
                "OpenZyme-Release-Digest",
                "OpenZyme-Public-Contract-Digest",
                "OpenZyme-Projection-Digest",
                "OpenZyme-Capability-Binding-Digest",
                "OpenZyme-Affordance-Snapshot-Digest",
            ):
                mutation_headers[name] = inspected.headers[name]
            task = await client.post(
                "/v3/sessions/session-1/tasks",
                headers=mutation_headers,
                json={
                    "task_id": "task-1",
                    "subject": "Inspect repository",
                    "description": "Use the exact Plugin-free Kernel route",
                },
            )
            assert task.status_code == 200, task.text

    asyncio.run(exercise())
    assert connection.execute(
        "SELECT subject FROM tasks WHERE task_id = 'task-1'"
    ).fetchone() == ("Inspect repository",)


def test_real_standard_host_message_signal_and_bounded_runtime_drain() -> None:
    app, _, store, clock, ids, runtime_adapter = _app()

    async def exercise() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/healthz")
            bootstrap_headers = {
                **_base_headers(),
                "Idempotency-Key": "bootstrap-runtime-session-1",
                "OpenZyme-Release-Digest": health.json()["release_digest"],
                "OpenZyme-Public-Contract-Digest": (
                    FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                ),
            }
            created = await client.post(
                "/v3/sessions",
                headers=bootstrap_headers,
                json={
                    "session_id": "session-1",
                    "project_id": "project-1",
                    "title": "Plugin-free runtime",
                    "objective": "Prove message to bounded runtime",
                },
            )
            assert created.status_code == 200, created.text
            child = _provision_ready_workspace(store, clock=clock, ids=ids)

            inspected = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert inspected.status_code == 200, inspected.text
            assert inspected.json()["core"]["workspace"]["generations"][0][
                "status"
            ] == "ready"

            def mutation_headers(idempotency_key: str) -> dict[str, str]:
                return {
                    **_base_headers(),
                    "Idempotency-Key": idempotency_key,
                    **{
                        name: inspected.headers[name]
                        for name in (
                            "OpenZyme-Release-Digest",
                            "OpenZyme-Public-Contract-Digest",
                            "OpenZyme-Projection-Digest",
                            "OpenZyme-Capability-Binding-Digest",
                            "OpenZyme-Affordance-Snapshot-Digest",
                        )
                    },
                }

            message = await client.post(
                "/v3/sessions/session-1/messages",
                headers=mutation_headers("message-runtime-1"),
                json={
                    "message_id": "message-runtime-1",
                    "content": "Continue one bounded turn.",
                    "task_id": None,
                    "lane_id": None,
                    "skill_keys": [],
                },
            )
            assert message.status_code == 200, message.text

            inspected = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            drained = await client.post(
                "/v3/sessions/session-1/runtime/drain",
                headers=mutation_headers("runtime-drain-1"),
                json={"max_signals": 1, "max_steps_per_agent": 2},
            )
            assert drained.status_code == 200, drained.text
            assert drained.json()["result"]["processed_signals"] == 1
            assert drained.json()["result"]["task_transition_performed"] is False
            assert child.workspace_generation == 1

    asyncio.run(exercise())
    assert len(runtime_adapter.commands) == 1
    command = runtime_adapter.commands[0]
    assert command.runtime_adapter_id == runtime_adapter.adapter_id
    runtime_lease = store.read(
        entity_type="session_runtime_lease",
        entity_id="session-1",
    )
    assert runtime_lease is not None
    assert runtime_lease.payload["released_at"] is not None
