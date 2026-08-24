from __future__ import annotations

import asyncio
from dataclasses import dataclass
from dataclasses import field
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from pathlib import Path
import sqlite3

from httpx import ASGITransport
from httpx import AsyncClient
import pytest
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
from openzyme_contracts import FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import GitObjectFormat
from openzyme_contracts import ProjectRepositoryBinding
from openzyme_contracts import RepositoryRefNamespacePolicy
from openzyme_contracts import RetryEligibility
from openzyme_contracts import SessionBootstrapAuthorization
from openzyme_contracts import SessionBootstrapAuthorityDecision
from openzyme_contracts import WorkspaceProvisioningReceipt
from openzyme_contracts import WorkspaceProvisioningReceiptDisposition
from openzyme_contracts import WorkspaceProvisioningRequest
from openzyme_contracts import WorkspacePortError
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import canonical_sha256_digest
from openzyme_host_api import HostSecurityPolicy
from openzyme_extension_spi import WorkspaceProvisionerPortError
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from scripts.test_gate.no_live_effects import ExternalEffectDenyGuard
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_standard import StandardOperationalAdapterSelection
from openzyme_standard.lifecycle import StandardProductComposition
from openzyme_standard.lifecycle import StandardProductLifecycle
from openzyme_standard.lifecycle import StandardProductLifecycleError
from openzyme_standard.lifecycle import StandardProductWorkerBounds
from openzyme_standard import StandardWorkspaceBootstrapDefaults
from openzyme_standard import build_standard_fresh_install_seed
from openzyme_standard import verify_standard_deployment_startup_read_only
from openzyme_store_sqlite import OPENZYME_STANDARD_OWNER_SCHEMA_PROFILE
from openzyme_store_sqlite import install_owner_partitioned_schema_for_offline_migration
from openzyme_store_sqlite import install_store_schema_for_offline_migration
from openzyme_store_sqlite import seed_fresh_install_composition_offline
from openzyme_store_sqlite import verify_composite_store_schema_read_only


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


@dataclass(frozen=True, slots=True)
class _BootstrapAuthority:
    now: datetime

    def issue(self, **facts: object) -> SessionBootstrapAuthorization:
        return SessionBootstrapAuthorization.create(
            authorization_id="bootstrap-authorization-1",
            operator_actor_id=str(facts["actor_id"]),
            project_id=str(facts["project_id"]),
            session_id=str(facts["session_id"]),
            root_authority_lease_digest=str(facts["root_authority_lease_digest"]),
            session_composition_pin_digest=str(facts["session_composition_pin_digest"]),
            extension_bundle_digest=str(facts["extension_bundle_digest"]),
            capability_binding_digest=str(facts["capability_binding_digest"]),
            repository_pin_digest=str(facts["repository_pin_digest"]),
            workspace_generation=int(facts["workspace_generation"]),
            workspace_provisioning_intent_id=str(
                facts["workspace_provisioning_intent_id"]
            ),
            workspace_provisioning_intent_digest=str(
                facts["workspace_provisioning_intent_digest"]
            ),
            generation=1,
            fence=1,
            issued_at=(self.now - timedelta(seconds=1)).isoformat(),
            expires_at=(self.now + timedelta(minutes=5)).isoformat(),
        )

    def verify(
        self,
        authorization: SessionBootstrapAuthorization,
        *,
        now_iso: str,
    ) -> SessionBootstrapAuthorityDecision:
        assert now_iso == self.now.isoformat()
        return SessionBootstrapAuthorityDecision(
            allowed=True,
            authorization_id=authorization.authorization_id,
            authorization_digest=authorization.authorization_digest,
        )


@dataclass(slots=True)
class _ReadyWorkspaceProvisioner:
    clock: DeterministicClock
    workspace_root: Path
    provider_id: str = "openzyme.workspace.git-lfs"
    adapter_binding_digest: str = field(
        default_factory=lambda: _digest("non-live-workspace-provisioner")
    )
    requests: list[WorkspaceProvisioningRequest] = field(default_factory=list)

    def provision(
        self,
        request: WorkspaceProvisioningRequest,
    ) -> WorkspaceProvisioningReceipt:
        assert self.workspace_root.is_dir()
        assert list(self.workspace_root.iterdir()) == []
        self.requests.append(request)
        return WorkspaceProvisioningReceipt(
            receipt_id=f"workspace-receipt-{request.request_id}",
            request_id=request.request_id,
            request_digest=request.request_digest,
            intent_id=request.intent_id,
            intent_digest=request.intent_digest,
            claim_token=request.claim_token,
            claim_epoch=request.claim_epoch,
            controlled_operation_id=request.controlled_operation_id,
            disposition=WorkspaceProvisioningReceiptDisposition.READY,
            session_id=request.session_id,
            agent_member_id=request.agent_member_id,
            workspace_id=request.workspace_id,
            generation=request.generation,
            repository_pin_digest=request.repository_pin_digest,
            provider_id=request.provider_id,
            target_id=request.target_id,
            adapter_binding_digest=request.adapter_binding_digest,
            effect_certainty=ExternalEffectCertainty.TERMINAL_KNOWN,
            mutation_applied=True,
            fallback_performed=False,
            retry_eligibility=RetryEligibility.TERMINAL,
            reconcile_required=False,
            observed_root_identity_digest=_digest(
                "workspace-root:"
                f"{self.workspace_root.resolve()}:"
                f"{request.workspace_id}:{request.generation}"
            ),
            terminal_receipt_digest=_digest(
                f"workspace-terminal:{request.request_digest}"
            ),
            completed_at=self.clock.now_iso(),
        )

    def reconcile(self, request):  # noqa: ANN001, ANN201
        raise AssertionError(f"Non-live E2E did not authorize reconcile: {request!r}")


@dataclass(slots=True)
class _UncertainThenReadyWorkspaceProvisioner:
    clock: DeterministicClock
    workspace_root: Path
    provider_id: str = "openzyme.workspace.git-lfs"
    adapter_binding_digest: str = field(
        default_factory=lambda: _digest("non-live-workspace-provisioner")
    )
    reconcile_no_effect: bool = False
    requests: list[WorkspaceProvisioningRequest] = field(default_factory=list)
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
        if self.reconcile_no_effect:
            raise WorkspacePortError(
                "non-live-reconciliation-observed-no-effect",
                "The non-live reconciliation proved that no mutation occurred",
                effect_certainty=ExternalEffectCertainty.NO_EFFECT,
                mutation_applied=False,
                diagnostic_id="diagnostic-non-live-reconciliation-no-effect",
            )
        return _ReadyWorkspaceProvisioner(
            clock=self.clock,
            workspace_root=self.workspace_root,
        ).provision(request.provision_request)


@dataclass(slots=True)
class _AssistantRuntimeAdapter:
    adapter_id = "test.runtime.assistant"
    adapter_contract_digest = _digest("assistant-runtime-adapter")
    wait_once: bool = False
    commands: list[object] = field(default_factory=list)

    def run_turn(self, command, capability_gateway):  # noqa: ANN001, ANN201
        correlation_id = command.messages[-1].correlation_id
        tool_names = tuple(
            tool.tool_name
            for tool in capability_gateway.list_tools(
                command_id=command.command_id,
                affordance_snapshot_digest=command.affordance_snapshot_digest,
            )
        )
        assert {
            "world.inspect",
            "capabilities.inspect",
            "task.create",
            "task.delegate",
            "task.finish",
            "task.update",
            "protocol.send",
            "approval.request",
        }.issubset(tool_names)
        waiting_continuation = self.wait_once and not self.commands
        self.commands.append(command)
        messages = (
            ()
            if waiting_continuation
            else (
                RuntimeMessage(
                    message_id=f"assistant-{command.command_id}",
                    role=RuntimeMessageRole.ASSISTANT,
                    content="I received the request and remain ready to collaborate.",
                    correlation_id=correlation_id,
                ),
            )
        )
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
            workflow_authority_id=command.workflow_authority_id,
            workflow_authority_epoch=command.workflow_authority_epoch,
            workflow_authority_digest=command.workflow_authority_digest,
            tool_exposure_snapshot_id=command.tool_exposure_snapshot_id,
            tool_exposure_snapshot_digest=command.tool_exposure_snapshot_digest,
            disposition=(
                RuntimeTurnDisposition.WAITING_CONTINUATION
                if waiting_continuation
                else RuntimeTurnDisposition.IDLE
            ),
            summary=(
                "deterministic continuation wait"
                if waiting_continuation
                else "deterministic non-live assistant turn"
            ),
            messages=messages,
            continuation_id=(
                f"continuation-{command.command_id}" if waiting_continuation else None
            ),
            task_id=command.task_id,
            lane_id=command.lane_id,
            correlation_id=correlation_id,
        )


@dataclass(frozen=True, slots=True)
class _DenyExternalBoundary:
    name: str

    def __getattr__(self, attribute: str):  # noqa: ANN204
        raise AssertionError(
            f"Non-live E2E attempted {self.name}.{attribute}; no external fallback is allowed"
        )


def _repository_binding() -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="repository-binding-1",
        project_id="project-1",
        binding_version=1,
        repository_id="repository-1",
        internal_git_service_id="git-service-1",
        internal_git_endpoint="https://git.internal/repositories/repository-1.git",
        lfs_service_id="lfs-service-1",
        lfs_endpoint=("https://git.internal/repositories/repository-1.git/info/lfs"),
        upstream_identity="upstream-1",
        upstream_url="https://example.invalid/repository-1.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/main",
        default_base_commit="1" * 40,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="policy-v1",
        repository_policy_digest=_digest("repository-policy"),
        created_at="2026-08-21T10:00:00+00:00",
        created_by="user:local-dev",
    )


def _bootstrap_defaults(
    provisioner: _ReadyWorkspaceProvisioner | _UncertainThenReadyWorkspaceProvisioner,
) -> dict[str, StandardWorkspaceBootstrapDefaults]:
    return {
        "project-1": StandardWorkspaceBootstrapDefaults(
            repository_binding=_repository_binding(),
            provider_id=provisioner.provider_id,
            target_id="non-live-local-host",
            adapter_binding_digest=provisioner.adapter_binding_digest,
        )
    }


def _initialize_file_store(database_path: Path):  # noqa: ANN201
    connection = sqlite3.connect(database_path, check_same_thread=False)
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
    wheel_digest = _digest("installed-standard-wheels")
    seed = build_standard_fresh_install_seed(
        schema_proof=schema,
        installed_wheel_set_digest=wheel_digest,
        host_build_digest=_digest("standard-host"),
        client_build_digest=_digest("standard-client"),
        epoch_id="standard-file-e2e",
        sequence=1,
        activated_by_actor_id="operator-1",
        activated_at="2026-08-21T10:00:00+00:00",
    )
    seed_fresh_install_composition_offline(connection, seed)
    connection.close()
    return seed, wheel_digest


@dataclass(slots=True)
class _E2ECompositionFactory:
    seed: object
    wheel_digest: str
    workspace_root: Path
    uncertain_then_ready: bool = False
    reconcile_no_effect: bool = False
    wait_once: bool = False
    factory_id: str = "test.standard.file-composition"
    factory_digest: str = field(
        default_factory=lambda: _digest("test-standard-file-composition")
    )
    provisioner: (
        _ReadyWorkspaceProvisioner | _UncertainThenReadyWorkspaceProvisioner | None
    ) = field(
        default=None,
        init=False,
    )
    runtime_adapter: _AssistantRuntimeAdapter | None = field(
        default=None,
        init=False,
    )

    def build(
        self,
        *,
        connection: sqlite3.Connection,
        component_configuration: object,
    ) -> StandardProductComposition:
        assert dict(component_configuration) == {}  # type: ignore[arg-type]
        now = datetime(2026, 8, 21, 10, tzinfo=UTC)
        clock = DeterministicClock(now)
        ids = DeterministicIdGenerator()
        startup = verify_standard_deployment_startup_read_only(
            connection,
            seed=self.seed,
            observed_installed_wheel_set_digest=self.wheel_digest,
            verified_at=clock.now_iso(),
        )
        provisioner = (
            _UncertainThenReadyWorkspaceProvisioner(
                clock=clock,
                workspace_root=self.workspace_root,
                reconcile_no_effect=self.reconcile_no_effect,
            )
            if self.uncertain_then_ready or self.reconcile_no_effect
            else _ReadyWorkspaceProvisioner(
                clock=clock,
                workspace_root=self.workspace_root,
            )
        )
        runtime_adapter = _AssistantRuntimeAdapter(wait_once=self.wait_once)
        self.provisioner = provisioner
        self.runtime_adapter = runtime_adapter
        return StandardProductComposition(
            startup=startup,
            clock=clock,
            ids=ids,
            bootstrap_authority=_BootstrapAuthority(now),
            bootstrap_defaults_by_project=_bootstrap_defaults(provisioner),
            security_policy=HostSecurityPolicy.from_settings(None),
            operational_selection=StandardOperationalAdapterSelection(
                runtime_adapter=runtime_adapter,
                workspace_mounts=_DenyExternalBoundary("workspace_mounts"),
                process_isolation=_DenyExternalBoundary("process_isolation"),
                revision_backend=_DenyExternalBoundary("revision_backend"),
                workspace_provisioner=provisioner,
            ),
            durable_root_paths=(self.workspace_root,),
            allow_non_live_adapters=True,
        )


def _compose_lifecycle(
    database_path: Path,
    *,
    seed: object,
    wheel_digest: str,
    workspace_root: Path,
    uncertain_then_ready: bool = False,
    reconcile_no_effect: bool = False,
    wait_once: bool = False,
) -> tuple[StandardProductLifecycle, _E2ECompositionFactory]:
    factory = _E2ECompositionFactory(
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_root=workspace_root,
        uncertain_then_ready=uncertain_then_ready,
        reconcile_no_effect=reconcile_no_effect,
        wait_once=wait_once,
    )
    lifecycle = StandardProductLifecycle.compose_file_backed(
        database_path=database_path,
        factory=factory,
        component_configuration={},
        expected_factory_id=factory.factory_id,
        expected_factory_digest=factory.factory_digest,
        worker_bounds=StandardProductWorkerBounds(
            poll_interval_seconds=60,
            maximum_sessions_per_tick=4,
            maximum_provisioning_per_session=1,
            maximum_runtime_commands_per_session=1,
            shutdown_timeout_seconds=2,
        ),
    )
    return lifecycle, factory


def _base_headers() -> dict[str, str]:
    return {
        "Accept": FILE_WORKSPACE_PUBLIC_V2_MEDIA_TYPE,
        "OpenZyme-Workspace-Contract": "file_workspace_public@2",
        "X-Request-Id": "request-standard-host",
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


def test_fresh_file_backed_standard_resident_loop_recovers_after_restart(
    tmp_path: Path,
    deny_external_effects: ExternalEffectDenyGuard,
) -> None:
    database_path = tmp_path / "standard.sqlite3"
    workspace_root = tmp_path / "workspace-root"
    workspace_root.mkdir()
    seed, wheel_digest = _initialize_file_store(database_path)
    lifecycle, factory = _compose_lifecycle(
        database_path,
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_root=workspace_root,
        wait_once=True,
    )
    lifecycle.start()
    app = lifecycle.app
    provisioner = factory.provisioner
    runtime_adapter = factory.runtime_adapter
    assert provisioner is not None
    assert runtime_adapter is not None
    assert lifecycle.preflight.durable_root_paths == (str(workspace_root.resolve()),)
    runtime = app.state.openzyme_standard_runtime

    async def exercise() -> tuple[str, str, str, str]:
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/healthz")
            created = await client.post(
                "/v3/sessions",
                headers={
                    **_base_headers(),
                    "Idempotency-Key": "bootstrap-session-1",
                    "OpenZyme-Release-Digest": health.json()["release_digest"],
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                },
                json={
                    "session_id": "session-1",
                    "project_id": "project-1",
                    "title": "Plugin-free Standard",
                    "objective": "Prove create-to-restart resident closure",
                },
            )
            assert created.status_code == 202, created.text
            assert created.json()["result"]["workspace_readiness"] == "provisioning"

            provisioning = await client.get(
                "/v3/sessions/session-1/workspace",
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
                "/v3/sessions/session-1/messages",
                headers=_mutation_headers(provisioning, "message-too-early"),
                json={
                    "message_id": "message-too-early",
                    "message": "This must remain blocked until ready.",
                    "task_id": None,
                    "lane_id": None,
                    "workflow_refs": [],
                },
            )
            assert early_message.status_code == 409, early_message.text

            provisioned = runtime.provisioning_worker.tick(
                session_id="session-1",
                maximum=1,
            )
            assert len(provisioned) == 1
            assert provisioned[0].result["readiness"] == "ready"

            ready = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert ready.status_code == 200, ready.text
            assert (
                ready.json()["core"]["session"]["resident_readiness"]["readiness"]
                == "ready"
            )
            task = await client.post(
                "/v3/sessions/session-1/tasks",
                headers=_mutation_headers(ready, "create-task-1"),
                json={
                    "task_id": "task-1",
                    "subject": "Inspect repository",
                    "description": "Use the exact Plugin-free Kernel route",
                },
            )
            assert task.status_code == 200, task.text
            ready = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert ready.status_code == 200, ready.text
            assert ready.json()["core"]["tasks"][0]["task_id"] == "task-1"
            initial_task_status = ready.json()["core"]["tasks"][0]["status"]
            assert initial_task_status not in {"completed", "failed", "cancelled"}

            message = await client.post(
                "/v3/sessions/session-1/messages",
                headers=_mutation_headers(ready, "message-runtime-1"),
                json={
                    "message_id": "message-runtime-1",
                    "message": "Continue one bounded teammate turn.",
                    "task_id": None,
                    "lane_id": None,
                    "workflow_refs": [],
                },
            )
            assert message.status_code == 202, message.text
            assert message.json()["result"]["runtime_executed"] is False
            authority_records = runtime.store.list_for_session(
                entity_type="workflow_authority_binding",
                session_id="session-1",
                max_items=4,
            )
            authority_links = runtime.store.list_for_session(
                entity_type="runtime_signal_authority_link",
                session_id="session-1",
                max_items=4,
            )
            assert len(authority_records) == 1
            assert len(authority_links) == 1
            workflow_authority = WorkflowAuthorityBinding.from_dict(
                authority_records[0].payload
            )
            assert workflow_authority.selected_workflow_refs == ()
            assert authority_links[0].payload["authority_id"] == (
                workflow_authority.authority_id
            )
            assert authority_links[0].payload["authority_binding_digest"] == (
                workflow_authority.binding_digest
            )

            queued = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert queued.status_code == 200, queued.text
            assert queued.json()["core"]["runtime"]["signals"][0]["status"] == (
                "pending"
            )
            drained = await client.post(
                "/v3/sessions/session-1/runtime/drain",
                headers=_mutation_headers(queued, "runtime-drain-1"),
                json={"max_signals": 1, "max_steps_per_agent": 2},
            )
            assert drained.status_code == 202, drained.text
            result = drained.json()["result"]
            assert result["runtime_command_id"]
            assert result["runtime_executed"] is False
            assert result["task_transition_performed"] is False
            assert result["fallback_performed"] is False
            assert runtime_adapter.commands == []

            worker_receipts = runtime.runtime_worker.tick(
                session_id="session-1",
                maximum=1,
            )
            assert len(worker_receipts) == 1
            assert worker_receipts[0].result["error_code"] is None, worker_receipts[
                0
            ].result["error_code"]
            assert worker_receipts[0].result["runtime_command_status"] == (
                "completed"
            ), worker_receipts[0].result
            assert worker_receipts[0].result["runtime_executed"] is True
            assert (
                worker_receipts[0].result["bounded_outcome_summary"][
                    "continuations_queued"
                ]
                == 1
            )
            assert len(runtime_adapter.commands) == 1
            continuation_records = runtime.store.list_for_session(
                entity_type="runtime_continuation_intent",
                session_id="session-1",
                max_items=4,
            )
            assert len(continuation_records) == 1
            continuation = continuation_records[0]
            assert continuation.payload["delivery_status"] == "delivered"
            continuation_signal_id = continuation.payload["delivery_signal_id"]
            assert isinstance(continuation_signal_id, str)
            continuation_signal = runtime.store.read(
                entity_type="agent_runtime_signal",
                entity_id=continuation_signal_id,
            )
            continuation_link = runtime.store.read(
                entity_type="runtime_signal_authority_link",
                entity_id=continuation_signal_id,
            )
            assert continuation_signal is not None
            assert continuation_signal.payload["status"] == "pending"
            assert continuation_link is not None
            assert continuation_link.payload["source_kind"] == ("continuation_delivery")
            assert continuation_link.payload["causation_ref"] == (
                continuation.entity_id
            )
            assert continuation_link.payload["authority_id"] == (
                workflow_authority.authority_id
            )
            assert continuation_link.payload["authority_binding_digest"] == (
                workflow_authority.binding_digest
            )

            continuation_queued = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert continuation_queued.status_code == 200
            continuation_drain = await client.post(
                "/v3/sessions/session-1/runtime/drain",
                headers=_mutation_headers(
                    continuation_queued,
                    "runtime-drain-continuation-1",
                ),
                json={"max_signals": 1, "max_steps_per_agent": 2},
            )
            assert continuation_drain.status_code == 202, continuation_drain.text
            second_worker_receipts = runtime.runtime_worker.tick(
                session_id="session-1",
                maximum=1,
            )
            assert len(second_worker_receipts) == 1
            assert second_worker_receipts[0].result["runtime_command_status"] == (
                "completed"
            )
            assert second_worker_receipts[0].result["runtime_executed"] is True
            assert (
                second_worker_receipts[0].result["bounded_outcome_summary"][
                    "continuations_queued"
                ]
                == 0
            )
            assert len(runtime_adapter.commands) == 2
            runtime_lease = runtime.store.read(
                entity_type="session_runtime_lease",
                entity_id="session-1",
            )
            assert runtime_lease is not None
            assert runtime_lease.payload["released_at"] is not None
            outcome_records = runtime.store.list_for_session(
                entity_type="runtime_turn_outcome",
                session_id="session-1",
                max_items=4,
            )
            assistant_records = tuple(
                item
                for item in runtime.store.list_for_session(
                    entity_type="conversation_message",
                    session_id="session-1",
                    max_items=4,
                )
                if item.payload.get("sender_kind") == "assistant"
            )
            assert len(outcome_records) == 2
            assert len(assistant_records) == 1
            assert {
                item["message_id"]
                for outcome_record in outcome_records
                for item in outcome_record.payload["outcome"]["messages"]
            } == {assistant_records[0].entity_id}
            assert {
                outcome_record.payload["outcome"]["disposition"]
                for outcome_record in outcome_records
            } == {"idle", "waiting_continuation"}

            settled = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert settled.status_code == 200, settled.text
            transcript = settled.json()["core"]["conversation"]["transcript"]
            assert settled.json()["core"]["tasks"][0]["status"] == (initial_task_status)
            assert [item["role"] for item in transcript["messages"]] == [
                "user",
                "assistant",
            ]
            assert transcript["messages"][1]["content"] == (
                "I received the request and remain ready to collaborate."
            )
            return (
                transcript["transcript_digest"],
                initial_task_status,
                workflow_authority.authority_id,
                workflow_authority.binding_digest,
            )

    try:
        (
            transcript_digest,
            initial_task_status,
            workflow_authority_id,
            workflow_authority_digest,
        ) = asyncio.run(exercise())
        assert len(provisioner.requests) == 1
        assert list(workspace_root.iterdir()) == []
    finally:
        lifecycle.stop()

    restarted_lifecycle, restarted_factory = _compose_lifecycle(
        database_path,
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_root=workspace_root,
    )
    restarted_lifecycle.start()
    restarted_app = restarted_lifecycle.app
    restarted_provisioner = restarted_factory.provisioner
    restarted_runtime = restarted_factory.runtime_adapter
    assert restarted_provisioner is not None
    assert restarted_runtime is not None

    async def inspect_restarted() -> None:
        async with AsyncClient(
            transport=ASGITransport(app=restarted_app),
            base_url="http://testserver",
        ) as client:
            response = await client.get(
                "/v3/sessions/session-1/workspace",
                headers=_base_headers(),
            )
            assert response.status_code == 200, response.text
            core = response.json()["core"]
            assert core["session"]["resident_readiness"]["readiness"] == "ready"
            assert core["tasks"][0]["task_id"] == "task-1"
            assert core["tasks"][0]["status"] == initial_task_status
            assert core["conversation"]["transcript"]["transcript_digest"] == (
                transcript_digest
            )
            assert core["runtime"]["commands"][0]["status"] == "completed"
            recovered_authorities = core["runtime"]["workflow_authority"]["bindings"]
            assert len(recovered_authorities) == 1
            assert recovered_authorities[0]["authority_id"] == (workflow_authority_id)
            assert recovered_authorities[0]["binding_digest"] == (
                workflow_authority_digest
            )

    try:
        asyncio.run(inspect_restarted())
        assert restarted_provisioner.requests == []
        assert restarted_runtime.commands == []
        assert list(workspace_root.iterdir()) == []
    finally:
        restarted_lifecycle.stop()
    assert deny_external_effects.attempts == []


def test_reconciliation_http_only_admits_before_bounded_worker_observation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "standard-reconciliation.sqlite3"
    workspace_root = tmp_path / "workspace-root-reconciliation"
    workspace_root.mkdir()
    seed, wheel_digest = _initialize_file_store(database_path)
    lifecycle, factory = _compose_lifecycle(
        database_path,
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_root=workspace_root,
        uncertain_then_ready=True,
    )
    lifecycle.start()
    runtime = lifecycle.runtime
    provisioner = factory.provisioner
    assert isinstance(provisioner, _UncertainThenReadyWorkspaceProvisioner)

    async def admit() -> tuple[str, int]:
        async with AsyncClient(
            transport=ASGITransport(app=lifecycle.app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/healthz")
            created = await client.post(
                "/v3/sessions",
                headers={
                    **_base_headers(),
                    "Idempotency-Key": "bootstrap-session-reconciliation-1",
                    "OpenZyme-Release-Digest": health.json()["release_digest"],
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                },
                json={
                    "session_id": "session-reconciliation-1",
                    "project_id": "project-1",
                    "title": "Explicit reconciliation",
                    "objective": "Keep HTTP admission separate from observation",
                },
            )
            assert created.status_code == 202, created.text
            first_tick = runtime.provisioning_worker.tick(
                session_id="session-reconciliation-1",
                maximum=1,
            )
            assert len(first_tick) == 1
            assert first_tick[0].result["readiness"] == "blocked"
            blocked = await client.get(
                "/v3/sessions/session-reconciliation-1/workspace",
                headers=_base_headers(),
            )
            assert blocked.status_code == 200, blocked.text
            provisioning = blocked.json()["core"]["workspace"]["provisioning"]
            assert provisioning["reconcile_required"] is True
            assert provisioning["next_action"] == ("reconcile_workspace_provisioning")
            response = await client.post(
                "/v3/sessions/session-reconciliation-1/"
                "workspace/provisioning/reconcile",
                headers=_mutation_headers(
                    blocked,
                    "reconcile-session-reconciliation-1",
                ),
                json={
                    "intent_id": provisioning["intent_id"],
                    "intent_digest": provisioning["intent_digest"],
                    "expected_intent_version": provisioning["intent_state_version"],
                    "claim_seconds": 41,
                },
            )
            assert response.status_code == 202, response.text
            receipt = response.json()
            assert receipt["operation"] == "admit_reconciliation"
            assert receipt["effect_certainty"] == "no_effect"
            assert receipt["result"]["reconciliation_enqueued"] is True
            assert receipt["result"]["external_effect_performed"] is False
            assert receipt["result"]["runtime_executed"] is False
            assert receipt["result"]["task_transition_performed"] is False
            assert receipt["fallback_performed"] is False
            return (
                provisioning["intent_id"],
                provisioning["intent_state_version"],
            )

    try:
        intent_id, intent_version = asyncio.run(admit())
        assert len(provisioner.requests) == 1
        assert provisioner.reconciliation_requests == []
        occurrences = runtime.store.list_for_session(
            entity_type="workspace_provisioning_reconciliation",
            session_id="session-reconciliation-1",
            max_items=4,
        )
        assert len(occurrences) == 1
        assert occurrences[0].payload["status"] == "pending"
        assert occurrences[0].payload["requested_claim_seconds"] == 41
        assert occurrences[0].payload["blocked_intent_state_version"] == (
            intent_version
        )
        assert occurrences[0].payload["intent_id"] == intent_id

        settled = runtime.provisioning_worker.tick(
            session_id="session-reconciliation-1",
            maximum=1,
        )
        assert len(settled) == 1
        assert len(provisioner.requests) == 1
        assert len(provisioner.reconciliation_requests) == 1
        request = provisioner.reconciliation_requests[0]
        assert request.reconciliation_id == occurrences[0].entity_id

        async def inspect_ready() -> None:
            async with AsyncClient(
                transport=ASGITransport(app=lifecycle.app),
                base_url="http://testserver",
            ) as client:
                response = await client.get(
                    "/v3/sessions/session-reconciliation-1/workspace",
                    headers=_base_headers(),
                )
                assert response.status_code == 200, response.text
                assert (
                    response.json()["core"]["session"]["resident_readiness"][
                        "readiness"
                    ]
                    == "ready"
                )

        asyncio.run(inspect_ready())
    finally:
        lifecycle.stop()


def test_file_backed_diagnosis_admits_one_historical_successor_generation(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "standard-successor.sqlite3"
    workspace_root = tmp_path / "workspace-root-successor"
    workspace_root.mkdir()
    seed, wheel_digest = _initialize_file_store(database_path)
    lifecycle, factory = _compose_lifecycle(
        database_path,
        seed=seed,
        wheel_digest=wheel_digest,
        workspace_root=workspace_root,
        reconcile_no_effect=True,
    )
    lifecycle.start()
    runtime = lifecycle.runtime
    provisioner = factory.provisioner
    assert isinstance(provisioner, _UncertainThenReadyWorkspaceProvisioner)

    async def bootstrap_and_admit_reconciliation() -> dict[str, object]:
        async with AsyncClient(
            transport=ASGITransport(app=lifecycle.app),
            base_url="http://testserver",
        ) as client:
            health = await client.get("/healthz")
            created = await client.post(
                "/v3/sessions",
                headers={
                    **_base_headers(),
                    "Idempotency-Key": "bootstrap-session-successor-1",
                    "OpenZyme-Release-Digest": health.json()["release_digest"],
                    "OpenZyme-Public-Contract-Digest": (
                        FILE_WORKSPACE_PUBLIC_V2_CONTRACT_DIGEST
                    ),
                },
                json={
                    "session_id": "session-successor-1",
                    "project_id": "project-1",
                    "title": "Diagnosed provisioning successor",
                    "objective": "Preserve generation history before replacement",
                },
            )
            assert created.status_code == 202, created.text
            failed = runtime.provisioning_worker.tick(
                session_id="session-successor-1",
                maximum=1,
            )
            assert len(failed) == 1
            assert failed[0].result["readiness"] == "blocked"
            blocked = await client.get(
                "/v3/sessions/session-successor-1/workspace",
                headers=_base_headers(),
            )
            assert blocked.status_code == 200, blocked.text
            provisioning = blocked.json()["core"]["workspace"]["provisioning"]
            assert provisioning["effect_certainty"] == "dispatch_in_doubt"
            assert provisioning["reconcile_required"] is True
            admitted = await client.post(
                "/v3/sessions/session-successor-1/workspace/provisioning/reconcile",
                headers=_mutation_headers(
                    blocked,
                    "reconcile-session-successor-1",
                ),
                json={
                    "intent_id": provisioning["intent_id"],
                    "intent_digest": provisioning["intent_digest"],
                    "expected_intent_version": provisioning["intent_state_version"],
                    "claim_seconds": 43,
                },
            )
            assert admitted.status_code == 202, admitted.text
            assert admitted.json()["result"]["reconciliation_enqueued"] is True
            return provisioning

    async def admit_successor(
        *,
        failed_provisioning: dict[str, object],
    ) -> tuple[dict[str, object], str]:
        async with AsyncClient(
            transport=ASGITransport(app=lifecycle.app),
            base_url="http://testserver",
        ) as client:
            diagnosed = await client.get(
                "/v3/sessions/session-successor-1/workspace",
                headers=_base_headers(),
            )
            assert diagnosed.status_code == 200, diagnosed.text
            provisioning = diagnosed.json()["core"]["workspace"]["provisioning"]
            reconciliation = provisioning["reconciliation"]
            assert provisioning["next_action"] == (
                "create_successor_workspace_generation"
            )
            assert reconciliation["status"] == "blocked"
            assert reconciliation["effect_certainty"] == "no_effect"
            assert reconciliation["mutation_applied"] is False
            assert reconciliation["reconcile_required"] is False
            reconciliation_id = reconciliation["reconciliation_id"]
            successor = await client.post(
                "/v3/sessions/session-successor-1/workspace/provisioning/successor",
                headers=_mutation_headers(
                    diagnosed,
                    "successor-session-successor-1",
                ),
                json={
                    "failed_intent_id": failed_provisioning["intent_id"],
                    "failed_intent_digest": failed_provisioning["intent_digest"],
                    "expected_failed_intent_version": failed_provisioning[
                        "intent_state_version"
                    ],
                    "resolved_reconciliation_id": reconciliation_id,
                },
            )
            assert successor.status_code == 202, successor.text
            receipt = successor.json()
            assert receipt["operation"] == "replace_failed_generation"
            assert receipt["effect_certainty"] == "no_effect"
            assert receipt["fallback_performed"] is False
            assert receipt["result"]["generation"] == 2
            assert receipt["result"]["readiness"] == "provisioning"
            return receipt, reconciliation_id

    try:
        failed_provisioning = asyncio.run(bootstrap_and_admit_reconciliation())
        failed_intent_id = str(failed_provisioning["intent_id"])
        failed_intent = runtime.store.read(
            entity_type="workspace_provisioning_intent",
            entity_id=failed_intent_id,
        )
        assert failed_intent is not None
        source_receipts = tuple(
            item
            for item in runtime.store.list_for_session(
                entity_type="workspace_provisioning_receipt",
                session_id="session-successor-1",
                max_items=8,
            )
            if item.payload["intent_id"] == failed_intent_id
        )
        assert len(source_receipts) == 1
        source_receipt = source_receipts[0]
        failed_intent_payload = dict(failed_intent.payload)
        source_receipt_payload = dict(source_receipt.payload)

        diagnosed = runtime.provisioning_worker.tick(
            session_id="session-successor-1",
            maximum=1,
        )
        assert len(diagnosed) == 1
        assert len(provisioner.requests) == 1
        assert len(provisioner.reconciliation_requests) == 1
        successor_receipt, reconciliation_id = asyncio.run(
            admit_successor(failed_provisioning=failed_provisioning)
        )
        assert successor_receipt["result"]["resolved_reconciliation_id"] == (
            reconciliation_id
        )
        # Successor admission is control-plane only; it does not provision or
        # perform another reconciliation observation in the HTTP request.
        assert len(provisioner.requests) == 1
        assert len(provisioner.reconciliation_requests) == 1

        intents = runtime.store.list_for_session(
            entity_type="workspace_provisioning_intent",
            session_id="session-successor-1",
            max_items=8,
        )
        assert len(intents) == 2
        assert sorted(item.payload["generation"] for item in intents) == [1, 2]
        successor_intent = next(
            item for item in intents if item.payload["generation"] == 2
        )
        assert successor_intent.payload["status"] == "pending"
        preserved_intent = runtime.store.read(
            entity_type="workspace_provisioning_intent",
            entity_id=failed_intent_id,
        )
        preserved_receipt = runtime.store.read(
            entity_type="workspace_provisioning_receipt",
            entity_id=source_receipt.entity_id,
        )
        assert preserved_intent is not None
        assert preserved_receipt is not None
        assert dict(preserved_intent.payload) == failed_intent_payload
        assert dict(preserved_receipt.payload) == source_receipt_payload

        generation_rows = lifecycle.store_writer.execute(
            """
            SELECT workspace_id, generation, workspace_state_version, status
            FROM workspace_generation_records
            WHERE session_id = ?
            ORDER BY generation
            """,
            ("session-successor-1",),
        ).fetchall()
        assert len(generation_rows) == 2
        assert [row[1] for row in generation_rows] == [1, 2]
        assert generation_rows[0][0] == generation_rows[1][0]
        assert generation_rows[0][3] == "failed"
        assert generation_rows[1][3] == "reserved"
        assert generation_rows[1][2] == generation_rows[0][2] + 1
        assert (
            lifecycle.store_writer.execute("PRAGMA foreign_key_check").fetchall() == []
        )
        assert list(workspace_root.iterdir()) == []
    finally:
        lifecycle.stop()


def test_file_backed_preflight_rejects_a_missing_durable_root(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "standard-missing-root.sqlite3"
    seed, wheel_digest = _initialize_file_store(database_path)

    with pytest.raises(StandardProductLifecycleError) as caught:
        _compose_lifecycle(
            database_path,
            seed=seed,
            wheel_digest=wheel_digest,
            workspace_root=tmp_path / "missing-workspace-root",
        )

    assert caught.value.code == "standard_durable_root_missing"
    assert caught.value.mutation_applied is False
    assert caught.value.fallback_performed is False
