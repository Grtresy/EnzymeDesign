from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess

import pytest

from openzyme_core import ArtifactBoundaryService
from openzyme_core import CoreRepositories
from openzyme_core import SandboxRuntimeError
from openzyme_core import SandboxRuntimeService
from openzyme_core import SandboxWorkspaceService
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import sandbox_image_record
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import Session
from openzyme_domain import SessionStatus


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _digest_text(content: str) -> str:
    return "sha256:" + hashlib.sha256(content.encode("utf-8")).hexdigest()


def _seed_session(repositories: CoreRepositories, *, session_id: str = "sess_s09") -> Session:
    session = Session(
        session_id=session_id,
        project_id="proj_001",
        title="S09",
        objective="Sandbox file command runtime",
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
    agent_id: str = "agent:executor",
    member_id: str = "member_executor",
) -> AgentMember:
    agent = AgentMember(
        agent_id=agent_id,
        session_id=session.session_id,
        lane_id=None,
        task_id=None,
        name="executor",
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


def _seed_workspace(
    repositories: CoreRepositories,
    tmp_path: Path,
) -> tuple[Session, AgentMember, SandboxWorkspaceRecord, Path]:
    session = _seed_session(repositories)
    agent = _seed_executor(repositories, session)
    assert agent.member_id is not None
    repositories.sandbox_images.save(
        sandbox_image_record(
            image_ref="localhost/openzyme-pipeline-sandbox@sha256:s09",
            image_digest="sha256:s09",
        )
    )
    workspace_root = tmp_path / "workspaces"
    workspace = SandboxWorkspaceService(
        repositories,
        workspace_root=workspace_root,
    ).create_or_get(session_id=session.session_id, agent_member_id=agent.member_id)
    return session, agent, workspace, workspace_root


def _service(
    repositories: CoreRepositories,
    *,
    workspace_root: Path,
    log_root: Path,
) -> SandboxRuntimeService:
    return SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        log_root=log_root,
        execution_backend="local",
    )


def test_sandbox_file_crud_records_audit_and_rejects_bad_patch(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")

    written = service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/tool.py",
        content="print('one')\n",
        create_dirs=True,
    )
    assert written["new_digest"] == _digest_text("print('one')\n")

    read = service.read_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/src/tool.py",
    )
    assert read["content"] == "print('one')\n"
    root_listing = service.list_files(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace",
    )
    assert [item["path"] for item in root_listing["items"]] == [
        "/workspace/logs",
        "/workspace/output",
        "/workspace/src",
        "/workspace/work",
    ]

    patch = (
        "--- /workspace/src/tool.py\n"
        "+++ /workspace/src/tool.py\n"
        "@@ -1 +1 @@\n"
        "-print('one')\n"
        "+print('two')\n"
    )
    patched = service.patch_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/tool.py",
        base_digest=str(written["new_digest"]),
        patch=patch,
    )
    assert patched["new_digest"] == _digest_text("print('two')\n")

    with pytest.raises(SandboxRuntimeError) as bad_patch:
        service.patch_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/tool.py",
            base_digest=str(patched["new_digest"]),
            patch=patch.replace("/workspace/src/tool.py", "/workspace/src/other.py"),
        )
    assert bad_patch.value.error_code == "sandbox_path_forbidden"

    deleted = service.delete_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/tool.py",
        expected_digest=str(patched["new_digest"]),
    )
    assert deleted["deleted"] is True
    audit = repositories.file_audit_entries.list_by_workspace(workspace.sandbox_workspace_id)
    assert [entry.operation for entry in audit] == ["write", "patch", "delete"]


def test_sandbox_write_conflicts_with_active_exec(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    active = SandboxRunRecord(
        sandbox_run_id="srun_active",
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=("python", "src/script.py"),
        argv_digest="sha256:argv",
        cwd="/workspace",
        env_digest="sha256:env",
        status=SandboxRunStatus.RUNNING,
        created_at="2026-05-28T00:02:00+00:00",
        updated_at="2026-05-28T00:02:00+00:00",
        changed_files_summary={},
    )
    repositories.sandbox_runs.save(active)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")

    with pytest.raises(SandboxRuntimeError) as exc_info:
        service.write_file(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            actor_ref=agent.agent_id,
            path="/workspace/src/script.py",
            content="print('blocked')\n",
            create_dirs=True,
        )
    assert exc_info.value.error_code == "sandbox_run_conflict"


def test_sandbox_exec_snapshots_source_and_allows_output_registration(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/script.py",
        content=(
            "from pathlib import Path\n"
            "Path('output/result.txt').write_text('ok\\n', encoding='utf-8')\n"
            "print('ran')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/script.py"],
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert run.exit_code == 0
    assert run.source_snapshot_artifact_id
    assert run.source_tree_digest
    assert run.stdout_summary == "ran\n"
    assert run.changed_files_summary
    assert "output/result.txt" in run.changed_files_summary["added"]
    refreshed = repositories.sandbox_workspaces.get(workspace.sandbox_workspace_id)
    assert refreshed is not None
    assert refreshed.last_command_summary["sandbox_run_id"] == run.sandbox_run_id

    registered = ArtifactBoundaryService(
        repositories,
        workspace_root=workspace_root,
        blob_store_root=tmp_path / "blobs",
    ).register(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        path="/workspace/output/result.txt",
        kind="result",
        format="text",
    )
    assert registered.artifact.metadata["source_snapshot_artifact_id"] == run.source_snapshot_artifact_id


def test_sandbox_exec_transport_smoke_returns_identity_binding(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/smoke.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s09.transport_smoke', {'call_identity': 'smoke_001'})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/smoke.py"],
    )

    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["sandbox_workspace_id"] == workspace.sandbox_workspace_id
    assert payload["sandbox_run_id"] == run.sandbox_run_id
    assert payload["source_snapshot_artifact_id"] == run.source_snapshot_artifact_id
    assert payload["call_identity"] == "smoke_001"


def test_sandbox_exec_requires_source_snapshot_and_forbids_env_secrets(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")

    with pytest.raises(SandboxRuntimeError) as empty_source:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "-c", "print('no source')"],
        )
    assert empty_source.value.error_code == "source_snapshot_empty"

    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/script.py",
        content="print('ready')\n",
        create_dirs=True,
    )
    with pytest.raises(SandboxRuntimeError) as bad_env:
        service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/script.py"],
            env={"OPENAI_API_KEY": "secret"},
        )
    assert bad_env.value.error_code == "sandbox_env_forbidden"


def test_sandbox_exec_timeout_nonzero_and_truncated_logs(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/fail.py",
        content=(
            "import sys\n"
            "print('x' * 40000)\n"
            "print('bad', file=sys.stderr)\n"
            "raise SystemExit(7)\n"
        ),
        create_dirs=True,
    )

    failed = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/fail.py"],
    )
    assert failed.status is SandboxRunStatus.FAILED
    assert failed.exit_code == 7
    assert failed.error_code == "sandbox_exec_nonzero"
    assert failed.log_artifact_ref == f"sandbox-log://{failed.sandbox_run_id}/stdout"
    assert len(repositories.command_log_artifacts.list_by_run(failed.sandbox_run_id)) == 1

    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/slow.py",
        content="import time\ntime.sleep(2)\n",
        create_dirs=True,
    )
    timed_out = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/slow.py"],
        timeout_seconds=1,
    )
    assert timed_out.status is SandboxRunStatus.TIMEOUT
    assert timed_out.error_code == "sandbox_exec_timeout"


def test_sandbox_exec_podman_backend_uses_isolation_policy(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        execution_backend="podman",
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/podman.py",
        content="print('podman')\n",
        create_dirs=True,
    )
    captured: dict[str, list[str]] = {}

    monkeypatch.setattr("shutil.which", lambda binary: f"/usr/bin/{binary}")

    def fake_run(
        command: list[str],
        *,
        capture_output: bool,
        text: bool,
        timeout: int,
        check: bool,
    ) -> subprocess.CompletedProcess[str]:
        del capture_output, text, timeout, check
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr("subprocess.run", fake_run)

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/podman.py"],
    )

    command = captured["command"]
    assert run.status is SandboxRunStatus.COMPLETED
    assert "--network=none" in command
    assert "--read-only" in command
    assert "--memory=2g" in command
    assert "--cpus=2" in command
    assert "--pids-limit=256" in command
    assert any(item.endswith(":/workspace:ro,Z") for item in command)
    assert any(item.endswith(":/workspace/input:ro,Z") for item in command)
    assert "/openzyme/control.sock" in " ".join(command)
    assert command[-3:] == [workspace.image_ref, "python", "src/podman.py"]
