from __future__ import annotations

from collections.abc import Callable
import json
from pathlib import Path
from typing import Any

from mcp_project_memory.config import ProjectMemoryConfig
from mcp_project_memory.models import utc_now_iso
from mcp_project_memory.store import ProjectMemoryStore

from .workspace import ProjectContext


class MemoryClient:
    def __init__(self, context: ProjectContext) -> None:
        self.context = context
        self.store = ProjectMemoryStore(
            ProjectMemoryConfig(projects={context.config.project_id: context.root})
        )

    @property
    def project_id(self) -> str:
        return self.context.config.project_id

    def create_episode(self, episode_id: str, goal: str) -> dict[str, Any]:
        goal_text = goal.strip()
        self.store.ensure_episode_dir(self.project_id, episode_id)
        self.store.save_episode_goal(self.project_id, episode_id, f"# Goal\n\n{goal_text}\n")
        state = {
            "status": "draft",
            "goal": {
                "path": f"episodes/{episode_id}/goal.md",
                "updated_at": utc_now_iso(),
            },
            "plan": {"status": "missing"},
            "steps": {},
            "runs": [],
        }
        return self.store.update_episode_state(self.project_id, episode_id, state)

    def load_goal(self, episode_id: str) -> str:
        return self.store.read_resource_text(
            f"enzyme://project/{self.project_id}/episode/{episode_id}/goal"
        )

    def load_state(self, episode_id: str) -> dict[str, Any]:
        try:
            raw = self.store.read_resource_text(
                f"enzyme://project/{self.project_id}/episode/{episode_id}/state"
            )
        except FileNotFoundError:
            return {}
        return json.loads(raw)

    def save_state(self, episode_id: str, state: dict[str, Any]) -> dict[str, Any]:
        return self.store.update_episode_state(self.project_id, episode_id, state)

    def update_state(
        self,
        episode_id: str,
        updater: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        episode_dir = self.store.ensure_episode_dir(self.project_id, episode_id)
        state_path = episode_dir / "state.json"
        with self.store._file_lock(state_path):
            try:
                current = json.loads(state_path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                current = {}
            updated = updater(current)
            return self.store.update_episode_state(self.project_id, episode_id, updated)

    def load_plan(self, episode_id: str) -> dict[str, Any]:
        raw = self.store.read_resource_text(
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
        confirmed = self.store.confirm_plan(self.project_id, episode_id, payload)
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
            },
            "steps": state.get("steps", {}),
            "runs": state.get("runs", []),
        }
        self.save_state(episode_id, updated)
        return confirmed

    def write_run_manifest(
        self, episode_id: str, run_id: str, payload: dict[str, Any]
    ) -> dict[str, Any]:
        return self.store.write_run_manifest(self.project_id, episode_id, run_id, payload)

    def load_run_manifest(self, run_id: str) -> dict[str, Any]:
        raw = self.store.read_resource_text(f"enzyme://run/{run_id}/manifest")
        return json.loads(raw)

    def list_episode_runs(self, episode_id: str) -> list[dict[str, Any]]:
        state = self.load_state(episode_id)
        runs = state.get("runs")
        if not isinstance(runs, list):
            return []
        return [item for item in runs if isinstance(item, dict)]
