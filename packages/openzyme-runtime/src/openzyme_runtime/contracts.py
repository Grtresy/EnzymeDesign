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
    artifacts: list[dict[str, Any]] = Field(default_factory=list)
    raw_notes: list[str] = Field(default_factory=list)
    recent_turns: list[ResearchTurnRecord] = Field(default_factory=list)


class DesignNextAction(BaseModel):
    action_kind: Literal[
        "collect_research",
        "curate_artifacts",
        "request_execution",
        "stop",
    ]
    summary: str
    rationale: str
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


class HpcCatalogEntrySummary(BaseModel):
    tool_id: str
    display_name: str
    summary: str
    stage_tags: list[str] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    execution_support: Literal["runnable", "query_only"] = "query_only"
    skill_ref: str


class ExecutionHandoff(BaseModel):
    execution_goal: str
    question_to_answer: str
    required_artifact_ids: list[str] = Field(default_factory=list)
    context_artifact_ids: list[str] = Field(default_factory=list)
    preferred_stage_tags: list[str] = Field(default_factory=list)
    preferred_capability_tags: list[str] = Field(default_factory=list)
    recommended_next_phase: str = "execution"


class ExecutionPlanDraft(BaseModel):
    catalog_tool_id: str
    rationale: str
    tool_inputs: dict[str, Any] = Field(default_factory=dict)
    execution_mode: str = "auto"
    expected_result_summary: str
    planner_summary: str | None = None


class ExecutionResultHandoff(BaseModel):
    catalog_tool_id: str
    result_summary: str
    run_summary: dict[str, Any] | None = None
    artifact_refs: list[dict[str, Any]] = Field(default_factory=list)
    output_artifact_ids: list[str] = Field(default_factory=list)
    structured_findings: dict[str, Any] = Field(default_factory=dict)
    status: str = "completed"
    recommended_next_phase: str = "design"


class ArtifactManifest(BaseModel):
    artifact_id: str
    episode_id: str
    kind: str
    storage_uri: str
    created_at: str
    run_id: str | None = None
    title: str | None = None
    description: str | None = None
    tags: list[str] = Field(default_factory=list)
    provenance: dict[str, Any] = Field(default_factory=dict)
    availability: dict[str, Any] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)


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


__all__ = [
    "ArtifactManifest",
    "CanonicalResearchSnapshot",
    "ConstraintItem",
    "ConstraintSet",
    "DesignNextAction",
    "DesignToolCallResult",
    "DesignBriefDraft",
    "EvidenceSynthesis",
    "EvidenceSynthesisItem",
    "ExecutionHandoff",
    "ExecutionPlanDraft",
    "ExecutionResultHandoff",
    "ResearchDossier",
    "ResearchSourceItem",
    "HpcCatalogEntrySummary",
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
