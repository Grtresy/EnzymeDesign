from __future__ import annotations

from dataclasses import replace
import json

from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRecord
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
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import SandboxImageCompatibility
from openzyme_domain import SandboxRunRecord
from openzyme_domain import SandboxRunStatus
from openzyme_domain import SandboxWorkspaceRecord
from openzyme_domain import SandboxWorkspaceStatus
from openzyme_domain import Session
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionStatus
from openzyme_domain import SourceRefKind
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


def _inspect_capabilities(
    repositories: CoreRepositories,
    *,
    session: Session,
    agent: AgentMember,
    task_id: str = "task_world",
    limit: int = 20,
) -> tuple[str, dict[str, object]]:
    registry = ToolRegistry()
    register_world_inspection_tools(registry)
    context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id=task_id),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )
    result = registry.dispatch(
        context,
        ToolInvocation(
            call_id="call_bounded_capabilities",
            tool_name="world.inspect",
            arguments={
                "sections": ["capabilities"],
                "task_id": task_id,
                "limit": limit,
            },
            task_id=task_id,
        ),
    )

    assert result.ok is True
    return result.content, json.loads(result.content)


def _max_length_opaque_ref(prefix: str, index: int, item_index: int) -> str:
    stem = f"{prefix}_{index:02d}_{item_index:02d}_"
    return stem + ("x" * (128 - len(stem)))


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
    assert payload["scientific_attempts"]["schema_id"] == (
        "scientific_attempt_readiness_summary@1"
    )
    assert payload["scientific_attempts"]["attempts"] == []
    assert "occurrences" not in json.dumps(payload["scientific_attempts"])
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


def test_capability_facts_are_filtered_bounded_and_do_not_inline_payloads() -> None:
    repositories = _build_repositories()
    session, agent = _seed_world(repositories)
    raw_marker = "RAW_CAPABILITY_PAYLOAD_MUST_NOT_LEAK"
    invocation_id = "inv_sandbox_adapter_op_world"
    document_id = "eng_world_large_output"
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id=document_id,
            session_id=session.session_id,
            invocation_id=invocation_id,
            document_kind="deep_research_dossier",
            payload={"raw": raw_marker * 30_000},
            created_at="2026-07-05T10:09:10+00:00",
            updated_at="2026-07-05T10:09:10+00:00",
        )
    )
    invocation = repositories.invocations.get(invocation_id)
    assert invocation is not None
    repositories.invocations.save(replace(invocation, output_ref=document_id))
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="art_world_large_output",
            session_id=session.session_id,
            task_id="task_world",
            lane_id=None,
            invocation_id=invocation_id,
            run_id=None,
            kind=ArtifactKind.RESULT,
            storage_uri="/tmp/private/large-output.json",
            relative_path="results/large-output.json",
            created_at="2026-07-05T10:09:11+00:00",
            metadata={"raw": raw_marker * 2_000},
        )
    )
    repositories.research_summaries.save(
        ResearchSummary(
            summary_id="summary_world",
            session_id=session.session_id,
            task_id="task_world",
            lane_id=None,
            invocation_id=invocation_id,
            status=ResearchSummaryStatus.COMPLETED,
            completion_reason="research_completed",
            research_brief="Inspect bounded capability facts.",
            summary=raw_marker * 1_000,
            created_at="2026-07-05T10:09:12+00:00",
            updated_at="2026-07-05T10:09:12+00:00",
        )
    )
    repositories.research_evidence.save(
        ResearchEvidence(
            evidence_id="evidence_world",
            session_id=session.session_id,
            task_id="task_world",
            lane_id=None,
            invocation_id=invocation_id,
            summary_id="summary_world",
            summary=raw_marker * 1_000,
            query=raw_marker,
            created_at="2026-07-05T10:09:13+00:00",
        )
    )
    repositories.research_source_refs.save(
        ResearchSourceRef(
            source_ref_id="source_world",
            session_id=session.session_id,
            task_id="task_world",
            lane_id=None,
            invocation_id=invocation_id,
            evidence_id="evidence_world",
            title=raw_marker,
            locator="https://example.org/raw",
            kind=SourceRefKind.WEB_PAGE,
            created_at="2026-07-05T10:09:14+00:00",
        )
    )
    repositories.research_gaps.save(
        ResearchGap(
            gap_id="gap_world",
            session_id=session.session_id,
            task_id="task_world",
            lane_id=None,
            invocation_id=invocation_id,
            summary_id="summary_world",
            summary=raw_marker * 1_000,
            created_at="2026-07-05T10:09:15+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_world_earlier",
            session_id=session.session_id,
            task_id="task_world",
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="world-earlier",
            started_at="2026-07-05T09:10:00+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_other",
            session_id=session.session_id,
            subject="Other task",
            description="Must be excluded by task filter.",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.NORMAL,
            kind="research",
            assigned_ref=None,
            created_at="2026-07-05T10:10:01+00:00",
            updated_at="2026-07-05T10:10:01+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_other_task",
            session_id=session.session_id,
            task_id="task_other",
            lane_id=None,
            engine_name="deep_research",
            status=EngineInvocationStatus.RUNNING,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="other-task",
            started_at="2026-07-05T10:10:02+00:00",
        )
    )

    result_content, payload = _inspect_capabilities(
        repositories,
        session=session,
        agent=agent,
        limit=1,
    )

    capability_items = [
        item for items in payload["capabilities"].values() for item in items
    ]
    assert len(capability_items) == 1
    item = capability_items[0]
    assert item["invocation_id"] == invocation_id
    assert item["task_id"] == "task_world"
    assert item["output_ref"] == document_id
    assert item["document_count"] == 1
    assert item["document_ids"] == [document_id]
    assert item["artifact_count"] == 1
    assert item["artifact_ids"] == ["art_world_large_output"]
    assert item["evidence_count"] == 1
    assert item["evidence_ids"] == ["evidence_world"]
    assert item["source_ref_count"] == 1
    assert item["source_ref_ids"] == ["source_world"]
    assert item["gap_count"] == 1
    assert item["gap_ids"] == ["gap_world"]
    assert payload["capability_facts_page"] == {
        "schema_version": "world.capability_facts.page.v1",
        "order": "started_at_desc_invocation_id_desc",
        "requested_limit": 1,
        "effective_invocation_limit": 1,
        "max_invocations": 20,
        "max_related_refs_per_kind": 8,
        "max_serialized_bytes": 65_536,
        "serialized_bytes": len(
            json.dumps(payload["capabilities"], sort_keys=True).encode("utf-8")
        ),
        "matching_invocation_count": 2,
        "returned_invocation_count": 1,
        "truncated": True,
    }
    assert "inv_world_earlier" not in result_content
    assert "inv_other_task" not in result_content
    assert raw_marker not in result_content
    assert len(result_content.encode("utf-8")) < 4_096
    forbidden_inline_fields = {
        "documents",
        "output_document",
        "output_payload",
        "evidence",
        "source_refs",
        "gaps",
    }
    assert forbidden_inline_fields.isdisjoint(item)


def test_capability_facts_reject_locator_and_credential_shaped_refs() -> None:
    repositories = _build_repositories()
    session, agent = _seed_world(repositories)
    invocation_id = "inv_sandbox_adapter_op_world"
    invocation = repositories.invocations.get(invocation_id)
    assert invocation is not None
    repositories.invocations.save(
        replace(
            invocation,
            engine_name="ssh://operator:password@private.example",
            output_ref="https://user:password@private.example/output.json",
        )
    )
    document_ids = (
        "document_world_safe",
        "inv_world:evidence:0",
        "run_world:outputs/result.json",
        "research:uniprot:P12345",
        "pipeline:0:provider_parsed/proteins.fasta",
        "https://private.example/document",
        "s3://private-bucket/document",
        "user:password@private.example",
        "private.example/path/to/document",
        "private.example",
        "private.example:22/output",
        "private-host:22/output",
        "cluster:home/operator/output",
        "credential_artifact:home/operator/key",
        "document_秘密",
        "ghp_abcdefghijklmnopqrstuvwxyz",
        "sk-proj-abcdefghijklmnopqrstuvwxyz",
        "plain_text_without_owned_prefix",
        "output_secret.txt",
    )
    for index, document_id in enumerate(document_ids):
        repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=document_id,
                session_id=session.session_id,
                invocation_id=invocation_id,
                document_kind="private_test_payload",
                payload={"must_not_inline": f"private-{index}"},
                created_at=f"2026-07-05T10:11:{index:02d}+00:00",
                updated_at=f"2026-07-05T10:11:{index:02d}+00:00",
            )
        )

    result_content, payload = _inspect_capabilities(
        repositories,
        session=session,
        agent=agent,
        limit=1,
    )

    assert set(payload["capabilities"]) == {"unknown"}
    item = payload["capabilities"]["unknown"][0]
    assert item["invocation_id"] == invocation_id
    assert item["engine_name"] == "unknown"
    assert item["output_ref"] is None
    assert item["document_count"] == len(document_ids)
    assert item["document_ids"] == [
        "document_world_safe",
        "inv_world:evidence:0",
        "run_world:outputs/result.json",
        "research:uniprot:P12345",
        "pipeline:0:provider_parsed/proteins.fasta",
    ]
    assert "://" not in result_content
    assert "@" not in result_content
    assert "private.example" not in result_content
    assert "cluster:home" not in result_content
    assert "credential_artifact" not in result_content
    assert "\\u79d8" not in result_content
    assert "ghp_" not in result_content
    assert "sk-proj" not in result_content
    assert "plain_text_without_owned_prefix" not in result_content
    assert "output_secret" not in result_content
    assert "password" not in result_content


def test_capability_facts_bind_teammate_to_current_task_and_keep_master_session_scope() -> None:
    repositories = _build_repositories()
    session, agent = _seed_world(repositories)
    repositories.tasks.save(
        Task(
            task_id="task_other",
            session_id=session.session_id,
            subject="Other task",
            description="Must not enter a teammate current-task inspection.",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.NORMAL,
            kind="research",
            assigned_ref=None,
            created_at="2026-07-05T10:30:00+00:00",
            updated_at="2026-07-05T10:30:00+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_other_task_newest",
            session_id=session.session_id,
            task_id="task_other",
            lane_id=None,
            engine_name="deep_research",
            status=EngineInvocationStatus.RUNNING,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="other-task-newest",
            started_at="2026-07-05T10:31:00+00:00",
        )
    )
    registry = ToolRegistry()
    register_world_inspection_tools(registry)
    teammate_context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id="task_world"),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )

    teammate_result = registry.dispatch(
        teammate_context,
        ToolInvocation(
            call_id="call_teammate_current_task",
            tool_name="world.inspect",
            arguments={"sections": ["capabilities"], "limit": 100},
            task_id="task_world",
        ),
    )
    assert teammate_result.ok is True
    teammate_payload = json.loads(teammate_result.content)
    assert teammate_payload["filters"]["task_id"] == "task_world"
    assert "inv_sandbox_adapter_op_world" in teammate_result.content
    assert "inv_other_task_newest" not in teammate_result.content

    canonical_product_task_id = (
        "aox_execution_cutover_daf581ffa2b34590940f55322e6bb5ec"
    )
    repositories.tasks.save(
        Task(
            task_id=canonical_product_task_id,
            session_id=session.session_id,
            subject="Canonical product task",
            description="A safe product-owned task id need not use the task_ prefix.",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.NORMAL,
            kind="execution",
            assigned_ref=agent.agent_id,
            created_at="2026-07-05T10:32:00+00:00",
            updated_at="2026-07-05T10:32:00+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_aox_product_task",
            session_id=session.session_id,
            task_id=canonical_product_task_id,
            lane_id=None,
            engine_name="execution",
            status=EngineInvocationStatus.RUNNING,
            input_ref=None,
            output_ref=None,
            approval_id=None,
            idempotency_key="aox-product-task",
            started_at="2026-07-05T10:32:01+00:00",
        )
    )
    product_task_context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(task_id=canonical_product_task_id),
        agent_id=agent.agent_id,
        actor_kind="teammate",
        actor_role="executor",
    )
    product_task_result = registry.dispatch(
        product_task_context,
        ToolInvocation(
            call_id="call_teammate_product_task",
            tool_name="world.inspect",
            arguments={
                "sections": ["tasks", "capabilities"],
                "task_id": canonical_product_task_id,
            },
            task_id=canonical_product_task_id,
        ),
    )
    assert product_task_result.ok is True
    assert json.loads(product_task_result.content)["filters"]["task_id"] == (
        canonical_product_task_id
    )
    product_payload = json.loads(product_task_result.content)
    assert product_payload["capabilities"]["execution"][0]["task_id"] == (
        canonical_product_task_id
    )

    product_mismatch_result = registry.dispatch(
        product_task_context,
        ToolInvocation(
            call_id="call_teammate_product_task_mismatch",
            tool_name="world.inspect",
            arguments={"sections": ["tasks"], "task_id": "task_other"},
            task_id=canonical_product_task_id,
        ),
    )
    assert product_mismatch_result.ok is False
    assert (
        product_mismatch_result.error_code
        == "world_inspection_task_scope_mismatch"
    )
    assert "task_other" not in product_mismatch_result.content
    assert json.loads(product_mismatch_result.content)["canonical_task_id"] == (
        canonical_product_task_id
    )

    mismatch_result = registry.dispatch(
        teammate_context,
        ToolInvocation(
            call_id="call_teammate_other_task",
            tool_name="world.inspect",
            arguments={
                "sections": ["capabilities"],
                "task_id": "task_other",
            },
            task_id="task_world",
        ),
    )
    assert mismatch_result.ok is False
    assert mismatch_result.error_code == "world_inspection_task_scope_mismatch"
    assert "task_other" not in mismatch_result.content
    assert json.loads(mismatch_result.content)["canonical_task_id"] == "task_world"

    master_context = SessionRuntimeContext(
        repositories=repositories,
        event_sink=MemoryEventBus(),
        snapshot=SessionRuntimeSnapshot.load(repositories, session.session_id),
        tool_registry=registry,
        restore_focus=RestoreFocus(),
        agent_id="agent:master",
        actor_kind="master",
        actor_role="master",
    )
    master_result = registry.dispatch(
        master_context,
        ToolInvocation(
            call_id="call_master_session_scope",
            tool_name="world.inspect",
            arguments={"sections": ["capabilities"], "limit": 100},
        ),
    )
    assert master_result.ok is True

    master_product_task_result = registry.dispatch(
        master_context,
        ToolInvocation(
            call_id="call_master_product_task",
            tool_name="world.inspect",
            arguments={
                "sections": ["tasks"],
                "task_id": canonical_product_task_id,
            },
        ),
    )
    assert master_product_task_result.ok is True
    assert json.loads(master_product_task_result.content)["filters"]["task_id"] == (
        canonical_product_task_id
    )

    foreign_session = Session(
        session_id="sess_foreign",
        project_id="proj_foreign",
        title="Foreign world",
        objective="Must stay outside the current session projection.",
        status=SessionStatus.ACTIVE,
        created_at="2026-07-05T10:40:00+00:00",
        updated_at="2026-07-05T10:40:00+00:00",
    )
    repositories.sessions.save(foreign_session)
    repositories.tasks.save(
        Task(
            task_id="aox_foreign_product_task",
            session_id=foreign_session.session_id,
            subject="Foreign private subject",
            description="Foreign private description",
            status=TaskStatus.IN_PROGRESS,
            priority=TaskPriority.NORMAL,
            kind="execution",
            assigned_ref=None,
            created_at="2026-07-05T10:40:01+00:00",
            updated_at="2026-07-05T10:40:01+00:00",
        )
    )
    foreign_task_result = registry.dispatch(
        master_context,
        ToolInvocation(
            call_id="call_master_foreign_task",
            tool_name="world.inspect",
            arguments={
                "sections": ["tasks"],
                "task_id": "aox_foreign_product_task",
            },
        ),
    )
    assert foreign_task_result.ok is True
    foreign_payload = json.loads(foreign_task_result.content)
    assert foreign_payload["tasks"]["assigned_task"] is None
    assert foreign_session.session_id not in foreign_task_result.content
    assert "Foreign private subject" not in foreign_task_result.content
    assert "Foreign private description" not in foreign_task_result.content
    assert "inv_sandbox_adapter_op_world" in master_result.content
    assert "inv_other_task_newest" in master_result.content


def test_capability_facts_enforce_invocation_ref_and_serialized_byte_budgets() -> None:
    repositories = _build_repositories()
    session, agent = _seed_world(repositories)
    invocation_ids: list[str] = []
    for invocation_index in range(24):
        invocation_id = f"inv_scale_{invocation_index:02d}"
        invocation_ids.append(invocation_id)
        repositories.invocations.save(
            EngineInvocation(
                invocation_id=invocation_id,
                session_id=session.session_id,
                task_id="task_world",
                lane_id=None,
                engine_name="execution",
                status=EngineInvocationStatus.RUNNING,
                input_ref=None,
                output_ref=_max_length_opaque_ref(
                    "output", invocation_index, 0
                ),
                approval_id=None,
                idempotency_key=f"scale-{invocation_index:02d}",
                started_at="2026-07-05T10:20:00+00:00",
            )
        )

    initial_content, initial_payload = _inspect_capabilities(
        repositories,
        session=session,
        agent=agent,
        limit=100,
    )
    initial_items = [
        item
        for items in initial_payload["capabilities"].values()
        for item in items
    ]
    initial_page = initial_payload["capability_facts_page"]
    assert len(initial_items) == 20
    assert initial_page["matching_invocation_count"] == 25
    assert initial_page["effective_invocation_limit"] == 20
    assert initial_page["returned_invocation_count"] == 20
    assert initial_page["truncated"] is True
    assert initial_items[0]["invocation_id"] == "inv_scale_23"
    assert "inv_scale_03" not in initial_content

    for invocation_index, invocation_id in enumerate(invocation_ids):
        summary_id = f"summary_scale_{invocation_index:02d}"
        repositories.research_summaries.save(
            ResearchSummary(
                summary_id=summary_id,
                session_id=session.session_id,
                task_id="task_world",
                lane_id=None,
                invocation_id=invocation_id,
                status=ResearchSummaryStatus.COMPLETED,
                completion_reason="research_completed",
                research_brief="Exercise bounded capability facts.",
                summary="Host-private body must not enter the facts index.",
                created_at="2026-07-05T10:21:00+00:00",
                updated_at="2026-07-05T10:21:00+00:00",
            )
        )
        for item_index in range(10):
            document_id = _max_length_opaque_ref(
                "document", invocation_index, item_index
            )
            artifact_id = _max_length_opaque_ref(
                "artifact", invocation_index, item_index
            )
            evidence_id = _max_length_opaque_ref(
                "evidence", invocation_index, item_index
            )
            source_ref_id = _max_length_opaque_ref(
                "source", invocation_index, item_index
            )
            gap_id = _max_length_opaque_ref("gap", invocation_index, item_index)
            repositories.engine_documents.save(
                EngineDocumentRecord(
                    document_id=document_id,
                    session_id=session.session_id,
                    invocation_id=invocation_id,
                    document_kind="large_private_payload",
                    payload={"raw": "not-public" * 100},
                    created_at="2026-07-05T10:22:00+00:00",
                    updated_at="2026-07-05T10:22:00+00:00",
                )
            )
            repositories.artifacts.save(
                SessionArtifactRecord(
                    artifact_id=artifact_id,
                    session_id=session.session_id,
                    task_id="task_world",
                    lane_id=None,
                    invocation_id=invocation_id,
                    run_id=None,
                    kind=ArtifactKind.RESULT,
                    storage_uri="/tmp/private/scale-result.json",
                    relative_path=(
                        f"results/{invocation_index:02d}-{item_index:02d}.json"
                    ),
                    created_at="2026-07-05T10:22:00+00:00",
                    metadata={"raw": "not-public" * 100},
                )
            )
            repositories.research_evidence.save(
                ResearchEvidence(
                    evidence_id=evidence_id,
                    session_id=session.session_id,
                    task_id="task_world",
                    lane_id=None,
                    invocation_id=invocation_id,
                    summary_id=summary_id,
                    summary="Private evidence body.",
                    query="Private query body.",
                    created_at="2026-07-05T10:22:00+00:00",
                )
            )
            repositories.research_source_refs.save(
                ResearchSourceRef(
                    source_ref_id=source_ref_id,
                    session_id=session.session_id,
                    task_id="task_world",
                    lane_id=None,
                    invocation_id=invocation_id,
                    evidence_id=evidence_id,
                    title="Private source body.",
                    locator="https://private.example/source",
                    kind=SourceRefKind.WEB_PAGE,
                    created_at="2026-07-05T10:22:00+00:00",
                )
            )
            repositories.research_gaps.save(
                ResearchGap(
                    gap_id=gap_id,
                    session_id=session.session_id,
                    task_id="task_world",
                    lane_id=None,
                    invocation_id=invocation_id,
                    summary_id=summary_id,
                    summary="Private gap body.",
                    created_at="2026-07-05T10:22:00+00:00",
                )
            )

    bounded_content, bounded_payload = _inspect_capabilities(
        repositories,
        session=session,
        agent=agent,
        limit=100,
    )
    bounded_items = [
        item
        for items in bounded_payload["capabilities"].values()
        for item in items
    ]
    bounded_page = bounded_payload["capability_facts_page"]
    assert 1 <= len(bounded_items) < 20
    assert bounded_page["max_related_refs_per_kind"] == 8
    assert bounded_page["max_serialized_bytes"] == 65_536
    assert bounded_page["serialized_bytes"] == len(
        json.dumps(bounded_payload["capabilities"], sort_keys=True).encode("utf-8")
    )
    assert bounded_page["serialized_bytes"] <= bounded_page["max_serialized_bytes"]
    assert bounded_page["returned_invocation_count"] == len(bounded_items)
    assert bounded_page["truncated"] is True
    assert len(bounded_content.encode("utf-8")) <= 68 * 1024
    for item in bounded_items:
        assert len(item["document_ids"]) <= 8
        assert len(item["artifact_ids"]) <= 8
        assert len(item["evidence_ids"]) <= 8
        assert len(item["source_ref_ids"]) <= 8
        assert len(item["gap_ids"]) <= 8
    assert "not-public" not in bounded_content
    assert "Private evidence body" not in bounded_content
