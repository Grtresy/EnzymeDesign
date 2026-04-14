from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class ConstraintItem(BaseModel):
    category: Literal["technical", "safety", "resource", "user_preference", "other"] = "other"
    description: str


class ConstraintSet(BaseModel):
    objective_summary: str
    constraints: list[ConstraintItem] = Field(default_factory=list)


class IntakeClarification(BaseModel):
    needs_clarification: bool = False
    question: str | None = None
    rationale: str | None = None


class DesignBriefDraft(BaseModel):
    design_brief: str
    success_criteria: list[str] = Field(default_factory=list)


class ResearchBriefDraft(BaseModel):
    research_brief: str
    focus_areas: list[str] = Field(default_factory=list)
    expected_outputs: list[str] = Field(default_factory=list)


class IntakePhaseOutput(BaseModel):
    clarification: IntakeClarification = Field(default_factory=IntakeClarification)
    constraint_set: ConstraintSet
    design_brief: DesignBriefDraft
    research_brief: ResearchBriefDraft


class ResearchUnitDraft(BaseModel):
    unit_id: str
    topic: str
    query: str
    rationale: str


class ResearchUnitPlan(BaseModel):
    units: list[ResearchUnitDraft]
    synthesis_goal: str


class ResearchSupervisorAction(BaseModel):
    action_kind: Literal["conduct_research", "complete"]
    rationale: str
    unit_plan: ResearchUnitPlan | None = None


class ResearchSourceItem(BaseModel):
    title: str
    locator: str
    kind: str
    snippet: str | None = None


class EvidenceSynthesisItem(BaseModel):
    summary: str
    query: str
    confidence_label: str | None = None
    sources: list[ResearchSourceItem] = Field(default_factory=list)


class EvidenceSynthesis(BaseModel):
    summary: str
    evidence_items: list[EvidenceSynthesisItem] = Field(default_factory=list)
    unresolved_gaps: list[str] = Field(default_factory=list)


class ResearchTurnRecord(BaseModel):
    turn_index: int
    action_kind: str
    status: str
    summary: str
    rationale: str
    tool_names: list[str] = Field(default_factory=list)
    observation_summary: str | None = None
    created_at: str


class ResearchDossier(BaseModel):
    status: Literal["completed", "partial", "needs_clarification", "failed"] = "completed"
    completion_reason: str = "research_completed"
    clarification_question: str | None = None
    research_brief: str
    summary: str
    evidence_items: list[EvidenceSynthesisItem] = Field(default_factory=list)
    unresolved_gaps: list[str] = Field(default_factory=list)
    raw_notes: list[str] = Field(default_factory=list)
    recent_turns: list[ResearchTurnRecord] = Field(default_factory=list)


class CandidateDraft(BaseModel):
    candidate_id: str
    title: str
    summary: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)
    rationale: str


class CandidateDraftCollection(BaseModel):
    candidates: list[CandidateDraft] = Field(default_factory=list)


class CandidateRankingDraft(BaseModel):
    candidate_id: str
    rank: int
    rationale: str


class CandidateComparison(BaseModel):
    selected_candidate_id: str
    selected_candidate_rationale: str
    approval_summary: str
    rankings: list[CandidateRankingDraft] = Field(default_factory=list)


class DesignNextAction(BaseModel):
    action_kind: Literal[
        "collect_research",
        "draft_candidates",
        "rank_candidates",
        "revise_candidate",
        "run_hpc",
        "request_run_approval",
        "stop",
    ]
    summary: str
    rationale: str
    target_candidate_id: str | None = None
    arguments: dict[str, Any] = Field(default_factory=dict)
    stop_reason: str | None = None


class DesignToolCallResult(BaseModel):
    tool_name: str
    summary: str
    payload: dict[str, Any] = Field(default_factory=dict)
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    canonical_updates: dict[str, Any] = Field(default_factory=dict)


class ExecutionRunSpecDraft(BaseModel):
    name: str
    stage: str
    command: list[str]
    execution_mode: str = "auto"
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionRequestDraft(BaseModel):
    tool_name: str
    runspec: ExecutionRunSpecDraft


class ReportDraft(BaseModel):
    title: str
    summary: str
    stage_summary: str
    key_decisions: list[str] = Field(default_factory=list)


class CanonicalResearchSnapshot(BaseModel):
    episode_id: str
    research_summary: dict[str, Any] | None = None
    evidence_refs: list[dict[str, Any]] = Field(default_factory=list)
    unresolved_gaps: list[dict[str, Any]] = Field(default_factory=list)


class CandidateSnapshot(BaseModel):
    episode_id: str
    candidate_id: str
    title: str
    summary: str
    supporting_evidence_ids: list[str] = Field(default_factory=list)


__all__ = [
    "CandidateComparison",
    "CandidateDraft",
    "CandidateDraftCollection",
    "CandidateRankingDraft",
    "CandidateSnapshot",
    "CanonicalResearchSnapshot",
    "ConstraintItem",
    "ConstraintSet",
    "DesignNextAction",
    "DesignToolCallResult",
    "DesignBriefDraft",
    "EvidenceSynthesis",
    "EvidenceSynthesisItem",
    "ResearchDossier",
    "ResearchSourceItem",
    "ResearchTurnRecord",
    "ExecutionRequestDraft",
    "ExecutionRunSpecDraft",
    "IntakeClarification",
    "IntakePhaseOutput",
    "ReportDraft",
    "ResearchBriefDraft",
    "ResearchSupervisorAction",
    "ResearchUnitDraft",
    "ResearchUnitPlan",
]
