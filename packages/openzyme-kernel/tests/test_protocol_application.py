from __future__ import annotations

from dataclasses import replace

import pytest

from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityDerivationKind
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_extension_spi import ProtocolApplicationCommand
from openzyme_extension_spi import ProtocolCommandKind
from openzyme_kernel import KernelContractError
from openzyme_kernel import ProtocolKernelApplicationService

from test_controlled_operation_application import _Clock
from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store
from test_controlled_operation_application import _digest


def _store() -> _Store:
    store = _Store()
    workflow = WorkflowAuthorityBinding(
        authority_id="workflow-authority-parent-1",
        session_id="session-1",
        project_id="project-1",
        request_lineage_id="request-lineage-1",
        source_message_id="root-message-1",
        source_principal_id="user-1",
        authorized_actor_id="agent-1",
        selected_workflow_refs=("workflow.code-review", "workflow.inspect"),
        selection_digest=canonical_sha256_digest(
            {
                "schema_version": "workflow_selection_binding@1",
                "registry_snapshot_digest": _digest("workflow-registry"),
                "selected_workflow_refs": [
                    "workflow.code-review",
                    "workflow.inspect",
                ],
            }
        ),
        registry_snapshot_digest=_digest("workflow-registry"),
        derivation_kind=WorkflowAuthorityDerivationKind.ROOT_MESSAGE,
        status=WorkflowAuthorityStatus.ACTIVE,
        epoch=1,
        state_version=1,
        created_at="2026-08-20T10:00:00+00:00",
        updated_at="2026-08-20T10:00:00+00:00",
    )
    records = (
        KernelRecordSnapshot.create(
            entity_type="workflow_authority_binding",
            entity_id=workflow.authority_id,
            state_version=1,
            payload=workflow.to_dict(),
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_member",
            entity_id="agent-2",
            state_version=1,
            payload={
                "session_id": "session-1",
                "agent_id": "agent-identity-2",
                "status": "active",
                "process_epoch": 3,
                "active_authority_lease_id": "lease-2",
                "workspace_generation": 5,
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="task",
            entity_id="task-1",
            state_version=2,
            payload={
                "session_id": "session-1",
                "owner_actor_id": "agent-1",
                "status": "in_progress",
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_authority_lease",
            entity_id="lease-2",
            state_version=1,
            payload={
                "session_id": "session-1",
                "agent_member_id": "agent-2",
                "agent_id": "agent-identity-2",
                "state": "active",
                "generation": 1,
                "fence": 1,
                "workspace_generation": 5,
                "lease_digest": _digest("lease-2"),
                "grants": [],
            },
        ),
        KernelRecordSnapshot.create(
            entity_type="agent_authority_lease",
            entity_id="lease-1",
            state_version=1,
            payload={
                "session_id": "session-1",
                "agent_member_id": "agent-1",
                "state": "active",
                "generation": 3,
                "fence": 8,
                "expires_at": "2026-08-20T11:00:00+00:00",
                "grants": [
                    {
                        "scope_id": "session-1",
                        "operations": [
                            "protocol.delegate",
                            "protocol.send",
                            "protocol.handoff",
                        ],
                    }
                ],
            },
        ),
    )
    for record in records:
        store.records[(record.entity_type, record.entity_id)] = record
    return store


def _context(*, command: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-{command}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=4,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"protocol-{command}",
        correlation_id="correlation-1",
    )


def _service(store: _Store) -> ProtocolKernelApplicationService:
    return ProtocolKernelApplicationService(store=store, clock=_Clock(), ids=_Ids())


def _workflow_payload(*, delegate: bool = False) -> dict[str, object]:
    binding = _store().read(
        entity_type="workflow_authority_binding",
        entity_id="workflow-authority-parent-1",
    )
    payload: dict[str, object] = {
        "workflow_authority_id": "workflow-authority-parent-1",
        "workflow_authority_epoch": 1,
        "workflow_authority_digest": binding.payload["binding_digest"],
    }
    if delegate:
        payload["workflow_refs"] = ["workflow.inspect"]
    return payload


def test_delegate_atomically_creates_protocol_inbox_signal_and_no_runtime_or_finish() -> None:
    store = _store()
    receipt = _service(store).execute(
        ProtocolApplicationCommand(
            context=_context(command="delegate"),
            operation=ProtocolCommandKind.DELEGATE,
            protocol_ref="delegation-1",
            payload={
                "task_id": "task-1",
                "recipient_actor_id": "agent-2",
                "instruction": "inspect published files",
                "parent_agent_id": "agent-1",
                **_workflow_payload(delegate=True),
            },
        )
    )

    delegation = store.read(entity_type="protocol_record", entity_id="delegation-1")
    task = store.read(entity_type="task", entity_id="task-1")
    inbox_id = receipt.result["inbox_message_id"]
    signal_id = receipt.result["runtime_signal_id"]
    assert delegation.payload["recipient_runtime_executed"] is False
    assert store.read(entity_type="inbox_message", entity_id=inbox_id).payload["status"] == "unread"
    signal = store.read(entity_type="agent_runtime_signal", entity_id=signal_id)
    assert signal.payload["status"] == "pending"
    assert signal.payload["agent_id"] == "agent-identity-2"
    assert signal.payload["capability_lease_id"] == "lease-2"
    assert signal.payload["workspace_generation"] == 5
    assert signal.payload["process_epoch"] == 3
    link = store.read(
        entity_type="runtime_signal_authority_link",
        entity_id=signal_id,
    )
    child = store.read(
        entity_type="workflow_authority_binding",
        entity_id=receipt.result["workflow_authority_id"],
    )
    assert link is not None and child is not None
    assert child.payload["parent_authority_id"] == "workflow-authority-parent-1"
    assert child.payload["selected_workflow_refs"] == ("workflow.inspect",)
    assert task.payload["status"] == "in_progress"
    assert receipt.result["recipient_runtime_executed"] is False
    assert receipt.result["task_transition_performed"] is False


def test_protocol_send_only_delivers_and_enqueues_wakeup() -> None:
    store = _store()
    receipt = _service(store).execute(
        ProtocolApplicationCommand(
            context=_context(command="send"),
            operation=ProtocolCommandKind.SEND,
            protocol_ref="message-1",
            payload={
                "recipient_actor_id": "agent-2",
                "message_type": "status_request",
                "content": "Please inspect the current revision.",
                **_workflow_payload(),
            },
        )
    )
    assert receipt.result["recipient_runtime_executed"] is False
    assert len(store.events) == len(store.outbox) == 1


def test_handoff_requires_verified_revision_path_and_active_task_owner() -> None:
    store = _store()
    service = _service(store)
    invalid = ProtocolApplicationCommand(
        context=_context(command="handoff"),
        operation=ProtocolCommandKind.HANDOFF,
        protocol_ref="handoff-1",
        payload={
            "recipient_actor_id": "agent-2",
            "task_id": "task-1",
            "revision_path_ref": {
                "publication_id": "publication-1",
                "commit_oid": "a" * 40,
                "tree_oid": "b" * 40,
                "path": "results/output.txt",
                "content_digest": _digest("output"),
                "verified": False,
            },
            **_workflow_payload(),
        },
    )
    with pytest.raises(KernelContractError, match="unverified") as rejected:
        service.execute(invalid)
    assert rejected.value.code == "protocol_handoff_revision_invalid"
    assert store.read(entity_type="protocol_record", entity_id="handoff-1") is None

    valid = replace(
        invalid,
        payload={
            **dict(invalid.payload),
            "revision_path_ref": {
                **dict(invalid.payload["revision_path_ref"]),
                "verified": True,
            },
        },
    )
    receipt = service.execute(valid)
    assert receipt.mutation_applied is True


def test_retired_recipient_and_nonowner_delegation_fail_before_any_write() -> None:
    store = _store()
    recipient = store.read(entity_type="agent_member", entity_id="agent-2")
    store.records[("agent_member", "agent-2")] = KernelRecordSnapshot.create(
        entity_type="agent_member",
        entity_id="agent-2",
        state_version=2,
        payload={**dict(recipient.payload), "status": "shutdown"},
    )
    command = ProtocolApplicationCommand(
        context=_context(command="delegate"),
        operation=ProtocolCommandKind.DELEGATE,
        protocol_ref="delegation-1",
        payload={
            "task_id": "task-1",
            "recipient_actor_id": "agent-2",
            "instruction": "work",
            **_workflow_payload(delegate=True),
        },
    )
    with pytest.raises(KernelContractError, match="retired"):
        _service(store).execute(command)
    assert store.events == []


def test_delegation_cannot_widen_parent_workflow_selection() -> None:
    store = _store()
    command = ProtocolApplicationCommand(
        context=_context(command="delegate-wide"),
        operation=ProtocolCommandKind.DELEGATE,
        protocol_ref="delegation-wide-1",
        payload={
            "task_id": "task-1",
            "recipient_actor_id": "agent-2",
            "instruction": "use an unauthorized workflow",
            **_workflow_payload(delegate=True),
            "workflow_refs": ["workflow.not-authorized"],
        },
    )

    with pytest.raises(KernelContractError) as rejected:
        _service(store).delegate(command)

    assert rejected.value.code == "workflow_authority_subset_violation"
    assert store.read(entity_type="protocol_record", entity_id="delegation-wide-1") is None

    store = _store()
    task = store.read(entity_type="task", entity_id="task-1")
    store.records[("task", "task-1")] = KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=3,
        payload={**dict(task.payload), "owner_actor_id": "agent-3"},
    )
    with pytest.raises(KernelContractError, match="Task owner"):
        _service(store).execute(command)
    assert store.events == []
