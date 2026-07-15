from __future__ import annotations

import json
from typing import Any


def render_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def render_records(title: str, rows: list[dict[str, Any]], fields: tuple[str, ...]) -> str:
    if not rows:
        return f"No {title.lower()} found."
    lines = [title]
    for row in rows:
        rendered_fields = [f"{field}={row.get(field)}" for field in fields]
        lines.append(f"- {' | '.join(rendered_fields)}")
    return "\n".join(lines)


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


def render_v3_runtime_health(health: dict[str, Any]) -> str:
    lines = [
        f"Runtime: {health.get('status', 'unknown')}",
        f"Deployment profile: {health.get('deployment_profile', 'unknown')}",
        f"Storage: {health.get('storage_profile', 'unknown')}",
    ]
    for name, component in sorted(dict(health.get("components") or {}).items()):
        lines.append(f"{name}: {dict(component).get('status', 'unknown')}")
    return "\n".join(lines)
