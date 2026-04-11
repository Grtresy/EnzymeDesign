from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from mcp_project_memory.models import utc_now_iso

from .capability import WorkflowAuditEvent
from .planning import AgentState
from .project_memory_service import ProjectMemoryService
from .workspace import ProjectContext


class MemoryClient:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.service = ProjectMemoryService(context)

    @property
    def project_id(self) -> str:
        return self.context.config.project_id

    def create_episode(self, episode_id: str, goal: str) -> dict[str, Any]:
        goal_text = goal.strip()
        self.service.ensure_episode_dir(episode_id)
        self.service.save_episode_goal(episode_id, f"# Goal\n\n{goal_text}\n")
        agent_state = AgentState.from_dict(
            {},
            episode_id=episode_id,
            objective=goal_text,
        ).to_dict()
        state = {
            "status": "draft",
            "stop_reason": agent_state.get("stop_reason", "active"),
            "next_step_suggestion": agent_state.get("next_step_suggestion", ""),
            "needs_user_intervention": agent_state.get("needs_user_intervention", False),
            "plain_language_explanation": agent_state.get("plain_language_explanation", ""),
            "technical_explanation": agent_state.get("technical_explanation", ""),
            "progress_summary": dict(agent_state.get("progress_summary") or {}),
            "goal": {
                "path": f"episodes/{episode_id}/goal.md",
                "updated_at": utc_now_iso(),
            },
            "plan": {"status": "missing"},
            "planning": {
                "status": "missing",
                "latest_revision_id": None,
                "latest_revision_status": None,
                "approved_revision_id": None,
                "history_length": 0,
            },
            "agent": agent_state,
            "steps": {},
            "runs": [],
        }
        self.service.save_agent_state(episode_id, agent_state)
        return self.service.update_episode_state(episode_id, state)

    def load_goal(self, episode_id: str) -> str:
        return self.service.read_text(
            f"enzyme://project/{self.project_id}/episode/{episode_id}/goal"
        )

    def load_state(self, episode_id: str) -> dict[str, Any]:
        try:
            raw = self.service.read_text(
                f"enzyme://project/{self.project_id}/episode/{episode_id}/state"
            )
        except FileNotFoundError:
            return {}
        return json.loads(raw)

    def save_state(self, episode_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return self.service.update_episode_state(episode_id, state)

    def update_state(
        self,
        episode_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        episode_dir = self.service.ensure_episode_dir(episode_id)
        state_path = episode_dir / "state.json"
        with self.service.store._file_lock(state_path):
            try:
                current = json.loads(state_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                current = {}
            updated = updater(current)
            return self.service.update_episode_state(episode_id, updated)

    def load_plan(self, episode_id: str) -> dict[str, Any]:
        raw = self.service.read_text(
            f"enzyme://project/{self.project_id}/episode/{episode_id}/plan"
        )
        return json.loads(raw)

    def confirm_plan(
        self,
        episode_id: str,
        plan: dict[str, Any],
        *,
        source_path: Path | None = None,
        imported_at: str | None = None,
    ) -> dict[str, Any]:
        meta = dict(plan.get("_meta") or {})
        if source_path is not None:
            meta["source_path"] = str(source_path.resolve())
        if imported_at is not None:
            meta["imported_at"] = imported_at
        payload = {
            **plan,
            "_meta": meta,
        }
        confirmed = self.service.confirm_plan(episode_id, payload)
        state = self.load_state(episode_id)
        updated = {
            **state,
            "status": state.get("status", "draft"),
            "goal": state.get("goal", {"path": f"episodes/{episode_id}/goal.md"}),
            "plan": {
                "status": "confirmed",
                "step_count": len(confirmed.get("steps") or []),
                "confirmed_at": confirmed.get("_meta", {}).get("confirmed_at"),
                "source_path": meta.get("source_path"),
                "revision_id": confirmed.get("_meta", {}).get("revision_id"),
                "planner": confirmed.get("_meta", {}).get("planner"),
            },
            "planning": state.get("planning", {}),
            "steps": state.get("steps", {}),
            "runs": state.get("runs", []),
        }
        self.save_state(episode_id, updated)
        return confirmed

    def write_run_manifest(
        self, episode_id: str, run_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.service.write_run_manifest(episode_id, run_id, payload)

    def load_run_manifest(self, run_id: str) -> dict[str, Any]:
        raw = self.service.read_text(f"enzyme://run/{run_id}/manifest")
        return json.loads(raw)

    def list_episode_runs(self, episode_id: str) -> list[dict[str, Any]]:
        state = self.load_state(episode_id)
        runs = state.get("runs")
        if not isinstance(runs, list):
            return []
        return [item for item in runs if isinstance(item, dict)]

    def load_agent_state(self, episode_id: str, *, objective: str) -> AgentState:
        try:
            raw = self.service.read_text(
                f"enzyme://project/{self.project_id}/episode/{episode_id}/agent-state"
            )
            payload = json.loads(raw)
        except FileNotFoundError:
            state = self.load_state(episode_id)
            payload = state.get("agent")
        return AgentState.from_dict(payload, episode_id=episode_id, objective=objective)

    def save_agent_state(
        self,
        episode_id: str,
        agent_state: AgentState,
        *,
        expected_state_version: int | None = None,
    ) -> dict[str, Any]:
        self.service.save_agent_state(
            episode_id,
            agent_state.to_dict(),
            expected_state_version=expected_state_version,
        )
        return self.update_state(
            episode_id,
            lambda current: {
                **current,
                "status": agent_state.status,
                "stop_reason": agent_state.stop_reason,
                "next_step_suggestion": agent_state.next_step_suggestion,
                "needs_user_intervention": agent_state.needs_user_intervention,
                "plain_language_explanation": agent_state.plain_language_explanation,
                "technical_explanation": agent_state.technical_explanation,
                "progress_summary": agent_state.progress_summary.to_dict(),
                "agent": agent_state.to_dict(),
            },
        )

    def update_agent_state(
        self,
        episode_id: str,
        objective: str,
        updater: Callable[[AgentState], AgentState],
    ) -> dict[str, Any]:
        def _apply(current: dict[str, Any]) -> dict[str, Any]:
            agent_state = AgentState.from_dict(current.get("agent"), episode_id=episode_id, objective=objective)
            updated = updater(agent_state)
            self.service.save_agent_state(episode_id, updated.to_dict())
            return {
                **current,
                "status": updated.status,
                "stop_reason": updated.stop_reason,
                "next_step_suggestion": updated.next_step_suggestion,
                "needs_user_intervention": updated.needs_user_intervention,
                "plain_language_explanation": updated.plain_language_explanation,
                "technical_explanation": updated.technical_explanation,
                "progress_summary": updated.progress_summary.to_dict(),
                "agent": updated.to_dict(),
            }

        return self.update_state(episode_id, _apply)

    def consume_resume_token(
        self,
        episode_id: str,
        *,
        state_version: int,
        resume_token: str,
    ) -> dict[str, Any]:
        return self.service.submit_resume(
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
        return self.service.record_decision(
            episode_id,
            decision_type=decision_type,
            reason=reason,
            author=author,
            evidence_refs=evidence_refs,
        )

    def append_workflow_event(self, episode_id: str, event: WorkflowAuditEvent) -> dict[str, Any]:
        return self.service.append_workflow_event(episode_id, event.to_dict())

    def load_workflow_audit(self, episode_id: str) -> list[dict[str, Any]]:
        try:
            raw = self.service.read_text(
                f"enzyme://project/{self.project_id}/episode/{episode_id}/workflow-audit"
            )
        except FileNotFoundError:
            return []
        payload = json.loads(raw)
        if not isinstance(payload, list):
            return []
        return [dict(item) for item in payload if isinstance(item, dict)]

    def write_planning_revision(self, episode_id: str, revision: dict[str, Any]) -> dict[str, Any]:
        revision_id = str(revision.get("revision_id") or "")
        if not revision_id:
            raise ValueError("Planning revision must include revision_id")
        path = self._planning_revision_path(episode_id, revision_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(revision, indent=2) + "\n", encoding="utf-8")
        return revision

    def load_planning_revision(self, episode_id: str, revision_id: str) -> dict[str, Any]:
        path = self._planning_revision_path(episode_id, revision_id)
        return json.loads(path.read_text(encoding="utf-8"))

    def list_planning_revisions(self, episode_id: str) -> list[dict[str, Any]]:
        directory = self._planning_dir(episode_id)
        if not directory.exists():
            return []
        revisions: list[tuple[int, dict[str, Any]]] = []
        for path in directory.glob("*.json"):
            payload = json.loads(path.read_text(encoding="utf-8"))
            payload.setdefault("_artifact_path", str(path.relative_to(self.context.root)))
            revisions.append((path.stat().st_mtime_ns, payload))
        revisions.sort(key=lambda item: item[0])
        return [payload for _, payload in revisions]

    def load_latest_planning_revision(self, episode_id: str) -> dict[str, Any] | None:
        revisions = self.list_planning_revisions(episode_id)
        if not revisions:
            return None
        return revisions[-1]

    def _planning_dir(self, episode_id: str) -> Path:
        return self.service.ensure_episode_dir(episode_id) / "artifacts" / "planning"

    def _planning_revision_path(self, episode_id: str, revision_id: str) -> Path:
        return self._planning_dir(episode_id) / f"{revision_id}.json"
