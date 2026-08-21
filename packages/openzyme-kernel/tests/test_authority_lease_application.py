from __future__ import annotations

from datetime import UTC
from datetime import datetime

import pytest

from openzyme_contracts import AgentAuthorityLease
from openzyme_contracts import AgentAuthorityLeaseState
from openzyme_contracts import AuthorityGrant
from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import KernelCommandContext
from openzyme_kernel import AgentAuthorityLeaseKernelApplicationService
from openzyme_kernel import AuthorityLeaseIssueCommand
from openzyme_kernel import AuthorityLeaseRevokeCommand
from openzyme_kernel import KernelContractError
from openzyme_kernel.testing import DeterministicClock
from openzyme_kernel.testing import DeterministicIdGenerator
from openzyme_kernel.testing import InMemoryControlStore


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _context(command_id: str) -> KernelCommandContext:
    return KernelCommandContext(
        command_id=command_id,
        session_id="session-1",
        actor_id="operator-1",
        owner_plugin_id="openzyme.kernel",
        authority_lease_id="issuer-lease",
        authority_generation=4,
        authority_fence=6,
        expected_session_version=3,
        extension_bundle_digest=_digest("extensions"),
        capability_binding_digest=_digest("binding"),
        idempotency_key=f"idempotency-{command_id}",
        correlation_id=f"correlation-{command_id}",
    )


def _lease(
    *,
    lease_id: str,
    member_id: str,
    generation: int,
    fence: int,
    idempotency_key: str,
    parent_lease_id: str | None = None,
    operations: tuple[str, ...] = ("workspace.fs.read",),
) -> AgentAuthorityLease:
    grant = AuthorityGrant.create(
        grant_id=f"grant-{lease_id}",
        scope_id="session-1",
        operations=operations,
        generation=generation,
        fence=fence,
    )
    return AgentAuthorityLease.create(
        lease_id=lease_id,
        session_id="session-1",
        agent_member_id=member_id,
        grants=(grant,),
        generation=generation,
        fence=fence,
        state=AgentAuthorityLeaseState.ACTIVE,
        issued_at="2026-08-19T00:00:00+00:00",
        expires_at="2026-08-20T00:00:00+00:00",
        agent_id="agent-1" if member_id == "member-1" else "operator-agent",
        workspace_generation=2 if member_id == "member-1" else None,
        parent_lease_id=parent_lease_id,
        policy_digest=_digest("policy"),
        idempotency_key=idempotency_key,
    )


def _store() -> InMemoryControlStore:
    issuer = _lease(
        lease_id="issuer-lease",
        member_id="operator-1",
        generation=4,
        fence=6,
        idempotency_key="issuer-bootstrap",
        operations=("authority.lease.issue", "authority.lease.revoke"),
    )
    return InMemoryControlStore(
        (
            KernelRecordSnapshot.create(
                entity_type="session",
                entity_id="session-1",
                state_version=3,
                payload={"status": "active"},
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_member",
                entity_id="member-1",
                state_version=1,
                payload={
                    "session_id": "session-1",
                    "agent_id": "agent-1",
                    "status": "working",
                    "process_epoch": 1,
                    "active_authority_lease_id": None,
                    "workspace_generation": None,
                },
            ),
            KernelRecordSnapshot.create(
                entity_type="agent_authority_lease",
                entity_id=issuer.lease_id,
                state_version=1,
                payload=issuer.to_dict(),
            ),
        )
    )


def _service(store: InMemoryControlStore) -> AgentAuthorityLeaseKernelApplicationService:
    return AgentAuthorityLeaseKernelApplicationService(
        store=store,
        reader=store,
        clock=DeterministicClock(datetime(2026, 8, 19, tzinfo=UTC)),
        ids=DeterministicIdGenerator(),
    )


def test_issue_and_revoke_advance_authority_generation_and_fence() -> None:
    store = _store()
    service = _service(store)
    issued = _lease(
        lease_id="target-lease-1",
        member_id="member-1",
        generation=1,
        fence=1,
        idempotency_key="idempotency-issue-target",
    )

    issue_receipt = service.issue(
        AuthorityLeaseIssueCommand(
            context=_context("issue-target"),
            lease=issued,
        )
    )
    revoke_receipt = service.revoke(
        AuthorityLeaseRevokeCommand(
            context=_context("revoke-target"),
            lease_id=issued.lease_id,
            expected_lease_version=1,
            reason="agent retirement requested",
        )
    )

    current = store.read(
        entity_type="agent_authority_lease", entity_id=issued.lease_id
    )
    assert current is not None
    restored = AgentAuthorityLease.from_dict(current.payload)
    assert restored.state is AgentAuthorityLeaseState.REVOKED
    assert restored.generation == 2
    assert restored.fence == 2
    assert all(grant.generation == 2 and grant.fence == 2 for grant in restored.grants)
    member = store.read(entity_type="agent_member", entity_id="member-1")
    assert member.payload["active_authority_lease_id"] is None
    assert member.payload["workspace_generation"] is None
    assert issue_receipt.mutation_applied is True
    assert revoke_receipt.mutation_applied is True
    assert [event.event_type for event in store.events] == [
        "authority.lease.issued",
        "authority.lease.revoked",
    ]


def test_successor_issue_supersedes_exact_parent_atomically() -> None:
    store = _store()
    service = _service(store)
    parent = _lease(
        lease_id="target-parent",
        member_id="member-1",
        generation=1,
        fence=1,
        idempotency_key="idempotency-issue-parent",
    )
    service.issue(
        AuthorityLeaseIssueCommand(
            context=_context("issue-parent"),
            lease=parent,
        )
    )
    child = _lease(
        lease_id="target-child",
        member_id="member-1",
        generation=2,
        fence=2,
        idempotency_key="idempotency-issue-child",
        parent_lease_id=parent.lease_id,
    )

    receipt = service.issue(
        AuthorityLeaseIssueCommand(
            context=_context("issue-child"),
            lease=child,
            expected_parent_version=1,
        )
    )

    parent_record = store.read(
        entity_type="agent_authority_lease", entity_id=parent.lease_id
    )
    child_record = store.read(
        entity_type="agent_authority_lease", entity_id=child.lease_id
    )
    assert parent_record is not None and child_record is not None
    assert AgentAuthorityLease.from_dict(parent_record.payload).state is (
        AgentAuthorityLeaseState.SUPERSEDED
    )
    assert AgentAuthorityLease.from_dict(child_record.payload).state is (
        AgentAuthorityLeaseState.ACTIVE
    )
    member = store.read(entity_type="agent_member", entity_id="member-1")
    assert member.payload["active_authority_lease_id"] == child.lease_id
    assert member.payload["workspace_generation"] == child.workspace_generation
    assert len(receipt.entity_refs) == 2


def test_stale_parent_rejects_successor_without_partial_child() -> None:
    store = _store()
    service = _service(store)
    parent = _lease(
        lease_id="target-parent",
        member_id="member-1",
        generation=1,
        fence=1,
        idempotency_key="idempotency-issue-parent",
    )
    service.issue(
        AuthorityLeaseIssueCommand(
            context=_context("issue-parent"), lease=parent
        )
    )
    child = _lease(
        lease_id="target-child",
        member_id="member-1",
        generation=2,
        fence=2,
        idempotency_key="idempotency-stale-child",
        parent_lease_id=parent.lease_id,
    )

    with pytest.raises(KernelContractError) as stale:
        service.issue(
            AuthorityLeaseIssueCommand(
                context=_context("stale-child"),
                lease=child,
                expected_parent_version=2,
            )
        )
    assert stale.value.code == "authority_parent_state_stale"
    assert store.read(
        entity_type="agent_authority_lease", entity_id=child.lease_id
    ) is None
