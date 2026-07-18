from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
import json
from pathlib import Path
import threading

import pytest

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
from openzyme_core import normalize_immutable_image_id
from openzyme_core import sandbox_image_record
from openzyme_core.sandbox_workspace import WORKSPACE_DIRECTORIES
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionStatus


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def test_normalize_immutable_image_id_accepts_only_full_sha256_ids() -> None:
    bare = "a" * 64

    assert normalize_immutable_image_id(bare) == f"sha256:{bare}"
    assert normalize_immutable_image_id(f"sha256:{bare}\n") == f"sha256:{bare}"

    for invalid in ("sha256:short", "latest", "sha256:" + "G" * 64):
        with pytest.raises(ValueError, match="full sha256 digest"):
            normalize_immutable_image_id(invalid)


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


def test_concurrent_first_create_across_services_keeps_one_ready_record(
    tmp_path: Path,
) -> None:
    database_path = tmp_path / "core.db"
    first_connection = connect_sqlite(str(database_path), check_same_thread=False)
    apply_sqlite_migrations(first_connection)
    first_repositories = CoreRepositories.from_connection(first_connection)
    session = _seed_session(first_repositories)
    agent = _seed_executor(first_repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(first_repositories)

    second_connection = connect_sqlite(str(database_path), check_same_thread=False)
    second_repositories = CoreRepositories.from_connection(second_connection)
    workspace_root = tmp_path / "sandboxes"
    layout_created = threading.Event()
    release_first_save = threading.Event()
    second_started = threading.Barrier(2)
    second_finished = threading.Event()

    class BlockingFirstCreateService(SandboxWorkspaceService):
        def _ensure_and_summarize_directory(
            self,
            workspace_path: Path,
        ) -> dict[str, object]:
            summary = super()._ensure_and_summarize_directory(workspace_path)
            layout_created.set()
            if not release_first_save.wait(timeout=5):
                raise AssertionError("timed out waiting to release the first workspace save")
            return summary

    first_service = BlockingFirstCreateService(
        first_repositories,
        workspace_root=workspace_root,
    )
    second_service = SandboxWorkspaceService(
        second_repositories,
        workspace_root=workspace_root,
    )

    def create_with_first_service():  # type: ignore[no-untyped-def]
        return first_service.create_or_get(
            session_id=session.session_id,
            agent_member_id=agent.member_id,
        )

    def create_with_second_service():  # type: ignore[no-untyped-def]
        second_started.wait(timeout=5)
        try:
            return second_service.create_or_get(
                session_id=session.session_id,
                agent_member_id=agent.member_id,
            )
        finally:
            second_finished.set()

    try:
        with ThreadPoolExecutor(max_workers=2) as executor:
            first_future = executor.submit(create_with_first_service)
            assert layout_created.wait(timeout=5)
            second_future = executor.submit(create_with_second_service)
            second_started.wait(timeout=5)
            completed_before_first_save = second_finished.wait(timeout=0.25)
            release_first_save.set()
            first = first_future.result(timeout=5)
            second = second_future.result(timeout=5)
    finally:
        release_first_save.set()

    assert not completed_before_first_save
    assert first.status is SandboxWorkspaceStatus.READY
    assert second.status is SandboxWorkspaceStatus.READY
    assert first.sandbox_workspace_id == second.sandbox_workspace_id
    assert first.created_at == second.created_at
    assert first.last_error is None
    assert second.last_error is None

    canonical = first_repositories.sandbox_workspaces.get_by_session_member(
        session.session_id,
        agent.member_id,
    )
    assert canonical is not None
    assert canonical.status is SandboxWorkspaceStatus.READY
    assert canonical.sandbox_workspace_id == first.sandbox_workspace_id
    assert canonical.created_at == first.created_at
    assert len(
        first_repositories.sandbox_workspaces.list_by_session(session.session_id)
    ) == 1
    assert second_repositories.sandbox_workspaces.get(
        canonical.sandbox_workspace_id
    ) == canonical


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
    sandbox_workspace = SandboxWorkspaceService(
        repositories, workspace_root=tmp_path
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id="srun_public_stdio",
            session_id=session.session_id,
            sandbox_workspace_id=sandbox_workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=("python", "src/probe.py"),
            argv_digest="sha256:argv",
            cwd="/workspace",
            env_digest="sha256:env",
            status=SandboxRunStatus.COMPLETED,
            stdout_summary="bounded output",
            stderr_summary="",
            stdout_metadata={
                "raw_digest": "sha256:stdout",
                "raw_size_bytes": 40000,
                "truncated": True,
                "log_ref": "sandbox-log://srun_public_stdio/stdout",
            },
            stderr_metadata={
                "raw_digest": "sha256:stderr",
                "raw_size_bytes": 0,
                "truncated": False,
                "log_ref": None,
            },
            created_at="2026-05-28T00:02:00+00:00",
            updated_at="2026-05-28T00:02:01+00:00",
        )
    )

    projection = SessionProjectionBuilder(repositories).build_session_workspace(
        session.session_id
    )
    payload = projection.to_dict()

    assert len(payload["sandbox_workspaces"]) == 1
    workspace = payload["sandbox_workspaces"][0]
    assert workspace["sandbox_workspace_id"].startswith("sw_")
    assert workspace["status"] == "ready"
    assert payload["sandbox_runs"][0]["stdout_metadata"] == {
        "raw_digest": "sha256:stdout",
        "raw_size_bytes": 40000,
        "truncated": True,
        "log_ref": "sandbox-log://srun_public_stdio/stdout",
    }
    assert payload["sandbox_runs"][0]["stderr_metadata"]["log_ref"] is None
    assert str(tmp_path) not in json.dumps(payload, sort_keys=True)


def test_executor_sandbox_status_tool_uses_current_agent_identity_and_context_root(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    registry = build_teammate_registry(agent_id=agent.agent_id)
    workspace_root = tmp_path / "attempt-sandboxes"
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
        sandbox_workspace_root=workspace_root,
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
    workspace_path = workspace_root / payload["sandbox_workspace_id"]
    assert {
        item.name for item in workspace_path.iterdir() if item.is_dir()
    } >= set(WORKSPACE_DIRECTORIES)


def test_executor_sandbox_runtime_implicit_workspace_uses_context_root(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    registry = build_teammate_registry(agent_id=agent.agent_id)
    workspace_root = tmp_path / "attempt-sandboxes"
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
        sandbox_workspace_root=workspace_root,
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_write",
            tool_name="sandbox.file.write",
            arguments={
                "path": "/workspace/src/probe.py",
                "content": "print('ok')\n",
                "create_dirs": True,
            },
        ),
    )

    assert result.ok
    workspace_id = derive_sandbox_workspace_id(session.session_id, agent.member_id)
    workspace_path = workspace_root / workspace_id
    assert (workspace_path / "src/probe.py").read_text(encoding="utf-8") == "print('ok')\n"
    assert {
        item.name for item in workspace_path.iterdir() if item.is_dir()
    } >= set(WORKSPACE_DIRECTORIES)


def test_executor_sandbox_runtime_explicit_workspace_enforces_agent_ownership(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    other = _seed_executor(
        repositories,
        session,
        agent_id="agent:executor:other",
        member_id="member_executor_other",
    )
    assert other.member_id is not None
    _register_compatible_image(repositories)
    workspace_root = tmp_path / "attempt-sandboxes"
    other_workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=workspace_root,
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id=other.member_id,
    )
    registry = build_teammate_registry(agent_id=agent.agent_id)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
        sandbox_workspace_root=workspace_root,
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_cross_workspace_list",
            tool_name="sandbox.file.list",
            arguments={
                "sandbox_workspace_id": other_workspace.sandbox_workspace_id,
                "path": "/workspace",
            },
        ),
    )

    assert not result.ok
    assert result.error_code == "sandbox_workspace_forbidden"


def test_existing_sandbox_workspace_missing_directory_is_corrupt(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)
    workspace = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )
    (tmp_path / workspace.sandbox_workspace_id / "input").rmdir()

    refreshed = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert refreshed.status is SandboxWorkspaceStatus.CORRUPT
    assert refreshed.last_error is not None
    assert refreshed.last_error["error_code"] == "sandbox_volume_corrupt"
    assert not (tmp_path / workspace.sandbox_workspace_id / "input").exists()


@pytest.mark.parametrize("symlink_name", (None, "input"))
def test_new_sandbox_workspace_rejects_preexisting_symlink_layout(
    tmp_path: Path,
    symlink_name: str | None,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    workspace_id = derive_sandbox_workspace_id(session.session_id, agent.member_id)
    workspace_path = tmp_path / workspace_id
    symlink_target = tmp_path / "symlink-target"
    symlink_target.mkdir()
    if symlink_name is None:
        workspace_path.symlink_to(symlink_target, target_is_directory=True)
    else:
        workspace_path.mkdir()
        (workspace_path / symlink_name).symlink_to(
            symlink_target,
            target_is_directory=True,
        )
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)

    workspace = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert workspace.status is SandboxWorkspaceStatus.CORRUPT
    assert workspace.last_error is not None
    assert workspace.last_error["error_code"] == "sandbox_volume_corrupt"
    assert list(symlink_target.iterdir()) == []


def test_new_sandbox_workspace_rejects_preexisting_orphan_directory(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    workspace_id = derive_sandbox_workspace_id(session.session_id, agent.member_id)
    workspace_path = tmp_path / workspace_id
    workspace_path.mkdir()
    orphan = workspace_path / "prior-science.fasta"
    orphan.write_text(">old\nAAAA\n", encoding="utf-8")

    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path,
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert workspace.status is SandboxWorkspaceStatus.CORRUPT
    assert orphan.read_text(encoding="utf-8") == ">old\nAAAA\n"
    assert {item.name for item in workspace_path.iterdir()} == {
        "prior-science.fasta"
    }


@pytest.mark.parametrize("symlink_name", (None, "input"))
def test_existing_sandbox_workspace_rejects_symlink_layout(
    tmp_path: Path,
    symlink_name: str | None,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    service = SandboxWorkspaceService(repositories, workspace_root=tmp_path)
    workspace = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )
    workspace_path = tmp_path / workspace.sandbox_workspace_id
    target = tmp_path / "existing-symlink-target"
    target.mkdir()
    if symlink_name is None:
        for child in workspace_path.iterdir():
            child.rmdir()
        workspace_path.rmdir()
        workspace_path.symlink_to(target, target_is_directory=True)
    else:
        (workspace_path / symlink_name).rmdir()
        (workspace_path / symlink_name).symlink_to(
            target,
            target_is_directory=True,
        )

    refreshed = service.create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )

    assert refreshed.status is SandboxWorkspaceStatus.CORRUPT


def test_workspace_projection_redacts_embedded_paths_from_historical_summary(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    _register_compatible_image(repositories)
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=tmp_path,
    ).create_or_get(
        session_id=session.session_id,
        agent_member_id=agent.member_id,
    )
    repositories.sandbox_workspaces.save(
        replace(
            workspace,
            last_command_summary={
                "error_code": "sandbox_exec_nonzero",
                "stderr_summary": "failed at /home/operator/private/config.toml",
            },
        )
    )

    projection = SessionProjectionBuilder(repositories).build_session_workspace(
        session.session_id
    )
    serialized = json.dumps(projection.to_dict(), sort_keys=True)

    assert "/home/operator" not in serialized
    assert "[redacted-host-path]" in serialized


def test_workspace_activity_feed_redacts_historical_runtime_signal_error() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_historical_private_error",
            session_id=session.session_id,
            agent_id=agent.agent_id,
            reason=AgentRuntimeSignalReason.TASK_AVAILABLE,
            status=AgentRuntimeSignalStatus.FAILED,
            created_at="2026-07-18T00:00:00+00:00",
            completed_at="2026-07-18T00:00:01+00:00",
            error_message="failed at /home/operator/private.toml",
            last_error="socket at /tmp/openzyme/private.sock",
        )
    )

    projection = SessionProjectionBuilder(repositories).build_session_workspace(
        session.session_id
    )
    serialized = json.dumps(projection.to_dict(), sort_keys=True)

    assert "/home/operator" not in serialized
    assert "/tmp/openzyme" not in serialized
    assert "[redacted-host-path]" in serialized
