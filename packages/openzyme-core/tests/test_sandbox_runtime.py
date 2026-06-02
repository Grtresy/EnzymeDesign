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
from openzyme_core.sandbox_runtime import S12_ROUTE_POLICIES
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ContinuationStateStatus
from openzyme_domain import ControlledOperation
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
    adapter_executor=None,
    hpc_fetch_executor=None,
) -> SandboxRuntimeService:
    return SandboxRuntimeService(
        repositories,
        workspace_root=workspace_root,
        log_root=log_root,
        execution_backend="local",
        adapter_executor=adapter_executor,
        hpc_fetch_executor=hpc_fetch_executor,
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


def _wait_for_operation_with_approval(
    repositories: CoreRepositories,
    operation_id: str,
    approval_id: str,
) -> ControlledOperation:
    for _ in range(100):
        operation = repositories.controlled_operations.get(operation_id)
        if operation is not None and operation.approval_id == approval_id:
            return operation
        time.sleep(0.05)
    raise AssertionError("expected controlled operation to be linked to approval")


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


def test_sandbox_exec_timeout_excludes_pending_approval_wait(tmp_path: Path) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s10_wait.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's10.supervised_rpc.v1',\n"
            "    'idempotency_key': 'op_wait_001',\n"
            "    'logical_operation_key': 'fake.wait_for_human',\n"
            "    'params_digest': 'sha256:params-wait',\n"
            "    'backend_category': 'provider_http',\n"
            "    'expected_outputs_summary': {'kind': 'json'},\n"
            "    'resource_estimate': {'seconds': 1},\n"
            "    'result_summary': {'message': 'approved after wait'},\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s10_wait.py"],
            timeout_seconds=2,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    time.sleep(2.25)
    assert thread.is_alive()
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["result_summary"] == {"message": "approved after wait"}


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


def test_sandbox_exec_s12_adapter_envelopes_separate_approval_and_result(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_provider.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import call\n"
            "result = call('s10.controlled_operation', {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'ncbi_fetch_proteins',\n"
            "    'idempotency_key': 's12_provider_001',\n"
            "    'params_digest': 'sha256:params-provider',\n"
            "    'input_artifact_ids': ['artifact_query'],\n"
            "    'input_artifact_digests': ['sha256:query'],\n"
            "    'expected_outputs': {'kind': 'fasta', 'storage_uri': '/private/out.fasta'},\n"
            "    'planned_fetch_intent': {'remote_path': '/private/provider/fetch'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "    'adapter_result': {\n"
            "        'status': 'completed',\n"
            "        'provider_request_id': 'provider_req_001',\n"
            "        'registered_artifact_ids': ['artifact_provider_fasta'],\n"
            "        'output_artifact_ids': ['artifact_provider_fasta'],\n"
            "        'validation_results': {'fasta': 'ok'},\n"
            "        'bounded_summary': {'records': 2},\n"
            "        'warnings': ['preview truncated'],\n"
            "        'remote_path': '/private/provider/cache.fasta',\n"
            "    },\n"
            "})\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_provider.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    approval_envelope = operation.adapter_approval_envelope or {}
    assert approval_envelope["adapter_envelope_schema_version"] == "s12.adapter_envelope.v1"
    assert approval_envelope["approval_id"] == pending.approval_id
    assert approval_envelope["sdk_module"] == "bio"
    assert approval_envelope["function_name"] == "ncbi_fetch_proteins"
    assert approval_envelope["route_policy_id"] == "bio.ncbi_fetch_proteins.provider:v1"
    assert approval_envelope["selected_backend"] == "provider_http"
    assert approval_envelope["provider_config_digest"] == "provider_config:ncbi:v1"
    assert approval_envelope["expected_outputs"] == {"kind": "fasta"}
    assert approval_envelope["planned_fetch_intent"] == {}
    assert "storage_uri" not in json.dumps(approval_envelope, sort_keys=True)
    assert "remote_path" not in json.dumps(approval_envelope, sort_keys=True)
    for post_run_key in {
        "fetch_refs",
        "registered_artifact_ids",
        "output_artifact_ids",
        "backend_run_id",
        "provider_request_id",
    }:
        assert post_run_key not in approval_envelope
    assert operation.adapter_result_envelope == {}

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["schema_version"] == "s12.adapter_envelope.v1"
    assert payload["adapter_approval_envelope"] == approval_envelope
    result_envelope = payload["adapter_result_envelope"]
    assert result_envelope["status"] == "completed"
    assert result_envelope["provider_request_id"] == "provider_req_001"
    assert result_envelope["registered_artifact_ids"] == ["artifact_provider_fasta"]
    assert result_envelope["bounded_summary"] == {"records": 2}
    assert result_envelope["warnings"] == [
        {
            "code": "adapter_warning",
            "stage": "adapter_result",
            "retryable": False,
            "summary": "preview truncated",
            "details_ref": None,
            "safe_diagnostics": None,
        }
    ]
    assert "remote_path" not in json.dumps(result_envelope, sort_keys=True)
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.adapter_result_envelope == result_envelope


def test_sandbox_exec_public_bio_sdk_uses_s12_controlled_operation(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_sdk.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import bio\n"
            "result = bio.ncbi_fetch_proteins(\n"
            "    accessions=['AAB57849.1'],\n"
            "    output_dir='/workspace/output/bio/ncbi',\n"
            "    fields=['definition'],\n"
            ")\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    assert operation.adapter_envelope_schema_version == "s12.adapter_envelope.v1"
    assert operation.sdk_module == "bio"
    assert operation.function_name == "ncbi_fetch_proteins"
    assert operation.route_policy_id == "bio.ncbi_fetch_proteins.provider:v1"
    assert operation.selected_backend == "provider_http"
    assert operation.provider_config_digest == "provider_config:ncbi:v1"
    assert operation.expected_outputs_summary == {"output_dir": "/workspace/output/bio/ncbi"}

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "adapter_execution_unavailable" in run.stderr_summary
    assert "sandbox_transport_method_forbidden" not in run.stderr_summary
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.FAILED
    assert persisted.error_code == "adapter_execution_unavailable"


def test_sandbox_exec_public_bio_sdk_uses_adapter_executor_after_approval(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    calls: list[dict[str, object]] = []

    def _adapter_executor(operation: ControlledOperation, envelope: dict[str, object]) -> dict[str, object]:
        calls.append({"operation_id": operation.operation_id, "params": dict(envelope["adapter_params"])})
        return {
            "adapter_result": {
                "status": "succeeded",
                "provider_request_id": "provider_req_core",
                "registered_artifact_ids": ["artifact_provider_core"],
                "output_artifact_ids": ["artifact_provider_core"],
                "validation_results": {"artifact_provider_core": {"passed": True}},
                "bounded_summary": {"provider": "ncbi", "record_count": 1},
                "warnings": [],
            },
            "result_summary": {"provider": "ncbi", "record_count": 1},
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_sdk.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import bio\n"
            "result = bio.ncbi_fetch_proteins(\n"
            "    accessions=['AAB57849.1'],\n"
            "    output_dir='/workspace/output/bio/ncbi',\n"
            "    fields=['definition'],\n"
            ")\n"
            "print(json.dumps(result, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["adapter_result_envelope"]["provider_request_id"] == "provider_req_core"
    assert payload["adapter_result_envelope"]["registered_artifact_ids"] == ["artifact_provider_core"]
    assert calls == [
        {
            "operation_id": operation.operation_id,
            "params": {
                "accessions": ["AAB57849.1"],
                "fields": ["definition"],
                "output_dir": "/workspace/output/bio/ncbi",
            },
        }
    ]
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.COMPLETED
    assert persisted.error_code is None


def test_sandbox_exec_public_bio_tools_hpc_run_can_fetch_declared_outputs(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    adapter_calls: list[dict[str, object]] = []
    fetch_calls: list[dict[str, object]] = []

    def _adapter_executor(operation: ControlledOperation, envelope: dict[str, object]) -> dict[str, object]:
        params = dict(envelope["adapter_params"])
        adapter_calls.append({"operation_id": operation.operation_id, "params": params})
        run_handle = {
            "kind": "hpc_run_handle",
            "run_id": "run_hpc_core",
            "runner_run_id": "runner_hpc_core",
            "status": "succeeded",
            "operation_id": operation.operation_id,
            "operation_digest": operation.operation_digest,
            "hpc_workspace_id": operation.hpc_workspace_id,
            "declared_outputs": list(params["expected_outputs"]),
            "summary": "bio_tools.mafft placement operation succeeded",
            "warnings": [],
        }
        return {
            "adapter_result": {
                "status": "succeeded",
                "backend_run_id": "runner_hpc_core",
                "fetch_refs": [],
                "registered_artifact_ids": [],
                "output_artifact_ids": [],
                "bounded_summary": run_handle,
                "warnings": [],
            },
            "result_summary": run_handle,
        }

    def _hpc_fetch_executor(params: dict[str, object]) -> dict[str, object]:
        fetch_calls.append(dict(params))
        return {
            "kind": "hpc_fetch_result",
            "run_id": params["run_id"],
            "status": "succeeded",
            "registered_artifact_ids": ["artifact_alignment_core"],
            "fetch_refs": [
                {
                    "fetch_ref_id": "fetch_alignment_core",
                    "run_id": params["run_id"],
                    "declared_output_path": "bio_tools/mafft/alignment.fasta",
                    "registered_artifact_id": "artifact_alignment_core",
                    "output_digest": "sha256:alignment",
                }
            ],
        }

    service = _service(
        repositories,
        workspace_root=workspace_root,
        log_root=tmp_path / "logs",
        adapter_executor=_adapter_executor,
        hpc_fetch_executor=_hpc_fetch_executor,
    )
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_tools_fetch.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts, bio_tools, hpc\n"
            "path = Path('output/inputs/reference.fasta')\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text('>one\\nMSEQONE\\n>two\\nMSEQTWO\\n', encoding='utf-8')\n"
            "registered = artifacts.register('/workspace/output/inputs/reference.fasta', kind='sequence', format='fasta')\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "stage_ref = ws.stage_artifact(registered['artifact']['artifact_id'], workspace_path='inputs/reference.fasta')\n"
            "run = bio_tools.mafft(\n"
            "    input_fasta=stage_ref,\n"
            "    placement=ws,\n"
            "    expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence', 'format': 'fasta'}],\n"
            ")\n"
            "fetch = ws.fetch_outputs(run)\n"
            "print(json.dumps({'run': run, 'fetch': fetch}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_tools_fetch.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["run"]["kind"] == "hpc_run_handle"
    assert payload["run"]["run_id"] == "run_hpc_core"
    assert payload["run"]["operation_id"] == operation.operation_id
    assert payload["fetch"]["registered_artifact_ids"] == ["artifact_alignment_core"]
    assert adapter_calls[0]["operation_id"] == operation.operation_id
    assert fetch_calls[0]["operation_id"] == operation.operation_id
    assert fetch_calls[0]["operation_digest"] == operation.operation_digest
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.COMPLETED
    assert persisted.adapter_result_envelope is not None
    assert persisted.adapter_result_envelope["registered_artifact_ids"] == ["artifact_alignment_core"]
    assert persisted.adapter_result_envelope["fetch_refs"][0]["fetch_ref_id"] == "fetch_alignment_core"


def test_sandbox_exec_public_artifacts_hpc_and_bio_tools_sdk_use_control_socket(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_bio_tools_sdk.py",
        content=(
            "import json\n"
            "from pathlib import Path\n"
            "from openzyme_pipeline import artifacts, bio_tools, hpc\n"
            "path = Path('output/inputs/reference.fasta')\n"
            "path.parent.mkdir(parents=True, exist_ok=True)\n"
            "path.write_text('>one\\nMSEQONE\\n>two\\nMSEQTWO\\n', encoding='utf-8')\n"
            "registered = artifacts.register('/workspace/output/inputs/reference.fasta', kind='sequence', format='fasta')\n"
            "artifact_id = registered['artifact']['artifact_id']\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "stage_ref = ws.stage_artifact(artifact_id, workspace_path='inputs/reference.fasta')\n"
            "result = bio_tools.mafft(\n"
            "    input_fasta=stage_ref,\n"
            "    placement=ws,\n"
            "    expected_outputs=[{'path': 'bio_tools/mafft/alignment.fasta', 'kind': 'sequence', 'format': 'fasta'}],\n"
            ")\n"
            "print(json.dumps({'registered': registered, 'stage_ref': stage_ref, 'result': result}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/public_bio_tools_sdk.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    assert operation.adapter_envelope_schema_version == "s12.adapter_envelope.v1"
    assert operation.sdk_module == "bio_tools"
    assert operation.function_name == "mafft"
    assert operation.route_policy_id == "bio_tools.mafft.hpc:v1"
    assert operation.selected_backend == "hpc"
    assert operation.placement == "hpc"
    assert operation.hpc_workspace_id
    assert len(operation.stage_refs) == 1
    assert operation.stage_refs[0]["kind"] == "hpc_stage_ref"
    assert operation.stage_refs[0]["artifact_id"]
    assert operation.planned_fetch_intent == {
        "declared_outputs": [
            {"path": "bio_tools/mafft/alignment.fasta", "kind": "sequence", "format": "fasta"}
        ]
    }

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.FAILED
    assert run.error_code == "sandbox_exec_nonzero"
    assert "adapter_execution_unavailable" in run.stderr_summary
    registered_artifacts = [
        artifact for artifact in repositories.artifacts.list_by_session(session.session_id)
        if artifact.relative_path == "inputs/reference.fasta"
    ]
    assert registered_artifacts
    assert "sandbox_transport_method_forbidden" not in run.stderr_summary
    persisted = repositories.controlled_operations.get(operation.operation_id)
    assert persisted is not None
    assert persisted.status is ControlledOperationStatus.FAILED
    assert persisted.error_code == "adapter_execution_unavailable"


def test_sandbox_exec_public_hpc_fetch_outputs_fails_structured_without_run(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/public_hpc_fetch.py",
        content=(
            "import json\n"
            "from openzyme_pipeline import hpc\n"
            "from openzyme_pipeline.client import PipelineSdkError\n"
            "ws = hpc.workspace('aox_hmm')\n"
            "try:\n"
            "    ws.fetch_outputs({'run_id': 'run_missing'})\n"
            "except PipelineSdkError as exc:\n"
            "    print(json.dumps({'error_code': exc.error_code, 'message': exc.message}, sort_keys=True))\n"
            "else:\n"
            "    raise SystemExit('expected hpc.fetch_outputs to fail')\n"
        ),
        create_dirs=True,
    )

    run = service.exec_command(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        agent_id=agent.agent_id,
        argv=["python", "src/public_hpc_fetch.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "error_code": "hpc_fetch_not_declared",
        "message": "hpc.fetch_outputs requires a completed Host-supervised HPC run with declared outputs",
    }
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_exec_s12_route_policy_failures_do_not_create_operations(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_route_failures.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "cases = {\n"
            "    'missing_policy': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'idempotency_key': 's12_missing_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'unknown_policy': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio.unknown.provider:v1',\n"
            "        'idempotency_key': 's12_unknown_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'fixture': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'test.fixture_adapter:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'mafft',\n"
            "        'idempotency_key': 's12_fixture_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'prerequisite': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'test.prerequisite_missing:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'mafft',\n"
            "        'idempotency_key': 's12_prerequisite_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'disabled': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio_tools.hmmer_search_cli.disabled:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'hmmer_search_cli',\n"
            "        'idempotency_key': 's12_disabled_policy',\n"
            "        'params_digest': 'sha256:params',\n"
            "    },\n"
            "    'mismatch': {\n"
            "        'schema_version': 's12.adapter_envelope.v1',\n"
            "        'route_policy_id': 'bio.ncbi_fetch_proteins.provider:v1',\n"
            "        'sdk_module': 'bio_tools',\n"
            "        'function_name': 'mafft',\n"
            "        'idempotency_key': 's12_mismatch_policy',\n"
            "        'params_digest': 'sha256:params',\n"
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
        argv=["python", "src/s12_route_failures.py"],
        timeout_seconds=10,
    )

    assert run.status is SandboxRunStatus.COMPLETED
    assert json.loads(str(run.stdout_summary)) == {
        "disabled": "unsupported_in_s14",
        "fixture": "fixture_backend_forbidden",
        "mismatch": "adapter_schema_incompatible",
        "missing_policy": "route_policy_missing",
        "prerequisite": "operation_prerequisite_missing",
        "unknown_policy": "route_policy_missing",
    }
    assert repositories.approvals.list_by_session(session.session_id) == []
    assert repositories.controlled_operations.list_by_run(run.sandbox_run_id) == []


def test_sandbox_runtime_s14_bio_tool_route_policy_table_is_fail_closed() -> None:
    enabled = {
        "bio_tools.cdhit.hpc:v1": ("cdhit", "cdhit_4.8.1.hpc_apptainer_sif:v1"),
        "bio_tools.mafft.hpc:v1": ("mafft", "mafft_7.525.hpc_apptainer_sif:v1"),
        "bio_tools.hmmbuild.hpc:v1": ("hmmbuild", "hmmer_3.4.hmmbuild.hpc_apptainer_sif:v1"),
        "bio_tools.hmmalign.hpc:v1": ("hmmalign", "hmmer_3.4.hmmalign.hpc_apptainer_sif:v1"),
    }
    for route_policy_id, (function_name, toolchain_id) in enabled.items():
        policy = S12_ROUTE_POLICIES[route_policy_id]
        assert policy["sdk_module"] == "bio_tools"
        assert policy["function_name"] == function_name
        assert policy["selected_backend"] == "hpc"
        assert policy["backend_category"] == "hpc_runner"
        assert policy["runtime_packaging_id"] == "hpc_apptainer_sif.aox_hmm_2026_05_30"
        assert policy["toolchain_id"] == toolchain_id
        assert policy["status"] == "ok"
        assert policy["evidence_ref"]
        assert policy["parameter_inventory_ref"]

    disabled = S12_ROUTE_POLICIES["bio_tools.hmmer_search_cli.disabled:v1"]
    assert disabled["sdk_module"] == "bio_tools"
    assert disabled["function_name"] == "hmmer_search_cli"
    assert disabled["selected_backend"] == "disabled"
    assert disabled["status"] == "disabled"
    assert disabled["error_code"] == "unsupported_in_s14"


def test_sandbox_exec_s12_hpc_requires_explicit_placement_stage_and_fetch_intent(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_hpc.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "stage_ref = {\n"
            "    'kind': 'hpc_stage_ref',\n"
            "    'stage_ref_id': 'stage_input_001',\n"
            "    'hpc_workspace_id': 'hpcws_s12',\n"
            "    'artifact_id': 'artifact_input_fasta',\n"
            "    'artifact_digest': 'sha256:input-fasta',\n"
            "    'workspace_relative_path': 'inputs/query.fasta',\n"
            "    'remote_path': 'hpc://private/input.fasta',\n"
            "}\n"
            "fetch_intent = {\n"
            "    'declared_outputs': [\n"
            "        {'path': 'outputs/alignment.fasta', 'format': 'fasta', 'remote_path': 'hpc://private/out'}\n"
            "    ],\n"
            "    'remote_path': 'hpc://private/run',\n"
            "}\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio_tools.mafft.hpc:v1',\n"
            "    'sdk_module': 'bio_tools',\n"
            "    'function_name': 'mafft',\n"
            "    'params_digest': 'sha256:hpc-params',\n"
            "    'input_artifact_ids': ['artifact_input_fasta'],\n"
            "    'input_artifact_digests': ['sha256:input-fasta'],\n"
            "    'expected_outputs': [{'path': 'outputs/alignment.fasta'}],\n"
            "    'resource_estimate': {'walltime_minutes': 5},\n"
            "}\n"
            "errors = {}\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(\n"
            "        base,\n"
            "        idempotency_key='s12_hpc_missing_placement',\n"
            "        hpc_workspace_id='hpcws_s12',\n"
            "        stage_refs=[stage_ref],\n"
            "        planned_fetch_intent=fetch_intent,\n"
            "    ))\n"
            "except PipelineSdkError as exc:\n"
            "    errors['missing_placement'] = exc.error_code\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(\n"
            "        base,\n"
            "        idempotency_key='s12_hpc_bad_path',\n"
            "        placement='hpc',\n"
            "        hpc_workspace_id='hpcws_s12',\n"
            "        stage_refs=[dict(stage_ref, workspace_relative_path='/remote/input.fasta')],\n"
            "        planned_fetch_intent=fetch_intent,\n"
            "    ))\n"
            "except PipelineSdkError as exc:\n"
            "    errors['bad_stage_path'] = exc.error_code\n"
            "result = call('s10.controlled_operation', dict(\n"
            "    base,\n"
            "    idempotency_key='s12_hpc_valid',\n"
            "    placement='hpc',\n"
            "    hpc_workspace_id='hpcws_s12',\n"
            "    stage_refs=[stage_ref],\n"
            "    planned_fetch_intent=fetch_intent,\n"
            "    adapter_result={\n"
            "        'status': 'completed',\n"
            "        'backend_run_id': 'slurm_123',\n"
            "        'fetch_refs': [{'fetch_ref_id': 'fetch_alignment', 'remote_path': 'hpc://private/out'}],\n"
            "        'registered_artifact_ids': ['artifact_alignment'],\n"
            "        'validation_results': {'alignment': 'ok'},\n"
            "        'bounded_summary': {'outputs': 1},\n"
            "    },\n"
            "))\n"
            "print(json.dumps({'errors': errors, 'result': result}, sort_keys=True))\n"
        ),
        create_dirs=True,
    )
    holder: dict[str, object] = {}

    def _run() -> None:
        holder["run"] = service.exec_command(
            session_id=session.session_id,
            sandbox_workspace_id=workspace.sandbox_workspace_id,
            agent_id=agent.agent_id,
            argv=["python", "src/s12_hpc.py"],
            timeout_seconds=10,
        )

    thread = threading.Thread(target=_run)
    thread.start()
    pending = _wait_for_pending_approval(repositories, session.session_id)
    operation = _wait_for_operation_with_approval(
        repositories,
        str(pending.request_ref),
        pending.approval_id,
    )
    approval_envelope = operation.adapter_approval_envelope or {}
    assert approval_envelope["placement"] == "hpc"
    assert approval_envelope["hpc_workspace_id"] == "hpcws_s12"
    assert approval_envelope["stage_refs"] == [
        {
            "kind": "hpc_stage_ref",
            "stage_ref_id": "stage_input_001",
            "hpc_workspace_id": "hpcws_s12",
            "artifact_id": "artifact_input_fasta",
            "artifact_digest": "sha256:input-fasta",
            "workspace_relative_path": "inputs/query.fasta",
        }
    ]
    assert approval_envelope["planned_fetch_intent"] == {
        "declared_outputs": [{"path": "outputs/alignment.fasta", "format": "fasta"}]
    }
    assert "fetch_refs" not in approval_envelope
    assert "remote_path" not in json.dumps(approval_envelope, sort_keys=True)

    _resolve_s10_approval(repositories, pending.approval_id, decision="approved")
    thread.join(timeout=5)

    assert not thread.is_alive()
    run = holder["run"]
    assert isinstance(run, SandboxRunRecord)
    assert run.status is SandboxRunStatus.COMPLETED
    payload = json.loads(str(run.stdout_summary))
    assert payload["errors"] == {
        "bad_stage_path": "hpc_stage_path_invalid",
        "missing_placement": "hpc_workspace_forbidden",
    }
    result_envelope = payload["result"]["adapter_result_envelope"]
    assert result_envelope["backend_run_id"] == "slurm_123"
    assert result_envelope["registered_artifact_ids"] == ["artifact_alignment"]
    assert result_envelope["bounded_summary"] == {"outputs": 1}
    assert "remote_path" not in json.dumps(result_envelope, sort_keys=True)
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert len(operations) == 1
    assert operations[0].operation_id == operation.operation_id


def test_sandbox_exec_s12_result_fields_do_not_affect_digest_but_prerun_fields_do(
    tmp_path: Path,
) -> None:
    repositories = _build_repositories()
    session, agent, workspace, workspace_root = _seed_workspace(repositories, tmp_path)
    service = _service(repositories, workspace_root=workspace_root, log_root=tmp_path / "logs")
    service.write_file(
        session_id=session.session_id,
        sandbox_workspace_id=workspace.sandbox_workspace_id,
        actor_ref=agent.agent_id,
        path="/workspace/src/s12_drift.py",
        content=(
            "import json\n"
            "from openzyme_pipeline.client import PipelineSdkError, call\n"
            "base = {\n"
            "    'schema_version': 's12.adapter_envelope.v1',\n"
            "    'route_policy_id': 'bio.uniprot_fetch.provider:v1',\n"
            "    'sdk_module': 'bio',\n"
            "    'function_name': 'uniprot_fetch',\n"
            "    'idempotency_key': 's12_digest_scope',\n"
            "    'params_digest': 'sha256:params-a',\n"
            "    'input_artifact_ids': ['artifact_query'],\n"
            "    'input_artifact_digests': ['sha256:query'],\n"
            "    'expected_outputs': {'kind': 'fasta'},\n"
            "    'resource_estimate': {'requests': 1},\n"
            "}\n"
            "first = call('s10.controlled_operation', dict(\n"
            "    base,\n"
            "    adapter_result={\n"
            "        'status': 'completed',\n"
            "        'provider_request_id': 'provider_req_first',\n"
            "        'bounded_summary': {'records': 1},\n"
            "    },\n"
            "))\n"
            "second = call('s10.controlled_operation', dict(\n"
            "    base,\n"
            "    adapter_result={\n"
            "        'status': 'completed',\n"
            "        'provider_request_id': 'provider_req_second',\n"
            "        'bounded_summary': {'records': 99},\n"
            "    },\n"
            "))\n"
            "try:\n"
            "    call('s10.controlled_operation', dict(base, params_digest='sha256:params-b'))\n"
            "except PipelineSdkError as exc:\n"
            "    drift_error = exc.error_code\n"
            "else:\n"
            "    raise SystemExit('expected S12 digest drift')\n"
            "print(json.dumps({\n"
            "    'drift_error': drift_error,\n"
            "    'first_operation': first['operation_id'],\n"
            "    'second_operation': second['operation_id'],\n"
            "    'second_provider_request_id': second['adapter_result_envelope']['provider_request_id'],\n"
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
            argv=["python", "src/s12_drift.py"],
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
    assert payload["drift_error"] == "operation_drift_detected"
    assert payload["first_operation"] == payload["second_operation"]
    assert payload["second_provider_request_id"] == "provider_req_first"
    operations = repositories.controlled_operations.list_by_run(run.sandbox_run_id)
    assert len(operations) == 1
    assert operations[0].adapter_result_envelope is not None
    assert operations[0].adapter_result_envelope["provider_request_id"] == "provider_req_first"


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

    def fake_active_timeout(
        self: SandboxRuntimeService,
        command: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout_seconds: int,
        sandbox_run_id: str,
    ) -> subprocess.CompletedProcess[str]:
        del self, cwd, env, timeout_seconds, sandbox_run_id
        captured["command"] = command
        return subprocess.CompletedProcess(command, 0, stdout="ok\n", stderr="")

    monkeypatch.setattr(SandboxRuntimeService, "_run_process_with_active_timeout", fake_active_timeout)

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
    assert any(item.endswith(":/openzyme/sdk:ro,Z") for item in command)
    assert "PYTHONPATH=/openzyme/sdk" in command
    assert "/openzyme/control.sock" in " ".join(command)
    assert command[-3:] == [workspace.image_ref, "python", "src/podman.py"]
