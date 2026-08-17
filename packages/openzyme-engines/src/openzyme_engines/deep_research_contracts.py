from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class IntakeClarification(BaseModel):
    needs_clarification: bool = False
    question: str | None = None
    rationale: str | None = None


class ResearchBriefDraft(BaseModel):
    research_brief: str
    focus_areas: list[str] = Field(default_factory=list)
    requested_deliverables: list[str] = Field(default_factory=list)


class ResearchSourceItem(BaseModel):
    title: str
    locator: str
    kind: str
    snippet: str | None = None


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
    files: list[dict[str, Any]] = Field(default_factory=list)
    raw_notes: list[str] = Field(default_factory=list)
    recent_turns: list[ResearchTurnRecord] = Field(default_factory=list)


__all__ = [
    "EvidenceSynthesis",
    "EvidenceSynthesisItem",
    "IntakeClarification",
    "ResearchBriefDraft",
    "ResearchDossier",
    "ResearchSourceItem",
    "ResearchSupervisorAction",
    "ResearchTurnRecord",
    "ResearchUnitDraft",
    "ResearchUnitPlan",
]
