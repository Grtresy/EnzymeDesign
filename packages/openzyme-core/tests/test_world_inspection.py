from __future__ import annotations

from dataclasses import replace
import json

from openzyme_core import CoreRepositories
from openzyme_core import MemoryEventBus
from openzyme_core import RestoreFocus
from openzyme_core import SessionRuntimeContext
from openzyme_core import SessionRuntimeSnapshot
from openzyme_core import ToolInvocation
from openzyme_core import ToolRegistry
from openzyme_core import apply_sqlite_migrations
from openzyme_core import build_agent_step_context
from openzyme_core import builtin_tool_descriptors
from openzyme_core import connect_sqlite
from openzyme_core import register_task_board_tools
from openzyme_core import register_world_inspection_tools
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_world(repositories: CoreRepositories) -> tuple[Session, AgentMember]:
    session = Session(
        session_id="sess_world",
        project_id="proj_001",
        title="World inspection",
        objective="Expose facts without workflow recommendations.",
        status=SessionStatus.ACTIVE,
        created_at="2026-07-05T10:00:00+00:00",
        updated_at="2026-07-05T10:00:00+00:00",
    )
    repositories.sessions.save(session)
    task = Task(
        task_id="task_world",
        session_id=session.session_id,
        subject="Inspect current world",
        description="Read facts and decide independently.",
        status=TaskStatus.IN_PROGRESS,
        priority=TaskPriority.HIGH,
        kind="execution",
        assigned_ref="agent:executor:world",
        created_at="2026-07-05T10:01:00+00:00",
        updated_at="2026-07-05T10:01:00+00:00",
    )
    repositories.tasks.save(task)
    agent = AgentMember(
        agent_id="agent:executor:world",
        session_id=session.session_id,
        lane_id=None,
        task_id=task.task_id,
        name="Executor",
        role="executor",
        status=AgentMemberStatus.BLOCKED,
        parent_agent_id=None,
        created_at="2026-07-05T10:02:00+00:00",
        updated_at="2026-07-05T10:02:00+00:00",
        runtime_state="blocked",
        current_correlation_id="corr_world",
    )
    repositories.agents.save(agent)
    stored_agent = repositories.agents.get(session.session_id, agent.agent_id)
    assert stored_agent is not None
    approval = ApprovalRequest(
        approval_id="appr_world",
        session_id=session.session_id,
        task_id=task.task_id,
        lane_id=None,
        kind="sdk_controlled_operation",
        requested_action="Approve controlled operation.",
        status=ApprovalRequestStatus.PENDING,
        request_ref="op_world",
        resolution_ref=None,
        created_at="2026-07-05T10:03:00+00:00",
    )
    repositories.approvals.save(approval)
    repositories.runtime_signals.save(
        AgentRuntimeSignal(
            signal_id="sig_world",
            session_id=session.session_id,
            agent_id=stored_agent.agent_id,
            task_id=task.task_id,
            reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at="2026-07-05T10:04:00+00:00",
            source_ref=approval.approval_id,
        )
    )
    repositories.sandbox_workspaces.save(
        SandboxWorkspaceRecord(
            sandbox_workspace_id="sws_world",
            session_id=session.session_id,
            agent_member_id=str(stored_agent.member_id),
            agent_id=stored_agent.agent_id,
            status=SandboxWorkspaceStatus.READY,
            image_ref="openzyme/sandbox:test",
            image_digest="sha256:image",
            image_version="test",
            sandbox_protocol_version="s12",
            image_compatibility=SandboxImageCompatibility.COMPATIBLE,
            manifest_version="1",
            created_at="2026-07-05T10:05:00+00:00",
            last_attached_at="2026-07-05T10:05:00+00:00",
            focus_task_id=task.task_id,
        )
    )
    repositories.sandbox_runs.save(
        SandboxRunRecord(
            sandbox_run_id="srun_world",
            session_id=session.session_id,
            sandbox_workspace_id="sws_world",
            agent_id=stored_agent.agent_id,
            argv=("python", "src/run.py"),
            argv_digest="sha256:argv",
            cwd="/workspace",
            env_digest="sha256:env",
            status=SandboxRunStatus.RUNNING,
            created_at="2026-07-05T10:06:00+00:00",
            updated_at="2026-07-05T10:06:00+00:00",
            task_id=task.task_id,
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_sandbox_adapter_op_world",
            session_id=session.session_id,
            task_id=task.task_id,
            lane_id=None,
            engine_name="sandbox_adapter",
            status=EngineInvocationStatus.RUNNING,
            input_ref="eng_in_world",
            output_ref=None,
            approval_id=approval.approval_id,
            idempotency_key="sandbox-adapter:op_world",
            started_at="2026-07-05T10:07:00+00:00",
        )
    )
    repositories.controlled_operations.save(
        ControlledOperation(
            operation_id="op_world",
            session_id=session.session_id,
            sandbox_workspace_id="sws_world",
            sandbox_run_id="srun_world",
            logical_operation_key="structure_tools.fpocket:abc",
            operation_digest="sha256:op",
            params_digest="sha256:params",
            backend_category="hpc_runner",
            status=ControlledOperationStatus.WAITING_APPROVAL,
            created_at="2026-07-05T10:08:00+00:00",
            updated_at="2026-07-05T10:08:00+00:00",
            task_id=task.task_id,
            approval_id=approval.approval_id,
            approval_state=ApprovalRequestStatus.PENDING.value,
            route_policy_id="structure_tools.fpocket.hpc:v1",
            selected_backend="hpc",
            approval_requirement={"required": True},
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_world_structure",
            session_id=session.session_id,
            task_id=task.task_id,
            lane_id=None,
            invocation_id=None,
            run_id=None,
            kind=ArtifactKind.STRUCTURE,
            storage_uri="/tmp/private/structure.pdb",
            relative_path="structures/target.pdb",
            created_at="2026-07-05T10:09:00+00:00",
            title="target.pdb",
            metadata={
                "format": "pdb",
                "content_digest": "sha256:structure",
                "sealed_digest": "sha256:sealed",
                "provider": "rcsb_pdb",
                "external_id": "1ABC",
            },
        )
    )
    return session, stored_agent


def test_world_inspection_exposes_structured_facts_without_recommendations() -> None:
    repositories = _build_repositories()
    session, agent = _seed_world(repositories)
    registry = ToolRegistry()
    register_task_board_tools(registry)
    register_world_inspection_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_world"),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
        correlation_id="corr_world",
        signal_id="sig_world",
        wakeup_reason=AgentRuntimeSignalReason.APPROVAL_RESOLVED.value,
    )
    context.refresh_restore_context()
    router = registry.to_tool_router(context, descriptors=builtin_tool_descriptors())
    step_context = build_agent_step_context(context, call_index=1)
    context.current_tool_router = router
    context.current_step_context = build_agent_step_context(
        context,
        call_index=1,
        tool_specs=router.model_visible_specs(step_context),
    )

    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_world",
            tool_name="world.inspect",
            arguments={"task_id": "task_world", "limit": 10},
            task_id="task_world",
        ),
    )

    assert result.ok is True
    payload = json.loads(result.content)
    assert payload["schema_version"] == "world.inspection.v1"
    assert payload["mode"] == "facts_only"
    assert payload["strategy_policy"]["harness_recommends_actions"] is False
    assert "recommended_actions" not in json.dumps(payload)
    assert payload["tasks"]["assigned_task"]["task_id"] == "task_world"
    assert payload["artifacts"]["items"][0]["digest"] == "sha256:sealed"
    assert "storage_uri" not in json.dumps(payload["artifacts"])
    assert payload["approvals"]["pending"][0]["approval_id"] == "appr_world"
    assert payload["operations"]["items"][0]["operation_id"] == "op_world"
    assert payload["operations"]["items"][0]["engine_invocation_status"] == "running"
    assert payload["outcomes"][0]["outcome_status"] == "pending"
    assert payload["diagnostics"]["warning_count"] >= 0
    assert any(
        policy["route_policy_id"] == "structure_tools.fpocket.hpc:v1"
        and policy["approval_requirement"] == {"required": True}
        for policy in payload["affordances"]["route_policies"]
    )
    assert any(
        tool["tool_name"] == "world.inspect"
        for tool in payload["affordances"]["tool_surface"]["visible_tools"]
    )


def test_terminal_controlled_operation_syncs_engine_invocation_terminal() -> None:
    repositories = _build_repositories()
    session, _ = _seed_world(repositories)
    operation = repositories.controlled_operations.get("op_world")
    assert operation is not None
    assert (
        repositories.invocations.get("inv_sandbox_adapter_op_world").status
        is EngineInvocationStatus.RUNNING
    )

    repositories.controlled_operations.save(
        replace(
            operation,
            status=ControlledOperationStatus.COMPLETED,
            result_summary={"status": "completed"},
            updated_at="2026-07-05T10:10:00+00:00",
        )
    )

    invocation = repositories.invocations.get("inv_sandbox_adapter_op_world")
    assert invocation is not None
    assert invocation.session_id == session.session_id
    assert invocation.status is EngineInvocationStatus.SUCCEEDED
    assert invocation.finished_at is not None
