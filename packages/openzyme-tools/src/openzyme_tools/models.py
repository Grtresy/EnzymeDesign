from __future__ import annotations

from typing import Any
from typing import Literal

from pydantic import BaseModel
from pydantic import Field


class HpcCatalogEntrySummary(BaseModel):
    tool_id: str
    display_name: str
    summary: str
    stage_tags: list[str] = Field(default_factory=list)
    capability_tags: list[str] = Field(default_factory=list)
    execution_support: Literal["runnable", "query_only"] = "query_only"
    skill_ref: str


class HpcSkillDocument(BaseModel):
    tool_id: str
    summary: str
    required_inputs: list[str] = Field(default_factory=list)
    optional_inputs: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    failure_signatures: list[str] = Field(default_factory=list)
    example_invocation_shape: dict[str, Any] = Field(default_factory=dict)
    raw_markdown: str


class ParsedExecutionResult(BaseModel):
    result_summary: str
    structured_findings: dict[str, Any] = Field(default_factory=dict)


__all__ = [
    "HpcCatalogEntrySummary",
    "HpcSkillDocument",
    "ParsedExecutionResult",
]
