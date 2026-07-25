from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_research import safe_public_locator
from openzyme_domain import AgentMember
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import InboxParticipantKind
from openzyme_domain import MemoryKind
from openzyme_runtime import sanitize_public_diagnostic_text

from .artifact_projection import PRIVATE_ARTIFACT_KEYS
from .artifact_projection import project_artifact_list_item_for_agent
from .artifact_projection import sanitize_private_artifact_fields
from .repositories import CoreRepositories
from .report_publication import is_published_report_link
from .task_board import TaskBoardService
from .lane_manager import LaneManager
from .conversation import build_conversation_projection
from .controlled_operation_projection import project_controlled_operation_summary
from .controlled_operation_projection import is_controlled_operation_artifact_public
from .protocols import ProtocolService
from .failure_repositories import project_failure_observation
from .runtime_consistency import RuntimeConsistencyService
from .scientific_attempts import ScientificAttemptService
from .scientific_workflow_contracts import ScientificWorkflowContractRegistry
from .trace_projection import project_public_llm_trace_step


def _project_structured_locator(value: object) -> object:
    """Project a schema-declared locator without rewriting arbitrary prose."""

    if not isinstance(value, str):
        return value
    if (
        value == "/workspace"
        or value.startswith("/workspace/")
        or value == "/openzyme/control.sock"
    ):
        return value
    if value.startswith("/"):
        return "[redacted-host-path]"
    return sanitize_public_diagnostic_text(value)


def _project_named_locators(
    value: object,
    *,
    fields: frozenset[str],
) -> object:
    if isinstance(value, dict):
        return {
            str(key): (
                _project_structured_locator(item)
                if str(key) in fields
                else _project_named_locators(item, fields=fields)
            )
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        return [_project_named_locators(item, fields=fields) for item in value]
    return value


def _project_locator_record(
    value: dict[str, Any],
    *,
    fields: frozenset[str],
) -> dict[str, Any]:
    projected = _project_named_locators(value, fields=fields)
    if not isinstance(projected, dict):  # pragma: no cover - structural invariant
        raise TypeError("structured locator projection must remain an object")
    return projected


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
            "unread_inbox_count": self.unread_inbox_count,
            "pending_signal_count": self.pending_signal_count,
            "latest_signal_reason": self.latest_signal_reason,
            "last_active_at": self.last_active_at,
            "idle_since": self.idle_since,
            "wakeup_reason": self.wakeup_reason,
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
    artifact_index: tuple[dict[str, Any], ...]
    sandbox_workspaces: tuple[dict[str, Any], ...]
    sandbox_runs: tuple[dict[str, Any], ...]
    report_drafts: tuple[dict[str, Any], ...]
    reports: tuple[dict[str, Any], ...]
    scientific_evidence: dict[str, Any]
    capabilities: dict[str, list[dict[str, Any]]]
    runtime_state: dict[str, Any]
    failure_observations: tuple[dict[str, Any], ...]
    scientific_attempts: dict[str, Any]

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
            "artifact_index": list(self.artifact_index),
            "sandbox_workspaces": list(self.sandbox_workspaces),
            "sandbox_runs": list(self.sandbox_runs),
            "report_drafts": list(self.report_drafts),
            "reports": list(self.reports),
            "scientific_evidence": self.scientific_evidence,
            "capabilities": self.capabilities,
            "runtime_state": self.runtime_state,
            "failure_observations": list(self.failure_observations),
            "scientific_attempts": self.scientific_attempts,
        }


@dataclass(slots=True)
class SessionProjectionBuilder:
    repositories: CoreRepositories
    scientific_workflow_contract_registry: (
        ScientificWorkflowContractRegistry | None
    ) = None

    def build_session_workspace(self, session_id: str) -> SessionWorkspaceProjection:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        task_board = (
            TaskBoardService(self.repositories).build_projection(session_id).to_dict()
        )
        lane_board = (
            LaneManager(self.repositories).build_projection(session_id).to_dict()
        )
        lane_board = _project_locator_record(
            lane_board,
            fields=frozenset({"cwd"}),
        )
        conversation = tuple(
            entry.to_dict()
            for entry in build_conversation_projection(self.repositories, session_id)
        )
        approvals = self.build_pending_approvals(session_id)
        inbox = tuple(
            message.to_dict()
            for message in self.repositories.inbox.list_by_session(session_id)
        )
        memory = tuple(
            _project_locator_record(
                entry.to_dict(),
                fields=frozenset({"source_range"}),
            )
            for entry in self.repositories.memory.list_by_session(session_id)
        )
        delegation = self.build_delegation_projection(session_id).to_dict()
        agent_traces = self.build_agent_traces_projection(session_id)
        activity_feed = self.build_public_activity_feed(session_id)
        artifacts = tuple(
            self._project_workspace_artifact(artifact)
            for artifact in self.repositories.artifacts.list_by_session(session_id)
            if is_controlled_operation_artifact_public(self.repositories, artifact)
        )
        artifact_index = tuple(self._build_artifact_index(artifacts))
        sandbox_workspaces = tuple(
            self._sanitize_execution_projection(workspace.to_dict())
            for workspace in self.repositories.sandbox_workspaces.list_by_session(
                session_id
            )
        )
        sandbox_runs = tuple(
            self._project_sandbox_run(run)
            for run in self.repositories.sandbox_runs.list_by_session(session_id)
        )
        report_drafts = tuple(
            self._project_report_draft_summary(draft)
            for draft in self.repositories.report_drafts.list_by_session(session_id)
        )
        reports = tuple(
            self._project_report_summary(report)
            for report in self.repositories.reports.list_by_session(session_id)
        )
        scientific_evidence = self._build_scientific_evidence_projection(
            session_id,
            artifacts=artifacts,
            report_drafts=report_drafts,
            reports=reports,
        )
        capabilities = self._build_capabilities_projection(session_id)
        runtime_state = self._sanitize_execution_projection(
            RuntimeConsistencyService(
                self.repositories,
                scientific_workflow_contract_registry=(
                    self.scientific_workflow_contract_registry
                ),
            )
            .audit_session(session_id)
            .to_dict()
        )
        failure_observations = tuple(
            self._sanitize_execution_projection(
                project_failure_observation(self.repositories, observation)
            )
            for observation in self.repositories.failure_observations.list_by_session(
                session_id
            )
        )
        scientific_attempts = self._sanitize_execution_projection(
            ScientificAttemptService(
                self.repositories,
                workflow_contract_registry=(
                    self.scientific_workflow_contract_registry
                ),
            ).project_session_readiness_summary(session_id)
        )
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
            artifact_index=artifact_index,
            sandbox_workspaces=sandbox_workspaces,
            sandbox_runs=sandbox_runs,
            report_drafts=report_drafts,
            reports=reports,
            scientific_evidence=scientific_evidence,
            capabilities=capabilities,
            runtime_state=runtime_state,
            failure_observations=failure_observations,
            scientific_attempts=scientific_attempts,
        )

    def build_pending_approvals(self, session_id: str) -> tuple[dict[str, Any], ...]:
        """Build the compact canonical approval-control projection.

        Approval coordination must not require projecting the artifact catalog,
        activity feed, reports, or capability read models.  The records still
        come from the same durable approval/operation/sandbox rows used by the
        composite workspace projection.
        """

        return tuple(
            self._project_pending_approval(approval)
            for approval in self.repositories.approvals.list_pending_by_session(
                session_id
            )
        )

    def build_public_activity_feed(self, session_id: str) -> tuple[dict[str, Any], ...]:
        return tuple(
            self._sanitize_execution_projection(item.to_dict())
            for item in self.build_activity_feed(session_id)
        )

    def _project_pending_approval(self, approval: Any) -> dict[str, Any]:
        projected = approval.to_dict()
        if approval.kind == "sdk_controlled_operation":
            operation = self.repositories.controlled_operations.get_by_approval_id(
                approval.approval_id
            )
            if operation is not None:
                projected["operation"] = self._project_operation_summary(operation)
                run = self.repositories.sandbox_runs.get(operation.sandbox_run_id)
                if run is not None:
                    projected["sandbox_run"] = self._project_sandbox_run(run)
        return self._sanitize_execution_projection(projected)

    def _project_operation_summary(self, operation: Any) -> dict[str, Any]:
        return self._sanitize_execution_projection(
            project_controlled_operation_summary(self.repositories, operation)
        )

    def _project_report_summary(self, report: Any) -> dict[str, Any]:
        return self._sanitize_execution_projection(
            {
                "report_id": report.report_id,
                "session_id": report.session_id,
                "task_id": report.task_id,
                "lane_id": report.lane_id,
                "invocation_id": report.invocation_id,
                "run_id": report.run_id,
                "artifact_id": report.artifact_id,
                "status": report.status.value,
                "title": report.title,
                "created_at": report.created_at,
                "updated_at": report.updated_at,
            }
        )

    def _project_report_draft_summary(self, draft: Any) -> dict[str, Any]:
        return self._sanitize_execution_projection(
            {
                "draft_id": draft.draft_id,
                "session_id": draft.session_id,
                "task_id": draft.task_id,
                "owner_agent_id": draft.owner_agent_id,
                "status": draft.status.value,
                "title": draft.title,
                "published_report_id": draft.published_report_id,
                "created_at": draft.created_at,
                "updated_at": draft.updated_at,
            }
        )

    def _project_sandbox_run(self, run: Any) -> dict[str, Any]:
        operations = self.repositories.controlled_operations.list_by_run(
            run.sandbox_run_id
        )
        payload = run.to_dict()
        payload["operation_ids"] = [operation.operation_id for operation in operations]
        payload["operation_statuses"] = {
            operation.operation_id: operation.status.value for operation in operations
        }
        return self._sanitize_execution_projection(payload)

    def _build_artifact_index(
        self, artifacts: tuple[dict[str, Any], ...]
    ) -> list[dict[str, Any]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for artifact in artifacts:
            relative_path = str(
                artifact.get("relative_path") or artifact.get("artifact_id") or ""
            )
            if not relative_path:
                continue
            grouped.setdefault(relative_path, []).append(artifact)
        index: list[dict[str, Any]] = []
        for relative_path, versions in grouped.items():
            ordered = sorted(
                versions,
                key=lambda item: (
                    str(item.get("created_at") or ""),
                    str(item.get("artifact_id") or ""),
                ),
            )
            latest = ordered[-1]
            index.append(
                {
                    "relative_path": relative_path,
                    "latest_artifact_id": latest.get("artifact_id"),
                    "artifact_ids": [item.get("artifact_id") for item in ordered],
                    "version_count": len(ordered),
                    "kind": latest.get("kind"),
                    "title": latest.get("title"),
                    "created_at": latest.get("created_at"),
                    "latest": latest,
                }
            )
        return sorted(index, key=lambda item: str(item["relative_path"]))

    def _project_research_source_ref(self, source_ref: Any) -> dict[str, Any]:
        locator = safe_public_locator(str(source_ref.locator or ""))
        projected = {
            "source_ref_id": source_ref.source_ref_id,
            "task_id": source_ref.task_id,
            "lane_id": source_ref.lane_id,
            "invocation_id": source_ref.invocation_id,
            "evidence_id": source_ref.evidence_id,
            "title": source_ref.title,
            "kind": source_ref.kind.value,
            "provider": self._safe_identifier(source_ref.provider),
            "external_id": self._safe_identifier(source_ref.external_id),
            "pmid": (
                source_ref.pmid
                if source_ref.pmid is not None and source_ref.pmid.isdigit()
                else None
            ),
            "doi": self._safe_short_text(source_ref.doi),
            "venue": self._safe_short_text(source_ref.venue),
            "publication_date": self._safe_short_text(source_ref.publication_date),
            "retrieved_at": self._safe_short_text(source_ref.retrieved_at),
            "request_digest": self._safe_digest(source_ref.request_digest),
            "response_digest": self._safe_digest(source_ref.response_digest),
            "evidence_artifact_id": self._safe_identifier(
                source_ref.evidence_artifact_id
            ),
            "created_at": source_ref.created_at,
        }
        if locator is not None:
            projected["locator"] = locator
        return {key: value for key, value in projected.items() if value is not None}

    def _project_provider_call(
        self,
        value: Any,
        *,
        invocation_id: str | None,
        observed_at: str,
    ) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        provenance = value.get("provenance")
        if not isinstance(provenance, dict):
            return None
        provider = self._safe_identifier(provenance.get("provider"))
        if provider is None:
            return None
        outcome = self._safe_status(
            value.get("outcome"),
            allowed={"completed", "empty", "degraded", "failed"},
            default="unknown",
        )
        item_count = value.get("item_count")
        if not isinstance(item_count, int) or isinstance(item_count, bool):
            item_count = 0
        failure = value.get("failure")
        error_code = (
            self._safe_identifier(failure.get("error_code"))
            if isinstance(failure, dict)
            else None
        )
        return {
            "provider": provider,
            "requirement": self._provider_requirement(provider),
            "outcome": outcome,
            "item_count": max(0, item_count),
            "request_digest": self._safe_digest(provenance.get("request_digest")),
            "response_digest": self._safe_digest(provenance.get("response_digest")),
            "retrieved_at": self._safe_short_text(provenance.get("retrieved_at")),
            "attempt_count": self._safe_nonnegative_int(
                provenance.get("attempt_count")
            ),
            "error_code": error_code,
            "invocation_id": invocation_id,
            "observed_at": observed_at,
        }

    def _project_quorum(self, value: Any) -> dict[str, Any] | None:
        if not isinstance(value, dict):
            return None
        status = self._safe_status(
            value.get("status"),
            allowed={"complete", "degraded", "failed"},
            default="failed",
        )
        members: list[dict[str, Any]] = []
        for raw_member in value.get("members") or []:
            if not isinstance(raw_member, dict):
                continue
            provider = self._safe_identifier(raw_member.get("provider"))
            if provider is None:
                continue
            member = {
                "provider": provider,
                "requirement": self._safe_status(
                    raw_member.get("requirement"),
                    allowed={"required", "enrichment"},
                    default=self._provider_requirement(provider),
                ),
                "outcome": self._safe_status(
                    raw_member.get("outcome"),
                    allowed={"completed", "empty", "degraded", "failed"},
                    default="unknown",
                ),
                "record_count": self._safe_nonnegative_int(
                    raw_member.get("record_count")
                ),
                "accepted": raw_member.get("accepted") is True,
                "error_code": self._safe_identifier(raw_member.get("error_code")),
            }
            members.append(member)
        return {
            "status": status,
            "cutover_eligible": value.get("cutover_eligible") is True,
            "members": members,
            "warning_count": len(value.get("warnings") or []),
        }

    def _project_cutover_artifact(self, artifact: dict[str, Any]) -> dict[str, Any]:
        metadata = artifact.get("metadata")
        if not isinstance(metadata, dict):
            metadata = {}
        provenance = metadata.get("provenance")
        if not isinstance(provenance, dict):
            provenance = {}
        candidate_count = self._safe_nonnegative_int(metadata.get("candidate_count"))
        scientific_outcome = self._safe_identifier(
            metadata.get("scientific_outcome") or metadata.get("scientific_status")
        )
        if (
            scientific_outcome is None
            and candidate_count == 0
            and "candidate_count" in metadata
        ):
            scientific_outcome = "empty_result"
        return {
            "artifact_id": artifact.get("artifact_id"),
            "kind": artifact.get("kind"),
            "title": artifact.get("title"),
            "relative_path": artifact.get("relative_path"),
            "schema_id": self._safe_identifier(
                metadata.get("schema_id") or metadata.get("schema_version")
            ),
            "provider": self._safe_identifier(
                metadata.get("provider") or provenance.get("provider")
            ),
            "provider_outcome": self._safe_status(
                metadata.get("provider_outcome"),
                allowed={"completed", "empty", "degraded", "failed"},
                default=None,
            ),
            "quorum_status": self._safe_status(
                metadata.get("quorum_status"),
                allowed={"complete", "degraded", "failed"},
                default=None,
            ),
            "cutover_eligible": (
                metadata.get("cutover_eligible")
                if isinstance(metadata.get("cutover_eligible"), bool)
                else None
            ),
            "content_digest": self._safe_digest(metadata.get("content_digest")),
            "sealed_digest": self._safe_digest(metadata.get("sealed_digest")),
            "request_digest": self._safe_digest(provenance.get("request_digest")),
            "response_digest": self._safe_digest(provenance.get("response_digest")),
            "verification_status": self._safe_status(
                metadata.get("verification_status") or metadata.get("verifier_status"),
                allowed={"passed", "failed", "pending"},
                default=None,
            ),
            "scientific_outcome": scientific_outcome,
            "candidate_count": candidate_count,
            "created_at": artifact.get("created_at"),
        }

    def _build_scientific_evidence_projection(
        self,
        session_id: str,
        *,
        artifacts: tuple[dict[str, Any], ...],
        report_drafts: tuple[dict[str, Any], ...],
        reports: tuple[dict[str, Any], ...],
    ) -> dict[str, Any]:
        provider_calls: dict[str, dict[str, Any]] = {}
        quorum: dict[str, Any] | None = None
        for document in self.repositories.engine_documents.list_by_session(session_id):
            if not isinstance(document.payload, dict):
                continue
            raw_ref = document.payload.get("raw_ref")
            if not isinstance(raw_ref, dict):
                continue
            provider_call = self._project_provider_call(
                raw_ref.get("provider_call"),
                invocation_id=document.invocation_id,
                observed_at=document.updated_at,
            )
            if provider_call is not None:
                provider_calls[provider_call["provider"]] = provider_call
            projected_quorum = self._project_quorum(
                raw_ref.get("call_local_literature_quorum")
            )
            if projected_quorum is not None:
                quorum = projected_quorum

        citations = [
            self._project_research_source_ref(source_ref)
            for source_ref in self.repositories.research_source_refs.list_by_session(
                session_id
            )
        ]
        artifact_summaries = [
            self._project_cutover_artifact(artifact) for artifact in artifacts
        ]
        for artifact in artifact_summaries:
            provider = artifact.get("provider")
            if not provider or provider in provider_calls:
                continue
            provider_calls[provider] = {
                "provider": provider,
                "requirement": self._provider_requirement(provider),
                "outcome": artifact.get("provider_outcome") or "recorded",
                "item_count": 0,
                "request_digest": artifact.get("request_digest"),
                "response_digest": artifact.get("response_digest"),
                "retrieved_at": artifact.get("created_at"),
                "attempt_count": None,
                "error_code": None,
                "invocation_id": None,
                "observed_at": artifact.get("created_at"),
            }

        active = bool(provider_calls) or any(
            artifact.get("cutover_eligible") is not None
            or str(artifact.get("schema_id") or "").startswith("aox_")
            for artifact in artifact_summaries
        )
        if active:
            for provider in ("pubmed", "semantic_scholar", "tavily"):
                provider_calls.setdefault(
                    provider,
                    {
                        "provider": provider,
                        "requirement": self._provider_requirement(provider),
                        "outcome": "not_attempted",
                        "item_count": 0,
                        "request_digest": None,
                        "response_digest": None,
                        "retrieved_at": None,
                        "attempt_count": None,
                        "error_code": "provider_absent",
                        "invocation_id": None,
                        "observed_at": None,
                    },
                )
            if quorum is not None:
                for member in quorum.get("members") or []:
                    provider = member.get("provider")
                    if provider not in provider_calls:
                        continue
                    provider_calls[provider]["requirement"] = member.get(
                        "requirement"
                    ) or self._provider_requirement(provider)
                    provider_calls[provider]["outcome"] = (
                        member.get("outcome") or provider_calls[provider]["outcome"]
                    )
                    provider_calls[provider]["item_count"] = (
                        member.get("record_count")
                        or provider_calls[provider]["item_count"]
                    )
                    provider_calls[provider]["error_code"] = (
                        member.get("error_code")
                        or provider_calls[provider]["error_code"]
                    )

        for provider, summary in provider_calls.items():
            provider_citations = [
                citation
                for citation in citations
                if citation.get("provider") == provider
            ]
            provider_artifacts = [
                artifact
                for artifact in artifact_summaries
                if artifact.get("provider") == provider
            ]
            summary["source_ref_ids"] = [
                citation["source_ref_id"] for citation in provider_citations
            ]
            summary["evidence_artifact_ids"] = [
                artifact["artifact_id"] for artifact in provider_artifacts
            ]
            if summary.get("item_count") == 0 and provider_citations:
                summary["item_count"] = len(provider_citations)

        if quorum is None and active:
            pubmed = provider_calls["pubmed"]
            explicit_artifact_eligibility = any(
                artifact.get("provider") == "pubmed"
                and artifact.get("cutover_eligible") is True
                for artifact in artifact_summaries
            )
            accepted = (
                pubmed.get("outcome") == "completed"
                and pubmed.get("item_count", 0) > 0
                and any(
                    citation.get("provider") == "pubmed"
                    and str(citation.get("pmid") or "").isdigit()
                    for citation in citations
                )
                and explicit_artifact_eligibility
            )
            artifact_quorum_status = next(
                (
                    artifact.get("quorum_status")
                    for artifact in reversed(artifact_summaries)
                    if artifact.get("provider") == "pubmed"
                    and artifact.get("quorum_status")
                ),
                None,
            )
            quorum = {
                "status": artifact_quorum_status
                or ("failed" if not accepted else "degraded"),
                "cutover_eligible": accepted,
                "members": [
                    {
                        "provider": provider,
                        "requirement": summary["requirement"],
                        "outcome": summary["outcome"],
                        "record_count": summary["item_count"],
                        "accepted": (
                            accepted
                            if provider == "pubmed"
                            else summary["outcome"] == "completed"
                        ),
                        "error_code": summary.get("error_code"),
                    }
                    for provider, summary in provider_calls.items()
                ],
                "warning_count": sum(
                    1
                    for provider in ("semantic_scholar", "tavily")
                    if provider_calls[provider]["outcome"] != "completed"
                ),
            }
        elif quorum is None:
            quorum = {
                "status": "not_evaluated",
                "cutover_eligible": False,
                "members": [],
                "warning_count": 0,
            }

        operation_summaries = [
            self._project_operation_summary(operation)
            for operation in self.repositories.controlled_operations.list_by_session(
                session_id
            )
        ]
        artifact_by_id = {
            artifact["artifact_id"]: artifact for artifact in artifact_summaries
        }
        published_drafts_by_report_id: dict[str, dict[str, Any]] = {}
        for draft_record in self.repositories.report_drafts.list_by_session(session_id):
            draft = draft_record.to_dict()
            report_id = str(draft.get("published_report_id") or "")
            content_ref = str(draft.get("content_ref") or "")
            content_document = (
                None
                if not content_ref
                else self.repositories.engine_documents.get(content_ref)
            )
            content_available = (
                content_document is not None
                and content_document.document_kind == "report_draft_content"
                and isinstance(content_document.payload, dict)
                and bool(str(content_document.payload.get("markdown") or "").strip())
            )
            if draft.get("status") == "published" and report_id and content_available:
                published_drafts_by_report_id[report_id] = dict(draft)
        report_summaries = [
            {
                **report,
                "published": (
                    report.get("report_id") in published_drafts_by_report_id
                    and is_published_report_link(
                        report,
                        published_drafts_by_report_id[
                            str(report.get("report_id") or "")
                        ],
                    )
                ),
                "artifact_registered": report.get("artifact_id") in artifact_by_id,
                "published_draft_id": dict(
                    published_drafts_by_report_id.get(
                        str(report.get("report_id") or ""),
                        {},
                    )
                ).get("draft_id"),
                "content_document_bound": report.get("report_id")
                in published_drafts_by_report_id,
                "cutover_eligible": (
                    report.get("report_id") in published_drafts_by_report_id
                    and is_published_report_link(
                        report,
                        published_drafts_by_report_id[
                            str(report.get("report_id") or "")
                        ],
                    )
                ),
            }
            for report in reports
        ]
        published_report_ids = {
            report["report_id"] for report in report_summaries if report["published"]
        }
        published_draft_ids = [
            draft["draft_id"]
            for draft in report_drafts
            if draft.get("status") == "published"
            and draft.get("published_report_id") in published_report_ids
        ]

        verification_artifacts = [
            artifact
            for artifact in artifact_summaries
            if artifact.get("schema_id") == "aox_blank_world_verification@1"
        ]
        verifier_passed = any(
            artifact.get("verification_status") == "passed"
            and artifact.get("cutover_eligible") is True
            for artifact in verification_artifacts
        )
        blockers: list[str] = []
        warnings: list[str] = []
        if active:
            if any(
                "fixture" in str(artifact.get("schema_id") or "").casefold()
                or str(artifact.get("scientific_outcome") or "").casefold()
                == "fixture_non_cutover"
                for artifact in artifact_summaries
            ):
                blockers.append("fixture_non_cutover")
            if quorum.get("cutover_eligible") is not True:
                blockers.extend(
                    str(member.get("error_code"))
                    for member in quorum.get("members") or []
                    if member.get("requirement") == "required"
                    and member.get("accepted") is not True
                    and member.get("error_code")
                )
                blockers.append("required_provider_quorum_incomplete")
            for operation in operation_summaries:
                if operation.get("status") in {"failed", "recovery_failed"}:
                    blockers.append(
                        operation.get("error_code") or "required_operation_failed"
                    )
                elif operation.get("status") not in {"completed", "succeeded"}:
                    blockers.append("required_operation_incomplete")
            if not any(report["published"] for report in report_summaries):
                blockers.append("published_report_missing")
            elif not any(report["cutover_eligible"] for report in report_summaries):
                blockers.append("published_report_not_evidence_bound")
            if not verifier_passed:
                blockers.append("offline_verifier_evidence_missing")
            for provider in ("semantic_scholar", "tavily"):
                if provider_calls[provider]["outcome"] != "completed":
                    warnings.append(f"{provider}_enrichment_degraded")

        blockers = list(dict.fromkeys(blockers))
        warnings = list(dict.fromkeys(warnings))
        cutover_eligible = active and verifier_passed and not blockers
        scientific_outcomes = [
            artifact.get("scientific_outcome")
            for artifact in artifact_summaries
            if artifact.get("scientific_outcome")
        ]
        return {
            "schema_version": "v3.scientific_evidence.v1",
            "active": active,
            "providers": sorted(
                provider_calls.values(),
                key=lambda item: (
                    item.get("requirement") != "required",
                    str(item.get("provider") or ""),
                ),
            ),
            "quorum": quorum,
            "citations": citations,
            "operations": operation_summaries,
            "artifacts": artifact_summaries,
            "reports": report_summaries,
            "published_draft_ids": published_draft_ids,
            "scientific_outcome": (
                "empty_result"
                if "empty_result" in scientific_outcomes
                else (scientific_outcomes[-1] if scientific_outcomes else "unknown")
            ),
            "verifier": {
                "status": "passed" if verifier_passed else "missing",
                "artifact_ids": [
                    artifact["artifact_id"] for artifact in verification_artifacts
                ],
            },
            "cutover": {
                "status": (
                    "eligible"
                    if cutover_eligible
                    else ("blocked" if active else "not_evaluated")
                ),
                "eligible": cutover_eligible,
                "blocker_codes": blockers,
                "warning_codes": warnings,
            },
        }

    def _provider_requirement(self, provider: str) -> str:
        return (
            "enrichment" if provider in {"semantic_scholar", "tavily"} else "required"
        )

    def _safe_identifier(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or len(text) > 200:
            return None
        if not all(char.isalnum() or char in "-._:@/+" for char in text):
            return None
        return text

    def _safe_short_text(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value).strip()
        if not text or len(text) > 300:
            return None
        if text.startswith(("/", "~", "file://", "storage://", "artifact://")):
            return None
        return text

    def _safe_digest(self, value: Any) -> str | None:
        if value is None:
            return None
        text = str(value)
        if not text.startswith("sha256:") or len(text) != 71:
            return None
        try:
            int(text.removeprefix("sha256:"), 16)
        except ValueError:
            return None
        return text

    def _safe_nonnegative_int(self, value: Any) -> int | None:
        if not isinstance(value, int) or isinstance(value, bool) or value < 0:
            return None
        return value

    def _safe_status(
        self,
        value: Any,
        *,
        allowed: set[str],
        default: str | None,
    ) -> str | None:
        text = str(value or "").strip().lower()
        return text if text in allowed else default

    def build_agent_traces_projection(
        self, session_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for document in self.repositories.engine_documents.list_by_session(session_id):
            if document.document_kind != "llm_trace_step":
                continue
            payload = project_public_llm_trace_step(
                document.payload,
                trace_id=document.document_id,
                created_at=document.created_at,
            )
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
                if message.sender == agent.agent_id
                or message.recipient == agent.agent_id
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
                        "request_message_type": None
                        if thread.request is None
                        else thread.request.message_type,
                        "response_count": len(thread.responses),
                        "latest_message_type": None
                        if not thread.responses
                        else thread.responses[-1].message_type,
                    }
                )
                if thread.status.value == "waiting":
                    pending.append(correlation_id)
            latest_message = None if not agent_messages else agent_messages[-1]
            agent_signals = [
                signal for signal in signals if signal.agent_id == agent.agent_id
            ]
            pending_signals = [
                signal
                for signal in agent_signals
                if signal.status is AgentRuntimeSignalStatus.PENDING
            ]
            latest_signal = None if not agent_signals else agent_signals[-1]
            items.append(
                DelegationProjectionItem(
                    agent=agent,
                    correlation_ids=correlation_ids,
                    latest_correlation_id=None
                    if latest_message is None
                    else latest_message.correlation_id,
                    latest_message_type=None
                    if latest_message is None
                    else latest_message.message_type,
                    latest_message_at=None
                    if latest_message is None
                    else latest_message.created_at,
                    pending_correlation_ids=tuple(pending),
                    thread_summaries=tuple(thread_summaries),
                    unread_inbox_count=len(
                        self.repositories.inbox.list_unread_for_recipient(
                            session_id, agent.agent_id
                        )
                    ),
                    pending_signal_count=len(pending_signals),
                    latest_signal_reason=None
                    if latest_signal is None
                    else latest_signal.reason.value,
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
            if (
                approval.status is not ApprovalRequestStatus.PENDING
                and approval.resolved_at is not None
            ):
                items.append(
                    ActivityFeedItem(
                        event_type="approval.resolved",
                        created_at=approval.resolved_at,
                        payload=approval.to_dict(),
                    )
                )
        for message in self.repositories.inbox.list_by_session(session_id):
            event_type = (
                "agent.message.delivered"
                if (
                    message.sender_kind is InboxParticipantKind.AGENT
                    or message.recipient_kind is InboxParticipantKind.AGENT
                )
                else "inbox.delivered"
            )
            if message.message_type == "background_completion":
                event_type = "background.completed"
            elif (
                message.message_type == "delegation_request"
                and message.recipient_kind is InboxParticipantKind.AGENT
            ):
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
                event_type = (
                    "agent.inbox_unread"
                    if signal.reason.value == "inbox_unread"
                    else "agent.wakeup_pending"
                )
            elif signal.status is AgentRuntimeSignalStatus.CLAIMED:
                event_type = "agent.woken"
            elif (
                signal.reason.value == "task_available"
                and signal.status is AgentRuntimeSignalStatus.COMPLETED
            ):
                event_type = "agent.task_claimed"
            else:
                event_type = "agent.runtime_signal.updated"
            items.append(
                ActivityFeedItem(
                    event_type=event_type,
                    created_at=signal.completed_at
                    or signal.claimed_at
                    or signal.created_at,
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
            if not is_controlled_operation_artifact_public(
                self.repositories,
                artifact,
            ):
                continue
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
                        payload=self._sanitize_execution_projection(
                            {
                                "run": run.to_dict(),
                                "artifact_ids": [
                                    artifact.artifact_id for artifact in artifacts
                                ],
                            }
                        ),
                    )
                )
        for operation in self.repositories.controlled_operations.list_by_session(
            session_id
        ):
            items.append(
                ActivityFeedItem(
                    event_type="sdk_controlled_operation.updated",
                    created_at=operation.updated_at,
                    payload=self._project_operation_summary(operation),
                )
            )
        for sandbox_run in self.repositories.sandbox_runs.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="sandbox.run.updated",
                    created_at=sandbox_run.updated_at,
                    payload=self._project_sandbox_run(sandbox_run),
                )
            )
        for draft in self.repositories.report_drafts.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="report_draft.updated",
                    created_at=draft.updated_at,
                    payload=self._project_report_draft_summary(draft),
                )
            )
        for report in self.repositories.reports.list_by_session(session_id):
            items.append(
                ActivityFeedItem(
                    event_type="report.generated"
                    if report.status.is_terminal
                    else "report.updated",
                    created_at=report.updated_at,
                    payload=self._project_report_summary(report),
                )
            )
        return sorted(items, key=lambda item: (item.created_at, item.event_type))

    def _build_capabilities_projection(
        self, session_id: str
    ) -> dict[str, list[dict[str, Any]]]:
        grouped: dict[str, list[dict[str, Any]]] = {}
        for invocation in self.repositories.invocations.list_by_session(session_id):
            grouped.setdefault(
                self._capability_key_for_engine(invocation.engine_name), []
            ).append(self._project_invocation(session_id, invocation))
        operations = [
            self._project_operation_summary(operation)
            for operation in self.repositories.controlled_operations.list_by_session(
                session_id
            )
        ]
        if operations:
            grouped["sdk_supervisor"] = operations
        return grouped

    def _project_invocation(self, session_id: str, invocation: Any) -> dict[str, Any]:
        projected = invocation.to_dict()
        documents = self.repositories.engine_documents.list_by_invocation(
            session_id, invocation.invocation_id
        )
        if documents:
            projected["documents"] = [
                self._sanitize_execution_projection(document.to_dict())
                for document in documents
            ]
            output_document = next(
                (
                    document
                    for document in reversed(documents)
                    if document.document_id == invocation.output_ref
                ),
                None,
            )
            if output_document is not None:
                output_dict = output_document.to_dict()
                projected["output_document"] = self._sanitize_execution_projection(
                    output_dict
                )
                projected["output_payload"] = self._sanitize_execution_projection(
                    output_document.payload
                )
        summary = self.repositories.research_summaries.get_by_invocation(
            session_id, invocation.invocation_id
        )
        if summary is not None:
            evidence = self.repositories.research_evidence.list_by_invocation(
                session_id, invocation.invocation_id
            )
            source_refs = self.repositories.research_source_refs.list_by_invocation(
                session_id, invocation.invocation_id
            )
            gaps = self.repositories.research_gaps.list_by_invocation(
                session_id, invocation.invocation_id
            )
            projected["canonical_summary"] = summary.to_dict()
            projected["evidence"] = [item.to_dict() for item in evidence]
            projected["source_refs"] = [
                self._project_research_source_ref(item) for item in source_refs
            ]
            projected["gaps"] = [item.to_dict() for item in gaps]
        runs = self.repositories.runs.list_by_invocation(
            session_id, invocation.invocation_id
        )
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
                    artifact_payload = project_artifact_list_item_for_agent(item)
                    artifact_payloads.append(artifact_payload)
            projected["artifacts"] = artifact_payloads
            projected["output_artifact_ids"] = [
                artifact["artifact_id"] for artifact in artifact_payloads
            ]
        request_document = next(
            (
                document
                for document in documents
                if document.document_kind == "execution_input"
            ),
            None,
        )
        request_runspec = {}
        if request_document is not None:
            request_runspec = dict(
                (request_document.payload.get("request") or {}).get("runspec") or {}
            )
        if request_runspec:
            metadata = dict(request_runspec.get("metadata") or {})
            projected["tool_contract"] = dict(metadata.get("tool_contract") or {})
            projected["input_artifact_ids"] = list(
                metadata.get("input_artifact_ids") or []
            )
            projected["preprocess_artifact_ids"] = list(
                metadata.get("preprocess_artifact_ids") or []
            )
            projected["bio_artifact_ids"] = list(metadata.get("bio_artifact_ids") or [])
            projected["pipeline_invocation_id"] = (
                metadata.get("pipeline_invocation_id") or invocation.invocation_id
            )
            projected["code_digest"] = metadata.get("code_digest")
            projected["sandbox_status"] = metadata.get(
                "sandbox_status",
                "completed" if invocation.status.is_terminal else "running",
            )
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
                projected["sandbox_status"] = (
                    "dry_run" if pipeline.get("dry_run") else "pending"
                )
                projected["hpc_run_ids"] = []
                projected["input_artifact_ids"] = list(
                    (pipeline.get("inputs") or {}).get("artifact_ids") or []
                )
                projected["preprocess_artifact_ids"] = []
                projected["bio_artifact_ids"] = list(
                    pipeline.get("bio_artifact_ids") or []
                )
        report = self.repositories.reports.get_by_invocation(
            session_id, invocation.invocation_id
        )
        if report is not None:
            projected["report"] = self._project_report_summary(report)
        return projected

    def _sanitize_execution_projection(self, value: Any) -> Any:
        private_keys = {
            "pipeline_code",
            "raw_ref",
            *PRIVATE_ARTIFACT_KEYS,
            "remote_path",
        }
        sensitive_keys = {
            "authorization",
            "cookie",
            "set_cookie",
            "private_locator",
        }
        if isinstance(value, dict):
            sanitized: dict[str, Any] = {}
            for key, item in value.items():
                key_lower = str(key).lower()
                if (
                    key_lower in private_keys
                    or key_lower in sensitive_keys
                    or any(
                        marker in key_lower
                        for marker in (
                            "api_key",
                            "credential",
                            "password",
                            "private_key",
                            "private",
                            "secret",
                        )
                    )
                    or key_lower.endswith("_token")
                ):
                    continue
                sanitized[key] = self._sanitize_execution_projection(item)
            return sanitized
        if isinstance(value, list | tuple):
            return [self._sanitize_execution_projection(item) for item in value]
        if isinstance(value, str):
            if value.startswith(("http://", "https://")):
                return safe_public_locator(value) or "[redacted]"
            if value.startswith("storage://"):
                return "[redacted]"
            return sanitize_public_diagnostic_text(value)
        return value

    def _string_or_none(self, value: Any) -> str | None:
        if value is None:
            return None
        if isinstance(value, str):
            return value or None
        return str(value)

    def _string_list(self, value: Any) -> list[str]:
        if not isinstance(value, list | tuple):
            return []
        return [str(item) for item in value if item is not None]

    def _source_artifact_ids(self, metadata: dict[str, Any]) -> list[str]:
        artifact_ids: list[str] = []
        source_artifact_id = self._string_or_none(metadata.get("source_artifact_id"))
        if source_artifact_id is not None:
            artifact_ids.append(source_artifact_id)
        artifact_ids.extend(self._string_list(metadata.get("source_artifact_ids")))
        return artifact_ids

    def _infer_artifact_format(
        self, payload: dict[str, Any], metadata: dict[str, Any]
    ) -> str | None:
        explicit = self._string_or_none(metadata.get("format")) or self._string_or_none(
            metadata.get("output_format")
        )
        if explicit is not None:
            return explicit
        filename = str(payload.get("relative_path") or "").rsplit("/", maxsplit=1)[-1]
        if "." not in filename or filename.endswith("."):
            return None
        return filename.rsplit(".", maxsplit=1)[-1].lower() or None

    def _project_artifact_provenance(
        self, payload: dict[str, Any], metadata: dict[str, Any]
    ) -> dict[str, Any]:
        run = (
            self.repositories.runs.get(payload["run_id"])
            if payload.get("run_id")
            else None
        )
        produced_by = (
            self._string_or_none(metadata.get("produced_by"))
            or self._string_or_none(metadata.get("source"))
            or ("execution_engine" if payload.get("run_id") else None)
        )
        return {
            "task_id": payload.get("task_id"),
            "lane_id": payload.get("lane_id"),
            "invocation_id": payload.get("invocation_id"),
            "run_id": payload.get("run_id"),
            "produced_by": produced_by,
            "source": self._string_or_none(metadata.get("source")),
            "format": self._infer_artifact_format(payload, metadata),
            "provider": self._string_or_none(metadata.get("provider")),
            "external_id": self._string_or_none(metadata.get("external_id")),
            "source_locator": safe_public_locator(
                str(metadata.get("source_locator") or "")
            ),
            "source_artifact_ids": self._source_artifact_ids(metadata),
            "input_artifact_ids": self._string_list(metadata.get("input_artifact_ids")),
            "preprocess_artifact_ids": self._string_list(
                metadata.get("preprocess_artifact_ids")
            ),
            "bio_artifact_ids": self._string_list(metadata.get("bio_artifact_ids")),
            "runner_run_id": self._string_or_none(metadata.get("runner_run_id"))
            or (run.runner_run_id if run is not None else None),
            "pipeline_invocation_id": self._string_or_none(
                metadata.get("pipeline_invocation_id")
            ),
            "code_digest": self._string_or_none(metadata.get("code_digest")),
            "source_code_artifact_id": self._string_or_none(
                metadata.get("source_code_artifact_id")
            ),
            "source_code_digest": self._string_or_none(
                metadata.get("source_code_digest")
            ),
            "source_code_version": metadata.get("source_code_version"),
            "tool_contract": dict(metadata.get("tool_contract"))
            if isinstance(metadata.get("tool_contract"), dict)
            else {},
        }

    def _project_workspace_artifact(self, artifact: Any) -> dict[str, Any]:
        # A session workspace is a collection read model, not the exact
        # single-artifact read surface.  Reuse the bounded list-item contract so
        # large canonical metadata remains available through artifact.get
        # without being repeated in artifacts, artifact_index, activity_feed,
        # and capability projections.
        payload = project_artifact_list_item_for_agent(artifact)
        metadata = dict(payload.get("metadata") or {})
        payload["provenance"] = self._project_artifact_provenance(payload, metadata)
        return self._sanitize_execution_projection(
            sanitize_private_artifact_fields(payload)
        )

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
