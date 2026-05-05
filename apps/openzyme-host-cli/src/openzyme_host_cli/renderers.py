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
        f"- Artifacts: {workflow['summary']['artifact_count']}",
        f"- Focused artifacts: {workflow['summary']['focused_artifact_count']}",
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


def render_v3_workspace(workspace: dict[str, Any]) -> str:
    session = workspace["session"]
    task_items = workspace.get("task_board", {}).get("items", [])
    lanes = workspace.get("lane_board", {}).get("lanes", [])
    approvals = workspace.get("pending_approvals", [])
    reports = workspace.get("reports", [])
    lines = [
        f"Session {session['session_id']}",
        f"Status: {session['status']}",
        f"Objective: {session['objective']}",
        f"Tasks: {len(task_items)}",
        f"Lanes: {len(lanes)}",
        f"Pending approvals: {len(approvals)}",
        f"Reports: {len(reports)}",
    ]
    if task_items:
        lines.append("Task board")
        for item in task_items:
            task = item["task"]
            lines.append(
                f"- {task['task_id']}: {task['subject']} [{task['status']}/{item['bucket']}]"
            )
    if lanes:
        lines.append("Lanes")
        for item in lanes:
            lane = item["lane"]
            lines.append(f"- {lane['lane_id']}: {lane['name']} [{lane['status']}]")
    return "\n".join(lines)


def render_v3_command_result(result: dict[str, Any]) -> str:
    lines = [render_v3_workspace(result["workspace"])]
    outputs = result.get("outputs") or []
    if outputs:
        lines.append("Assistant")
        lines.extend(f"- {output}" for output in outputs)
    lines.append(f"Events emitted: {len(result.get('events', []))}")
    return "\n".join(lines)
