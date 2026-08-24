from __future__ import annotations

from dataclasses import replace
from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
from openzyme_contracts import FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import ResolvedWorkflowSelection
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import WorkflowRegistryResolutionError
from openzyme_kernel import KernelContractError
from openzyme_kernel import MessageIngressCommand
from openzyme_kernel import MessageIngressKernelApplicationService
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


class _WorkflowRegistry:
    distribution_id = "openzyme.standard"
    registry_id = "standard-workflows"
    registry_snapshot_digest = _digest("standard-workflow-registry")

    def resolve(self, request):  # noqa: ANN001, ANN201
        selected = request.requested_workflow_refs
        if request.compatibility_skill_keys == ("workflow.code-review",):
            selected = ("workflow.code-review",)
        if not set(selected).issubset({"workflow.code-review"}):
            raise WorkflowRegistryResolutionError(
                code="workflow_selection_unknown",
                diagnostic_id="diagnostic-unknown-workflow",
                summary="Requested workflow is absent from the exact registry snapshot",
            )
        return ResolvedWorkflowSelection(
            request_id=request.request_id,
            request_digest=request.request_digest,
            distribution_id=self.distribution_id,
            registry_id=self.registry_id,
            registry_snapshot_digest=self.registry_snapshot_digest,
            selected_workflow_refs=selected,
            resolved_at="2026-08-21T12:00:00+00:00",
        )


class _ExplodingWorkflowRegistry(_WorkflowRegistry):
    def __init__(self, error: RuntimeError) -> None:
        self.error = error

    def resolve(self, request):  # noqa: ANN001, ANN201
        del request
        raise self.error


def _fixture(
    *,
    workspace_generation: int | None = 1,
    workflow_registry: _WorkflowRegistry | None = None,
) -> tuple[
    InMemoryControlStore, MessageIngressKernelApplicationService, MessageIngressCommand
]:
    clock = DeterministicClock(datetime(2026, 8, 21, 12, tzinfo=UTC))
    ids = DeterministicIdGenerator()
    lease = AgentAuthorityLease.create(
        lease_id="lease-master-1",
        session_id="session-1",
        agent_member_id="master-1",
        grants=(
            AuthorityGrant.create(
                grant_id="grant-message-1",
                scope_id="session-1",
                operations=("conversation.message.ingress",),
                generation=1,
                fence=1,
            ),
        ),
        generation=1,
        fence=1,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at=clock.now_iso(),
        expires_at=None,
        agent_id="agent-master-1",
        workspace_generation=workspace_generation,
        policy_digest=_digest("message-policy"),
        idempotency_key="bootstrap-master-1",
        updated_at=clock.now_iso(),
    )
    store = InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=3,
                payload={
                    "session_id": "session-1",
                    "project_id": "project-1",
                    "status": "active",
                    "updated_at": clock.now_iso(),
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="master-1",
                state_version=2,
                payload={
                    "agent_member_id": "master-1",
                    "agent_id": "agent-master-1",
                    "session_id": "session-1",
                    "status": "active",
                    "process_epoch": 2,
                    "active_authority_lease_id": lease.lease_id,
                    "workspace_generation": workspace_generation,
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=lease.lease_id,
                state_version=1,
                payload=lease.to_dict(),
            ),
        )
    )
    context = KernelCommandContext(
        command_id="command-message-1",
        session_id="session-1",
        actor_id="master-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id=lease.lease_id,
        authority_generation=1,
        authority_fence=1,
        expected_session_version=3,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key="message-1",
        correlation_id="request-message-1",
        workspace_generation=workspace_generation,
    )
    return (
        store,
        MessageIngressKernelApplicationService(
            store=store,
            reader=store,
            clock=clock,
            ids=ids,
            workflow_registry=workflow_registry or _WorkflowRegistry(),
        ),
        MessageIngressCommand(
            context=context,
            message_id="message-1",
            source_actor_id="user:operator-1",
            content="Continue the bounded task",
            distribution_id="openzyme.standard",
            request_lineage_id="request-lineage-1",
            task_id=None,
            skill_keys=("workflow.code-review",),
        ),
    )


def test_message_ingress_atomically_records_inbox_and_wakeup_without_drain() -> None:
    store, service, command = _fixture()

    receipt = service.execute(command)

    message = store.read(entity_type="conversation_message", entity_id="message-1")
    assert message is not None
    assert message.payload["sender_actor_id"] == "user:operator-1"
    assert message.payload["admitted_by_actor_id"] == "master-1"
    assert (
        len(
            tuple(
                record
                for record in store.records
                if record.entity_type == "inbox_message"
            )
        )
        == 1
    )
    signals = tuple(
        record
        for record in store.records
        if record.entity_type == "agent_runtime_signal"
    )
    assert len(signals) == 1
    assert signals[0].payload["status"] == "pending"
    bindings = tuple(
        record
        for record in store.records
        if record.entity_type == "workflow_authority_binding"
    )
    links = tuple(
        record
        for record in store.records
        if record.entity_type == "runtime_signal_authority_link"
    )
    assert len(bindings) == len(links) == 1
    assert bindings[0].payload["selected_workflow_refs"] == ("workflow.code-review",)
    assert links[0].entity_id == signals[0].entity_id
    assert receipt.result["runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False
    assert store.commit_count == 1


def test_message_ingress_without_ready_workspace_rolls_back_all_state() -> None:
    store, service, command = _fixture(workspace_generation=None)

    with pytest.raises(KernelContractError) as rejected:
        service.execute(command)

    assert rejected.value.code == "message_target_runtime_binding_missing"
    assert store.read(entity_type="conversation_message", entity_id="message-1") is None
    assert store.events == []
    assert store.commit_count == 0


def test_explicit_empty_selection_still_creates_active_root_authority() -> None:
    store, service, command = _fixture()

    receipt = service.execute(replace(command, skill_keys=()))

    binding = store.read(
        entity_type="workflow_authority_binding",
        entity_id=str(receipt.result["workflow_authority_id"]),
    )
    assert binding is not None
    assert binding.payload["status"] == "active"
    assert binding.payload["selected_workflow_refs"] == ()


def test_unknown_workflow_fails_before_message_or_signal_mutation() -> None:
    store, service, command = _fixture()
    unknown = replace(
        command,
        skill_keys=(),
        workflow_refs=("workflow.unknown",),
    )

    with pytest.raises(KernelContractError) as rejected:
        service.execute(unknown)

    assert rejected.value.code == "workflow_selection_unknown"
    assert rejected.value.details["diagnostic_recorded"] is True
    assert store.read(entity_type="conversation_message", entity_id="message-1") is None
    assert not any(
        record.entity_type
        in {
            "workflow_authority_binding",
            "runtime_signal_authority_link",
            "agent_runtime_signal",
            "inbox_message",
        }
        for record in store.records
    )
    failures = tuple(
        record
        for record in store.records
        if record.entity_type == "failure_observation"
    )
    diagnostics = tuple(
        record
        for record in store.records
        if record.entity_type == "private_diagnostic"
    )
    assert len(failures) == len(diagnostics) == 1
    assert failures[0].payload["diagnostic_id"] == diagnostics[0].entity_id
    assert failures[0].payload["mutation_applied"] is False
    assert failures[0].payload["fallback_performed"] is False
    assert store.commit_count == 1


def test_private_workflow_registry_failure_is_chained_and_secret_safe() -> None:
    private_error = RuntimeError("provider-token-super-secret")
    store, service, command = _fixture(
        workflow_registry=_ExplodingWorkflowRegistry(private_error)
    )

    with pytest.raises(KernelContractError) as rejected:
        service.execute(command)

    assert rejected.value.code == "workflow_registry_resolution_failed"
    assert rejected.value.details["diagnostic_id"].startswith("diagnostic-workflow-")
    assert rejected.value.details["diagnostic_recorded"] is True
    assert rejected.value.details["fallback_performed"] is False
    assert rejected.value.__cause__ is private_error
    assert "provider-token-super-secret" not in str(rejected.value)
    assert "provider-token-super-secret" not in str(rejected.value.details)
    assert store.read(entity_type="conversation_message", entity_id="message-1") is None
    failure = store.read(
        entity_type="failure_observation",
        entity_id=str(rejected.value.details["failure_id"]),
    )
    diagnostic = store.read(
        entity_type="private_diagnostic",
        entity_id=str(rejected.value.details["diagnostic_id"]),
    )
    assert failure is not None
    assert diagnostic is not None
    assert "provider-token-super-secret" not in str(failure.payload)
    assert "provider-token-super-secret" in diagnostic.payload["exception_message"]
    assert failure.payload["private_diagnostic_digest"] == (
        diagnostic.payload["record_digest"]
    )
    assert set(failure.payload["facts"]) <= FILE_WORKSPACE_FAILURE_FACT_PUBLIC_FIELDS
    assert set(failure.payload["identities"]) <= (
        FILE_WORKSPACE_FAILURE_IDENTITY_PUBLIC_FIELDS
    )
    assert store.commit_count == 1

    clock = service._clock
    assert isinstance(clock, DeterministicClock)
    clock.advance(seconds=30)
    with pytest.raises(KernelContractError) as duplicate:
        service.execute(command)
    assert duplicate.value.code == "workflow_registry_resolution_failed"
    assert duplicate.value.details["failure_id"] == rejected.value.details["failure_id"]
    assert duplicate.value.details["diagnostic_id"] == (
        rejected.value.details["diagnostic_id"]
    )
    assert store.commit_count == 1
