from __future__ import annotations

import pytest

from openzyme_contracts import KernelRecordSnapshot
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import CollaborationApplicationCommand
from openzyme_kernel import CollaborationCommandKind
from openzyme_kernel import CollaborationKernelApplicationService
from openzyme_kernel import KernelContractError

from test_controlled_operation_application import _Clock
from test_controlled_operation_application import _Ids
from test_controlled_operation_application import _Store
from test_controlled_operation_application import _digest


_OPERATIONS = [f"collaboration.{item.value}" for item in CollaborationCommandKind]


def _lease(*, actor_id: str = "agent-1") -> KernelRecordSnapshot:
    return KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "agent_member_id": actor_id,
            "state": "active",
            "generation": 3,
            "fence": 8,
            "expires_at": "2026-08-20T11:00:00+00:00",
            "grants": [{"scope_id": "session-1", "operations": _OPERATIONS}],
        },
    )


def _store() -> _Store:
    store = _Store()
    store.records[("agent_authority_lease", "lease-1")] = _lease()
    return store


def _context(*, operation: str, session_version: int = 4) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=f"command-{operation}",
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="lease-1",
        authority_generation=3,
        authority_fence=8,
        expected_session_version=session_version,
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"collaboration-{operation}",
        correlation_id="correlation-1",
    )


def _service(store: _Store) -> CollaborationKernelApplicationService:
    return CollaborationKernelApplicationService(
        store=store,
        clock=_Clock(),
        ids=_Ids(),
    )


def test_collaboration_create_session_cannot_depend_on_an_impossible_preseeded_lease() -> None:
    store = _store()
    del store.records[("session", "session-1")]
    with pytest.raises(KernelContractError) as rejected:
        _service(store).execute(
            CollaborationApplicationCommand(
                context=_context(operation="create-session", session_version=1),
                operation=CollaborationCommandKind.CREATE_SESSION,
                entity_id="session-1",
                payload={
                    "project_id": "project-1",
                    "title": "Kernel qualification",
                    "objective": "prove collaboration",
                },
            )
        )

    assert rejected.value.code == "session_bootstrap_command_required"
    assert store.read(entity_type="session", entity_id="session-1") is None
    assert store.events == []


def test_roster_lane_task_conversation_and_memory_share_one_kernel_owner() -> None:
    store = _store()
    service = _service(store)
    commands = (
        CollaborationApplicationCommand(
            context=_context(operation="register-agent", session_version=4),
            operation=CollaborationCommandKind.REGISTER_AGENT,
            entity_id="agent-2",
            payload={"name": "Researcher", "role": "researcher"},
        ),
        CollaborationApplicationCommand(
            context=_context(operation="create-lane", session_version=5),
            operation=CollaborationCommandKind.CREATE_LANE,
            entity_id="lane-1",
            payload={"name": "research"},
        ),
        CollaborationApplicationCommand(
            context=_context(operation="create-task", session_version=6),
            operation=CollaborationCommandKind.CREATE_TASK,
            entity_id="task-1",
            payload={
                "subject": "Inspect revision",
                "description": "Read immutable inputs",
                "owner_actor_id": "agent-2",
                "lane_id": "lane-1",
                "finish_validator_ids": [],
            },
        ),
        CollaborationApplicationCommand(
            context=_context(operation="conversation", session_version=7),
            operation=CollaborationCommandKind.RECORD_CONVERSATION,
            entity_id="message-1",
            payload={
                "sender_kind": "user",
                "message_type": "instruction",
                "content": "Inspect the current revision.",
            },
        ),
        CollaborationApplicationCommand(
            context=_context(operation="memory", session_version=8),
            operation=CollaborationCommandKind.WRITE_MEMORY,
            entity_id="memory-1",
            payload={
                "scope_kind": "task",
                "scope_ref": "task-1",
                "kind": "note",
                "summary": "Use the published revision only.",
            },
        ),
    )
    for command in commands:
        service.execute(command)

    assert store.read(entity_type="agent_member", entity_id="agent-2").payload[
        "owned_task_ids"
    ] == ("task-1",)
    assert store.read(entity_type="lane", entity_id="lane-1").payload["status"] == "idle"
    assert store.read(entity_type="task", entity_id="task-1").payload["status"] == "todo"
    assert store.read(entity_type="conversation_message", entity_id="message-1")
    assert store.read(entity_type="memory", entity_id="memory-1")
    assert len(store.events) == len(store.outbox) == 5


def test_task_dependency_cycle_fails_closed() -> None:
    store = _store()
    for task_id, blocked_by in (("task-1", ["task-2"]), ("task-2", [])):
        record = KernelRecordSnapshot.create(
            entity_type="task",
            entity_id=task_id,
            state_version=1,
            payload={
                "session_id": "session-1",
                "owner_actor_id": "agent-1",
                "status": "todo",
                "blocked_by": blocked_by,
            },
        )
        store.records[("task", task_id)] = record
    command = CollaborationApplicationCommand(
        context=_context(operation="dependency"),
        operation=CollaborationCommandKind.ADD_TASK_DEPENDENCY,
        entity_id="task-2",
        payload={"dependency_task_id": "task-1"},
    )
    with pytest.raises(KernelContractError, match="cycle") as rejected:
        _service(store).execute(command)
    assert rejected.value.code == "task_dependency_cycle"
    assert store.events == []


def test_retirement_rejects_unsettled_ownership_then_fences_member_and_lease() -> None:
    store = _store()
    member = KernelRecordSnapshot.create(
        entity_type="agent_member",
        entity_id="agent-1",
        state_version=2,
        payload={
            "session_id": "session-1",
            "status": "active",
            "process_epoch": 4,
            "owned_task_ids": ["task-1"],
        },
    )
    task = KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "owner_actor_id": "agent-1",
            "status": "in_progress",
        },
    )
    store.records[("agent_member", "agent-1")] = member
    store.records[("task", "task-1")] = task
    command = CollaborationApplicationCommand(
        context=_context(operation="retire"),
        operation=CollaborationCommandKind.RETIRE_AGENT,
        entity_id="agent-1",
        payload={"reason": "work complete", "terminal_proof_digest": _digest("proof")},
    )
    with pytest.raises(KernelContractError, match="owned Tasks") as rejected:
        _service(store).execute(command)
    assert rejected.value.code == "agent_retirement_ownership_unsettled"

    store.records[("task", "task-1")] = KernelRecordSnapshot.create(
        entity_type="task",
        entity_id="task-1",
        state_version=2,
        payload={**dict(task.payload), "status": "completed"},
    )
    receipt = _service(store).execute(command)
    retired = store.read(entity_type="agent_member", entity_id="agent-1")
    lease = store.read(entity_type="agent_authority_lease", entity_id="lease-1")
    assert retired.payload["status"] == "shutdown"
    assert retired.payload["process_epoch"] == 5
    assert retired.payload["retirement_settled"] is True
    assert lease.payload["state"] == "revoked"
    assert lease.payload["fence"] == 9
    assert receipt.result["task_transition_performed"] is False
