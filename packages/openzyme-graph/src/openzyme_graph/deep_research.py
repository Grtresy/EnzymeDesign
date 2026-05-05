from __future__ import annotations

from typing import Any

from openzyme_domain import Decision
from openzyme_domain import DecisionStatus
from openzyme_engines import build_deep_research_subgraph as _build_engine_deep_research_subgraph
from openzyme_engines import run_deep_research as _run_engine_deep_research
from openzyme_runtime import GraphAssemblyInputs
from openzyme_runtime import ResearchDossier


DeepResearchState = dict[str, Any]
RESEARCH_PHASE = "research"


def build_deep_research_subgraph(inputs: GraphAssemblyInputs) -> Any:
    return _build_engine_deep_research_subgraph(inputs)


def run_deep_research(
    inputs: GraphAssemblyInputs,
    *,
    episode_id: str,
    project_id: str | None,
    objective: str | None,
    design_brief: str | None,
    research_brief: str | None,
) -> ResearchDossier:
    dossier = _run_engine_deep_research(
        inputs,
        episode_id=episode_id,
        project_id=project_id,
        objective=objective,
        design_brief=design_brief,
        research_brief=research_brief,
    )
    compat_dossier = ResearchDossier.model_validate(dossier.model_dump())
    _persist_compat_research_turns(
        inputs,
        episode_id=episode_id,
        project_id=project_id,
        dossier=compat_dossier,
    )
    return compat_dossier


def _persist_compat_research_turns(
    inputs: GraphAssemblyInputs,
    *,
    episode_id: str,
    project_id: str | None,
    dossier: ResearchDossier,
) -> None:
    decisions = getattr(inputs.repositories, "decisions", None)
    if decisions is None or not hasattr(decisions, "save") or not hasattr(decisions, "list_by_episode"):
        return
    existing = [item for item in decisions.list_by_episode(episode_id) if getattr(item, "phase", None) == RESEARCH_PHASE]
    if existing:
        return
    for turn in dossier.recent_turns:
        decisions.save(
            Decision(
                decision_id=f"{episode_id}-research-turn-{turn.turn_index}",
                episode_id=episode_id,
                project_id=project_id,
                phase=RESEARCH_PHASE,
                turn_index=turn.turn_index,
                action_kind=turn.action_kind,
                status=DecisionStatus(turn.status),
                summary=turn.summary,
                rationale=turn.rationale,
                created_at=turn.created_at,
                action_payload=None if not turn.tool_names else {"tool_names": list(turn.tool_names)},
                observation_payload=None
                if turn.observation_summary is None
                else {"summary": turn.observation_summary},
            )
        )


__all__ = ["DeepResearchState", "build_deep_research_subgraph", "run_deep_research"]
