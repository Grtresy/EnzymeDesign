from __future__ import annotations

import json
from pathlib import Path

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SandboxWorkspaceService
from openzyme_core import SessionProjectionBuilder
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import apply_sqlite_migrations
from openzyme_core import build_teammate_registry
from openzyme_core import connect_sqlite
from openzyme_core import derive_sandbox_workspace_id
from openzyme_core import sandbox_image_record
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(
    repositories: CoreRepositories, *, session_id: str = "sess_s07"
) -> Session:
    session = Session(
        session_id=session_id,
        project_id="proj_001",
        title="S07",
        objective="Implement persistent sandbox foundation",
        status=SessionStatus.ACTIVE,
        created_at="2026-05-28T00:00:00+00:00",
        updated_at="2026-05-28T00:00:00+00:00",
    )
    repositories.sessions.save(session)
    return session


def _seed_executor(
    repositories: CoreRepositories,
    session: Session,
    *,
    agent_id: str = "agent:executor:workspace",
    member_id: str = "member_executor",
) -> AgentMember:
    agent = AgentMember(
        agent_id=agent_id,
        session_id=session.session_id,
        lane_id=None,
        task_id=None,
        name=agent_id.removeprefix("agent:"),
        role="executor",
        status=AgentMemberStatus.IDLE,
        parent_agent_id=None,
        created_at="2026-05-28T00:01:00+00:00",
        updated_at="2026-05-28T00:01:00+00:00",
        member_id=member_id,
    )
    repositories.agents.save(agent)
    saved = repositories.agents.get(session.session_id, agent_id)
    assert saved is not None
    return saved


def _register_compatible_image(repositories: CoreRepositories) -> None:
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:abc123",
            image_digest="sha256:abc123",
        )
    )


def test_sandbox_workspace_identity_is_stable_and_recoverable(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)

    first = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )
    second = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    expected_id = derive_sandbox_workspace_id(session.session_id, agent.member_id)
    assert first.sandbox_workspace_id == expected_id
    assert second.sandbox_workspace_id == expected_id
    assert first.status is SandboxWorkspaceStatus.READY
    assert second.volume_digest == first.volume_digest
    assert first.agent_id == "agent:executor:workspace"
    assert first.agent_member_id == "member_executor"

    recovered_repositories = CoreRepositories.from_connection(repositories.sessions.connection)
    recovered = SandboxWorkspaceService(
        recovered_repositories, workspace_root=tmp_path
    ).create_or_get(session_id=session.session_id, agent_member_id=agent.member_id)

    assert recovered.sandbox_workspace_id == expected_id
    assert recovered.volume_digest == first.volume_digest
    assert str(tmp_path) not in json.dumps(recovered.to_dict(), sort_keys=True)


def test_sandbox_workspace_status_forbids_cross_agent_access(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    other = _seed_executor(
        repositories,
        session,
        agent_id="agent:executor-2",
        member_id="member_executor_2",
    )
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)
    record = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    blocked, error_code, _hint = service.status_for_agent(
        session_id=session.session_id,
        agent_id=other.agent_id,
        sandbox_workspace_id=record.sandbox_workspace_id,
    )

    assert blocked is None
    assert error_code == "sandbox_workspace_forbidden"


def test_sandbox_workspace_status_forbids_cross_session_access(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories, session_id="sess_s07")
    other_session = _seed_session(repositories, session_id="sess_other")
    agent = _seed_executor(repositories, session)
    other_agent = _seed_executor(
        repositories,
        other_session,
        agent_id="agent:executor:other_session",
        member_id="member_other_executor",
    )
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)
    record = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    blocked, error_code, _hint = service.status_for_agent(
        session_id=other_session.session_id,
        agent_id=other_agent.agent_id,
        sandbox_workspace_id=record.sandbox_workspace_id,
    )

    assert blocked is None
    assert error_code == "sandbox_workspace_forbidden"


def test_sandbox_workspace_reports_missing_image_without_fallback(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)

    record = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert record.status is SandboxWorkspaceStatus.MISSING_IMAGE
    assert record.image_digest is None
    assert record.last_error is not None
    assert record.last_error["error_code"] == "sandbox_image_missing"


def test_sandbox_workspace_reports_image_incompatible(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:bad",
            image_digest="sha256:bad",
            sandbox_protocol_version="legacy",
        )
    )

    record = SandboxWorkspaceService(repositories, workspace_root=tmp_path).create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert record.status is SandboxWorkspaceStatus.IMAGE_INCOMPATIBLE
    assert record.last_error is not None
    assert record.last_error["error_code"] == "sandbox_image_incompatible"


def test_sandbox_workspace_reports_volume_corrupt_without_host_path(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    workspace_id = derive_sandbox_workspace_id(session.session_id, agent.member_id)
    (tmp_path / workspace_id).write_text("not-a-directory", encoding="utf-8")

    record = SandboxWorkspaceService(repositories, workspace_root=tmp_path).create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert record.status is SandboxWorkspaceStatus.CORRUPT
    assert record.last_error is not None
    assert record.last_error["error_code"] == "sandbox_volume_corrupt"
    assert record.directory_summary is not None
    assert record.directory_summary["summary_unavailable"] is True
    assert str(tmp_path) not in json.dumps(record.to_dict(), sort_keys=True)


def test_sandbox_workspace_quota_exceeded_is_projected_without_cleanup(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path, quota_bytes=5)
    record = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )
    oversized = tmp_path / record.sandbox_workspace_id / "work" / "large.txt"
    oversized.write_text("exceeds-quota", encoding="utf-8")

    updated = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert updated.status is SandboxWorkspaceStatus.QUOTA_EXCEEDED
    assert updated.last_error is not None
    assert updated.last_error["error_code"] == "sandbox_quota_exceeded"
    assert oversized.exists()


def test_workspace_projection_includes_safe_sandbox_summary(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    SandboxWorkspaceService(repositories, workspace_root=tmp_path).create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    projection = SessionProjectionBuilder(repositories).build_session_workspace(
        session.session_id
    )
    payload = projection.to_dict()

    assert len(payload["sandbox_workspaces"]) == 1
    workspace = payload["sandbox_workspaces"][0]
    assert workspace["sandbox_workspace_id"].startswith("sw_")
    assert workspace["status"] == "ready"
    assert str(tmp_path) not in json.dumps(payload, sort_keys=True)


def test_executor_sandbox_status_tool_uses_current_agent_identity(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    registry = build_teammate_registry(agent_id=agent.agent_id)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_status",
            tool_name="sandbox.workspace.status",
            arguments={},
        ),
    )

    assert result.ok
    payload = json.loads(result.content)
    assert payload["agent_member_id"] == agent.member_id
    assert payload["agent_id"] == agent.agent_id
