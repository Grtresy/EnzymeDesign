from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_project_memory.config import ProjectMemoryConfig
from mcp_project_memory.store import ProjectMemoryStore

from .workspace import ProjectContext


class ProjectMemoryService:
    """Stable contract wrapper around the canonical project memory implementation."""

    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.store = ProjectMemoryStore(
            ProjectMemoryConfig(projects={context.config.project_id: context.root})
        )

    @property
    def project_id(self) -> str:
        return self.context.config.project_id

    def read_text(self, uri: str) -> str:
        return self.store.read_resource_text(uri)

    def read_json(self, uri: str) -> dict[str, Any]:
        return json.loads(self.read_text(uri))

    def read_json_list(self, uri: str) -> list[dict[str, Any]]:
        raw = json.loads(self.read_text(uri))
        if not isinstance(raw, list):
            raise ValueError(f"Expected JSON array for resource: {uri}")
        return [dict(item) for item in raw if isinstance(item, dict)]

    def ensure_episode_dir(self, episode_id: str) -> Path:
        return self.store.ensure_episode_dir(self.project_id, episode_id)

    def update_episode_state(self, episode_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return self.store.update_episode_state(self.project_id, episode_id, state)

    def save_episode_goal(self, episode_id: str, goal_markdown: str) -> dict[str, Any]:
        return self.store.save_episode_goal(self.project_id, episode_id, goal_markdown)

    def save_agent_state(
        self,
        episode_id: str,
        agent_state: dict[str, Any],
        *,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        return self.store.save_agent_state(
            self.project_id,
            episode_id,
            agent_state,
            expected_state_version=expected_state_version,
        )

    def append_feedback(
        self,
        episode_id: str,
        feedback: dict[str, Any],
        *,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        return self.store.append_feedback(
            self.project_id,
            episode_id,
            feedback,
            expected_state_version=expected_state_version,
        )

    def upsert_approval_gate(
        self,
        episode_id: str,
        gate: dict[str, Any],
        *,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        return self.store.upsert_approval_gate(
            self.project_id,
            episode_id,
            gate,
            expected_state_version=expected_state_version,
        )

    def write_interrupts(
        self,
        episode_id: str,
        interrupts: list[dict[str, Any]],
        *,
        expected_state_version: int | None = None,
    ) -> list[dict[str, Any]]:
        return self.store.write_interrupts(
            self.project_id,
            episode_id,
            interrupts,
            expected_state_version=expected_state_version,
        )

    def save_session(
        self,
        episode_id: str,
        session: dict[str, Any],
        *,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        return self.store.save_session(
            self.project_id,
            episode_id,
            session,
            expected_state_version=expected_state_version,
        )

    def submit_resume(self, episode_id: str, *, state_version: int, resume_token: str) -> dict[str, Any]:
        return self.store.submit_resume(
            self.project_id,
            episode_id,
            state_version=state_version,
            resume_token=resume_token,
        )

    def record_decision(
        self,
        episode_id: str,
        *,
        decision_type: str,
        reason: str,
        author: str,
        evidence_refs: list[str] | None = None,
    ) -> dict[str, Any]:
        return self.store.record_decision(
            self.project_id,
            episode_id,
            decision_type,
            reason,
            author,
            evidence_refs=evidence_refs,
        )

    def confirm_plan(self, episode_id: str, plan: dict[str, Any]) -> dict[str, Any]:
        return self.store.confirm_plan(self.project_id, episode_id, plan)

    def write_run_manifest(self, episode_id: str, run_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.store.write_run_manifest(self.project_id, episode_id, run_id, payload)

    def append_workflow_event(self, episode_id: str, event: dict[str, Any]) -> dict[str, Any]:
        return self.store.append_workflow_event(self.project_id, episode_id, event)
