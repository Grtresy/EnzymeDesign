from __future__ import annotations

from dataclasses import dataclass

from openzyme_contracts import KernelRecordSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import AuthorityCheckRequest
from openzyme_extension_spi import KernelQueryContext
from openzyme_kernel import AuthorityKernelApplicationService


def _digest(label: str) -> str:
    return canonical_sha256_digest({"label": label})


@dataclass
class _Clock:
    value: str = "2026-08-20T10:00:00+00:00"

    def now_iso(self) -> str:
        return self.value


class _Reader:
    def __init__(self, record: KernelRecordSnapshot | None) -> None:
        self.record = record

    def read(self, *, entity_type: str, entity_id: str):
        if (
            self.record is not None
            and self.record.entity_type == entity_type
            and self.record.entity_id == entity_id
        ):
            return self.record
        return None


def _context() -> KernelQueryContext:
    return KernelQueryContext(
        session_id="session-1",
        actor_id="agent-1",
        owner_plugin_id="openzyme.science",
        authority_lease_id="lease-1",
        extension_bundle_digest=_digest("bundle"),
        capability_binding_digest=_digest("binding"),
        correlation_id="correlation-1",
    )


def _lease(*, state: str = "active", fence: int = 8) -> KernelRecordSnapshot:
    return KernelRecordSnapshot.create(
        entity_type="agent_authority_lease",
        entity_id="lease-1",
        state_version=1,
        payload={
            "session_id": "session-1",
            "agent_member_id": "agent-1",
            "state": state,
            "generation": 3,
            "fence": fence,
            "expires_at": "2026-08-20T11:00:00+00:00",
            "grants": [
                {
                    "scope_id": "workspace-1",
                    "operations": ["workspace.fs.read"],
                }
            ],
        },
    )


def _request(*, operation: str = "workspace.fs.read", fence: int = 8):
    return AuthorityCheckRequest(
        context=_context(),
        operation=operation,
        scope_id="workspace-1",
        expected_generation=3,
        expected_fence=fence,
    )


def test_exact_operation_scope_generation_and_fence_are_required() -> None:
    service = AuthorityKernelApplicationService(
        reader=_Reader(_lease()),
        clock=_Clock(),
    )
    assert service.authorize(_request()).allowed is True

    wrong_operation = service.authorize(_request(operation="workspace.fs.write"))
    assert wrong_operation.allowed is False
    assert wrong_operation.denial_code == "authority_operation_denied"

    stale = service.authorize(_request(fence=9))
    assert stale.allowed is False
    assert stale.denial_code == "authority_fence_stale"


def test_absent_inactive_and_expired_lease_fail_closed() -> None:
    missing = AuthorityKernelApplicationService(
        reader=_Reader(None),
        clock=_Clock(),
    ).authorize(_request())
    assert missing.denial_code == "authority_lease_not_found"

    inactive = AuthorityKernelApplicationService(
        reader=_Reader(_lease(state="revoked")),
        clock=_Clock(),
    ).authorize(_request())
    assert inactive.denial_code == "authority_lease_inactive"

    expired = AuthorityKernelApplicationService(
        reader=_Reader(_lease()),
        clock=_Clock("2026-08-20T12:00:00+00:00"),
    ).authorize(_request())
    assert expired.denial_code == "authority_lease_expired"
