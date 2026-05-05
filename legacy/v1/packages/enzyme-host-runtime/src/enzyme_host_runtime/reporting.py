from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mcp_project_memory.models import utc_now_iso


def format_status(
    project_name: str,
    project_root: Path,
    episode_id: str,
    goal: str,
    state: dict[str, Any],
) -> str:
    lines = [
        f"Project: {project_name}",
        f"Root: {project_root}",
        f"Episode: {episode_id}",
        f"Goal: {_first_goal_line(goal)}",
    ]
    plan = state.get("plan")
    if isinstance(plan, dict):
        lines.append(f"Plan: {plan.get('status', 'unknown')}")
    agent = state.get("agent")
    if isinstance(agent, dict):
        rendered = agent.get("status", "idle")
        session = agent.get("session")
        if isinstance(session, dict) and session.get("resume_token"):
            rendered = f"{rendered} ({session.get('resume_token')})"
        lines.append(f"Agent: {rendered}")
    steps = state.get("steps")
    if isinstance(steps, dict) and steps:
        lines.append("Steps:")
        for step_id, payload in sorted(steps.items()):
            if not isinstance(payload, dict):
                continue
            status = payload.get("status", "unknown")
            run_id = payload.get("run_id")
            suffix = f" ({run_id})" if run_id else ""
            lines.append(f"  - {step_id}: {status}{suffix}")
    runs = state.get("runs")
    if isinstance(runs, list) and runs:
        lines.append("Recent runs:")
        for item in runs[-5:]:
            if not isinstance(item, dict):
                continue
            lines.append(
                f"  - {item.get('run_id')}: {item.get('status', 'unknown')} [{item.get('step_id')}]"
            )
    return "\n".join(lines)


def build_report(
    project_name: str,
    episode_id: str,
    goal: str,
    plan: dict[str, Any] | None,
    state: dict[str, Any],
) -> str:
    lines = [
        f"# Episode Report: {episode_id}",
        "",
        f"- Generated: {utc_now_iso()}",
        f"- Project: {project_name}",
        f"- Episode: {episode_id}",
        "",
        "## Goal",
        "",
        goal.strip(),
        "",
        "## Plan",
        "",
    ]
    if plan is None:
        lines.extend(["No confirmed plan", ""])
    else:
        lines.extend(["```json", json.dumps(plan, indent=2), "```", ""])
    lines.extend(["## State", "", "```json", json.dumps(state, indent=2), "```", ""])
    return "\n".join(lines)


def report_path(project_root: Path, episode_id: str) -> Path:
    return project_root / "episodes" / episode_id / "report.md"


def _first_goal_line(goal: str) -> str:
    for line in goal.splitlines():
        stripped = line.strip().lstrip("#").strip()
        if stripped:
            return stripped
    return ""
