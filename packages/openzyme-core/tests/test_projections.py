from __future__ import annotations

from openzyme_domain import ApprovalRequest
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import AgentMember
from openzyme_domain import AgentMemberStatus
from openzyme_domain import EngineInvocation
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxMessage
from openzyme_domain import InboxParticipantKind
from openzyme_domain import InboxStatus
from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import ResearchEvidence
from openzyme_domain import ResearchGap
from openzyme_domain import ResearchSourceRef
from openzyme_domain import ResearchSummary
from openzyme_domain import ResearchSummaryStatus
from openzyme_domain import RunRecord
from openzyme_domain import RunStatus
from openzyme_domain import Session
from openzyme_domain import SessionReportDraftRecord
from openzyme_domain import SessionReportDraftStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import SessionReportRecord
from openzyme_domain import SessionReportStatus
from openzyme_domain import SessionStatus
from openzyme_domain import SourceRefKind
from openzyme_domain import ArtifactKind
from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_core import CoreRepositories
from openzyme_core import EngineDocumentRecord
from openzyme_core import ProtocolService
from openzyme_core import SessionProjectionBuilder
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_core import persist_conversation_message


def _build_repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def _seed_session(repositories: CoreRepositories) -> Session:
    session = Session(
        session_id="sess_001",
        project_id="proj_001",
        title="Workspace projection",
        objective="Assemble Session 06 read models",
        status=SessionStatus.ACTIVE,
        created_at="2026-04-17T13:00:00+00:00",
        updated_at="2026-04-17T13:00:00+00:00",
    )
    repositories.sessions.save(session)
    repositories.lanes.save(
        Lane(
            lane_id="lane_001",
            session_id=session.session_id,
            name="analysis",
            status=LaneStatus.CLAIMED,
            cwd="/tmp/analysis",
            branch_name="wt/analysis",
            claimed_ref="agent:planner",
            created_at="2026-04-17T13:00:01+00:00",
            updated_at="2026-04-17T13:00:01+00:00",
        )
    )
    repositories.tasks.save(
        Task(
            task_id="task_001",
            session_id=session.session_id,
            subject="Research target",
            description="Start analysis",
            status=TaskStatus.TODO,
            priority=TaskPriority.HIGH,
            kind="research",
            assigned_ref="agent:planner",
            created_at="2026-04-17T13:00:02+00:00",
            updated_at="2026-04-17T13:00:02+00:00",
            lane_id="lane_001",
        )
    )
    repositories.approvals.save(
        ApprovalRequest(
            approval_id="appr_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            kind="execution_launch",
            requested_action="Approve launch",
            status=ApprovalRequestStatus.PENDING,
            request_ref="artifact://approvals/appr_001.json",
            resolution_ref=None,
            created_at="2026-04-17T13:00:03+00:00",
        )
    )
    repositories.memory.save(
        MemoryEntry(
            memory_id="mem_001",
            session_id=session.session_id,
            scope_kind=MemoryScopeKind.SESSION,
            scope_ref=session.session_id,
            kind=MemoryKind.COMPACTION,
            summary="Compressed continuity",
            source_range="auto:harness_run",
            importance=8,
            created_at="2026-04-17T13:00:04+00:00",
        )
    )
    user_payload_ref = persist_conversation_message(
        repositories,
        session_id=session.session_id,
        message_id="msg_user_001",
        role="user",
        content="Start the research task.",
        created_at="2026-04-17T13:00:00+00:00",
    )
    assistant_payload_ref = persist_conversation_message(
        repositories,
        session_id=session.session_id,
        message_id="msg_assistant_001",
        role="assistant",
        content="I will create the research task and prepare the lane.",
        created_at="2026-04-17T13:00:01+00:00",
    )
    repositories.inbox.save(
        InboxMessage(
            message_id="msg_user_001",
            session_id=session.session_id,
            sender="user",
            sender_kind=InboxParticipantKind.USER,
            recipient="harness",
            recipient_kind=InboxParticipantKind.HARNESS,
            message_type="user_message",
            correlation_id=None,
            payload_ref=user_payload_ref,
            status=InboxStatus.DELIVERED,
            created_at="2026-04-17T13:00:00+00:00",
        )
    )
    repositories.inbox.save(
        InboxMessage(
            message_id="msg_assistant_001",
            session_id=session.session_id,
            sender="harness",
            sender_kind=InboxParticipantKind.HARNESS,
            recipient="user",
            recipient_kind=InboxParticipantKind.USER,
            message_type="assistant_message",
            correlation_id=None,
            payload_ref=assistant_payload_ref,
            status=InboxStatus.DELIVERED,
            created_at="2026-04-17T13:00:01+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="deep_research",
            status=EngineInvocationStatus.RUNNING,
            input_ref="artifact://engine/inv_001/input.json",
            output_ref=None,
            approval_id=None,
            idempotency_key="task_001:deep_research:1",
            started_at="2026-04-17T13:00:05+00:00",
        )
    )
    repositories.invocations.save(
        EngineInvocation(
            invocation_id="inv_exec_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            engine_name="execution",
            status=EngineInvocationStatus.SUCCEEDED,
            input_ref="artifact://engine/inv_exec_001/input.json",
            output_ref="eng_exec_out_001",
            approval_id="appr_001",
            idempotency_key="task_001:execution:1",
            started_at="2026-04-17T13:00:06+00:00",
            finished_at="2026-04-17T13:00:07+00:00",
        )
    )
    repositories.runs.save(
        RunRecord(
            run_id="run_exec_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_exec_001",
            approval_id="appr_001",
            engine_name="execution",
            runner_run_id="job_123",
            status=RunStatus.SUCCEEDED,
            execution_mode="sbatch",
            remote_run_dir="/remote/run_exec_001",
            summary="Execution completed successfully.",
            created_at="2026-04-17T13:00:06+00:00",
            updated_at="2026-04-17T13:00:07+00:00",
            finished_at="2026-04-17T13:00:07+00:00",
        )
    )
    repositories.artifacts.save(
        SessionArtifactRecord(
            artifact_id="run_exec_001:stdout.log",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_exec_001",
            run_id="run_exec_001",
            kind=ArtifactKind.LOG,
            storage_uri="/tmp/stdout.log",
            relative_path="stdout.log",
            title="stdout.log",
            description=None,
            metadata={"source": "execution_engine"},
            created_at="2026-04-17T13:00:07+00:00",
        )
    )
    repositories.reports.save(
        SessionReportRecord(
            report_id="report_inv_exec_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_exec_001",
            run_id="run_exec_001",
            artifact_id="run_exec_001:stdout.log",
            status=SessionReportStatus.READY,
            title="Execution report",
            summary="Report summary",
            stage_summary="Research summary: Normalized evidence dossier",
            created_at="2026-04-17T13:00:07+00:00",
            updated_at="2026-04-17T13:00:08+00:00",
        )
    )
    repositories.reports.save(
        SessionReportRecord(
            report_id="report_inv_report_001",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id=None,
            run_id=None,
            artifact_id=None,
            status=SessionReportStatus.READY,
            title="Workspace report",
            summary="Integrated workspace report",
            stage_summary="Research and execution summarized.",
            created_at="2026-04-17T13:00:09+00:00",
            updated_at="2026-04-17T13:00:10+00:00",
        )
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="eng_out_001",
            session_id=session.session_id,
            invocation_id="inv_001",
            document_kind="deep_research_dossier",
            payload={
                "status": "completed",
                "completion_reason": "research_completed",
                "research_brief": "Research target",
                "summary": "Normalized evidence dossier",
                "evidence_items": [],
                "source_refs": [],
                "unresolved_gaps": [],
                "raw_notes": [],
                "clarification_question": None,
                "recent_turns": [],
            },
            created_at="2026-04-17T13:00:05+00:00",
            updated_at="2026-04-17T13:00:05+00:00",
        )
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="eng_exec_out_001",
            session_id=session.session_id,
            invocation_id="inv_exec_001",
            document_kind="execution_result",
            payload={
                "run": {"run_id": "run_exec_001"},
                "parsed_result": {"result_summary": "Execution completed successfully.", "structured_findings": {}},
            },
            created_at="2026-04-17T13:00:07+00:00",
            updated_at="2026-04-17T13:00:07+00:00",
        )
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="draft_doc_001",
            session_id=session.session_id,
            invocation_id=None,
            document_kind="report_draft_content",
            payload={
                "markdown": "# Workspace report",
            },
            created_at="2026-04-17T13:00:08+00:00",
            updated_at="2026-04-17T13:00:08+00:00",
        )
    )
    repositories.engine_documents.save(
        EngineDocumentRecord(
            document_id="llmtrace_master_001",
            session_id=session.session_id,
            invocation_id=None,
            document_kind="llm_trace_step",
            payload={
                "trace_id": "llmtrace_master_001",
                "actor_ref": "harness",
                "actor_kind": "master",
                "display_name": "OpenZyme",
                "role": "master",
                "call_index": 1,
                "created_at": "2026-04-17T13:00:02+00:00",
                "response_text": "I will inspect the workspace.",
                "tool_calls": [
                    {
                        "call_id": "call_001",
                        "tool_name": "task.get",
                        "task_id": "task_001",
                        "lane_id": "lane_001",
                        "args_public": {"task_id": "task_001"},
                    }
                ],
            },
            created_at="2026-04-17T13:00:02+00:00",
            updated_at="2026-04-17T13:00:02+00:00",
        )
    )
    repositories.agents.save(
        AgentMember(
            agent_id="agent:reporter",
            session_id=session.session_id,
            lane_id="lane_001",
            task_id="task_001",
            name="Reporter",
            role="reporter",
            status=AgentMemberStatus.COMPLETED,
            parent_agent_id=None,
            created_at="2026-04-17T13:00:08+00:00",
            updated_at="2026-04-17T13:00:09+00:00",
        )
    )
    repositories.report_drafts.save(
        SessionReportDraftRecord(
            draft_id="draft_001",
            session_id=session.session_id,
            task_id="task_001",
            owner_agent_id="agent:reporter",
            status=SessionReportDraftStatus.PUBLISHED,
            title="Workspace report",
            summary="Integrated workspace report",
            content_ref="draft_doc_001",
            published_report_id="report_inv_report_001",
            created_at="2026-04-17T13:00:08+00:00",
            updated_at="2026-04-17T13:00:09+00:00",
        )
    )
    repositories.research_summaries.save(
        ResearchSummary(
            summary_id="inv_001:summary",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_001",
            status=ResearchSummaryStatus.COMPLETED,
            completion_reason="research_completed",
            research_brief="Research target",
            summary="Normalized evidence dossier",
            clarification_question=None,
            created_at="2026-04-17T13:00:05+00:00",
            updated_at="2026-04-17T13:00:05+00:00",
        )
    )
    repositories.research_evidence.save(
        ResearchEvidence(
            evidence_id="inv_001:evidence:1",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_001",
            summary_id="inv_001:summary",
            summary="Catalytic paper supports the brief",
            query="Research target",
            confidence_label="high",
            created_at="2026-04-17T13:00:05+00:00",
        )
    )
    repositories.research_source_refs.save(
        ResearchSourceRef(
            source_ref_id="inv_001:evidence:1:source:1",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_001",
            evidence_id="inv_001:evidence:1",
            title="Paper A",
            locator="https://example.org/paper-a",
            kind=SourceRefKind.PAPER,
            snippet="Key result",
            created_at="2026-04-17T13:00:05+00:00",
        )
    )
    repositories.research_gaps.save(
        ResearchGap(
            gap_id="inv_001:gap:1",
            session_id=session.session_id,
            task_id="task_001",
            lane_id="lane_001",
            invocation_id="inv_001",
            summary_id="inv_001:summary",
            summary="Need wet-lab validation",
            created_at="2026-04-17T13:00:05+00:00",
        )
    )
    invocation = repositories.invocations.get("inv_001")
    repositories.invocations.save(
        EngineInvocation(
            invocation_id=invocation.invocation_id,
            session_id=invocation.session_id,
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            engine_name=invocation.engine_name,
            status=invocation.status,
            input_ref=invocation.input_ref,
            output_ref="eng_out_001",
            approval_id=invocation.approval_id,
            idempotency_key=invocation.idempotency_key,
            started_at=invocation.started_at,
            finished_at=invocation.finished_at,
        )
    )
    service = ProtocolService(repositories)
    service.delegate(
        session_id=session.session_id,
        agent_id="agent:researcher",
        name="Researcher",
        role="delegate",
        payload_ref="artifact://delegations/deleg_001.json",
        task_id="task_001",
        correlation_id="corr_001",
    )
    return session


def test_session_projection_builder_assembles_workspace_sections() -> None:
    repositories = _build_repositories()
    session = _seed_session(repositories)

    workspace = SessionProjectionBuilder(repositories).build_session_workspace(session.session_id).to_dict()

    assert workspace["session"]["session_id"] == session.session_id
    assert [entry["role"] for entry in workspace["conversation"]] == ["user", "assistant"]
    assert workspace["conversation"][0]["content"] == "Start the research task."
    assert workspace["task_board"]["next_task_id"] == "task_001"
    assert workspace["lane_board"]["lanes"][0]["lane"]["lane_id"] == "lane_001"
    assert workspace["pending_approvals"][0]["approval_id"] == "appr_001"
    assert any(
        item["agent"]["agent_id"] == "agent:researcher"
        for item in workspace["delegation"]["agents"]
    )
    assert workspace["artifacts"][0]["artifact_id"] == "run_exec_001:stdout.log"
    assert {report["report_id"] for report in workspace["reports"]} == {
        "report_inv_exec_001",
        "report_inv_report_001",
    }
    assert workspace["report_drafts"][0]["draft_id"] == "draft_001"
    assert workspace["report_drafts"][0]["published_report_id"] == "report_inv_report_001"
    assert workspace["agent_traces"]["harness"][0]["response_text"] == "I will inspect the workspace."
    assert workspace["agent_traces"]["harness"][0]["tool_calls"][0]["tool_name"] == "task.get"
    assert "deep_research" in workspace["capabilities"]
    assert "execution" in workspace["capabilities"]
    assert "reporting" not in workspace["capabilities"]
    assert workspace["capabilities"]["deep_research"][0]["output_payload"]["summary"] == "Normalized evidence dossier"
    assert workspace["capabilities"]["deep_research"][0]["canonical_summary"]["summary"] == "Normalized evidence dossier"
    assert workspace["capabilities"]["deep_research"][0]["evidence"][0]["confidence_label"] == "high"
    assert workspace["capabilities"]["deep_research"][0]["source_refs"][0]["kind"] == "paper"
    assert workspace["capabilities"]["deep_research"][0]["gaps"][0]["summary"] == "Need wet-lab validation"
    assert workspace["capabilities"]["execution"][0]["runs"][0]["run_id"] == "run_exec_001"
    assert workspace["capabilities"]["execution"][0]["artifacts"][0]["artifact_id"] == "run_exec_001:stdout.log"
    assert workspace["capabilities"]["execution"][0]["report"]["report_id"] == "report_inv_exec_001"
    assert any(item["event_type"] == "approval.requested" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "agent.spawned" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "engine.invocation.started" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "research.summary.updated" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "artifact.recorded" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "report_draft.updated" for item in workspace["activity_feed"])
    assert any(item["event_type"] == "report.generated" for item in workspace["activity_feed"])
