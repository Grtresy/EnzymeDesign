from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import UTC
from datetime import datetime
from datetime import timedelta

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import FILE_WORKSPACE_CORE_SECTION_FIELDS
from openzyme_contracts import FileWorkspaceCoreProjectionV2
from openzyme_contracts import FileWorkspacePublicV2
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionCompositionPin
from openzyme_contracts import ToolInvocation
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import ToolResult
from openzyme_contracts import WorkspaceGeneration
from openzyme_contracts import WorkspaceGenerationStatus
from openzyme_contracts import WorkspaceKind
from openzyme_contracts import AgentRuntimeSignalReason
from openzyme_contracts import AgentRuntimeSignalStatus
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_extension_spi import KernelMutationReceipt
from openzyme_extension_spi import KernelQueryContext
from openzyme_host_api import FileWorkspaceV2HostProjection
from openzyme_host_api import HostV2CommandError
from openzyme_host_api import HostV2MutationInvocation
from openzyme_host_api import HostV2SessionBootstrapInvocation
from openzyme_kernel import SessionBootstrapCommand
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore
from openzyme_kernel import AgentAuthorityLeaseKernelApplicationService
from openzyme_kernel import ApprovalKernelApplicationService
from openzyme_kernel import CollaborationKernelApplicationService
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel import ControlStoreRuntimeOutcomeRepository
from openzyme_kernel import ProtocolKernelApplicationService
from openzyme_kernel import RuntimeCoordinationKernelApplicationService
from openzyme_kernel import RuntimeTurnAdmission
from openzyme_kernel import RuntimeTurnBudget
from openzyme_kernel import RuntimeTurnCoordinator
from openzyme_kernel import TaskKernelApplicationService
from openzyme_standard import STANDARD_ROOT_AUTHORITY_OPERATIONS
from openzyme_standard import StandardKernelCoordinationRouteApplication
from openzyme_standard import StandardKernelOperationalRouteApplication
from openzyme_standard import StandardLocalWorkspaceToolContextResolver
from openzyme_standard import StandardBoundedRuntimeDrainApplication
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_standard import StandardHostKernelCommandGateway

import pytest


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _epoch() -> DeploymentActivationEpoch:
    release = LayeredReleaseIdentity(
        kernel_contract_digest=_digest("kernel"),
        core_schema_digest=_digest("schema"),
        adapter_bundle_digest=_digest("adapters"),
        extension_bundle_digest=_digest("plugin-free"),
        declared_tool_catalog_digest=_digest("tools"),
        route_catalog_digest=_digest("routes"),
        projection_catalog_digest=_digest("projections"),
        migration_catalog_digest=_digest("migrations"),
        workspace_backend_digest=_digest("workspace"),
        host_build_digest=_digest("host"),
        client_build_digest=_digest("client"),
    )
    return DeploymentActivationEpoch.create(
        epoch_id="epoch-1",
        sequence=1,
        distribution_id="openzyme.standard",
        kernel_manifest_digest=_digest("kernel-manifest"),
        distribution_manifest_digest=_digest("distribution-manifest"),
        composition_document_digest=_digest("composition-document"),
        composition_activation_digest=_digest("composition-activation"),
        driver_bundle_digest=_digest("drivers"),
        http_route_catalog_digest=_digest("http-routes"),
        contribution_catalogs_digest=_digest("contributions"),
        release_identity=release,
        schema_verification_digest=_digest("schema-proof"),
        wheel_verification_digest=_digest("wheel-proof"),
        activated_by_actor_id="user:operator-1",
        activated_at="2026-08-21T10:00:00+00:00",
    )


@dataclass
class _BootstrapService:
    commands: list[SessionBootstrapCommand]

    def bootstrap(self, command: SessionBootstrapCommand) -> KernelMutationReceipt:
        self.commands.append(command)
        return KernelMutationReceipt.create(
            command_id=command.command_id,
            service_id="openzyme.kernel.session-bootstrap",
            operation="session.bootstrap",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result={"session_id": command.session_id},
        )


@dataclass
class _Authority:
    issued: list[SessionBootstrapAuthorization]

    def issue(self, **facts: str) -> SessionBootstrapAuthorization:
        issued_at = datetime(2026, 8, 21, 10, tzinfo=UTC)
        authorization = SessionBootstrapAuthorization.create(
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
            expires_at=(issued_at + timedelta(minutes=1)).isoformat(),
        )
        self.issued.append(authorization)
        return authorization

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


def test_standard_gateway_builds_exact_atomic_kernel_bootstrap_command() -> None:
    service = _BootstrapService([])
    authority = _Authority([])
    gateway = StandardHostKernelCommandGateway(
        deployment_epoch=_epoch(),
        bootstrap_service=service,  # type: ignore[arg-type]
        bootstrap_authority=authority,
        clock=DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
        route_applications={},
    )

    receipt = gateway.bootstrap(
        HostV2SessionBootstrapInvocation(
            session_id="session-1",
            actor_id="user:operator-1",
            idempotency_key="bootstrap-session-1",
            correlation_id="request-bootstrap-1",
            payload={
                "session_id": "session-1",
                "project_id": "project-1",
                "title": "Plugin-free Standard",
                "objective": "Prove the complete Kernel path",
            },
        )
    )

    assert receipt.mutation_applied is True
    command = service.commands[0]
    assert command.authorization == authority.issued[0]
    assert command.authorization.operator_actor_id == "user:operator-1"
    assert command.initial_capability_binding.inventory_bindings == ()
    assert command.initial_capability_binding.extension_bundle_digest == (
        _epoch().release_identity.extension_bundle_digest
    )
    assert command.session_composition_pin.deployment_epoch_id == "epoch-1"
    assert command.root_authority_lease.agent_member_id == command.master_member_id
    operations = command.root_authority_lease.grants[0].operations
    assert operations == STANDARD_ROOT_AUTHORITY_OPERATIONS
    assert "workspace.process.exec" in operations
    assert "protocol.delegate" in operations


def _coordination_fixture() -> tuple[
    StandardKernelCoordinationRouteApplication,
    InMemoryControlStore,
    FileWorkspaceV2HostProjection,
]:
    clock = DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    grant = AuthorityGrant.create(
        grant_id="root-grant-1",
        scope_id="session-1",
        operations=STANDARD_ROOT_AUTHORITY_OPERATIONS,
        generation=1,
        fence=1,
    )
    lease = AgentAuthorityLease.create(
        lease_id="root-lease-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(grant,),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=clock.now_iso(),
        expires_at=None,
        agent_id="master-1",
        workspace_generation=1,
        policy_digest=_digest("root-policy"),
        idempotency_key="bootstrap-session-1",
        updated_at=clock.now_iso(),
    )
    session_payload = {
        "session_id": "session-1",
        "project_id": "project-1",
        "title": "Standard",
        "objective": "Coordinate",
        "status": "active",
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
    }
    member_payload = {
        "agent_member_id": "master-1",
        "agent_id": "master-1",
        "session_id": "session-1",
        "parent_agent_id": None,
        "lane_id": None,
        "name": "Master",
        "role": "master",
        "status": "active",
        "process_epoch": 1,
        "active_authority_lease_id": lease.lease_id,
        "workspace_generation": 1,
        "owned_task_ids": [],
        "created_at": clock.now_iso(),
        "updated_at": clock.now_iso(),
    }
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=1,
                payload=session_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="master-1",
                state_version=1,
                payload=member_payload,
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=lease.lease_id,
                state_version=1,
                payload=lease.to_dict(),
            ),
        )
    )
    core: dict[str, object] = {
        field: [] if field in {
            "tasks",
            "lanes",
            "agents",
            "approvals",
            "authority_leases",
            "publications",
        } else {}
        for field in FILE_WORKSPACE_CORE_SECTION_FIELDS
    }
    binding_digest = _digest("binding")
    core["session"] = {**session_payload, "state_version": 1}
    core["agents"] = [{**member_payload, "state_version": 1}]
    core["authority_leases"] = [{**lease.to_dict(), "state_version": 1}]
    core["capability_binding"] = {"binding_digest": binding_digest}
    core["tool_reflection"] = {
        "declared_tool_catalog_digest": _epoch().release_identity.declared_tool_catalog_digest,
        "capability_binding_digest": binding_digest,
        "affordance_snapshot_digest": _digest("affordance"),
        "available_tool_names": [],
        "affordances": [],
    }
    projection = FileWorkspacePublicV2(
        release=_epoch().release_identity,
        core=FileWorkspaceCoreProjectionV2(core),
        extensions=(),
    )
    host_projection = FileWorkspaceV2HostProjection(
        projection=projection,
        query_context=KernelQueryContext(
            session_id="session-1",
            actor_id="user:local-dev",
            owner_plugin_id="openzyme.kernel",
            authority_lease_id=lease.lease_id,
            extension_bundle_digest=_epoch().release_identity.extension_bundle_digest,
            capability_binding_digest=binding_digest,
            correlation_id="request-1",
        ),
        capability_binding_digest=binding_digest,
        affordance_snapshot_digest=_digest("affordance"),
    )
    return (
        StandardKernelCoordinationRouteApplication(
            collaboration=CollaborationKernelApplicationService(
                store=store,
                clock=clock,
                ids=ids,
            ),
            tasks=TaskKernelApplicationService(
                store=store,
                reader=store,
                clock=clock,
                ids=ids,
            ),
            protocols=ProtocolKernelApplicationService(
                store=store,
                clock=clock,
                ids=ids,
            ),
            approvals=ApprovalKernelApplicationService(
                store=store,
                clock=clock,
                ids=ids,
            ),
            authority_leases=AgentAuthorityLeaseKernelApplicationService(
                store=store,
                reader=store,
                clock=clock,
                ids=ids,
            ),
            message_ingress=MessageIngressKernelApplicationService(
                store=store,
                clock=clock,
                ids=ids,
            ),
            ids=ids,
        ),
        store,
        host_projection,
    )


def test_standard_coordination_route_uses_projected_cas_and_root_agent() -> None:
    application, store, precondition = _coordination_fixture()

    receipt = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.task.create@2",
            method="POST",
            path="/v3/sessions/session-1/tasks",
            session_id="session-1",
            actor_id="user:local-dev",
            idempotency_key="create-task-1",
            correlation_id="request-create-task-1",
            payload={
                "task_id": "task-1",
                "subject": "Inspect repository",
                "description": "Use the Plugin-free Kernel path",
            },
            precondition=precondition,
        )
    )

    assert receipt.mutation_applied is True
    task = store.read(entity_type="task", entity_id="task-1")
    assert task is not None
    assert task.payload["owner_actor_id"] == "master-1"
    assert store.read(entity_type="session", entity_id="session-1").state_version == 2  # type: ignore[union-attr]


def test_standard_message_route_preserves_user_source_and_only_enqueues_runtime() -> None:
    application, store, precondition = _coordination_fixture()

    receipt = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.message.send@2",
            method="POST",
            path="/v3/sessions/session-1/messages",
            session_id="session-1",
            actor_id="user:operator-1",
            idempotency_key="send-message-1",
            correlation_id="request-send-message-1",
            payload={
                "message_id": "message-1",
                "content": "Continue the bounded task",
                "task_id": None,
                "lane_id": None,
                "skill_keys": ["workflow.code-review"],
            },
            precondition=precondition,
        )
    )

    message = store.read(entity_type="conversation_message", entity_id="message-1")
    assert message is not None
    assert message.payload["sender_actor_id"] == "user:operator-1"
    assert message.payload["admitted_by_actor_id"] == "master-1"
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False


def test_standard_coordination_route_never_maps_shared_user_to_agent() -> None:
    application, _, precondition = _coordination_fixture()

    with pytest.raises(HostV2CommandError) as rejected:
        application.invoke(
            HostV2MutationInvocation(
                route_id="openzyme.kernel.task.create@2",
                method="POST",
                path="/v3/sessions/session-1/tasks",
                session_id="session-1",
                actor_id="user:operator-1",
                idempotency_key="create-task-1",
                correlation_id="request-create-task-1",
                payload={
                    "task_id": "task-1",
                    "subject": "Forbidden impersonation",
                    "description": "",
                },
                precondition=precondition,
            )
        )

    assert rejected.value.code == "standard_operator_agent_authority_required"
    assert rejected.value.mutation_applied is False


@dataclass
class _RuntimeDrain:
    calls: list[HostV2MutationInvocation]

    def invoke(self, invocation: HostV2MutationInvocation) -> KernelMutationReceipt:
        self.calls.append(invocation)
        return KernelMutationReceipt.create(
            command_id="runtime-command-1",
            service_id="openzyme.kernel.runtime-drain",
            operation="runtime.drain",
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            result={"task_transition_performed": False},
        )


@dataclass
class _WorkspaceRuntime:
    calls: list[object]

    def invoke(self, invocation):  # noqa: ANN001, ANN201
        self.calls.append(invocation)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            status="workspace_operation_settled",
            summary="settled",
            payload={
                "operation": {
                    "effect_certainty": "terminal_known",
                    "mutation_applied": True,
                },
                "task_transition_performed": False,
            },
        )


@dataclass
class _CommandApplication:
    calls: list[object]

    def execute(self, command):  # noqa: ANN001, ANN201
        self.calls.append(command)
        return KernelMutationReceipt.create(
            command_id=command.context.command_id,
            service_id="openzyme.kernel.test-application",
            operation=command.operation.value,
            mutation_applied=True,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
        )


def test_standard_operational_routes_use_injected_kernel_applications() -> None:
    _, _, precondition = _coordination_fixture()
    runtime_drain = _RuntimeDrain([])
    filesystem = _WorkspaceRuntime([])
    process = _WorkspaceRuntime([])
    publications = _CommandApplication([])
    protocols = _CommandApplication([])
    application = StandardKernelOperationalRouteApplication(
        runtime_drain=runtime_drain,
        workspace_tools={
            "workspace.fs.mutate": filesystem,
            "workspace.exec": process,
        },
        publications=publications,  # type: ignore[arg-type]
        protocols=protocols,  # type: ignore[arg-type]
        ids=DeterministicIdGenerator(),
    )

    workspace = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.workspace.fs.mutate@2",
            method="POST",
            path="/v3/sessions/session-1/workspace/filesystem",
            session_id="session-1",
            actor_id="user:local-dev",
            idempotency_key="workspace-mutate-1",
            correlation_id="request-workspace-1",
            payload={"operation": "mkdir", "path": "results"},
            precondition=precondition,
        )
    )
    assert workspace.effect_certainty is ExternalEffectCertainty.TERMINAL_KNOWN
    assert workspace.mutation_applied is True
    assert filesystem.calls[0].agent_member_id == "master-1"  # type: ignore[attr-defined]

    runtime = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.runtime.drain@2",
            method="POST",
            path="/v3/sessions/session-1/runtime/drain",
            session_id="session-1",
            actor_id="user:local-dev",
            idempotency_key="runtime-drain-1",
            correlation_id="request-runtime-1",
            payload={"max_turns": 1},
            precondition=precondition,
        )
    )
    assert runtime.result["task_transition_performed"] is False
    assert len(runtime_drain.calls) == 1

    checkpoint = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.workspace.checkpoint@2",
            method="POST",
            path="/v3/sessions/session-1/workspace/checkpoints",
            session_id="session-1",
            actor_id="user:local-dev",
            idempotency_key="checkpoint-1",
            correlation_id="request-checkpoint-1",
            payload={
                "resource_id": "checkpoint-1",
                "workspace_id": "workspace-1",
                "expected_workspace_generation": 1,
                "proof": {},
            },
            precondition=precondition,
        )
    )
    assert checkpoint.operation == "verify_checkpoint"
    assert publications.calls[0].resource_id == "checkpoint-1"  # type: ignore[attr-defined]

    handoff = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.workspace.handoff@2",
            method="POST",
            path="/v3/sessions/session-1/workspace/handoffs",
            session_id="session-1",
            actor_id="user:local-dev",
            idempotency_key="handoff-1",
            correlation_id="request-handoff-1",
            payload={
                "protocol_ref": "handoff-1",
                "recipient_actor_id": "researcher-1",
                "task_id": "task-1",
                "revision_path_ref": {},
                "message": "Inspect this revision",
            },
            precondition=precondition,
        )
    )
    assert handoff.operation == "handoff"
    assert protocols.calls[0].protocol_ref == "handoff-1"  # type: ignore[attr-defined]


@dataclass(frozen=True)
class _QueryRecords:
    store: InMemoryControlStore

    def read(self, *, entity_type: str, entity_id: str):  # noqa: ANN201
        return self.store.read(entity_type=entity_type, entity_id=entity_id)

    def list_for_session(
        self,
        *,
        entity_type: str,
        session_id: str,
        max_items: int,
    ):  # noqa: ANN201
        matching = tuple(
            item
            for item in self.store.records
            if item.entity_type == entity_type
            and item.payload.get("session_id") == session_id
        )
        return matching[:max_items]


def test_standard_workspace_context_uses_only_canonical_kernel_records() -> None:
    _, store, _ = _coordination_fixture()
    epoch = _epoch()
    capability = SessionCapabilityBindingRevision.create(
        binding_id="capability-binding-1",
        session_id="session-1",
        revision=1,
        extension_bundle_digest=epoch.release_identity.extension_bundle_digest,
        route_catalog_digest=epoch.release_identity.route_catalog_digest,
        inventory_bindings=(),
        created_by_actor_id="user:operator-1",
        created_at="2026-08-21T10:00:00+00:00",
    )
    pin = SessionCompositionPin.create(
        pin_id="composition-pin-1",
        session_id="session-1",
        deployment_epoch=epoch,
        initial_capability_binding_id=capability.binding_id,
        initial_capability_binding_revision=capability.revision,
        initial_capability_binding_digest=capability.binding_digest,
        created_by_actor_id="user:operator-1",
        created_at="2026-08-21T10:00:00+00:00",
    )
    generation = WorkspaceGeneration(
        workspace_id="workspace-1",
        workspace_kind=WorkspaceKind.AGENT_LOCAL,
        session_id="session-1",
        owner_member_id="master-1",
        generation=1,
        state_version=3,
        status=WorkspaceGenerationStatus.READY,
        provider_id="openzyme.workspace.git-lfs",
        target_id="local:host",
        created_at="2026-08-21T10:00:00+00:00",
        updated_at="2026-08-21T10:00:02+00:00",
        root_identity_digest=_digest("workspace-root"),
        transition_receipt_digest=_digest("workspace-ready"),
        controlled_operation_id="workspace-provision-1",
    )
    for entity_type, entity_id, payload in (
        ("session_composition_pin", "session-1", pin.to_dict()),
        (
            "session_capability_binding_revision",
            capability.binding_id,
            capability.to_dict(),
        ),
        ("workspace_generation", generation.workspace_id, generation.to_dict()),
        (
            "workspace_runtime_binding",
            generation.workspace_id,
            generation.runtime_binding().to_dict(),
        ),
    ):
        store.seed(
            KernelRecordSnapshot.create(
                entity_type=entity_type,
                entity_id=entity_id,
                state_version=1,
                payload=payload,
            )
        )

    resolved = StandardLocalWorkspaceToolContextResolver(
        _QueryRecords(store)
    ).resolve(
        ToolInvocation(
            call_id="call-1",
            tool_name="workspace.exec",
            arguments={"argv": ["python", "-V"]},
            session_id="session-1",
            agent_member_id="master-1",
            affordance_snapshot_digest=_digest("affordance"),
        ),
        effectful=True,
    )

    assert resolved.binding == generation.runtime_binding()
    assert resolved.command_context.route_id == "openzyme.workspace.git-lfs"
    assert resolved.command_context.capability_binding_digest == capability.binding_digest
    assert resolved.process_epoch == 1


@dataclass
class _IdleAdapter:
    adapter_id = "test.runtime.idle"
    adapter_contract_digest = _digest("idle-adapter")
    calls: int = 0

    def run_turn(self, command, capability_gateway):  # noqa: ANN001, ANN201
        del capability_gateway
        self.calls += 1
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


@dataclass(frozen=True)
class _NoToolsGateway:
    def list_tools(self, **kwargs):  # noqa: ANN003, ANN201
        del kwargs
        return ()

    def invoke(self, **kwargs):  # noqa: ANN003, ANN201
        raise AssertionError(f"No tool call expected: {kwargs!r}")


@dataclass(frozen=True)
class _AdmissionSource:
    store: InMemoryControlStore
    epoch: DeploymentActivationEpoch
    authority_digest: str

    def pending_signals(self, *, session_id: str, maximum: int):  # noqa: ANN201
        return tuple(
            item
            for item in self.store.records
            if item.entity_type == "agent_runtime_signal"
            and item.payload.get("session_id") == session_id
            and item.payload.get("status") == "pending"
        )[:maximum]

    def build_admission(
        self,
        *,
        signal,
        signal_claim_token: str,
        session_lease: SessionRuntimeLease,
        runtime_lease_generation: int,
        command_id: str,
        turn_id: str,
        budget: RuntimeTurnBudget,
        observed_at: str,
    ) -> RuntimeTurnAdmission:
        binding = SessionCapabilityBindingRevision.create(
            binding_id="runtime-binding-1",
            session_id="session-1",
            revision=1,
            extension_bundle_digest=(
                self.epoch.release_identity.extension_bundle_digest
            ),
            route_catalog_digest=self.epoch.release_identity.route_catalog_digest,
            inventory_bindings=(),
            created_by_actor_id="user:operator-1",
            created_at="2026-08-21T10:00:00+00:00",
        )
        snapshot = ToolAffordanceSnapshot(
            snapshot_id="runtime-affordance-1",
            session_id="session-1",
            agent_member_id="master-1",
            turn_id=turn_id,
            declared_tool_catalog_digest=(
                self.epoch.release_identity.declared_tool_catalog_digest
            ),
            capability_binding_digest=binding.binding_digest,
            authority_lease_digest=self.authority_digest,
            workspace_generation=1,
            health_observation_digest=_digest("runtime-health"),
            subject_policy_digest=_digest("runtime-policy"),
            affordances=(),
            created_at="2026-08-21T10:00:00+00:00",
            snapshot_digest="sha256:" + "0" * 64,
        )
        snapshot = replace(
            snapshot,
            snapshot_digest=canonical_sha256_digest(snapshot.digest_payload()),
        )
        return RuntimeTurnAdmission(
            command_id=command_id,
            turn_id=turn_id,
            agent_member_id="master-1",
            signal_claim_token=signal_claim_token,
            signal=signal,
            session_lease=session_lease,
            runtime_lease_generation=runtime_lease_generation,
            process_epoch=1,
            distribution_id=self.epoch.distribution_id,
            distribution_manifest_digest=self.epoch.distribution_manifest_digest,
            release_identity=self.epoch.release_identity,
            capability_binding=binding,
            affordance_snapshot=snapshot,
            runtime_adapter_id=_IdleAdapter.adapter_id,
            runtime_adapter_contract_digest=_IdleAdapter.adapter_contract_digest,
            budget=budget,
            messages=(
                RuntimeMessage(
                    message_id="runtime-message-1",
                    role=RuntimeMessageRole.USER,
                    content="Continue one bounded turn.",
                ),
            ),
            observed_at=observed_at,
        )

    def discard(self, command_id: str) -> None:
        del command_id


def test_standard_runtime_drain_claims_runs_consumes_and_releases() -> None:
    _, store, precondition = _coordination_fixture()
    lease = store.read(entity_type="agent_authority_lease", entity_id="root-lease-1")
    assert lease is not None
    signal_payload = {
        "signal_id": "signal-1",
        "session_id": "session-1",
        "agent_id": "master-1",
        "agent_member_id": "master-1",
        "reason": AgentRuntimeSignalReason.MANUAL_RESUME.value,
        "status": AgentRuntimeSignalStatus.PENDING.value,
        "created_at": "2026-08-21T10:00:00+00:00",
        "task_id": None,
        "lane_id": None,
        "correlation_id": "request-runtime-drain",
        "source_ref": None,
        "claimed_at": None,
        "claimed_by": None,
        "claim_token": None,
        "claim_expires_at": None,
        "attempt_count": 0,
        "completed_at": None,
        "error_message": None,
        "last_error": None,
        "session_lease_token": None,
        "session_fencing_token": None,
        "runtime_lease_generation": None,
        "capability_lease_id": "root-lease-1",
        "capability_lease_digest": lease.payload["lease_digest"],
        "workspace_generation": 1,
        "process_epoch": 1,
        "enqueue_command_digest": _digest("enqueue"),
        "claim_command_digest": None,
    }
    store.seed(
        KernelRecordSnapshot.create(
            entity_type="agent_runtime_signal",
            entity_id="signal-1",
            state_version=1,
            payload=signal_payload,
        )
    )
    clock = DeterministicClock(datetime(2026, 8, 21, 10, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    adapter = _IdleAdapter()
    outcomes = ControlStoreRuntimeOutcomeRepository(
        store=store,
        reader=store,
        clock=clock,
        ids=ids,
    )
    application = StandardBoundedRuntimeDrainApplication(
        coordination=RuntimeCoordinationKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
        ),
        turns=RuntimeTurnCoordinator(adapter=adapter, outcomes=outcomes),
        outcomes=outcomes,
        records=_QueryRecords(store),
        admissions=_AdmissionSource(
            store=store,
            epoch=_epoch(),
            authority_digest=str(lease.payload["lease_digest"]),
        ),
        capability_gateway=_NoToolsGateway(),
        clock=clock,
        ids=ids,
    )

    result = application.invoke(
        HostV2MutationInvocation(
            route_id="openzyme.kernel.runtime.drain@2",
            method="POST",
            path="/v3/sessions/session-1/runtime/drain",
            session_id="session-1",
            actor_id="user:local-dev",
            idempotency_key="runtime-drain-1",
            correlation_id="request-runtime-drain",
            payload={"max_signals": 1, "max_steps_per_agent": 2},
            precondition=precondition,
        )
    )

    assert result.result["processed_signals"] == 1
    assert result.result["task_transition_performed"] is False
    assert adapter.calls == 1
    signal = store.read(entity_type="agent_runtime_signal", entity_id="signal-1")
    runtime_lease = store.read(
        entity_type="session_runtime_lease",
        entity_id="session-1",
    )
    assert signal is not None and signal.payload["status"] == "completed"
    assert runtime_lease is not None and runtime_lease.payload["released_at"] is not None
    assert store.read(
        entity_type="runtime_outcome_consumption",
        entity_id=result.result["turns"][0]["command_id"],
    ) is not None
