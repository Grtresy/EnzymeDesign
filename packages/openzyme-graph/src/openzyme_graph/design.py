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
from openzyme_domain import ArtifactKind
from openzyme_domain import Decision
from openzyme_domain import DecisionStatus
from openzyme_domain import EvidenceRecord
from openzyme_domain import ResearchSummaryRecord
from openzyme_domain import SourceRef
from openzyme_domain import SourceRefKind
from openzyme_domain import UnresolvedGapRecord
from openzyme_runtime import DesignNextAction
from openzyme_runtime import DesignTool
from openzyme_runtime import DesignToolContext
from openzyme_runtime import ExecutionResultHandoff
from openzyme_runtime import ResearchDossier
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .deep_research import run_deep_research
from .state import DesignHandoff
from .state import ExecutionHandoff
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


def _build_artifact_id(run_id: str, index: int) -> str:
    return f"{run_id}-artifact-{index}"


def _build_decision_id(episode_id: str, turn_index: int) -> str:
    return f"{episode_id}-design-turn-{turn_index}"


def _build_source_artifact_id(source_ref_id: str) -> str:
    return f"{source_ref_id}-artifact"


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


def _execution_ready_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready: list[dict[str, Any]] = []
    for artifact in artifacts:
        availability = dict(artifact.get("availability") or {})
        if bool(availability.get("execution_input")) or artifact.get("kind") == ArtifactKind.STRUCTURE.value:
            ready.append(artifact)
    return ready


def _required_execution_artifacts(artifacts: list[dict[str, Any]]) -> list[dict[str, Any]]:
    ready = _execution_ready_artifacts(artifacts)
    local_ready = [artifact for artifact in ready if bool((artifact.get("availability") or {}).get("local_readable"))]
    return local_ready or ready


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
            "focused_artifact_ids": []
            if turn.action_payload is None
            else list(turn.action_payload.get("focused_artifact_ids") or turn.action_payload.get("required_artifact_ids") or []),
            "observation_summary": _summarize_observation(turn.observation_payload),
            "created_at": turn.created_at,
        }
        for turn in design_turns
    ]
    return payloads[-limit:]


def _recommended_next_action(state: dict[str, Any]) -> DesignNextAction:
    latest_execution_result = dict(state.get("execution_result_handoff") or {})
    latest_findings = dict(latest_execution_result.get("structured_findings") or {})
    design_signal = str(latest_findings.get("design_signal") or "")
    execution_iteration_count = int(state.get("execution_iteration_count") or 0)
    execution_ready_artifacts = _execution_ready_artifacts(list(state.get("artifact_refs") or []))
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
        state.get("latest_turn_action_kind") == "request_execution"
        and state.get("latest_turn_status") == DecisionStatus.FAILED.value
    ):
        return DesignNextAction(
            action_kind="stop",
            summary="Stop after the latest execution request did not complete successfully.",
            rationale="The last execution request failed validation, so the loop should hand off the current state.",
            stop_reason="request_execution_not_completed",
            arguments={},
        )
    if execution_iteration_count >= 3:
        return DesignNextAction(
            action_kind="stop",
            summary="Stop after reaching the execution iteration limit.",
            rationale="Execution results have already been reviewed multiple times; avoid another loop without new evidence.",
            stop_reason="execution_iteration_limit",
            arguments={},
        )
    if not state.get("evidence_refs"):
        return DesignNextAction(
            action_kind="collect_research",
            summary="Collect research evidence before curating the artifact workspace.",
            rationale="No canonical evidence exists for the current objective.",
            arguments={},
        )
    if not state.get("artifact_workspace_summary"):
        return DesignNextAction(
            action_kind="curate_artifacts",
            summary="Curate the current artifacts and references into a usable workspace.",
            rationale="Research evidence exists, but the artifact workspace summary has not been prepared.",
            arguments={},
        )
    if design_signal == "revise":
        return DesignNextAction(
            action_kind="curate_artifacts",
            summary="Re-curate the artifact workspace based on the latest execution findings.",
            rationale="The latest execution findings indicate the workspace needs refinement before reporting.",
            arguments={"curation_goal": str(latest_findings.get("revision_goal") or "Address the latest execution issues.")},
        )
    if not execution_ready_artifacts:
        return DesignNextAction(
            action_kind="curate_artifacts",
            summary="Curate the workspace to identify execution-ready artifacts.",
            rationale="The current workspace has no artifact explicitly marked as usable for execution.",
            arguments={},
        )
    if design_signal == "rerun":
        return DesignNextAction(
            action_kind="request_execution",
            summary="Request a follow-up execution run using a different evaluator or configuration.",
            rationale="The latest execution findings require another evaluation step before design can conclude.",
            arguments={"execution_goal": str(latest_execution_result.get("result_summary") or "Follow up the latest execution finding.")},
        )
    if not state.get("run_summary"):
        return DesignNextAction(
            action_kind="request_execution",
            summary="Route the curated artifact workspace into execution for HPC evaluation.",
            rationale="Execution-ready artifacts exist and no execution result has been recorded.",
            arguments={},
        )
    return DesignNextAction(
        action_kind="stop",
        summary="Stop the loop and package the current design dossier.",
        rationale="The current design state already has a curated artifact workspace and execution outcome.",
        stop_reason="design_loop_complete",
        arguments={},
    )


def _latest_failed_turn(state: dict[str, Any]) -> dict[str, Any] | None:
    status = state.get("latest_turn_status")
    if status != DecisionStatus.FAILED.value:
        return None
    return {
        "action_kind": state.get("latest_turn_action_kind"),
        "status": status,
    }


def _build_design_action_policy(state: dict[str, Any]) -> dict[str, Any]:
    recommended_action = _recommended_next_action(state)
    evidence_refs = list(state.get("evidence_refs") or [])
    artifact_refs = list(state.get("artifact_refs") or [])
    workspace_summary = state.get("artifact_workspace_summary")
    execution_ready_artifacts = _execution_ready_artifacts(artifact_refs)
    latest_execution_result = dict(state.get("execution_result_handoff") or {})
    latest_findings = dict(latest_execution_result.get("structured_findings") or {})
    design_signal = str(latest_findings.get("design_signal") or "")
    latest_failed_turn = _latest_failed_turn(state)

    allowed_actions: list[str] = []
    blocked_actions: list[dict[str, str]] = []

    if latest_failed_turn is not None:
        allowed_actions.append("stop")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "The latest design tool turn failed; stop and surface the failed state instead of retrying implicitly.",
                },
                {
                    "action_kind": "curate_artifacts",
                    "reason": "The latest design tool turn failed; curation should not hide the failed state.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "The latest design tool turn failed; execution should not be requested from a failed design state.",
                },
            ]
        )
    elif int(state.get("execution_iteration_count") or 0) >= 3:
        allowed_actions.append("stop")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "The execution iteration budget has already been reached.",
                },
                {
                    "action_kind": "curate_artifacts",
                    "reason": "The execution iteration budget has already been reached.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "The execution iteration budget has already been reached.",
                },
            ]
        )
    elif not evidence_refs and not state.get("research_summary"):
        allowed_actions.append("collect_research")
        blocked_actions.extend(
            [
                {
                    "action_kind": "curate_artifacts",
                    "reason": "No evidence or artifact exists yet for curation.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "No curated execution-ready artifact exists yet.",
                },
            ]
        )
    elif not workspace_summary:
        allowed_actions.append("curate_artifacts")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "Canonical evidence already exists; move to workspace curation.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "The artifact workspace has not been curated yet.",
                },
            ]
        )
    elif design_signal == "revise":
        allowed_actions.append("curate_artifacts")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "Research evidence already exists; the latest execution finding asks for curation revision.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "The latest execution finding asks for a workspace revision before another run.",
                },
            ]
        )
    elif not execution_ready_artifacts:
        allowed_actions.append("curate_artifacts")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "Research evidence already exists; curation needs to identify execution inputs.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "The current workspace has no execution-ready artifact.",
                },
            ]
        )
    elif not state.get("run_summary") or design_signal == "rerun":
        allowed_actions.append("request_execution")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "Canonical evidence already exists; repeated research is not legal in this state.",
                },
                {
                    "action_kind": "curate_artifacts",
                    "reason": "The workspace already contains execution-ready artifacts.",
                },
            ]
        )
    else:
        allowed_actions.append("stop")
        blocked_actions.extend(
            [
                {
                    "action_kind": "collect_research",
                    "reason": "Research evidence already exists and the design loop has an execution result.",
                },
                {
                    "action_kind": "curate_artifacts",
                    "reason": "The workspace is already curated and execution-ready.",
                },
                {
                    "action_kind": "request_execution",
                    "reason": "An execution result is already recorded; stop and package the current dossier.",
                },
            ]
        )

    return {
        "allowed_actions": allowed_actions,
        "blocked_actions": blocked_actions,
        "recommended_next_action": recommended_action.action_kind,
        "state_machine_guidance": {
            "existing_evidence_count": len(evidence_refs),
            "existing_evidence_ids": [
                str(item.get("evidence_id") or item.get("id") or "")
                for item in evidence_refs
            ],
            "has_artifact_workspace": workspace_summary is not None,
            "artifact_workspace_summary": workspace_summary or {},
            "execution_ready_artifact_ids": [
                str(item.get("artifact_id") or "") for item in execution_ready_artifacts
            ],
            "run_summary": state.get("run_summary") or {},
            "latest_failed_turn": latest_failed_turn,
            "latest_execution_design_signal": design_signal or None,
            "recommended_next_action": recommended_action.action_kind,
            "recommended_action_summary": recommended_action.summary,
        },
    }


def _failed_planner_action(*, summary: str, rationale: str) -> DesignNextAction:
    return DesignNextAction(
        action_kind="stop",
        summary=summary,
        rationale=rationale,
        stop_reason="planner_failed",
        arguments={},
    )


def _diagnostic_observation(
    state: dict[str, Any], observation: dict[str, Any]
) -> dict[str, Any]:
    violation = state.get("planner_contract_violation")
    if not violation:
        return observation
    return {
        **observation,
        "diagnostic_observations": [
            *list(observation.get("diagnostic_observations") or []),
            violation,
        ],
    }


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
    research_summary: dict[str, Any] | None
    evidence_refs: list[dict[str, Any]]
    unresolved_gaps: list[dict[str, Any]]
    artifact_workspace_summary: dict[str, Any] | None
    focused_artifact_ids: list[str]
    run_request: dict[str, Any] | None
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    observation_payload: dict[str, Any] | None
    design_summary: dict[str, Any] | None
    design_handoff: DesignHandoff | None
    execution_handoff: ExecutionHandoff | None
    execution_result_handoff: ExecutionResultHandoff | None
    execution_iteration_count: int
    recommended_next_phase: str | None
    latest_turn_action_kind: str | None
    latest_turn_status: str | None
    allowed_actions: list[str]
    blocked_actions: list[dict[str, Any]]
    recommended_next_action: str | None
    state_machine_guidance: dict[str, Any]
    planner_contract_violation: dict[str, Any] | None


def build_phase_c_design_graph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    tools: dict[str, DesignTool] = {
        "collect_research": ResearchCollectTool(inputs),
    }

    def load_design_context(state: DesignSupervisorState) -> dict[str, Any]:
        episode_id = state["episode_id"]
        snapshot = inputs.host_toolbox.load_canonical_research(episode_id)
        runs = inputs.repositories.runs.list_by_episode(episode_id)
        latest_run = None if not runs else runs[-1]
        design_turns = [
            turn for turn in inputs.repositories.decisions.list_by_episode(episode_id) if turn.phase == GraphPhase.DESIGN.value
        ]
        execution_turns = [
            turn for turn in inputs.repositories.decisions.list_by_episode(episode_id) if turn.phase == GraphPhase.EXECUTION.value
        ]
        turn_count = len(design_turns)
        latest_turn = None if not design_turns else design_turns[-1]
        artifact_refs = inputs.host_toolbox.list_artifacts(episode_id)
        artifact_workspace_summary = {
            "artifact_count": len(artifact_refs),
            "execution_ready_artifact_ids": [
                artifact["artifact_id"]
                for artifact in _execution_ready_artifacts(artifact_refs)
            ],
            "external_reference_artifact_ids": [
                artifact["artifact_id"]
                for artifact in artifact_refs
                if str((artifact.get("provenance") or {}).get("source_type") or "") == "external_reference"
            ],
        }
        focused_artifact_ids = list(artifact_workspace_summary["execution_ready_artifact_ids"] or [artifact["artifact_id"] for artifact in artifact_refs])
        return {
            "current_phase": GraphPhase.DESIGN.value,
            "status": SupervisorStatus.ACTIVE.value,
            "pending_interrupt": state.get("pending_interrupt"),
            "turn_index": turn_count,
            "current_action": None,
            "current_tool_name": None,
            "action_status": None,
            "observation_payload": None,
            "research_summary": snapshot.research_summary,
            "evidence_refs": snapshot.evidence_refs,
            "unresolved_gaps": snapshot.unresolved_gaps,
            "artifact_workspace_summary": artifact_workspace_summary if artifact_refs else None,
            "focused_artifact_ids": focused_artifact_ids,
            "run_summary": None if latest_run is None else latest_run.to_dict(),
            "artifact_refs": artifact_refs,
            "execution_handoff": None,
            "execution_result_handoff": state.get("execution_result_handoff"),
            "execution_iteration_count": len(execution_turns),
            "latest_turn_action_kind": None if latest_turn is None else latest_turn.action_kind,
            "latest_turn_status": None if latest_turn is None else latest_turn.status.value,
            "allowed_actions": [],
            "blocked_actions": [],
            "recommended_next_action": None,
            "state_machine_guidance": {},
            "planner_contract_violation": None,
            "progress": _progress(
                "load_design_context",
                ProgressStatus.RUNNING,
                "Loaded current design context",
            ),
        }

    def diagnose_next_action(state: DesignSupervisorState) -> dict[str, Any]:
        policy = _build_design_action_policy(state)
        allowed_actions = list(policy["allowed_actions"])
        blocked_actions = list(policy["blocked_actions"])
        state_machine_guidance = dict(policy["state_machine_guidance"])
        recommended_next_action = str(policy["recommended_next_action"])
        action_source = "provided"
        planner_contract_violation = None
        planner_failure: dict[str, Any] | None = None
        if state.get("current_action") is not None:
            action = DesignNextAction.model_validate(state["current_action"])
        elif inputs.model_factory is not None:
            action_source = "llm"
            try:
                invoker = inputs.model_factory.create_structured_invoker(purpose="design_next_action")
                action = invoker.invoke_structured(
                    schema=DesignNextAction,
                    system_prompt=(
                        "You are the design loop planner for an enzyme engineering workflow. "
                        "Inspect the current state and return exactly one next action. "
                        "You must choose action_kind from allowed_actions only. "
                        "Do not request collect_research, curate_artifacts, or request_execution when that action is listed in blocked_actions. "
                        "If the recommended_next_action is sufficient, use it. Keep the summary concise."
                    ),
                    user_payload={
                        "episode_id": state.get("episode_id"),
                        "objective": state.get("objective"),
                        "design_brief": state.get("design_brief"),
                        "research_brief": state.get("research_brief"),
                        "allowed_actions": allowed_actions,
                        "blocked_actions": blocked_actions,
                        "recommended_next_action": recommended_next_action,
                        "state_machine_guidance": state_machine_guidance,
                        "research_summary": state.get("research_summary") or {},
                        "evidence_refs": state.get("evidence_refs") or [],
                        "artifact_refs": state.get("artifact_refs") or [],
                        "artifact_workspace_summary": state.get("artifact_workspace_summary") or {},
                        "focused_artifact_ids": state.get("focused_artifact_ids") or [],
                        "run_summary": state.get("run_summary") or {},
                        "execution_result_handoff": state.get("execution_result_handoff") or {},
                        "execution_iteration_count": state.get("execution_iteration_count") or 0,
                    },
                )
            except Exception as exc:
                action = _failed_planner_action(
                    summary="Design planner failed before selecting a legal next action.",
                    rationale="The LLM planner raised an exception; the design loop must surface the failed decision instead of substituting a heuristic action.",
                )
                planner_failure = {
                    "type": "planner_failed",
                    "message": "Design planner raised an exception.",
                    "source": action_source,
                    "error_type": type(exc).__name__,
                    "error": str(exc),
                    "allowed_actions": allowed_actions,
                    "blocked_actions": blocked_actions,
                    "recommended_next_action": recommended_next_action,
                    "retryable": True,
                }
        else:
            action = _failed_planner_action(
                summary="Design planner is not configured.",
                rationale="A configured model factory is required to choose the next design action; deterministic fallback planning has been removed.",
            )
            planner_failure = {
                "type": "planner_failed",
                "message": "Design planner requires a configured model_factory.",
                "source": "configuration",
                "error_type": "missing_model_factory",
                "allowed_actions": allowed_actions,
                "blocked_actions": blocked_actions,
                "recommended_next_action": recommended_next_action,
                "retryable": False,
            }
        if planner_failure is None and action.action_kind not in allowed_actions:
            original_action = action
            planner_contract_violation = {
                "type": "planner_contract_violation",
                "message": "Design planner returned an action outside the allowed action set.",
                "source": action_source,
                "original_action": original_action.model_dump(),
                "allowed_actions": allowed_actions,
                "blocked_actions": blocked_actions,
                "recommended_next_action": recommended_next_action,
            }
        failed_observation = planner_failure or planner_contract_violation
        action_status = (
            DecisionStatus.FAILED.value
            if failed_observation is not None
            else DecisionStatus.PROPOSED.value
        )
        return {
            "current_action": action.model_dump(),
            "action_status": action_status,
            "action_error": None if failed_observation is None else str(failed_observation["type"]),
            "current_tool_name": None,
            "allowed_actions": allowed_actions,
            "blocked_actions": blocked_actions,
            "recommended_next_action": recommended_next_action,
            "state_machine_guidance": state_machine_guidance,
            "planner_contract_violation": planner_contract_violation,
            "observation_payload": failed_observation,
            "design_summary": None
            if failed_observation is None
            else {
                "outcome": "planner_failed",
                "message": str(failed_observation["message"]),
            },
            "progress": _progress(
                "diagnose_next_action",
                ProgressStatus.FAILED
                if failed_observation is not None
                else ProgressStatus.RUNNING,
                str(failed_observation["message"])
                if failed_observation is not None
                else f"Diagnosed next design action: {action.action_kind}",
            ),
        }

    def validate_action(
        state: DesignSupervisorState,
    ) -> Command[Literal["dispatch_action", "persist_turn", "finalize_design"]]:
        if state.get("current_action") is None:
            raise RuntimeError("design action validation requires current_action")
        action = DesignNextAction.model_validate(state["current_action"])
        if state.get("action_status") == DecisionStatus.FAILED.value:
            return Command(
                update={
                    "current_action": action.model_dump(),
                    "current_tool_name": None,
                    "action_status": DecisionStatus.FAILED.value,
                    "progress": _progress(
                        "validate_action",
                        ProgressStatus.FAILED,
                        str(
                            (state.get("observation_payload") or {}).get("message")
                            or "Design planner failed"
                        ),
                    ),
                },
                goto="persist_turn",
            )
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
                    }
                    if not state.get("planner_contract_violation")
                    else _diagnostic_observation(
                        state,
                        {
                            "summary": action.summary,
                            "message": action.stop_reason or "requested_stop",
                        },
                    ),
                    "action_status": DecisionStatus.COMPLETED.value,
                    "progress": _progress(
                        "validate_action",
                        ProgressStatus.SUCCEEDED,
                        "Design loop chose to stop and finalize the dossier",
                    ),
                },
                goto="persist_turn",
            )

        if action.action_kind == "request_execution":
            execution_ready_artifacts = _required_execution_artifacts(list(state.get("artifact_refs") or []))
            if not execution_ready_artifacts:
                observation = {
                    "summary": "Cannot request execution without an execution-ready artifact.",
                    "message": "no execution-ready artifact",
                }
                action_status = DecisionStatus.FAILED
        elif action.action_kind == "collect_research":
            tool_name = "collect_research"
        elif action.action_kind == "curate_artifacts":
            if not state.get("evidence_refs") and not state.get("artifact_refs"):
                observation = {
                    "summary": "Cannot curate artifacts until some evidence or artifact exists.",
                    "message": "missing evidence and artifacts",
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
                    "observation_payload": _diagnostic_observation(state, observation),
                    "progress": _progress(
                        "validate_action",
                        ProgressStatus.FAILED,
                        observation["summary"],
                    ),
                },
                goto="persist_turn",
            )

        return Command(
            update={
                "current_action": action.model_dump(),
                "current_tool_name": tool_name,
                "current_tool_requires_clarification": False,
                "progress": _progress(
                    "validate_action",
                    ProgressStatus.RUNNING,
                    f"Validated action {action.action_kind}",
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
                        }
                        if not state.get("planner_contract_violation")
                        else _diagnostic_observation(
                            state,
                            {
                                "summary": str(tool_result.get("summary") or "Research collection failed."),
                                "message": str(tool_result.get("completion_reason") or "research_failed"),
                                "status": completion_status,
                                "completion_reason": tool_result.get("completion_reason"),
                                "clarification_question": tool_result.get("clarification_question"),
                            },
                        ),
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
                    source_ref = SourceRef(
                        source_ref_id=f"{evidence_id}-source-{source_index}",
                        evidence_id=evidence_id,
                        episode_id=state["episode_id"],
                        title=str(source["title"]),
                        locator=str(source["locator"]),
                        kind=SourceRefKind(str(source["kind"])),
                        created_at=str(now),
                    )
                    inputs.repositories.source_refs.save(source_ref)
                    inputs.host_toolbox.register_artifact(
                        artifact_id=_build_source_artifact_id(source_ref.source_ref_id),
                        episode_id=state["episode_id"],
                        kind=ArtifactKind.RESULT,
                        storage_uri=source_ref.locator,
                        created_at=str(now),
                        title=source_ref.title,
                        description=f"External reference mirrored from research evidence {evidence_id}.",
                        tags=["research", "reference", source_ref.kind.value],
                        provenance={
                            "source_type": "external_reference",
                            "source_ref_id": source_ref.source_ref_id,
                            "evidence_id": evidence_id,
                        },
                        availability={"local_readable": False, "execution_input": True},
                        metadata={"locator": source_ref.locator, "kind": source_ref.kind.value},
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
                "artifact_refs": inputs.host_toolbox.list_artifacts(state["episode_id"]),
                "artifact_workspace_summary": {
                    "artifact_count": len(inputs.host_toolbox.list_artifacts(state["episode_id"])),
                    "execution_ready_artifact_ids": [
                        artifact["artifact_id"]
                        for artifact in _execution_ready_artifacts(inputs.host_toolbox.list_artifacts(state["episode_id"]))
                    ],
                    "external_reference_artifact_ids": [
                        artifact["artifact_id"]
                        for artifact in inputs.host_toolbox.list_artifacts(state["episode_id"])
                        if str((artifact.get("provenance") or {}).get("source_type") or "") == "external_reference"
                    ],
                },
                "observation_payload": _diagnostic_observation(state, observation),
                "action_status": status.value,
                "progress": _progress(
                    "dispatch_action",
                    ProgressStatus.SUCCEEDED,
                    observation["summary"],
                ),
            }, goto="persist_turn")

        if action.action_kind == "curate_artifacts":
            artifact_refs = inputs.host_toolbox.list_artifacts(state["episode_id"])
            execution_ready_artifacts = _execution_ready_artifacts(artifact_refs)
            workspace_summary = {
                "artifact_count": len(artifact_refs),
                "execution_ready_artifact_ids": [artifact["artifact_id"] for artifact in execution_ready_artifacts],
                "external_reference_artifact_ids": [
                    artifact["artifact_id"]
                    for artifact in artifact_refs
                    if str((artifact.get("provenance") or {}).get("source_type") or "") == "external_reference"
                ],
                "goal": str(action.arguments.get("curation_goal") or "Prepare a reusable artifact workspace."),
            }
            observation = {
                "summary": f"Curated {len(artifact_refs)} artifact(s) into the working workspace.",
                "artifact_workspace_summary": workspace_summary,
                "focused_artifact_ids": [artifact["artifact_id"] for artifact in execution_ready_artifacts]
                or [artifact["artifact_id"] for artifact in artifact_refs],
            }
            return Command(update={
                "artifact_refs": artifact_refs,
                "artifact_workspace_summary": workspace_summary,
                "focused_artifact_ids": list(observation["focused_artifact_ids"]),
                "execution_result_handoff": None,
                "observation_payload": _diagnostic_observation(state, observation),
                "action_status": status.value,
                "progress": _progress("dispatch_action", ProgressStatus.SUCCEEDED, observation["summary"]),
            }, goto="persist_turn")

        if action.action_kind == "request_execution":
            artifact_refs = inputs.host_toolbox.list_artifacts(state["episode_id"])
            focused_artifact_ids = set(state.get("focused_artifact_ids") or [])
            focused_artifacts = [artifact for artifact in artifact_refs if artifact["artifact_id"] in focused_artifact_ids]
            required_artifacts = _required_execution_artifacts(focused_artifacts or artifact_refs)
            if not required_artifacts:
                return Command(update={
                    "action_status": DecisionStatus.FAILED.value,
                    "observation_payload": {
                        "summary": "Could not identify an execution-ready artifact for handoff.",
                        "message": "missing execution-ready artifact",
                    }
                    if not state.get("planner_contract_violation")
                    else _diagnostic_observation(
                        state,
                        {
                            "summary": "Could not identify an execution-ready artifact for handoff.",
                            "message": "missing execution-ready artifact",
                        },
                    ),
                    "progress": _progress("dispatch_action", ProgressStatus.FAILED, "Execution handoff failed"),
                }, goto="persist_turn")
            execution_handoff: ExecutionHandoff = {
                "execution_goal": str(action.arguments.get("execution_goal") or "Evaluate the focused artifact set with an HPC tool."),
                "question_to_answer": str(action.arguments.get("question_to_answer") or "Which fast evaluator should run next for this artifact set?"),
                "required_artifact_ids": [artifact["artifact_id"] for artifact in required_artifacts],
                "context_artifact_ids": [
                    artifact["artifact_id"]
                    for artifact in artifact_refs
                    if artifact["artifact_id"] not in {item["artifact_id"] for item in required_artifacts}
                ],
                "preferred_stage_tags": list(action.arguments.get("preferred_stage_tags") or ["execution", "evaluator"]),
                "preferred_capability_tags": list(action.arguments.get("preferred_capability_tags") or ["pocket_detection"]),
                "recommended_next_phase": GraphPhase.EXECUTION.value,
            }
            return Command(update={
                "execution_handoff": execution_handoff,
                "execution_result_handoff": None,
                "observation_payload": _diagnostic_observation(
                    state,
                    {
                        "summary": "Prepared execution handoff for the curated artifact workspace.",
                        "execution_goal": execution_handoff["execution_goal"],
                        "required_artifact_ids": execution_handoff["required_artifact_ids"],
                    },
                ),
                "action_status": DecisionStatus.COMPLETED.value,
                "progress": _progress("dispatch_action", ProgressStatus.SUCCEEDED, "Prepared execution handoff"),
            }, goto="persist_turn")

        return Command(update={
            "action_status": DecisionStatus.FAILED.value,
            "observation_payload": {
                "summary": f"Action {action.action_kind} could not be dispatched.",
                "message": "dispatch failure",
            }
            if not state.get("planner_contract_violation")
            else _diagnostic_observation(
                state,
                {
                    "summary": f"Action {action.action_kind} could not be dispatched.",
                    "message": "dispatch failure",
                },
            ),
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
            action_payload={
                **action.model_dump(),
                "focused_artifact_ids": list(state.get("focused_artifact_ids") or []),
                "state_machine_policy": {
                    "allowed_actions": list(state.get("allowed_actions") or []),
                    "blocked_actions": list(state.get("blocked_actions") or []),
                    "recommended_next_action": state.get("recommended_next_action"),
                    "state_machine_guidance": dict(state.get("state_machine_guidance") or {}),
                },
                "planner_contract_violation": state.get("planner_contract_violation"),
            },
            observation_payload=state.get("observation_payload"),
            created_at=_utc_now_iso(),
        )
        inputs.repositories.decisions.save(decision)
        return {
            "turn_index": turn_index,
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
        if action_status is DecisionStatus.FAILED:
            return "finalize_design"
        if action.action_kind == "stop":
            return "finalize_design"
        if state.get("execution_handoff") is not None and action.action_kind == "request_execution" and action_status is DecisionStatus.COMPLETED:
            return "finalize_design"
        return "load_design_context"

    def finalize_design(state: DesignSupervisorState) -> dict[str, Any]:
        if state.get("execution_handoff") is not None:
            return {
                "execution_handoff": state["execution_handoff"],
                "recommended_next_phase": GraphPhase.EXECUTION.value,
                "status": SupervisorStatus.COMPLETED.value,
                "progress": _progress(
                    "finalize_design",
                    ProgressStatus.SUCCEEDED,
                    "Prepared design-to-execution handoff",
                ),
            }

        design_summary = state.get("design_summary") or {
            "outcome": "ready_for_report",
            "message": "Design loop completed and packaged a final dossier.",
        }
        recent_turns = _recent_turns(inputs, state["episode_id"])
        design_handoff: DesignHandoff = {
            "artifact_workspace_summary": dict(state.get("artifact_workspace_summary") or {}),
            "run_summary": state.get("run_summary"),
            "artifact_refs": list(state.get("artifact_refs") or []),
            "design_summary": {
                **design_summary,
                "research_summary": state.get("research_summary"),
                "unresolved_gaps": list(state.get("unresolved_gaps") or []),
            },
            "recent_turns": recent_turns,
            "recommended_next_phase": GraphPhase.REPORT_REVIEW.value,
        }
        return {
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
    graph.add_node("dispatch_action", dispatch_action)
    graph.add_node("clarification_gate", clarification_gate)
    graph.add_node("persist_turn", persist_turn)
    graph.add_node("finalize_design", finalize_design)

    graph.add_edge(START, "load_design_context")
    graph.add_edge("load_design_context", "diagnose_next_action")
    graph.add_edge("diagnose_next_action", "validate_action")
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
