from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import AgentMember
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import MemoryKind

from .repositories import CoreRepositories
from .task_board import TaskBoardService
from .lane_manager import LaneManager


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
    latest_message_type: str | None
    latest_message_at: str | None
    pending_correlation_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent.to_dict(),
            "correlation_ids": list(self.correlation_ids),
            "latest_message_type": self.latest_message_type,
            "latest_message_at": self.latest_message_at,
            "pending_correlation_ids": list(self.pending_correlation_ids),
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
    task_board: dict[str, Any]
    lane_board: dict[str, Any]
    pending_approvals: tuple[dict[str, Any], ...]
    inbox: tuple[dict[str, Any], ...]
    memory: tuple[dict[str, Any], ...]
    delegation: dict[str, Any]
    activity_feed: tuple[dict[str, Any], ...]
    artifacts: tuple[dict[str, Any], ...]
    reports: tuple[dict[str, Any], ...]
    capabilities: dict[str, list[dict[str, Any]]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session,
            "task_board": self.task_board,
            "lane_board": self.lane_board,
            "pending_approvals": list(self.pending_approvals),
            "inbox": list(self.inbox),
            "memory": list(self.memory),
            "delegation": self.delegation,
            "activity_feed": list(self.activity_feed),
            "artifacts": list(self.artifacts),
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
        approvals = tuple(approval.to_dict() for approval in self.repositories.approvals.list_pending_by_session(session_id))
        inbox = tuple(message.to_dict() for message in self.repositories.inbox.list_by_session(session_id))
        memory = tuple(entry.to_dict() for entry in self.repositories.memory.list_by_session(session_id))
        delegation = self.build_delegation_projection(session_id).to_dict()
        activity_feed = tuple(item.to_dict() for item in self.build_activity_feed(session_id))
        artifacts = tuple(artifact.to_dict() for artifact in self.repositories.artifacts.list_by_session(session_id))
        reports = tuple(report.to_dict() for report in self.repositories.reports.list_by_session(session_id))
        capabilities = self._build_capabilities_projection(session_id)
        return SessionWorkspaceProjection(
            session=session.to_dict(),
            task_board=task_board,
            lane_board=lane_board,
            pending_approvals=approvals,
            inbox=inbox,
            memory=memory,
            delegation=delegation,
            activity_feed=activity_feed,
            artifacts=artifacts,
            reports=reports,
            capabilities=capabilities,
        )

    def build_delegation_projection(self, session_id: str) -> DelegationProjection:
        messages = self.repositories.inbox.list_by_session(session_id)
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
            for correlation_id in correlation_ids:
                correlation_messages = [
                    message for message in agent_messages if message.correlation_id == correlation_id
                ]
                if any(message.message_type == "background_completion" for message in correlation_messages):
                    continue
                if any(
                    message.message_type.endswith("_response") or message.message_type.endswith("_result")
                    for message in correlation_messages
                ):
                    continue
                pending.append(correlation_id)
            latest_message = None if not agent_messages else agent_messages[-1]
            items.append(
                DelegationProjectionItem(
                    agent=agent,
                    correlation_ids=correlation_ids,
                    latest_message_type=None if latest_message is None else latest_message.message_type,
                    latest_message_at=None if latest_message is None else latest_message.created_at,
                    pending_correlation_ids=tuple(pending),
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
            items.append(
                ActivityFeedItem(
                    event_type="artifact.recorded",
                    created_at=artifact.created_at,
                    payload=artifact.to_dict(),
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
            projected["documents"] = [document.to_dict() for document in documents]
            output_document = next(
                (document for document in reversed(documents) if document.document_id == invocation.output_ref),
                None,
            )
            if output_document is not None:
                projected["output_document"] = output_document.to_dict()
                projected["output_payload"] = output_document.payload
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
            artifact_payloads: list[dict[str, Any]] = []
            for run in runs:
                artifact_payloads.extend(item.to_dict() for item in self.repositories.artifacts.list_by_run(run.run_id))
            projected["artifacts"] = artifact_payloads
        report = self.repositories.reports.get_by_invocation(session_id, invocation.invocation_id)
        if report is not None:
            projected["report"] = report.to_dict()
        return projected

    def _capability_key_for_engine(self, engine_name: str) -> str:
        return {
            "deep_research": "deep_research",
            "execution": "execution",
            "reporting": "reporting",
        }.get(engine_name, engine_name)


__all__ = [
    "ActivityFeedItem",
    "DelegationProjection",
    "DelegationProjectionItem",
    "SessionProjectionBuilder",
    "SessionWorkspaceProjection",
]
