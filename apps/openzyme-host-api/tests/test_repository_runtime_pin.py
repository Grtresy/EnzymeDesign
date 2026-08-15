from __future__ import annotations

import asyncio

import pytest

from openzyme_core import CoreRepositories
from openzyme_core import RepositoryBindingRequiredError
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_domain import Session
from openzyme_host_api.v3_service import V3EventStore
from openzyme_host_api.v3_service import V3HostApiService


class _RejectingBindingService:
    def __init__(self) -> None:
        self.prerequisites: list[str] = []

    def require_session_binding(
        self,
        session_id: str,
        *,
        prerequisite: str,
    ) -> None:
        self.prerequisites.append(prerequisite)
        raise RepositoryBindingRequiredError(
            f"session {session_id!r} requires an exact repository binding"
        )


def _legacy_service() -> tuple[V3HostApiService, _RejectingBindingService]:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    repositories = CoreRepositories.from_connection(connection)
    repositories.sessions.save(
        Session.create(
            "sess_legacy_runtime",
            "openzyme",
            "Legacy runtime",
            "Must not enter runtime before explicit repository mapping",
        )
    )
    binding_service = _RejectingBindingService()
    service = V3HostApiService(
        repositories=repositories,
        event_store=V3EventStore(repositories),
        repository_binding_service=binding_service,  # type: ignore[arg-type]
    )
    return service, binding_service


def test_message_rejects_unpinned_session_before_any_runtime_write() -> None:
    service, binding_service = _legacy_service()

    with pytest.raises(RepositoryBindingRequiredError, match="exact"):
        service.post_message(
            session_id="sess_legacy_runtime",
            message="This must remain unwritten.",
        )

    assert binding_service.prerequisites == ["agent_workspace"]
    assert service.repositories.agents.list_by_session("sess_legacy_runtime") == []
    assert service.repositories.inbox.list_by_session("sess_legacy_runtime") == []
    assert service.event_store.list("sess_legacy_runtime") == []


def test_manual_drain_and_background_runtime_reject_unpinned_session() -> None:
    service, binding_service = _legacy_service()

    with pytest.raises(RepositoryBindingRequiredError, match="exact"):
        service.drain_runtime(session_id="sess_legacy_runtime")
    with pytest.raises(RepositoryBindingRequiredError, match="exact"):
        asyncio.run(
            service.run_background_runtime_once(session_id="sess_legacy_runtime")
        )

    assert binding_service.prerequisites == [
        "agent_workspace",
        "agent_workspace",
    ]
