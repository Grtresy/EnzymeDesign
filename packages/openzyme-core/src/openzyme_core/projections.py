from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import AgentMember
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import MemoryKind

from .repositories import CoreRepositories
from .task_board import TaskBoardService
from .lane_manager import LaneManager
from .conversation import build_conversation_projection
from .protocols import ProtocolService


@dataclass(frozen=True, slots=True)
class ActivityFeedItem:
    event_type: str
    created_at: str
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "event_type": self.event_type,
            "created_at": self.created_at,
            "payload": self.payload,
        }


@dataclass(frozen=True, slots=True)
class DelegationProjectionItem:
    agent: AgentMember
    correlation_ids: tuple[str, ...]
    latest_correlation_id: str | None
    latest_message_type: str | None
    latest_message_at: str | None
    pending_correlation_ids: tuple[str, ...]
    thread_summaries: tuple[dict[str, Any], ...]
    unread_inbox_count: int
    pending_signal_count: int
    latest_signal_reason: str | None
    last_active_at: str | None
    idle_since: str | None
    wakeup_reason: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent.to_dict(),
            "correlation_ids": list(self.correlation_ids),
            "latest_correlation_id": self.latest_correlation_id,
            "latest_message_type": self.latest_message_type,
            "latest_message_at": self.latest_message_at,
            "pending_correlation_ids": list(self.pending_correlation_ids),
            "thread_summaries": list(self.thread_summaries),
            "last_active_at": self.last_active_at,
            "idle_since": self.idle_since,
        }


@dataclass(frozen=True, slots=True)
class DelegationProjection:
    session_id: str
    agents: tuple[DelegationProjectionItem, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "agents": [agent.to_dict() for agent in self.agents],
        }


@dataclass(frozen=True, slots=True)
class SessionWorkspaceProjection:
    session: dict[str, Any]
    conversation: tuple[dict[str, Any], ...]
    task_board: dict[str, Any]
    lane_board: dict[str, Any]
    pending_approvals: tuple[dict[str, Any], ...]
    inbox: tuple[dict[str, Any], ...]
    memory: tuple[dict[str, Any], ...]
    delegation: dict[str, Any]
    agent_traces: dict[str, list[dict[str, Any]]]
    activity_feed: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]
    report_drafts: tuple[dict[str, Any], ...]
    reports: tuple[dict[str, Any], ...]
    capabilities: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "conversation": list(self.conversation),
            "task_board": self.task_board,
            "lane_board": self.lane_board,
            "pending_approvals": list(self.pending_approvals),
            "inbox": list(self.inbox),
            "memory": list(self.memory),
            "delegation": self.delegation,
            "agent_traces": self.agent_traces,
            "activity_feed": list(self.activity_feed),
            "artifacts": list(self.artifacts),
            "report_drafts": list(self.report_drafts),
            "reports": list(self.reports),
            "capabilities": self.capabilities,
        }


@dataclass(slots=True)
class SessionProjectionBuilder:
    repositories: CoreRepositories

    def build_session_workspace(self, session_id: str) -> SessionWorkspaceProjection:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        task_board = TaskBoardService(self.repositories).build_projection(session_id).to_dict()
        lane_board = LaneManager(self.repositories).build_projection(session_id).to_dict()
        conversation = tuple(entry.to_dict() for entry in build_conversation_projection(self.repositories, session_id))
        approvals = tuple(approval.to_dict() for approval in self.repositories.approvals.list_pending_by_session(session_id))
        inbox = tuple(message.to_dict() for message in self.repositories.inbox.list_by_session(session_id))
        memory = tuple(entry.to_dict() for entry in self.repositories.memory.list_by_session(session_id))
        delegation = self.build_delegation_projection(session_id).to_dict()
        agent_traces = self.build_agent_traces_projection(session_id)
        activity_feed = tuple(item.to_dict() for item in self.build_activity_feed(session_id))
        artifacts = tuple(self._project_workspace_artifact(artifact) for artifact in self.repositories.artifacts.list_by_session(session_id))
        report_drafts = tuple(draft.to_dict() for draft in self.repositories.report_drafts.list_by_session(session_id))
        reports = tuple(report.to_dict() for report in self.repositories.reports.list_by_session(session_id))
        capabilities = self._build_capabilities_projection(session_id)
        return SessionWorkspaceProjection(
            session=session.to_dict(),
            conversation=conversation,
            task_board=task_board,
            lane_board=lane_board,
            pending_approvals=approvals,
            inbox=inbox,
            memory=memory,
            delegation=delegation,
            agent_traces=agent_traces,
            activity_feed=activity_feed,
            artifacts=artifacts,
            report_drafts=report_drafts,
            reports=reports,
            capabilities=capabilities,
        )

    def build_agent_traces_projection(
        self, session_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for document in self.repositories.engine_documents.list_by_session(session_id):
            if document.document_kind != "llm_trace_step":
                continue
            payload = dict(document.payload)
            payload.setdefault("trace_id", document.document_id)
            payload.setdefault("created_at", document.created_at)
            actor_ref = str(payload.get("actor_ref") or "harness")
            grouped.setdefault(actor_ref, []).append(payload)
        for entries in grouped.values():
            entries.sort(
                key=lambda item: (
                    str(item.get("created_at") or ""),
                    int(item.get("call_index") or 0),
                    str(item.get("trace_id") or ""),
                )
            )
        return dict(sorted(grouped.items(), key=lambda item: item[0]))

    def build_delegation_projection(self, session_id: str) -> DelegationProjection:
        messages = self.repositories.inbox.list_by_session(session_id)
        signals = self.repositories.runtime_signals.list_by_session(session_id)
        protocol = ProtocolService(self.repositories)
        items: list[DelegationProjectionItem] = []
        for agent in self.repositories.agents.list_by_session(session_id):
            agent_messages = [
                message
                for message in messages
                if message.sender == agent.agent_id or message.recipient == agent.agent_id
            ]
            correlation_ids = tuple(
                dict.fromkeys(
                    message.correlation_id
                    for message in agent_messages
                    if message.correlation_id is not None
                )
            )
            pending: list[str] = []
            thread_summaries: list[dict[str, Any]] = []
            for correlation_id in correlation_ids:
                thread = protocol.build_thread(session_id, correlation_id)
                thread_summaries.append(
                    {
                        "correlation_id": correlation_id,
                        "status": thread.status.value,
                        "request_message_type": None if thread.request is None else thread.request.message_type,
                        "response_count": len(thread.responses),
                        "latest_message_type": None if not thread.responses else thread.responses[-1].message_type,
                    }
                )
                if thread.status.value == "waiting":
                    pending.append(correlation_id)
            latest_message = None if not agent_messages else agent_messages[-1]
            agent_signals = [signal for signal in signals if signal.agent_id == agent.agent_id]
            pending_signals = [signal for signal in agent_signals if signal.status is AgentRuntimeSignalStatus.PENDING]
            latest_signal = None if not agent_signals else agent_signals[-1]
            items.append(
                DelegationProjectionItem(
                    agent=agent,
                    correlation_ids=correlation_ids,
                    latest_correlation_id=None if latest_message is None else latest_message.correlation_id,
                    latest_message_type=None if latest_message is None else latest_message.message_type,
                    latest_message_at=None if latest_message is None else latest_message.created_at,
                    pending_correlation_ids=tuple(pending),
                    thread_summaries=tuple(thread_summaries),
                    unread_inbox_count=len(self.repositories.inbox.list_unread_for_recipient(session_id, agent.agent_id)),
                    pending_signal_count=len(pending_signals),
                    latest_signal_reason=None if latest_signal is None else latest_signal.reason.value,
                    last_active_at=agent.last_active_at,
                    idle_since=agent.idle_since,
                    wakeup_reason=agent.wakeup_reason,
                )
            )
        return DelegationProjection(session_id=session_id, agents=tuple(items))

    def build_activity_feed(self, session_id: str) -> list[ActivityFeedItem]:
        items: list[ActivityFeedItem] = []
        for event in self.repositories.lane_events.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type=event.event_type,
                    created_at=event.created_at,
                    payload=event.to_dict(),
                )
            )
        for approval in self.repositories.approvals.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="approval.requested",
                    created_at=approval.created_at,
                    payload=approval.to_dict(),
                )
            )
            if approval.status is not ApprovalRequestStatus.PENDING and approval.resolved_at is not None:
                items.append(
                    ActivityFeedItem(
                        event_type="approval.resolved",
                        created_at=approval.resolved_at,
                        payload=approval.to_dict(),
                    )
                )
        for message in self.repositories.inbox.list_by_session(session_id):
            event_type = "agent.message.delivered" if (
                message.sender_kind is InboxParticipantKind.AGENT or message.recipient_kind is InboxParticipantKind.AGENT
            ) else "inbox.delivered"
            if message.message_type == "background_completion":
                event_type = "background.completed"
            elif message.message_type == "delegation_request" and message.recipient_kind is InboxParticipantKind.AGENT:
                event_type = "agent.delegated"
            items.append(
                ActivityFeedItem(
                    event_type=event_type,
                    created_at=message.created_at,
                    payload=message.to_dict(),
                )
            )
        for entry in self.repositories.memory.list_by_session(session_id):
            if entry.kind is MemoryKind.COMPACTION:
                items.append(
                    ActivityFeedItem(
                        event_type="memory.compacted",
                        created_at=entry.created_at,
                        payload=entry.to_dict(),
                    )
                )
        for agent in self.repositories.agents.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="agent.spawned",
                    created_at=agent.created_at,
                    payload=agent.to_dict(),
                )
            )
            if agent.updated_at != agent.created_at:
                items.append(
                    ActivityFeedItem(
                        event_type="agent.status_updated",
                        created_at=agent.updated_at,
                        payload=agent.to_dict(),
                    )
                )
        for signal in self.repositories.runtime_signals.list_by_session(session_id):
            if signal.status is AgentRuntimeSignalStatus.PENDING:
                event_type = "agent.inbox_unread" if signal.reason.value == "inbox_unread" else "agent.wakeup_pending"
            elif signal.status is AgentRuntimeSignalStatus.CLAIMED:
                event_type = "agent.woken"
            elif signal.reason.value == "task_available" and signal.status is AgentRuntimeSignalStatus.COMPLETED:
                event_type = "agent.task_claimed"
            else:
                event_type = "agent.runtime_signal.updated"
            items.append(
                ActivityFeedItem(
                    event_type=event_type,
                    created_at=signal.completed_at or signal.claimed_at or signal.created_at,
                    payload=signal.to_dict(),
                )
            )
        for invocation in self.repositories.invocations.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="engine.invocation.started",
                    created_at=invocation.started_at,
                    payload=invocation.to_dict(),
                )
            )
            if invocation.finished_at is not None or invocation.status in {
                EngineInvocationStatus.SUCCEEDED,
                EngineInvocationStatus.FAILED,
                EngineInvocationStatus.CANCELLED,
            }:
                items.append(
                    ActivityFeedItem(
                        event_type="engine.invocation.completed",
                        created_at=invocation.finished_at or invocation.started_at,
                        payload=invocation.to_dict(),
                    )
                )
            else:
                items.append(
                    ActivityFeedItem(
                        event_type="engine.invocation.updated",
                        created_at=invocation.started_at,
                        payload=invocation.to_dict(),
                    )
                )
        for summary in self.repositories.research_summaries.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="research.summary.updated",
                    created_at=summary.updated_at,
                    payload=summary.to_dict(),
                )
            )
        for evidence in self.repositories.research_evidence.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="research.evidence.recorded",
                    created_at=evidence.created_at,
                    payload=evidence.to_dict(),
                )
            )
        for artifact in self.repositories.artifacts.list_by_session(session_id):
            artifact_payload = self._project_workspace_artifact(artifact)
            if artifact.metadata and artifact.metadata.get("source") == "preprocess":
                items.append(
                    ActivityFeedItem(
                        event_type="execution.preprocess.completed",
                        created_at=artifact.created_at,
                        payload=artifact_payload,
                    )
                )
            items.append(
                ActivityFeedItem(
                    event_type="artifact.recorded",
                    created_at=artifact.created_at,
                    payload=artifact_payload,
                )
            )
        for run in self.repositories.runs.list_by_session(session_id):
            artifacts = self.repositories.artifacts.list_by_run(run.run_id)
            if artifacts:
                items.append(
                    ActivityFeedItem(
                        event_type="execution.artifacts.fetched",
                        created_at=run.finished_at or run.updated_at,
                        payload=self._sanitize_execution_projection({
                            "run": run.to_dict(),
                            "artifact_ids": [artifact.artifact_id for artifact in artifacts],
                        }),
                    )
                )
        for draft in self.repositories.report_drafts.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="report_draft.updated",
                    created_at=draft.updated_at,
                    payload=draft.to_dict(),
                )
            )
        for report in self.repositories.reports.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="report.generated" if report.status.is_terminal else "report.updated",
                    created_at=report.updated_at,
                    payload=report.to_dict(),
                )
            )
        return sorted(items, key=lambda item: (item.created_at, item.event_type))

    def _build_capabilities_projection(self, session_id: str) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for invocation in self.repositories.invocations.list_by_session(session_id):
            grouped.setdefault(self._capability_key_for_engine(invocation.engine_name), []).append(
                self._project_invocation(session_id, invocation)
            )
        return grouped

    def _project_invocation(self, session_id: str, invocation: Any) -> dict[str, Any]:
        projected = invocation.to_dict()
        documents = self.repositories.engine_documents.list_by_invocation(session_id, invocation.invocation_id)
        if documents:
            projected["documents"] = [
                self._sanitize_execution_projection(document.to_dict())
                if invocation.engine_name == "execution"
                else document.to_dict()
                for document in documents
            ]
            output_document = next(
                (document for document in reversed(documents) if document.document_id == invocation.output_ref),
                None,
            )
            if output_document is not None:
                output_dict = output_document.to_dict()
                projected["output_document"] = (
                    self._sanitize_execution_projection(output_dict)
                    if invocation.engine_name == "execution"
                    else output_dict
                )
                projected["output_payload"] = (
                    self._sanitize_execution_projection(output_document.payload)
                    if invocation.engine_name == "execution"
                    else output_document.payload
                )
        summary = self.repositories.research_summaries.get_by_invocation(session_id, invocation.invocation_id)
        if summary is not None:
            evidence = self.repositories.research_evidence.list_by_invocation(session_id, invocation.invocation_id)
            source_refs = self.repositories.research_source_refs.list_by_invocation(session_id, invocation.invocation_id)
            gaps = self.repositories.research_gaps.list_by_invocation(session_id, invocation.invocation_id)
            projected["canonical_summary"] = summary.to_dict()
            projected["evidence"] = [item.to_dict() for item in evidence]
            projected["source_refs"] = [item.to_dict() for item in source_refs]
            projected["gaps"] = [item.to_dict() for item in gaps]
        runs = self.repositories.runs.list_by_invocation(session_id, invocation.invocation_id)
        if runs:
            projected["runs"] = [run.to_dict() for run in runs]
            run = runs[-1]
            projected["run"] = run.to_dict()
            if invocation.engine_name != "execution":
                projected["remote_run_dir"] = run.remote_run_dir
            projected["terminal_summary"] = run.summary
            artifact_payloads: list[dict[str, Any]] = []
            for run in runs:
                for item in self.repositories.artifacts.list_by_run(run.run_id):
                    artifact_payload = item.to_dict()
                    if invocation.engine_name == "execution":
                        artifact_payload.pop("storage_uri", None)
                    artifact_payloads.append(artifact_payload)
            projected["artifacts"] = artifact_payloads
            projected["output_artifact_ids"] = [artifact["artifact_id"] for artifact in artifact_payloads]
        request_document = next(
            (document for document in documents if document.document_kind == "execution_input"),
            None,
        )
        request_runspec = {}
        if request_document is not None:
            request_runspec = dict((request_document.payload.get("request") or {}).get("runspec") or {})
        if request_runspec:
            metadata = dict(request_runspec.get("metadata") or {})
            projected["tool_contract"] = dict(metadata.get("tool_contract") or {})
            projected["input_artifact_ids"] = list(metadata.get("input_artifact_ids") or [])
            projected["preprocess_artifact_ids"] = list(metadata.get("preprocess_artifact_ids") or [])
            projected["pipeline_invocation_id"] = metadata.get("pipeline_invocation_id") or invocation.invocation_id
            projected["code_digest"] = metadata.get("code_digest")
            projected["sandbox_status"] = metadata.get("sandbox_status", "completed" if invocation.status.is_terminal else "running")
            projected["hpc_run_ids"] = [
                run["runner_run_id"]
                for run in projected.get("runs", [])
                if isinstance(run, dict) and run.get("runner_run_id")
            ]
        elif invocation.engine_name == "execution" and request_document is not None:
            pipeline = dict(request_document.payload.get("pipeline") or {})
            if pipeline:
                projected["pipeline_invocation_id"] = invocation.invocation_id
                projected["code_digest"] = pipeline.get("code_digest")
                projected["sandbox_status"] = "dry_run" if pipeline.get("dry_run") else "pending"
                projected["hpc_run_ids"] = []
                projected["input_artifact_ids"] = list((pipeline.get("inputs") or {}).get("artifact_ids") or [])
                projected["preprocess_artifact_ids"] = []
        report = self.repositories.reports.get_by_invocation(session_id, invocation.invocation_id)
        if report is not None:
            projected["report"] = report.to_dict()
        return projected

    def _sanitize_execution_projection(self, value: Any) -> Any:
        private_keys = {
            "pipeline_code",
            "storage_uri",
            "local_path",
            "source_storage_uri",
            "intermediate_storage_uri",
        }
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                if key in private_keys:
                    continue
                sanitized[key] = self._sanitize_execution_projection(item)
            return sanitized
        if isinstance(value, list):
            return [self._sanitize_execution_projection(item) for item in value]
        return value

    def _project_workspace_artifact(self, artifact: Any) -> dict[str, Any]:
        payload = artifact.to_dict()
        metadata = dict(payload.get("metadata") or {})
        if metadata.get("source") in {"execution_engine", "preprocess"} or metadata.get("pipeline_invocation_id"):
            return self._sanitize_execution_projection(payload)
        return payload

    def _capability_key_for_engine(self, engine_name: str) -> str:
        return {
            "deep_research": "deep_research",
            "execution": "execution",
        }.get(engine_name, engine_name)


__all__ = [
    "ActivityFeedItem",
    "DelegationProjection",
    "DelegationProjectionItem",
    "SessionProjectionBuilder",
    "SessionWorkspaceProjection",
]
