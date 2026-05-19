from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from contextvars import copy_context
from datetime import UTC
from datetime import datetime
from typing import Any
from typing import Literal
from typing import TypedDict

from langgraph.graph import END
from langgraph.graph import START
from langgraph.graph import StateGraph
from langgraph.types import Command
from openzyme_domain import DecisionStatus
from openzyme_runtime import DefaultResearchToolProvider
from openzyme_runtime import GraphAssemblyInputs
from openzyme_runtime import ResearchTool
from openzyme_runtime import ResearchToolContext
from pydantic import ValidationError

from .deep_research_contracts import EvidenceSynthesis
from .deep_research_contracts import EvidenceSynthesisItem
from .deep_research_contracts import IntakeClarification
from .deep_research_contracts import ResearchBriefDraft
from .deep_research_contracts import ResearchDossier
from .deep_research_contracts import ResearchSourceItem
from .deep_research_contracts import ResearchSupervisorAction
from .deep_research_contracts import ResearchTurnRecord


def _utc_now_iso() -> str:
    return datetime.now(tz=UTC).replace(microsecond=0).isoformat()


def _default_research_brief(state: dict[str, Any]) -> str:
    return str(
        state.get("research_brief")
        or state.get("design_brief")
        or state.get("objective")
        or "Investigate the current objective and collect supporting evidence."
    )


def _extract_tool_calls(message: Any) -> list[dict[str, Any]]:
    return list(getattr(message, "tool_calls", None) or message.get("tool_calls", []))


def _research_turns(state: dict[str, Any], limit: int = 10) -> list[ResearchTurnRecord]:
    turns = list(state.get("recent_turns") or [])
    return [ResearchTurnRecord.model_validate(turn) for turn in turns[-limit:]]


def _record_research_turn(
    state: dict[str, Any],
    *,
    action_kind: str,
    status: DecisionStatus,
    summary: str,
    rationale: str,
    tool_names: list[str] | None = None,
    observation_payload: dict[str, Any] | None = None,
) -> ResearchTurnRecord:
    current_turns = list(state.get("recent_turns") or [])
    turn_index = len(current_turns) + 1
    created_at = _utc_now_iso()
    return ResearchTurnRecord(
        turn_index=turn_index,
        action_kind=action_kind,
        status=status.value,
        summary=summary,
        rationale=rationale,
        tool_names=[] if tool_names is None else tool_names,
        observation_summary=None
        if observation_payload is None
        else (observation_payload.get("summary") or observation_payload.get("message")),
        created_at=created_at,
    )


def _has_research_findings(state: dict[str, Any]) -> bool:
    return any(result.get("findings") for result in state.get("unit_results") or [])


def _failed_dossier(
    state: dict[str, Any],
    *,
    completion_reason: str,
    summary: str,
    unresolved_gap: str,
) -> ResearchDossier:
    return ResearchDossier(
        status="failed",
        completion_reason=completion_reason,
        clarification_question=None,
        research_brief=_default_research_brief(state),
        summary=summary,
        evidence_items=[],
        unresolved_gaps=[unresolved_gap],
        artifacts=[],
        raw_notes=list(state.get("raw_notes") or []),
        recent_turns=_research_turns(state),
    )


class DeepResearchState(TypedDict, total=False):
    episode_id: str
    project_id: str | None
    objective: str | None
    design_brief: str | None
    research_brief: str | None
    clarification_question: str | None
    completion_reason: str | None
    research_iterations: int
    current_action: dict[str, Any] | None
    planned_units: list[dict[str, Any]]
    unit_results: list[dict[str, Any]]
    raw_notes: list[str]
    recent_turns: list[dict[str, Any]]
    research_dossier: dict[str, Any] | None


def _build_tool_context(
    state: DeepResearchState,
    *,
    tool_call_iterations: int,
) -> ResearchToolContext:
    return ResearchToolContext(
        episode_id=str(state["episode_id"]),
        project_id=state.get("project_id"),
        objective=state.get("objective"),
        design_brief=state.get("design_brief"),
        research_brief=_default_research_brief(state),
        tool_call_iterations=tool_call_iterations,
    )


def _resolve_research_tools(
    inputs: GraphAssemblyInputs,
    state: DeepResearchState,
    *,
    tool_call_iterations: int,
) -> list[ResearchTool]:
    provider = inputs.research_tool_provider or DefaultResearchToolProvider(
        inputs.research_adapter,
        mcp_enabled=inputs.settings.research.mcp_enabled,
        mcp_tool_allowlist=inputs.settings.research.mcp_tool_allowlist,
        limiter_registry=inputs.limiter_registry,
    )
    return list(
        provider.list_tools(
            _build_tool_context(state, tool_call_iterations=tool_call_iterations)
        )
    )


def _build_langchain_tool(tool_def: ResearchTool, context: ResearchToolContext) -> Any:
    from langchain_core.tools import StructuredTool

    def _invoke(**kwargs: Any) -> str:
        result = tool_def.invoke(args=kwargs, context=context)
        return json.dumps(
            {
                "tool_name": result.tool_name,
                "summary": result.summary,
                "payload": result.payload,
            },
            ensure_ascii=True,
            sort_keys=True,
        )

    return StructuredTool.from_function(
        func=_invoke,
        name=tool_def.name,
        description=tool_def.description,
        args_schema=tool_def.args_schema,
    )


def _summarize_unit_observations(
    observations: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], list[str], list[str], str, list[dict[str, Any]]]:
    findings: list[dict[str, Any]] = []
    unresolved_gaps: list[str] = []
    summary_parts: list[str] = []
    artifacts: list[dict[str, Any]] = []
    for observation in observations:
        summary_parts.append(str(observation.get("summary") or ""))
        payload = observation.get("payload") or {}
        unresolved_gaps.extend(str(item) for item in payload.get("unresolved_gaps", []))
        findings.extend(list(payload.get("findings", [])))
        artifacts.extend(dict(item) for item in payload.get("artifacts", []))
    summary = " ".join(part for part in summary_parts if part).strip()
    return findings, unresolved_gaps, summary_parts, summary, artifacts


def _run_research_unit(
    inputs: GraphAssemblyInputs,
    state: DeepResearchState,
    unit: dict[str, Any],
) -> dict[str, Any]:
    try:
        from langchain_core.messages import HumanMessage
        from langchain_core.messages import ToolMessage
    except ImportError:
        HumanMessage = None  # type: ignore[assignment]
        ToolMessage = None  # type: ignore[assignment]

    unit_id = str(unit.get("unit_id") or "unit")
    unit_topic = str(unit.get("topic") or "supporting evidence")
    unit_query = str(unit.get("query") or "").strip()
    if not unit_query:
        return {
            "unit_id": unit_id,
            "topic": unit_topic,
            "query": "",
            "summary": "Research unit is missing a query.",
            "findings": [],
            "unresolved_gaps": [
                "Research planning returned a unit without a query."
            ],
            "artifacts": [],
            "status": "failed",
            "raw_notes": [],
            "turns": [],
        }

    research_prompt = (
        f"Research topic: {unit_query}\n"
        f"Topic label: {unit.get('topic') or 'supporting evidence'}\n"
        f"Research brief: {_default_research_brief(state)}"
    )
    messages: list[Any]
    if HumanMessage is None:
        messages = [{"role": "user", "content": research_prompt}]
    else:
        messages = [HumanMessage(content=research_prompt)]

    observations: list[dict[str, Any]] = []
    raw_notes: list[str] = []
    turns: list[dict[str, Any]] = []

    max_tool_calls = max(1, inputs.settings.research.max_react_tool_calls)
    executed_tool_call_count = 0
    for tool_call_iterations in range(max_tool_calls):
        available_tools = _resolve_research_tools(
            inputs,
            state,
            tool_call_iterations=tool_call_iterations,
        )
        if not available_tools:
            return {
                "unit_id": str(unit.get("unit_id") or "unit"),
                "topic": str(unit.get("topic") or "supporting evidence"),
                "query": str(unit.get("query") or _default_research_brief(state)),
                "summary": "No research tools are available for this unit.",
                "findings": [],
                "unresolved_gaps": [
                    "No research tools configured for this deep-research run."
                ],
                "status": "failed",
                "raw_notes": [],
                "turns": [],
            }
        if inputs.model_factory is None:
            return {
                "unit_id": unit_id,
                "topic": unit_topic,
                "query": unit_query,
                "summary": "Deep research requires a configured model factory.",
                "findings": [],
                "unresolved_gaps": [
                    "No model factory configured for deep-research tool selection."
                ],
                "artifacts": [],
                "status": "failed",
                "raw_notes": [],
                "turns": [],
            }
        try:
            invoker = inputs.model_factory.create_tool_calling_invoker(
                purpose="deep_research_researcher"
            )
            response = invoker.invoke_with_tools(
                system_prompt=(
                    "You are a reusable deep research agent. "
                    "Use the provided tools to gather evidence for downstream enzyme design. "
                    "On the first turn for a research unit, call a search tool such as web.search when one is available. "
                    "After a search returns enough credible sources to support synthesis, stop calling tools and let synthesis run. "
                    "Do not continue searching only to improve completeness or polish."
                ),
                messages=list(messages),
                tools=[
                    _build_langchain_tool(
                        tool,
                        _build_tool_context(
                            state, tool_call_iterations=tool_call_iterations
                        ),
                    )
                    for tool in available_tools
                ],
            )
        except Exception as exc:
            return {
                "unit_id": unit_id,
                "topic": unit_topic,
                "query": unit_query,
                "summary": "Deep research model failed while selecting tool calls.",
                "findings": [],
                "unresolved_gaps": [
                    f"Model tool-call selection failed: {type(exc).__name__}: {exc}"
                ],
                "artifacts": [],
                "status": "failed",
                "raw_notes": [],
                "turns": [],
            }
        tool_calls = _extract_tool_calls(response)
        messages.append(response)
        if not tool_calls:
            break
        remaining_tool_call_budget = max_tool_calls - executed_tool_call_count
        if len(tool_calls) > remaining_tool_call_budget:
            raw_notes.append(
                "Research tool-call budget truncated "
                f"{len(tool_calls) - remaining_tool_call_budget} excess call(s)."
            )
            tool_calls = tool_calls[:remaining_tool_call_budget]
        if not tool_calls:
            break

        tools_by_name = {tool.name: tool for tool in available_tools}
        for tool_call in tool_calls:
            executed_tool_call_count += 1
            tool_name = str(tool_call["name"])
            observation_status = DecisionStatus.COMPLETED
            tool = tools_by_name.get(tool_name)
            if tool is None:
                observation = {
                    "tool_name": tool_name,
                    "summary": f"Tool {tool_name} is unavailable.",
                    "payload": {"message": "tool unavailable"},
                }
                observation_status = DecisionStatus.FAILED
            else:
                try:
                    result = tool.invoke(
                        args=dict(tool_call.get("args") or {}),
                        context=_build_tool_context(
                            state, tool_call_iterations=tool_call_iterations
                        ),
                    )
                    observation = {
                        "tool_name": result.tool_name,
                        "summary": result.summary,
                        "payload": result.payload,
                    }
                    if str((result.payload or {}).get("status") or "").lower() in {
                        "failed",
                        "error",
                    }:
                        observation_status = DecisionStatus.FAILED
                except ValidationError as exc:
                    observation = {
                        "tool_name": tool_name,
                        "summary": f"Tool {tool_name} rejected invalid arguments.",
                        "payload": {
                            "status": "failed",
                            "error_type": "tool_argument_validation",
                            "message": str(exc),
                            "unresolved_gaps": [
                                f"Tool {tool_name} received invalid arguments."
                            ],
                            "retryable": True,
                        },
                    }
                    observation_status = DecisionStatus.FAILED

            observations.append(observation)
            raw_notes.append(str(observation["summary"]))
            turns.append(
                {
                    "action_kind": tool_name,
                    "status": observation_status.value,
                    "summary": str(observation["summary"]),
                    "rationale": f"Executed research tool {tool_name}.",
                    "tool_names": [tool_name],
                    "observation_payload": observation,
                }
            )
            if ToolMessage is None:
                messages.append(
                    {
                        "role": "tool",
                        "name": tool_name,
                        "tool_call_id": tool_call.get("id"),
                        "content": json.dumps(
                            observation, ensure_ascii=True, sort_keys=True
                        ),
                    }
                )
            else:
                messages.append(
                    ToolMessage(
                        content=json.dumps(
                            observation, ensure_ascii=True, sort_keys=True
                        ),
                        name=tool_name,
                        tool_call_id=str(tool_call.get("id") or tool_name),
                    )
                )

    findings, unresolved_gaps, _summary_parts, summary, artifacts = (
        _summarize_unit_observations(observations)
    )
    had_failure = any(turn["status"] == DecisionStatus.FAILED.value for turn in turns)
    if findings and not had_failure:
        status = "completed"
    elif findings or any(turn["status"] != DecisionStatus.FAILED.value for turn in turns):
        status = "partial"
    else:
        status = "failed"
    return {
        "unit_id": unit_id,
        "topic": unit_topic,
        "query": unit_query,
        "summary": summary
        or f"Completed research for {unit_query}",
        "findings": findings,
        "unresolved_gaps": unresolved_gaps,
        "artifacts": artifacts,
        "status": status,
        "raw_notes": raw_notes,
        "turns": turns,
    }


def build_deep_research_subgraph(inputs: GraphAssemblyInputs) -> Any:
    def clarify_research_scope(
        state: DeepResearchState,
    ) -> Command[Literal["write_research_brief", "synthesize_research_dossier"]]:
        if not inputs.settings.research.allow_clarification:
            return Command(goto="write_research_brief")
        if inputs.model_factory is None:
            dossier = _failed_dossier(
                state,
                completion_reason="missing_model_factory",
                summary="Deep research requires a configured model factory.",
                unresolved_gap="No model factory configured for deep-research clarification.",
            )
            return Command(
                update={"research_dossier": dossier.model_dump()},
                goto="synthesize_research_dossier",
            )
        try:
            invoker = inputs.model_factory.create_structured_invoker(
                purpose="deep_research_brief"
            )
            clarification = invoker.invoke_structured(
                schema=IntakeClarification,
                system_prompt=(
                    "You are checking whether a deep-research request is specific enough to execute. "
                    "If the objective is underspecified, ask exactly one concise clarification question."
                ),
                user_payload={
                    "episode_id": state.get("episode_id"),
                    "objective": state.get("objective"),
                    "design_brief": state.get("design_brief"),
                    "research_brief": state.get("research_brief"),
                },
            )
        except Exception as exc:
            dossier = _failed_dossier(
                state,
                completion_reason="clarification_model_failed",
                summary="Deep research clarification failed.",
                unresolved_gap=f"Clarification model failed: {type(exc).__name__}: {exc}",
            )
            return Command(
                update={"research_dossier": dossier.model_dump()},
                goto="synthesize_research_dossier",
            )

        if clarification.needs_clarification:
            return Command(
                update={
                    "clarification_question": clarification.question,
                    "completion_reason": clarification.rationale
                    or "clarification_requested",
                },
                goto="synthesize_research_dossier",
            )
        return Command(goto="write_research_brief")

    def write_research_brief(state: DeepResearchState) -> dict[str, Any]:
        if inputs.model_factory is None:
            return {
                "research_dossier": _failed_dossier(
                    state,
                    completion_reason="missing_model_factory",
                    summary="Deep research requires a configured model factory.",
                    unresolved_gap="No model factory configured for research brief drafting.",
                ).model_dump()
            }
        try:
            invoker = inputs.model_factory.create_structured_invoker(
                purpose="deep_research_brief"
            )
            brief = invoker.invoke_structured(
                schema=ResearchBriefDraft,
                system_prompt=(
                    "You are preparing a concise research brief for a reusable deep research workflow. "
                    "Rewrite the current objective into a focused brief with no extra commentary."
                ),
                user_payload={
                    "episode_id": state.get("episode_id"),
                    "objective": state.get("objective"),
                    "design_brief": state.get("design_brief"),
                    "research_brief": state.get("research_brief"),
                },
            )
            return {"research_brief": brief.research_brief}
        except Exception as exc:
            return {
                "research_dossier": _failed_dossier(
                    state,
                    completion_reason="brief_model_failed",
                    summary="Deep research brief drafting failed.",
                    unresolved_gap=f"Brief model failed: {type(exc).__name__}: {exc}",
                ).model_dump()
            }

    def supervisor_plan_research(
        state: DeepResearchState,
    ) -> Command[Literal["dispatch_research_units", "synthesize_research_dossier"]]:
        if state.get("research_dossier") is not None:
            return Command(goto="synthesize_research_dossier")
        iterations = int(state.get("research_iterations", 0))
        findings_available = _has_research_findings(state)
        if iterations >= max(1, inputs.settings.research.max_research_iterations):
            action = ResearchSupervisorAction(
                action_kind="complete",
                rationale="The configured research iteration budget has been reached.",
            )
            completion_reason = "iteration_budget_reached"
        elif inputs.model_factory is not None:
            try:
                invoker = inputs.model_factory.create_structured_invoker(
                    purpose="deep_research_supervisor"
                )
                action = invoker.invoke_structured(
                    schema=ResearchSupervisorAction,
                    system_prompt=(
                        "You supervise a reusable deep research workflow. "
                        "Choose whether to conduct another batch of research or complete the research dossier. "
                        "If any usable unit result or finding already exists, prefer complete immediately; "
                        "do not continue research for perfection, breadth, or polish. "
                        "Only choose conduct_research when there are no usable findings yet. "
                        "If you choose conduct_research, return a small standalone unit plan."
                    ),
                    user_payload={
                        "episode_id": state.get("episode_id"),
                        "objective": state.get("objective"),
                        "design_brief": state.get("design_brief"),
                        "research_brief": state.get("research_brief"),
                        "unit_results": state.get("unit_results") or [],
                        "recent_turns": state.get("recent_turns") or [],
                        "completion_guidance": {
                            "findings_available": findings_available,
                            "recommended_action": "complete"
                            if findings_available
                            else "conduct_research",
                            "reason": (
                                "At least one usable finding exists; synthesize now."
                                if findings_available
                                else "No usable findings exist yet; one concise research batch is allowed."
                            ),
                        },
                        "max_research_iterations": inputs.settings.research.max_research_iterations,
                        "max_concurrent_research_units": inputs.settings.research.max_concurrent_research_units,
                    },
                )
            except Exception as exc:
                dossier = _failed_dossier(
                    state,
                    completion_reason="supervisor_model_failed",
                    summary="Deep research supervisor failed.",
                    unresolved_gap=f"Supervisor model failed: {type(exc).__name__}: {exc}",
                )
                return Command(
                    update={"research_dossier": dossier.model_dump()},
                    goto="synthesize_research_dossier",
                )
            completion_reason = "supervisor_complete"
        else:
            dossier = _failed_dossier(
                state,
                completion_reason="missing_model_factory",
                summary="Deep research requires a configured model factory.",
                unresolved_gap="No model factory configured for deep-research supervision.",
            )
            return Command(
                update={"research_dossier": dossier.model_dump()},
                goto="synthesize_research_dossier",
            )

        research_turn = _record_research_turn(
            state,
            action_kind=action.action_kind,
            status=DecisionStatus.COMPLETED,
            summary=(
                "Plan another research batch."
                if action.action_kind == "conduct_research"
                else "Stop research and synthesize the dossier."
            ),
            rationale=action.rationale,
        )
        update = {
            "current_action": action.model_dump(),
            "research_iterations": iterations + 1,
            "recent_turns": [
                *(state.get("recent_turns") or []),
                research_turn.model_dump(),
            ],
            "completion_reason": completion_reason,
        }
        if action.action_kind == "complete":
            return Command(update=update, goto="synthesize_research_dossier")
        if action.unit_plan is None or not action.unit_plan.units:
            dossier = _failed_dossier(
                state,
                completion_reason="missing_research_unit_plan",
                summary="Deep research supervisor did not provide a unit plan.",
                unresolved_gap="Supervisor selected conduct_research without research units.",
            )
            return Command(
                update={"research_dossier": dossier.model_dump()},
                goto="synthesize_research_dossier",
            )
        planned_units = action.unit_plan.units[
            : max(1, inputs.settings.research.max_concurrent_research_units)
        ]
        return Command(
            update={
                **update,
                "planned_units": [unit.model_dump() for unit in planned_units],
            },
            goto="dispatch_research_units",
        )

    def dispatch_research_units(
        state: DeepResearchState,
    ) -> Command[Literal["supervisor_plan_research", "synthesize_research_dossier"]]:
        planned_units = list(state.get("planned_units") or [])
        if not planned_units:
            return Command(
                update={
                    "completion_reason": state.get("completion_reason")
                    or "no_research_units_planned"
                },
                goto="synthesize_research_dossier",
            )

        max_workers = max(1, inputs.settings.research.max_concurrent_research_units)
        scheduled_units = planned_units[:max_workers]
        if max_workers == 1:
            unit_results = [_run_research_unit(inputs, state, scheduled_units[0])]
        else:
            scheduled_with_context = [
                (unit, copy_context()) for unit in scheduled_units
            ]
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                unit_results = list(
                    executor.map(
                        lambda item: item[1].run(
                            _run_research_unit, inputs, state, item[0]
                        ),
                        scheduled_with_context,
                    )
                )

        recent_turns = list(state.get("recent_turns") or [])
        raw_notes = list(state.get("raw_notes") or [])
        for result in unit_results:
            raw_notes.extend(str(note) for note in result.get("raw_notes", []))
            for turn in result.get("turns", []):
                recorded = _record_research_turn(
                    {"recent_turns": recent_turns},
                    action_kind=str(turn["action_kind"]),
                    status=DecisionStatus(str(turn["status"])),
                    summary=str(turn["summary"]),
                    rationale=str(turn["rationale"]),
                    tool_names=list(turn.get("tool_names") or []),
                    observation_payload=turn.get("observation_payload"),
                )
                recent_turns.append(recorded.model_dump())

        return Command(
            update={
                "planned_units": [],
                "unit_results": [*(state.get("unit_results") or []), *unit_results],
                "recent_turns": recent_turns,
                "raw_notes": raw_notes,
            },
            goto="supervisor_plan_research",
        )

    def synthesize_research_dossier(state: DeepResearchState) -> dict[str, Any]:
        if state.get("research_dossier") is not None:
            return {"research_dossier": state["research_dossier"]}
        if state.get("clarification_question"):
            dossier = ResearchDossier(
                status="needs_clarification",
                completion_reason=str(
                    state.get("completion_reason") or "clarification_requested"
                ),
                clarification_question=str(state["clarification_question"]),
                research_brief=_default_research_brief(state),
                summary="Research paused until the scope is clarified.",
                evidence_items=[],
                unresolved_gaps=[
                    "Research scope needs clarification before evidence collection can continue."
                ],
                artifacts=[],
                raw_notes=list(state.get("raw_notes") or []),
                recent_turns=_research_turns(state),
            )
            return {"research_dossier": dossier.model_dump()}

        unit_results = list(state.get("unit_results") or [])
        synthesis: EvidenceSynthesis | None = None
        findings_available = any(result.get("findings") for result in unit_results)
        if inputs.model_factory is not None and findings_available:
            try:
                invoker = inputs.model_factory.create_structured_invoker(
                    purpose="deep_research_synthesis"
                )
                synthesis = invoker.invoke_structured(
                    schema=EvidenceSynthesis,
                    system_prompt=(
                        "You are synthesizing a reusable deep research dossier. "
                        "Compress the research results into a concise summary, normalized evidence items, and unresolved gaps."
                    ),
                    user_payload={
                        "episode_id": state.get("episode_id"),
                        "research_brief": state.get("research_brief"),
                        "unit_results": unit_results,
                    },
                )
            except Exception as exc:
                error_type = type(exc).__name__
                error_message = str(exc)
                dossier = _failed_dossier(
                    state,
                    completion_reason="synthesis_model_failed",
                    summary="Deep research synthesis model failed.",
                    unresolved_gap=(
                        "Synthesis model failed: "
                        f"{error_type}: {error_message}"
                    ),
                )
                raw_notes = [
                    *dossier.raw_notes,
                    (
                        "synthesis_model_failed "
                        f"error_type={error_type} error_message={error_message}"
                    ),
                ]
                return {
                    "research_dossier": dossier.model_copy(
                        update={"raw_notes": raw_notes}
                    ).model_dump()
                }

        if synthesis is None:
            evidence_items: list[EvidenceSynthesisItem] = []
            unresolved_gaps: list[str] = []
            summary_parts: list[str] = []
            artifacts: list[dict[str, Any]] = []
            for result in unit_results:
                if result.get("summary"):
                    summary_parts.append(str(result["summary"]))
                unresolved_gaps.extend(
                    str(gap) for gap in result.get("unresolved_gaps", [])
                )
                artifacts.extend(dict(item) for item in result.get("artifacts", []))
                for finding in result.get("findings", []):
                    evidence_items.append(
                        EvidenceSynthesisItem(
                            summary=str(finding["summary"]),
                            query=str(finding["query"]),
                            confidence_label=None
                            if finding.get("confidence_label") is None
                            else str(finding["confidence_label"]),
                            sources=[
                                ResearchSourceItem.model_validate(source)
                                for source in finding.get("sources", [])
                            ],
                        )
                    )
            synthesis = EvidenceSynthesis(
                summary=" ".join(summary_parts).strip()
                or "Research completed without a synthesized summary.",
                evidence_items=evidence_items,
                unresolved_gaps=unresolved_gaps,
            )
        else:
            artifacts = []

        unit_statuses = {str(result.get("status") or "") for result in unit_results}
        if synthesis.evidence_items and unit_statuses <= {"completed"}:
            status = "completed"
        elif synthesis.evidence_items or (unit_results and unit_statuses - {"failed"}):
            status = "partial"
        else:
            status = "failed"
        completion_reason = str(
            state.get("completion_reason")
            or (
                "research_completed"
                if status == "completed"
                else "research_partial"
                if status == "partial"
                else "research_failed"
            )
        )

        dossier = ResearchDossier(
            status=status,
            completion_reason=completion_reason,
            clarification_question=None,
            research_brief=_default_research_brief(state),
            summary=synthesis.summary,
            evidence_items=synthesis.evidence_items,
            unresolved_gaps=synthesis.unresolved_gaps,
            artifacts=artifacts,
            raw_notes=list(state.get("raw_notes") or []),
            recent_turns=_research_turns(state),
        )
        return {"research_dossier": dossier.model_dump()}

    graph = StateGraph(DeepResearchState)
    graph.add_node("clarify_research_scope", clarify_research_scope)
    graph.add_node("write_research_brief", write_research_brief)
    graph.add_node("supervisor_plan_research", supervisor_plan_research)
    graph.add_node("dispatch_research_units", dispatch_research_units)
    graph.add_node("synthesize_research_dossier", synthesize_research_dossier)
    graph.add_edge(START, "clarify_research_scope")
    graph.add_edge("write_research_brief", "supervisor_plan_research")
    graph.add_edge("synthesize_research_dossier", END)
    return graph.compile()


def run_deep_research(
    inputs: GraphAssemblyInputs,
    *,
    episode_id: str,
    project_id: str | None,
    objective: str | None,
    design_brief: str | None,
    research_brief: str | None,
) -> ResearchDossier:
    graph = build_deep_research_subgraph(inputs)
    result = graph.invoke(
        {
            "episode_id": episode_id,
            "project_id": project_id,
            "objective": objective,
            "design_brief": design_brief,
            "research_brief": research_brief,
        }
    )
    return ResearchDossier.model_validate(result["research_dossier"])


__all__ = ["DeepResearchState", "build_deep_research_subgraph", "run_deep_research"]
