from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal
from typing import TypedDict

from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Command
from langgraph.types import interrupt
from openzyme_domain import Approval
from openzyme_domain import ApprovalStatus
from openzyme_domain import ArtifactKind
from openzyme_domain import ArtifactRecord
from openzyme_domain import Decision
from openzyme_domain import DecisionStatus
from openzyme_domain import Run
from openzyme_runtime import ExecutionPlanDraft
from openzyme_runtime import ExecutionResultHandoff
from openzyme_runtime import HpcCatalogQuery
from openzyme_runtime.bootstrap import GraphAssemblyInputs

from .state import GraphPhase
from .state import InterruptType
from .state import ProgressStatus
from .state import SupervisorStatus


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _progress(active_node: str, status: ProgressStatus, message: str) -> dict[str, Any]:
    return {
        "phase": GraphPhase.EXECUTION.value,
        "active_node": active_node,
        "status": status.value,
        "updated_at": _utc_now_iso(),
        "message": message,
    }


def _build_execution_approval_id(episode_id: str, turn_index: int) -> str:
    return f"{episode_id}-execution-approval-{turn_index}"


def _build_execution_decision_id(episode_id: str, turn_index: int) -> str:
    return f"{episode_id}-execution-turn-{turn_index}"


def _build_artifact_id(run_id: str, index: int) -> str:
    return f"{run_id}-artifact-{index}"


def _artifact_kind_from_path(storage_uri: str) -> ArtifactKind:
    path = storage_uri.lower()
    if path.endswith(".log") or "/logs/" in path:
        return ArtifactKind.LOG
    if path.endswith((".pdb", ".cif", ".mol2", ".sdf")):
        return ArtifactKind.STRUCTURE
    return ArtifactKind.RESULT


class ExecutionSubgraphState(TypedDict, total=False):
    episode_id: str
    project_id: str
    objective: str
    design_brief: str
    research_brief: str
    current_phase: str
    status: str
    progress: dict[str, Any]
    pending_interrupt: dict[str, Any] | None
    execution_handoff: dict[str, Any] | None
    execution_result_handoff: dict[str, Any] | None
    current_plan: dict[str, Any] | None
    current_plan_status: str | None
    observation_payload: dict[str, Any] | None
    turn_index: int
    approval_id: str | None
    approval_summary: str | None
    discovered_tools: list[dict[str, Any]]
    selected_skill: dict[str, Any] | None
    planner_trace: dict[str, Any]
    run_request: dict[str, Any] | None
    run_summary: dict[str, Any] | None
    artifact_refs: list[dict[str, Any]]
    recommended_next_phase: str | None


class SearchCatalogArgs(TypedDict, total=False):
    query: str
    execution_support: str


@dataclass(frozen=True, slots=True)
class SearchCatalogTool:
    inputs: GraphAssemblyInputs
    name: str = "hpc.search_catalog"
    description: str = "Search the HPC catalog and return concise tool summaries."

    def invoke(self, *, args: dict[str, Any]) -> dict[str, Any]:
        provider = self.inputs.hpc_catalog_provider
        if provider is None:
            return {"tools": [], "summary": "HPC catalog provider unavailable."}
        query = HpcCatalogQuery(
            query=str(args.get("query") or ""),
            execution_support=None if args.get("execution_support") in {None, ""} else str(args["execution_support"]),
        )
        results = provider.search_catalog(query)
        return {
            "summary": f"Found {len(results)} HPC tool(s).",
            "tools": [entry.model_dump() for entry in results],
        }


@dataclass(frozen=True, slots=True)
class ReadSkillTool:
    inputs: GraphAssemblyInputs
    name: str = "hpc.read_skill"
    description: str = "Read one HPC tool skill document by tool id."

    def invoke(self, *, args: dict[str, Any]) -> dict[str, Any]:
        provider = self.inputs.hpc_catalog_provider
        if provider is None:
            return {"summary": "HPC catalog provider unavailable.", "tool_id": None, "skill": ""}
        tool_id = str(args.get("tool_id") or "").strip()
        if not tool_id:
            return {"summary": "Missing tool id.", "tool_id": None, "skill": ""}
        return {
            "summary": f"Loaded skill for {tool_id}.",
            "tool_id": tool_id,
            "skill": provider.read_skill(tool_id).model_dump(),
        }


def _build_langchain_tool(tool_def: Any) -> Any:
    from langchain_core.tools import StructuredTool
    from pydantic import BaseModel
    from pydantic import Field

    if tool_def.name == "hpc.search_catalog":
        class SearchSchema(BaseModel):
            query: str = ""
            execution_support: str | None = Field(default=None)
        args_schema = SearchSchema
    else:
        class ReadSchema(BaseModel):
            tool_id: str
        args_schema = ReadSchema

    def _invoke(**kwargs: Any) -> str:
        return json.dumps(tool_def.invoke(args=kwargs), ensure_ascii=True, sort_keys=True)

    return StructuredTool.from_function(
        func=_invoke,
        name=tool_def.name,
        description=tool_def.description,
        args_schema=args_schema,
    )


def _fallback_execution_plan(state: ExecutionSubgraphState) -> ExecutionPlanDraft:
    discovered = list(state.get("discovered_tools") or [])
    preferred = next(
        (tool for tool in discovered if tool.get("tool_id") == "fpocket"),
        None,
    )
    tool_id = "fpocket" if preferred is None else str(preferred["tool_id"])
    required_artifact_ids = list((state.get("execution_handoff") or {}).get("required_artifact_ids") or [])
    primary_ref = None if not required_artifact_ids else required_artifact_ids[0]
    return ExecutionPlanDraft(
        catalog_tool_id=tool_id,
        rationale="Use the runnable pocket-detection evaluator as the default execution path.",
        tool_inputs={"structure_path": f"{str(primary_ref or 'input_structure')}.pdb"},
        execution_mode="auto",
        expected_result_summary="Return a quick evaluator run for the selected artifact set.",
        planner_summary="Fallback planner selected the default runnable evaluator.",
    )


def build_execution_subgraph(inputs: GraphAssemblyInputs, *, include_checkpointer: bool = True) -> Any:
    search_tool = SearchCatalogTool(inputs)
    read_tool = ReadSkillTool(inputs)

    def load_execution_context(state: ExecutionSubgraphState) -> dict[str, Any]:
        return {
            "current_phase": GraphPhase.EXECUTION.value,
            "status": SupervisorStatus.ACTIVE.value,
            "turn_index": len(
                [
                    turn for turn in inputs.repositories.decisions.list_by_episode(state["episode_id"])
                    if turn.phase == GraphPhase.EXECUTION.value
                ]
            ),
            "current_plan": None,
            "run_request": None,
            "run_summary": None,
            "artifact_refs": [],
            "planner_trace": {"catalog_queries": [], "skill_reads": [], "selected_tool_id": None, "planner_summary": None},
            "recommended_next_phase": None,
            "progress": _progress("load_execution_context", ProgressStatus.RUNNING, "Loaded execution context"),
        }

    def discover_tools(state: ExecutionSubgraphState) -> dict[str, Any]:
        handoff = state.get("execution_handoff") or {}
        query = str(handoff.get("execution_goal") or "")
        result = search_tool.invoke(args={"query": query})
        return {
            "discovered_tools": list(result.get("tools") or []),
            "observation_payload": {"summary": result["summary"], "catalog_search": {"query": query}},
            "progress": _progress("discover_tools", ProgressStatus.SUCCEEDED, result["summary"]),
        }

    def select_execution_plan(state: ExecutionSubgraphState) -> dict[str, Any]:
        plan = _fallback_execution_plan(state)
        selected_skill = None
        planner_trace = {
            "catalog_queries": [{"query": str((state.get("execution_handoff") or {}).get("execution_goal") or "")}],
            "skill_reads": [],
            "selected_tool_id": plan.catalog_tool_id,
            "planner_summary": "Fallback execution planner selected a runnable tool.",
        }
        if inputs.model_factory is not None:
            try:
                invoker = inputs.model_factory.create_tool_calling_invoker(purpose="execution_planner")
                messages = [
                    {
                        "role": "user",
                        "content": json.dumps(
                            {
                        "execution_handoff": state.get("execution_handoff") or {},
                        "discovered_tools": state.get("discovered_tools") or [],
                        "available_artifacts": inputs.host_toolbox.resolve_artifacts(
                            state["episode_id"],
                            list((state.get("execution_handoff") or {}).get("required_artifact_ids") or [])
                            + list((state.get("execution_handoff") or {}).get("context_artifact_ids") or []),
                        ),
                    },
                    ensure_ascii=True,
                    sort_keys=True,
                        ),
                    }
                ]
                for _ in range(2):
                    response = invoker.invoke_with_tools(
                        system_prompt=(
                            "You are an execution planner for HPC evaluation. "
                            "Use hpc.search_catalog to inspect available tools, "
                            "use hpc.read_skill for one tool when needed, and stop once you can choose one runnable tool."
                        ),
                        messages=messages,
                        tools=[_build_langchain_tool(search_tool), _build_langchain_tool(read_tool)],
                    )
                    tool_calls = getattr(response, "tool_calls", None) or response.get("tool_calls", [])
                    if not tool_calls:
                        break
                    tool_results: list[dict[str, Any]] = []
                    for tool_call in tool_calls:
                        name = str(tool_call["name"])
                        args = dict(tool_call.get("args") or {})
                        if name == search_tool.name:
                            planner_trace["catalog_queries"].append(args)
                            tool_results.append(search_tool.invoke(args=args))
                        if name == read_tool.name:
                            skill_result = read_tool.invoke(args=args)
                            selected_skill = dict(skill_result.get("skill") or {})
                            planner_trace["skill_reads"].append({"tool_id": skill_result.get("tool_id")})
                            tool_results.append(skill_result)
                    messages.append({"role": "assistant", "content": json.dumps({"tool_calls": tool_calls}, ensure_ascii=True, sort_keys=True)})
                    messages.append({"role": "user", "content": json.dumps({"tool_results": tool_results}, ensure_ascii=True, sort_keys=True)})
                structured_invoker = inputs.model_factory.create_structured_invoker(purpose="execution_plan")
                plan = structured_invoker.invoke_structured(
                    schema=ExecutionPlanDraft,
                    system_prompt=(
                        "Choose one runnable HPC catalog tool and return the execution plan. "
                        "Only choose a tool that is marked runnable in the discovered summaries."
                    ),
                    user_payload={
                        "execution_handoff": state.get("execution_handoff") or {},
                        "discovered_tools": state.get("discovered_tools") or [],
                        "available_artifacts": inputs.host_toolbox.resolve_artifacts(
                            state["episode_id"],
                            list((state.get("execution_handoff") or {}).get("required_artifact_ids") or [])
                            + list((state.get("execution_handoff") or {}).get("context_artifact_ids") or []),
                        ),
                        "selected_skill": selected_skill,
                    },
                )
                planner_trace["selected_tool_id"] = plan.catalog_tool_id
                planner_trace["planner_summary"] = f"Planner selected {plan.catalog_tool_id} after querying catalog data."
                plan.planner_summary = str(planner_trace["planner_summary"])
            except Exception:
                plan = _fallback_execution_plan(state)
        if selected_skill is None and plan.catalog_tool_id:
            try:
                selected_skill = read_tool.invoke(args={"tool_id": plan.catalog_tool_id}).get("skill")
                planner_trace["skill_reads"].append({"tool_id": plan.catalog_tool_id})
            except Exception:
                selected_skill = None
        return {
            "current_plan": plan.model_dump(),
            "selected_skill": selected_skill,
            "planner_trace": planner_trace,
            "current_plan_status": DecisionStatus.PROPOSED.value,
            "progress": _progress("select_execution_plan", ProgressStatus.SUCCEEDED, f"Selected execution tool {plan.catalog_tool_id}"),
        }

    def validate_execution_plan(state: ExecutionSubgraphState) -> Command[Literal["prepare_approval", "finalize_execution"]]:
        plan = ExecutionPlanDraft.model_validate(state.get("current_plan") or _fallback_execution_plan(state).model_dump())
        provider = inputs.hpc_catalog_provider
        if provider is None or not hasattr(provider, "get_entry"):
            return Command(
                update={
                    "current_plan": plan.model_dump(),
                    "current_plan_status": DecisionStatus.FAILED.value,
                    "observation_payload": {"summary": "HPC catalog provider unavailable."},
                    "progress": _progress("validate_execution_plan", ProgressStatus.FAILED, "Execution planning failed"),
                },
                goto="finalize_execution",
            )
        entry = provider.get_entry(plan.catalog_tool_id)  # type: ignore[attr-defined]
        if entry is None:
            return Command(
                update={
                    "current_plan": plan.model_dump(),
                    "current_plan_status": DecisionStatus.FAILED.value,
                    "observation_payload": {"summary": f"Unknown HPC tool {plan.catalog_tool_id}."},
                    "progress": _progress("validate_execution_plan", ProgressStatus.FAILED, "Unknown execution tool"),
                },
                goto="finalize_execution",
            )
        if str(entry.get("execution_support")) != "runnable":
            return Command(
                update={
                    "current_plan": plan.model_dump(),
                    "current_plan_status": DecisionStatus.FAILED.value,
                    "observation_payload": {"summary": f"{plan.catalog_tool_id} is discovery-only in V1."},
                    "progress": _progress("validate_execution_plan", ProgressStatus.FAILED, "Execution tool is not runnable"),
                },
                goto="finalize_execution",
            )
        previous_execution_turns = [
            turn for turn in inputs.repositories.decisions.list_by_episode(state["episode_id"])
            if turn.phase == GraphPhase.EXECUTION.value and turn.action_payload is not None
        ]
        if previous_execution_turns:
            latest_turn = previous_execution_turns[-1]
            latest_payload = dict(latest_turn.action_payload or {})
            same_required_artifacts = list((state.get("execution_handoff") or {}).get("required_artifact_ids") or []) == list(
                latest_payload.get("required_artifact_ids") or []
            )
            same_tool = str(latest_payload.get("catalog_tool_id") or "") == plan.catalog_tool_id
            same_inputs = dict(latest_payload.get("tool_inputs") or {}) == dict(plan.tool_inputs)
            if latest_turn.status is DecisionStatus.COMPLETED and same_required_artifacts and same_tool and same_inputs:
                return Command(
                    update={
                        "current_plan": plan.model_dump(),
                        "current_plan_status": DecisionStatus.FAILED.value,
                        "observation_payload": {"summary": f"Repeated execution plan {plan.catalog_tool_id} was rejected without new rationale."},
                        "progress": _progress("validate_execution_plan", ProgressStatus.FAILED, "Repeated execution plan rejected"),
                    },
                    goto="finalize_execution",
                )
        return Command(
            update={
                "current_plan": plan.model_dump(),
                "approval_summary": f"Approve execution tool {plan.catalog_tool_id}",
                "progress": _progress("validate_execution_plan", ProgressStatus.WAITING, "Execution plan requires approval"),
            },
            goto="prepare_approval",
        )

    def prepare_approval(state: ExecutionSubgraphState) -> dict[str, Any]:
        next_turn = int(state.get("turn_index", 0)) + 1
        approval_id = _build_execution_approval_id(state["episode_id"], next_turn)
        requested_action = str(state.get("approval_summary") or "Approve execution run")
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
            "status": SupervisorStatus.INTERRUPTED.value,
            "pending_interrupt": {
                "type": InterruptType.APPROVAL.value,
                "episode_id": state["episode_id"],
                "phase": GraphPhase.EXECUTION.value,
                "approval_id": approval_id,
                "requested_action": requested_action,
            },
            "progress": _progress("approval_gate", ProgressStatus.WAITING, "Waiting for execution approval"),
        }

    def approval_gate(state: ExecutionSubgraphState) -> Command[Literal["compile_execution_request", "finalize_execution"]]:
        decision = interrupt(state["pending_interrupt"])
        approved = bool(decision.get("approved")) if isinstance(decision, dict) else bool(decision)
        requested_action = str(state.get("approval_summary") or "Approve execution run")
        inputs.repositories.approvals.save(
            Approval(
                approval_id=str(state["approval_id"]),
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
                    "pending_interrupt": None,
                    "status": SupervisorStatus.ACTIVE.value,
                    "current_plan_status": DecisionStatus.REJECTED.value,
                    "observation_payload": {"summary": "Execution approval rejected."},
                    "progress": _progress("approval_gate", ProgressStatus.FAILED, "Execution approval rejected"),
                },
                goto="finalize_execution",
            )
        return Command(
            update={
                "pending_interrupt": None,
                "status": SupervisorStatus.ACTIVE.value,
                "progress": _progress("approval_gate", ProgressStatus.RUNNING, "Execution approval received"),
            },
            goto="compile_execution_request",
        )

    def compile_execution_request_node(state: ExecutionSubgraphState) -> Command[Literal["submit_execution", "finalize_execution"]]:
        plan = ExecutionPlanDraft.model_validate(state["current_plan"])
        try:
            if inputs.hpc_execution_registry is None:
                raise ValueError("HPC execution registry unavailable.")
            request = inputs.hpc_execution_registry.compile_request(
                tool_id=plan.catalog_tool_id,
                plan=plan,
                handoff={"episode_id": state["episode_id"], **dict(state["execution_handoff"] or {})},
                host_toolbox=inputs.host_toolbox,
            )
        except Exception as exc:
            return Command(
                update={
                    "current_plan_status": DecisionStatus.FAILED.value,
                    "observation_payload": {"summary": str(exc)},
                    "progress": _progress("compile_execution_request", ProgressStatus.FAILED, "Execution request compilation failed"),
                },
                goto="finalize_execution",
            )
        return Command(
            update={
                "run_request": request,
                "progress": _progress("compile_execution_request", ProgressStatus.SUCCEEDED, "Compiled execution request"),
            },
            goto="submit_execution",
        )

    def submit_execution(state: ExecutionSubgraphState) -> Command[Literal["finalize_execution"]]:
        if inputs.execution_adapter is None:
            return Command(
                update={
                    "current_plan_status": DecisionStatus.FAILED.value,
                    "observation_payload": {"summary": "Execution adapter unavailable."},
                    "progress": _progress("submit_execution", ProgressStatus.FAILED, "Execution adapter unavailable"),
                },
                goto="finalize_execution",
            )
        plan = ExecutionPlanDraft.model_validate(state["current_plan"])
        outcome = inputs.execution_adapter.submit_execution(state["episode_id"], dict(state["run_request"] or {}))
        created_at = _utc_now_iso()
        run_summary = {
            "run_id": outcome.run_id,
            "status": outcome.status.value,
            "execution_mode": outcome.execution_mode,
            "remote_run_dir": outcome.remote_run_dir,
        }
        inputs.repositories.runs.save(
            Run(
                run_id=outcome.run_id,
                episode_id=state["episode_id"],
                approval_id=state.get("approval_id"),
                status=outcome.status,
                execution_mode=outcome.execution_mode,
                created_at=created_at,
                completed_at=created_at if outcome.status.is_terminal else None,
            )
        )
        artifact_refs: list[dict[str, Any]] = []
        for index, artifact in enumerate(outcome.artifacts, start=1):
            record = ArtifactRecord(
                artifact_id=_build_artifact_id(outcome.run_id, index),
                episode_id=state["episode_id"],
                run_id=outcome.run_id,
                kind=_artifact_kind_from_path(artifact.storage_uri),
                storage_uri=artifact.storage_uri,
                created_at=created_at,
                title=artifact.relative_path,
                description=f"Execution output artifact {artifact.relative_path} from run {outcome.run_id}.",
                tags=("execution", "generated", plan.catalog_tool_id),
                provenance={"source_type": "generated", "catalog_tool_id": plan.catalog_tool_id, "run_id": outcome.run_id},
                availability={"local_readable": True, "execution_input": False},
                metadata={"relative_path": artifact.relative_path},
            )
            inputs.repositories.artifact_records.save(record)
            artifact_refs.append(record.to_dict())
        output_artifact_ids = [artifact["artifact_id"] for artifact in artifact_refs]
        parsed_result = (
            inputs.hpc_execution_registry.parse_result(
                tool_id=plan.catalog_tool_id,
                outcome=outcome,
                plan=plan,
                artifact_refs=artifact_refs,
            )
            if inputs.hpc_execution_registry is not None
            else ExecutionResultHandoff(
                catalog_tool_id=plan.catalog_tool_id,
                result_summary="Execution submitted and recorded.",
                structured_findings={"design_signal": "proceed"},
            )
        )
        return Command(
            update={
                "run_summary": run_summary,
                "artifact_refs": artifact_refs,
                "current_plan_status": DecisionStatus.COMPLETED.value,
                "observation_payload": {
                    "summary": parsed_result.result_summary,
                    "planner_trace": dict(state.get("planner_trace") or {}),
                    "structured_findings": parsed_result.structured_findings,
                    "output_artifact_ids": output_artifact_ids,
                },
                "progress": _progress("submit_execution", ProgressStatus.SUCCEEDED, "Execution submitted"),
            },
            goto="finalize_execution",
        )

    def finalize_execution(state: ExecutionSubgraphState) -> dict[str, Any]:
        plan = state.get("current_plan") or {}
        status = str(state.get("current_plan_status") or DecisionStatus.FAILED.value)
        observation = dict(state.get("observation_payload") or {})
        return {
            "execution_result_handoff": {
                "catalog_tool_id": plan.get("catalog_tool_id"),
                "result_summary": str(observation.get("summary") or "Execution finished."),
                "run_summary": state.get("run_summary"),
                "artifact_refs": list(state.get("artifact_refs") or []),
                "output_artifact_ids": list(observation.get("output_artifact_ids") or []),
                "structured_findings": dict(observation.get("structured_findings") or {}),
                "status": status,
                "recommended_next_phase": GraphPhase.DESIGN.value,
            },
            "recommended_next_phase": GraphPhase.DESIGN.value,
            "status": SupervisorStatus.COMPLETED.value,
            "progress": _progress("finalize_execution", ProgressStatus.SUCCEEDED, "Execution handoff prepared for design"),
        }

    def persist_turn(state: ExecutionSubgraphState) -> dict[str, Any]:
        plan = state.get("current_plan") or {}
        turn_index = int(state.get("turn_index", 0)) + 1
        inputs.repositories.decisions.save(
            Decision(
                decision_id=_build_execution_decision_id(state["episode_id"], turn_index),
                episode_id=state["episode_id"],
                project_id=state.get("project_id"),
                phase=GraphPhase.EXECUTION.value,
                turn_index=turn_index,
                action_kind=str(plan.get("catalog_tool_id") or "execution"),
                status=DecisionStatus(str(state.get("current_plan_status") or DecisionStatus.COMPLETED.value)),
                summary=str((state.get("observation_payload") or {}).get("summary") or "Execution turn recorded."),
                rationale=str(plan.get("rationale") or "Execution planning result."),
                action_payload=None
                if not plan
                else {
                    **plan,
                    "required_artifact_ids": list((state.get("execution_handoff") or {}).get("required_artifact_ids") or []),
                    "context_artifact_ids": list((state.get("execution_handoff") or {}).get("context_artifact_ids") or []),
                },
                observation_payload={
                    **dict(state.get("observation_payload") or {}),
                    "planner_trace": dict(state.get("planner_trace") or {}),
                    "selected_skill": state.get("selected_skill"),
                },
                created_at=_utc_now_iso(),
            )
        )
        return {"turn_index": turn_index}

    graph = StateGraph(ExecutionSubgraphState)
    graph.add_node("load_execution_context", load_execution_context)
    graph.add_node("discover_tools", discover_tools)
    graph.add_node("select_execution_plan", select_execution_plan)
    graph.add_node("validate_execution_plan", validate_execution_plan)
    graph.add_node("prepare_approval", prepare_approval)
    graph.add_node("approval_gate", approval_gate)
    graph.add_node("compile_execution_request", compile_execution_request_node)
    graph.add_node("submit_execution", submit_execution)
    graph.add_node("persist_turn", persist_turn)
    graph.add_node("finalize_execution", finalize_execution)

    graph.add_edge(START, "load_execution_context")
    graph.add_edge("load_execution_context", "discover_tools")
    graph.add_edge("discover_tools", "select_execution_plan")
    graph.add_edge("select_execution_plan", "validate_execution_plan")
    graph.add_edge("prepare_approval", "approval_gate")
    graph.add_edge("submit_execution", "persist_turn")
    graph.add_edge("persist_turn", "finalize_execution")
    if include_checkpointer:
        return graph.compile(checkpointer=inputs.checkpointer)
    return graph.compile()


__all__ = ["ExecutionSubgraphState", "build_execution_subgraph"]
