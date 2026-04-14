from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Command
from langgraph.types import interrupt
from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import CandidateRankingRecord
from openzyme_domain import CandidateRecord
from openzyme_domain import Decision
from openzyme_domain import DecisionStatus
from openzyme_domain import EvidenceRecord
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import Run
from openzyme_domain import RunStatus
from openzyme_domain import SelectedCandidateRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord
from openzyme_runtime import CandidateComparison
from openzyme_runtime import CandidateDraftCollection
from openzyme_runtime import DesignNextAction
from openzyme_runtime import DesignTool
from openzyme_runtime import DesignToolContext
from openzyme_runtime import ResearchDossier
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .deep_research import run_deep_research
from .state import DesignHandoff
from .state import GraphPhase
from .state import InterruptType
from .state import ProgressStatus
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.DESIGN.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


def _build_design_approval_id(episode_id: str, turn_index: int) -> str:
    return f"{episode_id}-design-approval-{turn_index}"


def _build_artifact_id(run_id: str, index: int) -> str:
    return f"{run_id}-artifact-{index}"


def _build_decision_id(episode_id: str, turn_index: int) -> str:
    return f"{episode_id}-design-turn-{turn_index}"


def _resolve_artifact_kind(value: str) -> ArtifactKind:
    try:
        return ArtifactKind(value)
    except ValueError:
        return ArtifactKind.RESULT


def _summarize_observation(observation: dict[str, Any] | None) -> str | None:
    if not observation:
        return None
    if observation.get("message"):
        return str(observation["message"])
    if observation.get("summary"):
        return str(observation["summary"])
    if observation.get("tool_result", {}).get("summary"):
        return str(observation["tool_result"]["summary"])
    return None


def _recent_turns(inputs: GraphAssemblyInputs, episode_id: str, limit: int = 10) -> list[dict[str, Any]]:
    turns = inputs.repositories.decisions.list_by_episode(episode_id)
    design_turns = [turn for turn in turns if turn.phase == GraphPhase.DESIGN.value]
    payloads = [
        {
            "turn_index": turn.turn_index,
            "action_kind": turn.action_kind,
            "status": turn.status.value,
            "summary": turn.summary,
            "rationale": turn.rationale,
            "target_candidate_id": None
            if turn.action_payload is None
            else turn.action_payload.get("target_candidate_id"),
            "observation_summary": _summarize_observation(turn.observation_payload),
            "created_at": turn.created_at,
        }
        for turn in design_turns
    ]
    return payloads[-limit:]


def _fallback_next_action(state: dict[str, Any]) -> DesignNextAction:
    if (
        state.get("latest_turn_action_kind") == "collect_research"
        and state.get("latest_turn_status") == DecisionStatus.FAILED.value
    ):
        return DesignNextAction(
            action_kind="stop",
            summary="Stop after research collection did not produce usable evidence.",
            rationale="The latest research collection attempt failed, so the loop should hand off the current state.",
            stop_reason="collect_research_not_completed",
            arguments={},
        )
    if (
        state.get("latest_turn_action_kind") == "run_hpc"
        and state.get("latest_turn_status") in {DecisionStatus.REJECTED.value, DecisionStatus.FAILED.value}
    ):
        return DesignNextAction(
            action_kind="stop",
            summary="Stop after the latest HPC action did not complete successfully.",
            rationale="The last HPC action was rejected or failed, so the loop should hand off the current state.",
            stop_reason="run_hpc_not_completed",
            arguments={},
        )
    if not state.get("evidence_refs"):
        return DesignNextAction(
            action_kind="collect_research",
            summary="Collect research evidence before designing candidates.",
            rationale="No canonical evidence exists for the current objective.",
            arguments={},
        )
    if not state.get("candidate_payloads"):
        return DesignNextAction(
            action_kind="draft_candidates",
            summary="Draft candidate options from the current evidence.",
            rationale="Evidence exists but candidate drafts do not.",
            arguments={},
        )
    if not state.get("selected_candidate_id"):
        return DesignNextAction(
            action_kind="rank_candidates",
            summary="Rank the current candidates and pick the strongest next option.",
            rationale="Candidates exist but no selected candidate is recorded.",
            arguments={},
        )
    if not state.get("run_summary") and not state.get("approval_requested"):
        return DesignNextAction(
            action_kind="run_hpc",
            summary="Run the selected candidate through the HPC execution tool.",
            rationale="A selected candidate exists and no execution result has been recorded.",
            target_candidate_id=state.get("selected_candidate_id"),
            arguments={},
        )
    return DesignNextAction(
        action_kind="stop",
        summary="Stop the loop and package the current design dossier.",
        rationale="The current design state already has a selected candidate and execution outcome.",
        stop_reason="design_loop_complete",
        arguments={},
    )


@dataclass(frozen=True, slots=True)
class ResearchCollectTool:
    inputs: GraphAssemblyInputs
    name: str = "research.collect"
    requires_approval: bool = False

    def invoke(self, context: DesignToolContext) -> dict[str, Any]:
        now = _utc_now_iso()
        dossier = run_deep_research(
            self.inputs,
            episode_id=context.episode_id,
            project_id=context.project_id,
            objective=context.objective,
            design_brief=context.design_brief,
            research_brief=(
                context.current_action.get("arguments", {}).get("brief")
                or context.research_brief
                or context.design_brief
                or context.objective
            ),
        )
        return _research_collect_result_from_dossier(dossier, created_at=now)


def _research_collect_result_from_dossier(
    dossier: ResearchDossier,
    *,
    created_at: str,
) -> dict[str, Any]:
    evidence_items: list[dict[str, Any]] = []
    for index, item in enumerate(dossier.evidence_items, start=1):
        evidence_sources = item.sources or [
            {
                "title": f"Deep research source {index}",
                "locator": f"local://deep-research/{index}/1",
                "kind": SourceRefKind.WEB_PAGE.value,
                "snippet": None,
            }
        ]
        sources = []
        for source_index, source in enumerate(evidence_sources, start=1):
            source_payload = source.model_dump() if hasattr(source, "model_dump") else dict(source)
            locator = str(source_payload.get("locator") or f"local://deep-research/{index}/{source_index}")
            sources.append(
                {
                    "title": str(source_payload.get("title") or f"Deep research source {index}"),
                    "locator": locator,
                    "kind": str(source_payload.get("kind") or SourceRefKind.WEB_PAGE.value),
                }
            )
        evidence_items.append(
            {
                "summary": item.summary,
                "query": item.query,
                "confidence_label": item.confidence_label,
                "sources": sources,
            }
        )
    return {
        "status": dossier.status,
        "completion_reason": dossier.completion_reason,
        "clarification_question": dossier.clarification_question,
        "summary": dossier.summary,
        "research_brief": dossier.research_brief,
        "evidence_items": evidence_items,
        "unresolved_gaps": list(dossier.unresolved_gaps),
        "raw_notes": list(dossier.raw_notes),
        "recent_turns": [
            turn.model_dump() if hasattr(turn, "model_dump") else dict(turn)
            for turn in dossier.recent_turns
        ],
        "created_at": created_at,
    }


@dataclass(frozen=True, slots=True)
class HpcRunTool:
    inputs: GraphAssemblyInputs
    name: str = "hpc.run"
    requires_approval: bool = True

    def invoke(self, context: DesignToolContext) -> dict[str, Any]:
        candidate_id = context.current_action.get("target_candidate_id")
        if candidate_id is None:
            return {
                "summary": "No candidate is available for HPC execution.",
                "status": "failed",
                "message": "Missing selected candidate.",
            }
        candidate_snapshot = self.inputs.host_toolbox.load_candidate(context.episode_id, str(candidate_id))
        if candidate_snapshot is None:
            return {
                "summary": f"Selected candidate {candidate_id} could not be loaded for execution.",
                "status": "failed",
                "message": "Missing candidate snapshot.",
            }
        arguments = dict(context.current_action.get("arguments") or {})
        execution_request = self.inputs.host_toolbox.build_execution_request(
            candidate=candidate_snapshot,
            execution_mode=str(arguments.get("execution_mode") or "auto"),
            command=list(arguments.get("command") or ["echo", candidate_snapshot.title]),
            metadata=dict(arguments.get("metadata") or {}),
            tool_name=str(arguments.get("tool_name") or "exec.run"),
        )
        run_request = execution_request.model_dump()
        if self.inputs.execution_adapter is None:
            return {
                "summary": "Execution adapter unavailable; skipping HPC submission.",
                "status": "failed",
                "message": "execution_adapter is not configured",
                "candidate_plan": candidate_snapshot.model_dump(),
                "run_request": run_request,
            }
        outcome = self.inputs.execution_adapter.submit_execution(context.episode_id, run_request)
        return {
            "summary": "Design HPC run finished.",
            "status": outcome.status.value,
            "candidate_plan": candidate_snapshot.model_dump(),
            "run_request": run_request,
            "run_summary": {
                "run_id": outcome.run_id,
                "status": outcome.status.value,
                "execution_mode": outcome.execution_mode,
                "remote_run_dir": outcome.remote_run_dir,
            },
            "artifacts": [
                {
                    "kind": artifact.kind.value,
                    "storage_uri": artifact.storage_uri,
                }
                for artifact in outcome.artifacts
            ],
        }


class DesignSupervisorState(TypedDict, total=False):
    episode_id: str
    project_id: str
    objective: str
    design_brief: str
    research_brief: str
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    turn_index: int
    current_action: dict[str, Any] | None
    current_tool_name: str | None
    current_tool_requires_clarification: bool
    action_status: str | None
    action_error: str | None
    action_requires_approval: bool
    approval_requested: bool
    approval_id: str | None
    approval_summary: str | None
    approval_decision: dict[str, Any] | None
    research_summary: dict[str, Any] | None
    evidence_refs: list[dict[str, Any]]
    unresolved_gaps: list[dict[str, Any]]
    candidate_payloads: list[dict[str, Any]]
    ranking_payloads: list[dict[str, Any]]
    selected_candidate_id: str | None
    selected_candidate_rationale: str | None
    candidate_plan: dict[str, Any] | None
    run_request: dict[str, Any] | None
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    observation_payload: dict[str, Any] | None
    design_summary: dict[str, Any] | None
    design_handoff: DesignHandoff | None
    recommended_next_phase: str | None
    latest_turn_action_kind: str | None
    latest_turn_status: str | None


def build_phase_c_design_graph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    tools: dict[str, DesignTool] = {
        "collect_research": ResearchCollectTool(inputs),
        "run_hpc": HpcRunTool(inputs),
    }

    def load_design_context(state: DesignSupervisorState) -> dict[str, Any]:
        episode_id = state["episode_id"]
        snapshot = inputs.host_toolbox.load_canonical_research(episode_id)
        candidates = [candidate.to_dict() for candidate in inputs.repositories.candidates.list_by_episode(episode_id)]
        rankings = [ranking.to_dict() for ranking in inputs.repositories.candidate_rankings.list_by_episode(episode_id)]
        selected_candidate = inputs.repositories.selected_candidates.get_by_episode(episode_id)
        runs = inputs.repositories.runs.list_by_episode(episode_id)
        latest_run = None if not runs else runs[-1]
        design_turns = [
            turn for turn in inputs.repositories.decisions.list_by_episode(episode_id) if turn.phase == GraphPhase.DESIGN.value
        ]
        turn_count = len(design_turns)
        latest_turn = None if not design_turns else design_turns[-1]
        artifact_refs = [
            {
                "artifact_id": artifact.artifact_id,
                "kind": artifact.kind.value,
                "storage_uri": artifact.storage_uri,
            }
            for artifact in inputs.repositories.artifact_records.list_by_episode(episode_id)
        ]
        return {
            "current_phase": GraphPhase.DESIGN.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": state.get("pending_interrupt"),
            "turn_index": turn_count,
            "research_summary": snapshot.research_summary,
            "evidence_refs": snapshot.evidence_refs,
            "unresolved_gaps": snapshot.unresolved_gaps,
            "candidate_payloads": candidates,
            "ranking_payloads": rankings,
            "selected_candidate_id": None if selected_candidate is None else selected_candidate.candidate_id,
            "selected_candidate_rationale": None if selected_candidate is None else selected_candidate.rationale,
            "run_summary": None if latest_run is None else latest_run.to_dict(),
            "artifact_refs": artifact_refs,
            "latest_turn_action_kind": None if latest_turn is None else latest_turn.action_kind,
            "latest_turn_status": None if latest_turn is None else latest_turn.status.value,
            "progress": _progress(
                "load_design_context",
                ProgressStatus.RUNNING,
                "Loaded current design context",
            ),
        }

    def diagnose_next_action(state: DesignSupervisorState) -> dict[str, Any]:
        if state.get("approval_requested") and state.get("current_action") is not None:
            action = DesignNextAction.model_validate(state["current_action"])
        elif inputs.model_factory is not None:
            try:
                invoker = inputs.model_factory.create_structured_invoker(purpose="design_next_action")
                action = invoker.invoke_structured(
                    schema=DesignNextAction,
                    system_prompt=(
                        "You are the design loop planner for an enzyme engineering workflow. "
                        "Inspect the current state and return exactly one next action. "
                        "Choose only among the allowed action kinds and keep the summary concise."
                    ),
                    user_payload={
                        "episode_id": state.get("episode_id"),
                        "objective": state.get("objective"),
                        "design_brief": state.get("design_brief"),
                        "research_brief": state.get("research_brief"),
                        "research_summary": state.get("research_summary") or {},
                        "evidence_refs": state.get("evidence_refs") or [],
                        "candidate_payloads": state.get("candidate_payloads") or [],
                        "ranking_payloads": state.get("ranking_payloads") or [],
                        "selected_candidate_id": state.get("selected_candidate_id"),
                        "run_summary": state.get("run_summary") or {},
                        "approval_requested": state.get("approval_requested", False),
                    },
                )
            except Exception:
                action = _fallback_next_action(state)
        else:
            action = _fallback_next_action(state)
        return {
            "current_action": action.model_dump(),
            "action_status": DecisionStatus.PROPOSED.value,
            "action_error": None,
            "current_tool_name": None,
            "progress": _progress(
                "diagnose_next_action",
                ProgressStatus.RUNNING,
                f"Diagnosed next design action: {action.action_kind}",
            ),
        }

    def validate_action(
        state: DesignSupervisorState,
    ) -> Command[Literal["prepare_approval", "dispatch_action", "persist_turn", "finalize_design"]]:
        action = DesignNextAction.model_validate(state.get("current_action") or _fallback_next_action(state).model_dump())
        selected_candidate_id = state.get("selected_candidate_id")
        candidate_ids = {str(item["candidate_id"]) for item in state.get("candidate_payloads") or []}
        observation: dict[str, Any] | None = None
        action_status = DecisionStatus.PROPOSED
        tool_name: str | None = None

        if action.action_kind == "stop":
            return Command(
                update={
                    "current_action": action.model_dump(),
                    "design_summary": {
                        "outcome": "stopped",
                        "message": action.summary,
                        "stop_reason": action.stop_reason or "requested_stop",
                    },
                    "observation_payload": {
                        "summary": action.summary,
                        "message": action.stop_reason or "requested_stop",
                    },
                    "action_status": DecisionStatus.COMPLETED.value,
                    "progress": _progress(
                        "validate_action",
                        ProgressStatus.SUCCEEDED,
                        "Design loop chose to stop and finalize the dossier",
                    ),
                },
                goto="persist_turn",
            )

        if action.action_kind in {"run_hpc", "request_run_approval"}:
            target_candidate_id = action.target_candidate_id or selected_candidate_id
            if target_candidate_id is None:
                observation = {
                    "summary": "Cannot submit HPC work without a selected candidate.",
                    "message": "no selected candidate",
                }
                action_status = DecisionStatus.FAILED
            else:
                action.target_candidate_id = target_candidate_id
                tool_name = "run_hpc"
        elif action.action_kind == "collect_research":
            tool_name = "collect_research"
        elif action.action_kind == "draft_candidates":
            if not state.get("evidence_refs"):
                observation = {
                    "summary": "Cannot draft candidates until some research evidence exists.",
                    "message": "missing evidence",
                }
                action_status = DecisionStatus.FAILED
        elif action.action_kind == "rank_candidates":
            if not state.get("candidate_payloads"):
                observation = {
                    "summary": "Cannot rank candidates until candidates have been drafted.",
                    "message": "missing candidates",
                }
                action_status = DecisionStatus.FAILED
        elif action.action_kind == "revise_candidate":
            if action.target_candidate_id is None:
                action.target_candidate_id = selected_candidate_id
            if action.target_candidate_id is None or action.target_candidate_id not in candidate_ids:
                observation = {
                    "summary": "Cannot revise a missing candidate.",
                    "message": "missing target candidate",
                }
                action_status = DecisionStatus.FAILED
        else:
            observation = {
                "summary": f"Unsupported action kind: {action.action_kind}",
                "message": "unsupported action",
            }
            action_status = DecisionStatus.FAILED

        if observation is not None:
            return Command(
                update={
                    "current_action": action.model_dump(),
                    "current_tool_name": tool_name,
                    "action_status": action_status.value,
                    "observation_payload": observation,
                    "progress": _progress(
                        "validate_action",
                        ProgressStatus.FAILED,
                        observation["summary"],
                    ),
                },
                goto="persist_turn",
            )

        requires_approval = False if tool_name is None else tools[tool_name].requires_approval
        if requires_approval and not state.get("approval_requested"):
            return Command(
                update={
                    "current_action": action.model_dump(),
                "current_tool_name": tool_name,
                "current_tool_requires_clarification": False,
                "action_requires_approval": True,
                "approval_requested": False,
                    "progress": _progress(
                        "validate_action",
                        ProgressStatus.WAITING,
                        f"{tool_name} requires approval before execution",
                    ),
                },
                goto="prepare_approval",
            )
        return Command(
            update={
                "current_action": action.model_dump(),
                "current_tool_name": tool_name,
                "current_tool_requires_clarification": False,
                "action_requires_approval": requires_approval,
                "approval_requested": state.get("approval_requested", False),
                "progress": _progress(
                    "validate_action",
                    ProgressStatus.RUNNING,
                    f"Validated action {action.action_kind}",
                ),
            },
            goto="dispatch_action",
        )

    def prepare_approval(state: DesignSupervisorState) -> dict[str, Any]:
        next_turn = int(state.get("turn_index", 0)) + 1
        approval_id = state.get("approval_id") or _build_design_approval_id(state["episode_id"], next_turn)
        action = DesignNextAction.model_validate(state["current_action"])
        requested_action = (
            action.summary
            if action.action_kind != "request_run_approval"
            else f"Approve HPC execution for candidate {action.target_candidate_id}"
        )
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.PENDING,
                requested_action=requested_action,
                created_at=_utc_now_iso(),
            )
        )
        return {
            "approval_id": approval_id,
            "approval_summary": requested_action,
            "approval_requested": True,
            "status": SupervisorStatus.INTERRUPTED.value,
            "pending_interrupt": {
                "type": InterruptType.APPROVAL.value,
                "episode_id": state["episode_id"],
                "phase": GraphPhase.DESIGN.value,
                "approval_id": approval_id,
                "requested_action": requested_action,
            },
            "progress": _progress(
                "approval_gate",
                ProgressStatus.WAITING,
                "Waiting for tool approval",
            ),
        }

    def approval_gate(
        state: DesignSupervisorState,
    ) -> Command[Literal["dispatch_action", "persist_turn"]]:
        approval_id = str(state["approval_id"])
        decision = interrupt(state["pending_interrupt"])
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        requested_action = str(state.get("approval_summary") or "Approve design tool action")
        inputs.repositories.approvals.save(
            Approval(
                approval_id=approval_id,
                episode_id=state["episode_id"],
                status=ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED,
                requested_action=requested_action,
                created_at=_utc_now_iso(),
                resolved_at=_utc_now_iso(),
            )
        )
        if not approved:
            return Command(
                update={
                    "approval_decision": {"approved": False},
                    "pending_interrupt": None,
                    "status": SupervisorStatus.ACTIVE.value,
                    "approval_requested": False,
                    "action_status": DecisionStatus.REJECTED.value,
                    "observation_payload": {
                        "summary": "Requested tool action was rejected during review.",
                        "message": requested_action,
                    },
                    "progress": _progress(
                        "approval_gate",
                        ProgressStatus.FAILED,
                        "Tool approval rejected",
                    ),
                },
                goto="persist_turn",
            )
        return Command(
            update={
                "approval_decision": {"approved": True},
                "pending_interrupt": None,
                "status": SupervisorStatus.ACTIVE.value,
                "approval_requested": True,
                "progress": _progress(
                    "approval_gate",
                    ProgressStatus.RUNNING,
                    "Tool approval received; dispatching action",
                ),
            },
            goto="dispatch_action",
        )

    def dispatch_action(
        state: DesignSupervisorState,
    ) -> Command[Literal["clarification_gate", "persist_turn"]]:
        action = DesignNextAction.model_validate(state["current_action"])
        observation: dict[str, Any]
        status = DecisionStatus.COMPLETED
        current_tool_name = state.get("current_tool_name")

        if current_tool_name == "collect_research":
            context = DesignToolContext(
                episode_id=state["episode_id"],
                project_id=state.get("project_id"),
                objective=state.get("objective"),
                design_brief=state.get("design_brief"),
                research_brief=state.get("research_brief"),
                current_action=action.model_dump(),
            )
            tool_result = tools[current_tool_name].invoke(context)
            if tool_result.get("status") == "needs_clarification":
                question = str(
                    tool_result.get("clarification_question")
                    or "Research scope needs clarification before evidence collection can continue."
                )
                return Command(
                    update={
                        "status": SupervisorStatus.INTERRUPTED.value,
                        "current_tool_requires_clarification": True,
                        "pending_interrupt": {
                            "type": InterruptType.CLARIFICATION.value,
                            "episode_id": state["episode_id"],
                            "phase": GraphPhase.DESIGN.value,
                            "reason": "research clarification required",
                            "details": {
                                "question": question,
                                "completion_reason": tool_result.get("completion_reason"),
                            },
                        },
                        "progress": _progress(
                            "dispatch_action",
                            ProgressStatus.WAITING,
                            "Research needs clarification before continuing",
                        ),
                    },
                    goto="clarification_gate",
                )

            now = tool_result.get("created_at", _utc_now_iso())
            completion_status = str(tool_result.get("status") or "completed")
            if completion_status in {"failed", "partial"} and not tool_result.get("evidence_items"):
                return Command(
                    update={
                        "observation_payload": {
                            "summary": str(tool_result.get("summary") or "Research collection failed."),
                            "message": str(tool_result.get("completion_reason") or "research_failed"),
                            "status": completion_status,
                            "completion_reason": tool_result.get("completion_reason"),
                            "clarification_question": tool_result.get("clarification_question"),
                        },
                        "design_summary": {
                            "outcome": "research_failed",
                            "message": str(tool_result.get("summary") or "Research collection failed."),
                        },
                        "action_status": DecisionStatus.FAILED.value,
                        "progress": _progress(
                            "dispatch_action",
                            ProgressStatus.FAILED,
                            "Research collection failed to produce usable evidence",
                        ),
                    },
                    goto="persist_turn",
                )
            evidence_index = len(state.get("evidence_refs") or [])
            for finding in tool_result.get("evidence_items", []):
                evidence_index += 1
                evidence_id = f"{state['episode_id']}-evidence-{evidence_index}"
                record = EvidenceRecord(
                    evidence_id=evidence_id,
                    episode_id=state["episode_id"],
                    summary=str(finding["summary"]),
                    query=str(finding["query"]),
                    confidence_label=None if finding.get("confidence_label") is None else str(finding["confidence_label"]),
                    created_at=str(now),
                )
                inputs.repositories.evidence_records.save(record)
                for source_index, source in enumerate(finding.get("sources", []), start=1):
                    inputs.repositories.source_refs.save(
                        SourceRef(
                            source_ref_id=f"{evidence_id}-source-{source_index}",
                            evidence_id=evidence_id,
                            episode_id=state["episode_id"],
                            title=str(source["title"]),
                            locator=str(source["locator"]),
                            kind=SourceRefKind(str(source["kind"])),
                            created_at=str(now),
                        )
                    )
            existing_gap_count = len(inputs.repositories.unresolved_gaps.list_by_episode(state["episode_id"]))
            for gap_index, gap in enumerate(tool_result.get("unresolved_gaps", []), start=1):
                inputs.repositories.unresolved_gaps.save(
                    UnresolvedGapRecord(
                        gap_id=f"{state['episode_id']}-gap-{existing_gap_count + gap_index}",
                        episode_id=state["episode_id"],
                        summary=str(gap),
                        created_at=str(now),
                    )
                )
            inputs.repositories.research_summaries.save(
                ResearchSummaryRecord(
                    episode_id=state["episode_id"],
                    summary=str(tool_result.get("summary") or "Research collected inside design."),
                    created_at=str(now),
                    updated_at=str(now),
                )
            )
            snapshot = inputs.host_toolbox.load_canonical_research(state["episode_id"])
            observation = {
                "summary": f"Collected {len(snapshot.evidence_refs)} evidence item(s) inside design.",
                "tool_result": tool_result,
                "status": completion_status,
                "completion_reason": tool_result.get("completion_reason"),
                "clarification_question": tool_result.get("clarification_question"),
            }
            return Command(update={
                "research_summary": snapshot.research_summary,
                "evidence_refs": snapshot.evidence_refs,
                "unresolved_gaps": snapshot.unresolved_gaps,
                "observation_payload": observation,
                "action_status": status.value,
                "progress": _progress(
                    "dispatch_action",
                    ProgressStatus.SUCCEEDED,
                    observation["summary"],
                ),
            }, goto="persist_turn")

        if action.action_kind == "draft_candidates":
            evidence_refs = list(state.get("evidence_refs") or [])
            research_summary = str((state.get("research_summary") or {}).get("summary") or "")
            if inputs.model_factory is not None:
                invoker = inputs.model_factory.create_structured_invoker(purpose="design_candidates")
                candidate_collection = invoker.invoke_structured(
                    schema=CandidateDraftCollection,
                    system_prompt=(
                        "You propose concise enzyme design candidates from the current evidence. "
                        "Return short candidate drafts with evidence links."
                    ),
                    user_payload={
                        "episode_id": state.get("episode_id"),
                        "objective": state.get("objective"),
                        "design_brief": state.get("design_brief"),
                        "research_summary": state.get("research_summary") or {},
                        "evidence_refs": evidence_refs,
                        "prior_candidates": state.get("candidate_payloads") or [],
                    },
                )
                candidate_payloads = [candidate.model_dump() for candidate in candidate_collection.candidates[:3]]
            else:
                candidate_payloads = [
                    {
                        "candidate_id": f"{state['episode_id']}-candidate-{index}",
                        "title": f"Candidate {index}",
                        "summary": f"{research_summary} Focus on evidence: {evidence['summary']}",
                        "supporting_evidence_ids": [evidence["evidence_id"]],
                        "rationale": "Derived from the strongest current design evidence.",
                    }
                    for index, evidence in enumerate(evidence_refs[:2], start=1)
                ]
            now = _utc_now_iso()
            for payload in candidate_payloads:
                inputs.repositories.candidates.save(
                    CandidateRecord(
                        candidate_id=str(payload["candidate_id"]),
                        episode_id=state["episode_id"],
                        title=str(payload["title"]),
                        summary=str(payload["summary"]),
                        supporting_evidence_ids=tuple(str(item) for item in payload["supporting_evidence_ids"]),
                        created_at=now,
                    )
                )
            observation = {
                "summary": f"Drafted {len(candidate_payloads)} candidate option(s).",
                "candidate_ids": [payload["candidate_id"] for payload in candidate_payloads],
            }
            return Command(update={
                "candidate_payloads": [
                    candidate.to_dict()
                    for candidate in inputs.repositories.candidates.list_by_episode(state["episode_id"])
                ],
                "observation_payload": observation,
                "action_status": status.value,
                "progress": _progress("dispatch_action", ProgressStatus.SUCCEEDED, observation["summary"]),
            }, goto="persist_turn")

        if action.action_kind == "rank_candidates":
            candidate_payloads = list(state.get("candidate_payloads") or [])
            if inputs.model_factory is not None and candidate_payloads:
                invoker = inputs.model_factory.create_structured_invoker(purpose="design_ranking")
                comparison = invoker.invoke_structured(
                    schema=CandidateComparison,
                    system_prompt=(
                        "You compare current enzyme design candidates and pick the best next candidate to run. "
                        "Return one chosen candidate plus concise ranking rationales."
                    ),
                    user_payload={
                        "episode_id": state.get("episode_id"),
                        "objective": state.get("objective"),
                        "research_summary": state.get("research_summary") or {},
                        "candidate_payloads": candidate_payloads,
                    },
                )
                rankings = comparison.rankings
                selected_candidate_id = comparison.selected_candidate_id
                selected_candidate_rationale = comparison.selected_candidate_rationale
            else:
                rankings = [
                    CandidateRankingRecord(
                        ranking_id=f"{candidate['candidate_id']}-ranking",
                        episode_id=state["episode_id"],
                        candidate_id=str(candidate["candidate_id"]),
                        rank=index,
                        rationale=f"Candidate {index} ranked from current design evidence.",
                        created_at=_utc_now_iso(),
                    )
                    for index, candidate in enumerate(candidate_payloads, start=1)
                ]
                selected_candidate_id = None if not candidate_payloads else str(candidate_payloads[0]["candidate_id"])
                selected_candidate_rationale = "Top-ranked candidate selected inside the design loop."
            if rankings and not isinstance(rankings[0], CandidateRankingRecord):
                ranking_records = [
                    CandidateRankingRecord(
                        ranking_id=f"{ranking.candidate_id}-ranking",
                        episode_id=state["episode_id"],
                        candidate_id=ranking.candidate_id,
                        rank=ranking.rank,
                        rationale=ranking.rationale,
                        created_at=_utc_now_iso(),
                    )
                    for ranking in rankings
                ]
            else:
                ranking_records = rankings  # type: ignore[assignment]
            for record in ranking_records:
                inputs.repositories.candidate_rankings.save(record)
            if selected_candidate_id is not None:
                inputs.repositories.selected_candidates.save(
                    SelectedCandidateRecord(
                        episode_id=state["episode_id"],
                        candidate_id=selected_candidate_id,
                        rationale=selected_candidate_rationale,
                        selected_at=_utc_now_iso(),
                    )
                )
            observation = {
                "summary": f"Ranked {len(ranking_records)} candidate option(s).",
                "selected_candidate_id": selected_candidate_id,
            }
            return Command(update={
                "ranking_payloads": [ranking.to_dict() for ranking in ranking_records],
                "selected_candidate_id": selected_candidate_id,
                "selected_candidate_rationale": selected_candidate_rationale,
                "observation_payload": observation,
                "action_status": status.value,
                "progress": _progress("dispatch_action", ProgressStatus.SUCCEEDED, observation["summary"]),
            }, goto="persist_turn")

        if action.action_kind == "revise_candidate":
            candidate_snapshot = inputs.host_toolbox.load_candidate(state["episode_id"], str(action.target_candidate_id))
            if candidate_snapshot is None:
                return Command(update={
                    "action_status": DecisionStatus.FAILED.value,
                    "observation_payload": {
                        "summary": "Could not load candidate for revision.",
                        "message": "missing candidate snapshot",
                    },
                    "progress": _progress("dispatch_action", ProgressStatus.FAILED, "Candidate revision failed"),
                }, goto="persist_turn")
            revision_id = f"{candidate_snapshot.candidate_id}-rev-{int(state.get('turn_index', 0)) + 1}"
            revised_summary = (
                f"{candidate_snapshot.summary} Revision focus: "
                f"{action.arguments.get('revision_goal') or 'improve the current design hypothesis'}."
            )
            revised_candidate = CandidateRecord(
                candidate_id=revision_id,
                episode_id=state["episode_id"],
                title=f"{candidate_snapshot.title} Revision",
                summary=revised_summary,
                supporting_evidence_ids=tuple(candidate_snapshot.supporting_evidence_ids),
                created_at=_utc_now_iso(),
            )
            inputs.repositories.candidates.save(revised_candidate)
            observation = {
                "summary": f"Created revised candidate {revision_id}.",
                "revised_candidate_id": revision_id,
            }
            return Command(update={
                "candidate_payloads": [
                    candidate.to_dict()
                    for candidate in inputs.repositories.candidates.list_by_episode(state["episode_id"])
                ],
                "observation_payload": observation,
                "action_status": status.value,
                "progress": _progress("dispatch_action", ProgressStatus.SUCCEEDED, observation["summary"]),
            }, goto="persist_turn")

        if current_tool_name == "run_hpc":
            context = DesignToolContext(
                episode_id=state["episode_id"],
                project_id=state.get("project_id"),
                objective=state.get("objective"),
                design_brief=state.get("design_brief"),
                research_brief=state.get("research_brief"),
                current_action=action.model_dump(),
            )
            tool_result = tools[current_tool_name].invoke(context)
            if tool_result.get("run_summary") is None:
                return Command(update={
                    "candidate_plan": tool_result.get("candidate_plan"),
                    "run_request": tool_result.get("run_request"),
                    "action_status": DecisionStatus.FAILED.value,
                    "observation_payload": {
                        "summary": str(tool_result.get("summary") or "HPC execution could not be submitted."),
                        "message": str(tool_result.get("message") or "execution failed"),
                    },
                    "design_summary": {
                        "outcome": "execution_unavailable",
                        "message": str(tool_result.get("summary") or "Execution unavailable."),
                    },
                    "progress": _progress("dispatch_action", ProgressStatus.FAILED, "HPC execution did not start"),
                }, goto="persist_turn")
            created_at = _utc_now_iso()
            run_summary = dict(tool_result["run_summary"])
            inputs.repositories.runs.save(
                Run(
                    run_id=str(run_summary["run_id"]),
                    episode_id=state["episode_id"],
                    approval_id=state.get("approval_id"),
                    status=RunStatus(str(run_summary["status"])),
                    execution_mode=str(run_summary["execution_mode"]),
                    created_at=created_at,
                    completed_at=created_at if RunStatus(str(run_summary["status"])).is_terminal else None,
                )
            )
            artifact_refs: list[dict[str, Any]] = []
            for index, artifact in enumerate(tool_result.get("artifacts", []), start=1):
                record = ArtifactRecord(
                    artifact_id=_build_artifact_id(str(run_summary["run_id"]), index),
                    episode_id=state["episode_id"],
                    run_id=str(run_summary["run_id"]),
                    kind=_resolve_artifact_kind(str(artifact["kind"])),
                    storage_uri=str(artifact["storage_uri"]),
                    created_at=_utc_now_iso(),
                )
                inputs.repositories.artifact_records.save(record)
                artifact_refs.append(record.to_dict())
            run_status = RunStatus(str(run_summary["status"]))
            observation = {
                "summary": "Submitted HPC execution and recorded the resulting run.",
                "tool_result": tool_result,
            }
            return Command(update={
                "candidate_plan": tool_result.get("candidate_plan"),
                "run_request": tool_result.get("run_request"),
                "run_summary": run_summary,
                "artifact_refs": artifact_refs,
                "observation_payload": observation,
                "action_status": (DecisionStatus.COMPLETED if run_status is RunStatus.SUCCEEDED else DecisionStatus.FAILED).value,
                "design_summary": {
                    "outcome": "run_completed" if run_status is RunStatus.SUCCEEDED else "run_failed",
                    "message": "Design run completed." if run_status is RunStatus.SUCCEEDED else "Design run failed.",
                },
                "progress": _progress(
                    "dispatch_action",
                    ProgressStatus.SUCCEEDED if run_status is RunStatus.SUCCEEDED else ProgressStatus.FAILED,
                    observation["summary"],
                ),
            }, goto="persist_turn")

        return Command(update={
            "action_status": DecisionStatus.FAILED.value,
            "observation_payload": {
                "summary": f"Action {action.action_kind} could not be dispatched.",
                "message": "dispatch failure",
            },
            "progress": _progress("dispatch_action", ProgressStatus.FAILED, "Dispatch failed"),
        }, goto="persist_turn")

    def clarification_gate(
        state: DesignSupervisorState,
    ) -> Command[Literal["persist_turn"]]:
        response = interrupt(state["pending_interrupt"])
        if isinstance(response, dict):
            clarification_text = str(response.get("answer") or response.get("message") or response.get("text") or "").strip()
        else:
            clarification_text = str(response or "").strip()
        merged_brief = str(state.get("research_brief") or state.get("design_brief") or state.get("objective") or "")
        if clarification_text:
            merged_brief = f"{merged_brief}\n\nClarification: {clarification_text}".strip()
        question = (
            (state.get("pending_interrupt") or {}).get("details", {}) or {}
        ).get("question")
        return Command(
            update={
                "research_brief": merged_brief,
                "pending_interrupt": None,
                "status": SupervisorStatus.ACTIVE.value,
                "current_tool_requires_clarification": False,
                "action_status": DecisionStatus.COMPLETED.value,
                "observation_payload": {
                    "summary": "Captured research clarification and updated the research brief.",
                    "message": clarification_text or "clarification received",
                    "question": question,
                },
                "progress": _progress(
                    "clarification_gate",
                    ProgressStatus.SUCCEEDED,
                    "Research clarification captured",
                ),
            },
            goto="persist_turn",
        )

    def persist_turn(state: DesignSupervisorState) -> dict[str, Any]:
        action = DesignNextAction.model_validate(state["current_action"])
        turn_index = int(state.get("turn_index", 0)) + 1
        decision = Decision(
            decision_id=_build_decision_id(state["episode_id"], turn_index),
            episode_id=state["episode_id"],
            project_id=state.get("project_id"),
            phase=GraphPhase.DESIGN.value,
            turn_index=turn_index,
            action_kind=action.action_kind,
            status=DecisionStatus(str(state.get("action_status") or DecisionStatus.COMPLETED.value)),
            summary=action.summary,
            rationale=action.rationale,
            action_payload=action.model_dump(),
            observation_payload=state.get("observation_payload"),
            created_at=_utc_now_iso(),
        )
        inputs.repositories.decisions.save(decision)
        return {
            "turn_index": turn_index,
            "approval_id": None,
            "approval_summary": None,
            "approval_requested": False,
            "pending_interrupt": None,
            "status": SupervisorStatus.ACTIVE.value,
            "current_tool_requires_clarification": False,
            "progress": _progress(
                "persist_turn",
                ProgressStatus.SUCCEEDED,
                f"Recorded design turn {turn_index}",
            ),
        }

    def finalize_or_continue(state: DesignSupervisorState) -> str:
        action = DesignNextAction.model_validate(state["current_action"])
        action_status = DecisionStatus(str(state.get("action_status") or DecisionStatus.COMPLETED.value))
        if action.action_kind == "stop":
            return "finalize_design"
        if state.get("run_summary") is not None and action.action_kind == "run_hpc" and action_status is DecisionStatus.COMPLETED:
            return "finalize_design"
        if action_status is DecisionStatus.REJECTED:
            return "load_design_context"
        if action_status is DecisionStatus.FAILED and action.action_kind == "run_hpc":
            return "load_design_context"
        return "load_design_context"

    def finalize_design(state: DesignSupervisorState) -> dict[str, Any]:
        selected_candidate_id = state.get("selected_candidate_id")
        candidate_plan = state.get("candidate_plan")
        if candidate_plan is None and selected_candidate_id is not None:
            candidate_snapshot = inputs.host_toolbox.load_candidate(state["episode_id"], selected_candidate_id)
            candidate_plan = None if candidate_snapshot is None else candidate_snapshot.model_dump()

        design_summary = state.get("design_summary") or {
            "outcome": "ready_for_report",
            "message": "Design loop completed and packaged a final dossier.",
        }
        recent_turns = _recent_turns(inputs, state["episode_id"])
        design_handoff: DesignHandoff = {
            "candidate_plan": candidate_plan or {},
            "run_summary": state.get("run_summary"),
            "artifact_refs": list(state.get("artifact_refs") or []),
            "design_summary": {
                **design_summary,
                "research_summary": state.get("research_summary"),
                "unresolved_gaps": list(state.get("unresolved_gaps") or []),
            },
            "selected_candidate_id": selected_candidate_id,
            "recent_turns": recent_turns,
            "recommended_next_phase": GraphPhase.REPORT_REVIEW.value,
        }
        return {
            "candidate_plan": candidate_plan,
            "design_handoff": design_handoff,
            "recommended_next_phase": GraphPhase.REPORT_REVIEW.value,
            "status": SupervisorStatus.COMPLETED.value,
            "progress": _progress(
                "finalize_design",
                ProgressStatus.SUCCEEDED,
                "Finalized the design dossier for report review",
            ),
        }

    graph = StateGraph(DesignSupervisorState)
    graph.add_node("load_design_context", load_design_context)
    graph.add_node("diagnose_next_action", diagnose_next_action)
    graph.add_node("validate_action", validate_action)
    graph.add_node("prepare_approval", prepare_approval)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("dispatch_action", dispatch_action)
    graph.add_node("clarification_gate", clarification_gate)
    graph.add_node("persist_turn", persist_turn)
    graph.add_node("finalize_design", finalize_design)

    graph.add_edge(START, "load_design_context")
    graph.add_edge("load_design_context", "diagnose_next_action")
    graph.add_edge("diagnose_next_action", "validate_action")
    graph.add_edge("prepare_approval", "approval_gate")
    graph.add_conditional_edges(
        "persist_turn",
        finalize_or_continue,
        {
            "load_design_context": "load_design_context",
            "finalize_design": "finalize_design",
        },
    )
    graph.add_edge("finalize_design", END)
    if include_checkpointer:
        return graph.compile(checkpointer=inputs.checkpointer)
    return graph.compile()
