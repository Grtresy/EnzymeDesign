from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import subprocess
import threading
import time

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
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ControlledOperationStatus
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


def _wait_for_pending_approval(
    repositories: CoreRepositories,
    session_id: str,
) -> ApprovalRequest:
    for _ in range(100):
        pending_items = repositories.approvals.list_pending_by_session(session_id)
        if pending_items:
            return pending_items[0]
        time.sleep(0.05)
    raise AssertionError("expected pending approval")


def _resolve_s10_approval(
    repositories: CoreRepositories,
    approval_id: str,
    *,
    decision: str,
) -> None:
    approval = repositories.approvals.get(approval_id)
    assert approval is not None
    status = (
        ApprovalRequestStatus.APPROVED
        if decision == "approved"
        else ApprovalRequestStatus.REJECTED
    )
    repositories.approvals.save(
        replace(
            approval,
            status=status,
            resolved_at="2026-05-28T00:05:00+00:00",
        )
    )
    repositories.continuation_states.resolve_for_approval(
        approval.approval_id,
        decision=decision,
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


def test_sandbox_exec_controlled_operation_approval_resumes_same_rpc(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_approve_001',\n"
            "    'logical_operation_key': 'fake.controlled',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'provider_http',\n"
            "    'input_artifact_digests': ['artifact_a:sha256:input'],\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "    'result_summary': {'message': 'approved result'},\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        try:
            holder["run"] = service.exec_command(
                session_id=session.session_id,
                sandbox_workspace_id=workspace.sandbox_workspace_id,
                agent_id=agent.agent_id,
                argv=["python", "src/s10.py"],
                timeout_seconds=10,
            )
        except Exception as exc:  # pragma: no cover - surfaced by assertion below
            holder["error"] = exc

    thread = threading.Thread(target=_run)
    thread.start()
    pending = None
    for _ in range(100):
        pending_items = repositories.approvals.list_pending_by_session(session.session_id)
        if pending_items:
            pending = pending_items[0]
            break
        time.sleep(0.05)
    assert pending is not None
    assert pending.kind == "sdk_controlled_operation"
    operation = repositories.controlled_operations.get(str(pending.request_ref))
    assert operation is not None
    assert operation.status is ControlledOperationStatus.WAITING_APPROVAL
    continuation = repositories.continuation_states.get_by_operation_id(operation.operation_id)
    assert continuation is not None
    assert continuation.status is ContinuationStateStatus.WAITING_APPROVAL
    assert thread.is_alive()

    repositories.approvals.save(
        pending.__class__(
            approval_id=pending.approval_id,
            session_id=pending.session_id,
            task_id=pending.task_id,
            lane_id=pending.lane_id,
            kind=pending.kind,
            requested_action=pending.requested_action,
            status=ApprovalRequestStatus.APPROVED,
            request_ref=pending.request_ref,
            resolution_ref=pending.resolution_ref,
            created_at=pending.created_at,
            resolved_at="2026-05-28T00:05:00+00:00",
        )
    )
    repositories.continuation_states.resolve_for_approval(pending.approval_id, decision="approved")
    thread.join(timeout=5)
    assert not thread.is_alive()
    assert "error" not in holder
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["approval_id"] == pending.approval_id
    assert payload["approval_state"] == "approved"
    assert payload["status"] == "completed"
    assert payload["result_summary"] == {"message": "approved result"}
    completed_operation = repositories.controlled_operations.get(operation.operation_id)
    completed_continuation = repositories.continuation_states.get(continuation.continuation_id)
    assert completed_operation is not None
    assert completed_operation.status is ControlledOperationStatus.COMPLETED
    assert completed_continuation is not None
    assert completed_continuation.status is ContinuationStateStatus.COMPLETED
    assert completed_continuation.claimed_by == f"sandbox-supervisor:{run.sandbox_run_id}"


def test_sandbox_exec_controlled_operation_reject_returns_sdk_error(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_reject.py",
        content=(
            "from openzyme_pipeline.client import call\n"
            "call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_reject_001',\n"
            "    'logical_operation_key': 'fake.rejected',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'host_local_tool',\n"
            "    'expected_outputs_summary': {},\n"
            "    'resource_estimate': {},\n"
            "})\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_reject.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = None
    for _ in range(100):
        pending_items = repositories.approvals.list_pending_by_session(session.session_id)
        if pending_items:
            pending = pending_items[0]
            break
        time.sleep(0.05)
    assert pending is not None
    repositories.approvals.save(
        pending.__class__(
            approval_id=pending.approval_id,
            session_id=pending.session_id,
            task_id=pending.task_id,
            lane_id=pending.lane_id,
            kind=pending.kind,
            requested_action=pending.requested_action,
            status=ApprovalRequestStatus.REJECTED,
            request_ref=pending.request_ref,
            resolution_ref=pending.resolution_ref,
            created_at=pending.created_at,
            resolved_at="2026-05-28T00:06:00+00:00",
        )
    )
    repositories.continuation_states.resolve_for_approval(pending.approval_id, decision="rejected")
    thread.join(timeout=5)
    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "PipelineSdkError" in str(run.stderr_summary)
    operation = repositories.controlled_operations.get(str(pending.request_ref))
    assert operation is not None
    assert operation.status is ControlledOperationStatus.FAILED
    assert operation.error_code == "approval_rejected"


def test_sandbox_exec_controlled_operation_detects_idempotency_digest_drift(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_drift.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "first = call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_drift_001',\n"
            "    'logical_operation_key': 'fake.drift',\n"
            "    'params_digest': 'sha256:params-a',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "})\n"
            "try:\n"
            "    call('s10.controlled_operation', {\n"
            "        'schema_version': 's10.supervised_rpc.v1',\n"
            "        'idempotency_key': 'op_drift_001',\n"
            "        'logical_operation_key': 'fake.drift',\n"
            "        'params_digest': 'sha256:params-b',\n"
            "        'backend_category': 'provider_http',\n"
            "        'expected_outputs_summary': {'kind': 'json'},\n"
            "        'resource_estimate': {'seconds': 1},\n"
            "    })\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({'first_status': first['status'], 'error_code': exc.error_code}, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected operation drift')\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_drift.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload == {
        "error_code": "operation_drift_detected",
        "first_status": "completed",
    }
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert len(operations) == 1
    assert operations[0].status is ControlledOperationStatus.COMPLETED


def test_sandbox_exec_controlled_operation_structured_schema_and_prerequisite_errors(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_failures.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "cases = {\n"
            "    'schema': {'schema_version': 's09.transport'},\n"
            "    'prerequisite': {\n"
            "        'schema_version': 's10.supervised_rpc.v1',\n"
            "        'idempotency_key': 'op_bad_backend',\n"
            "        'logical_operation_key': 'fake.bad_backend',\n"
            "        'params_digest': 'sha256:params',\n"
            "        'backend_category': 'unsupported_backend',\n"
            "        'expected_outputs_summary': {},\n"
            "        'resource_estimate': {},\n"
            "    },\n"
            "}\n"
            "errors = {}\n"
            "for name, params in cases.items():\n"
            "    try:\n"
            "        call('s10.controlled_operation', params)\n"
            "    except PipelineSdkError as exc:\n"
            "        errors[name] = exc.error_code\n"
            "    else:\n"
            "        raise SystemExit(f'expected {name} failure')\n"
            "print(json.dumps(errors, sort_keys=True))\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/s10_failures.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "prerequisite": "operation_prerequisite_missing",
        "schema": "sdk_rpc_schema_unsupported",
    }
    assert repositories.approvals.list_by_session(session.session_id) == []
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_controlled_operation_reuses_approved_digest_without_second_approval(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_reuse.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "base = {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'logical_operation_key': 'fake.reuse',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "}\n"
            "first = call('s10.controlled_operation', dict(base, idempotency_key='op_reuse_a'))\n"
            "second = call('s10.controlled_operation', dict(base, idempotency_key='op_reuse_b'))\n"
            "print(json.dumps({\n"
            "    'first_approval': first['approval_id'],\n"
            "    'second_approval': second['approval_id'],\n"
            "    'same_operation': first['operation_id'] == second['operation_id'],\n"
            "    'statuses': [first['status'], second['status']],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_reuse.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["first_approval"] == pending.approval_id
    assert payload["second_approval"] == pending.approval_id
    assert payload["same_operation"] is False
    assert payload["statuses"] == ["completed", "completed"]
    assert len(repositories.approvals.list_by_session(session.session_id)) == 1
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert [operation.status for operation in operations] == [
        ControlledOperationStatus.COMPLETED,
        ControlledOperationStatus.COMPLETED,
    ]

    replay_run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/s10_reuse.py"],
        timeout_seconds=10,
    )

    assert replay_run.status is SandboxRunStatus.COMPLETED
    replay_payload = json.loads(str(replay_run.stdout_summary))
    assert replay_payload["first_approval"] == pending.approval_id
    assert replay_payload["second_approval"] == pending.approval_id
    assert len(repositories.approvals.list_by_session(session.session_id)) == 1


def test_sandbox_exec_controlled_operation_does_not_reuse_rejected_digest(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_rejected_no_reuse.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "base = {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'logical_operation_key': 'fake.rejected_no_reuse',\n"
            "    'params_digest': 'sha256:params',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "}\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(base, idempotency_key='op_rejected_a'))\n"
            "except PipelineSdkError as exc:\n"
            "    rejected_error = exc.error_code\n"
            "else:\n"
            "    raise SystemExit('expected rejected operation')\n"
            "second = call('s10.controlled_operation', dict(base, idempotency_key='op_rejected_b'))\n"
            "print(json.dumps({\n"
            "    'rejected_error': rejected_error,\n"
            "    'second_approval': second['approval_id'],\n"
            "    'second_status': second['status'],\n"
            "}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_rejected_no_reuse.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    first_pending = _wait_for_pending_approval(repositories, session.session_id)
    first_operation = repositories.controlled_operations.get(str(first_pending.request_ref))
    assert first_operation is not None
    _resolve_s10_approval(
        repositories,
        first_pending.approval_id,
        decision="rejected",
    )
    second_pending = _wait_for_pending_approval(repositories, session.session_id)
    second_operation = repositories.controlled_operations.get(str(second_pending.request_ref))
    assert second_operation is not None
    assert second_pending.approval_id != first_pending.approval_id
    assert second_operation.operation_digest == first_operation.operation_digest
    _resolve_s10_approval(
        repositories,
        second_pending.approval_id,
        decision="approved",
    )
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload == {
        "rejected_error": "approval_rejected",
        "second_approval": second_pending.approval_id,
        "second_status": "completed",
    }
    completed_first = repositories.controlled_operations.get(first_operation.operation_id)
    completed_second = repositories.controlled_operations.get(second_operation.operation_id)
    assert completed_first is not None
    assert completed_first.status is ControlledOperationStatus.FAILED
    assert completed_second is not None
    assert completed_second.status is ControlledOperationStatus.COMPLETED


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
