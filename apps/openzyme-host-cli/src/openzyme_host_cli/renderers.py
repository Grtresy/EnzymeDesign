from __future__ import annotations

import json
from typing import Any


def render_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def render_projects(projects: list[dict[str, Any]]) -> str:
    if not projects:
        return "No projects available."
    lines = ["Projects"]
    for project in projects:
        lines.append(f"- {project['project_id']}: {project['name']}")
    return "\n".join(lines)


def render_episode_list(episodes: list[dict[str, Any]]) -> str:
    if not episodes:
        return "No episodes available for this project."
    lines = ["Episodes"]
    for episode in episodes:
        lines.append(
            f"- {episode['episode_id']}: {episode['objective']} [{episode['status']}]"
        )
    return "\n".join(lines)


def render_workspace(workspace: dict[str, Any]) -> str:
    workflow = workspace["workflow"]
    lines = [
        f"Episode {workspace['episode_id']}",
        f"Phase: {workflow['current_phase']}",
        f"Status: {workflow['status']}",
        f"Active node: {workflow['progress']['active_node']}",
        f"Message: {workflow['progress']['message'] or '-'}",
        f"Updated at: {workflow['updated_at']}",
        "Summary",
        f"- Evidence: {workflow['summary']['evidence_count']}",
        f"- Candidates: {workflow['summary']['candidate_count']}",
        f"- Selected candidate: {workflow['summary']['selected_candidate_id'] or '-'}",
        f"- Report: {workflow['summary']['report_id'] or '-'} ({workflow['summary']['report_status'] or 'pending'})",
    ]
    pending = workspace.get("pending_actions") or []
    if pending:
        lines.append("Pending actions")
        for action in pending:
            lines.append(
                f"- {action['approval_id']}: {action['requested_action']} [{action['status']}]"
            )
    return "\n".join(lines)


def render_records(title: str, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    if not rows:
        return f"No {title.lower()} found."
    lines = [title]
    for row in rows:
        rendered_fields = [f"{field}={row.get(field)}" for field in fields]
        lines.append(f"- {' | '.join(rendered_fields)}")
    return "\n".join(lines)


def render_command_result(result: dict[str, Any]) -> str:
    workspace = result["workspace"]
    return "\n".join(
        [
            render_workspace(workspace),
            "",
            f"Snapshot events emitted: {len(result.get('events', []))}",
        ]
    )
