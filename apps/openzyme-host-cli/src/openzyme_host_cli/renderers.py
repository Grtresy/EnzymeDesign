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


def render_v3_runtime_command(command: dict[str, Any]) -> str:
    """Render command, scheduler, and projection state as distinct facts."""

    summary = dict(command.get("bounded_outcome_summary") or {})
    schema_version = str(summary.get("schema_version") or "unavailable")
    lines = [
        f"Runtime command {command.get('command_id', 'unknown')}",
        f"Command status: {command.get('status', 'unknown')}",
        f"Outcome schema: {schema_version}",
    ]
    if schema_version == "runtime_command_outcome@2":
        lines.extend(
            (
                f"Core receipt formed: {summary.get('core_receipt_formed')}",
                f"Scheduler: {summary.get('scheduler_status', 'unknown')}",
                (
                    "Processed signals: "
                    f"{summary.get('processed_signal_count', 'unknown')}"
                ),
                f"Suspended: {summary.get('suspended', 'unknown')}",
                f"Projection: {summary.get('projection_status', 'unknown')}",
                (
                    "Projection error: "
                    f"{summary.get('projection_error_code') or 'none'}"
                ),
                (
                    "Projection stage: "
                    f"{summary.get('projection_failed_stage') or 'none'}"
                ),
                f"Replay safe: {summary.get('replay_safe', 'unknown')}",
                (
                    "Bounded identities: "
                    f"outputs={summary.get('output_count', 0)} "
                    f"events={summary.get('event_count', 0)}"
                ),
            )
        )
    elif schema_version == "runtime_command_outcome@1":
        lines.extend(
            (
                (
                    "Processed signals: "
                    f"{summary.get('processed_signal_count', 'unknown')}"
                ),
                f"Suspended: {summary.get('suspended', 'unknown')}",
                "Scheduler: unavailable in historical @1 receipt",
                "Projection: unavailable in historical @1 receipt",
                "Replay safe: unknown for historical @1 receipt",
            )
        )
    if command.get("error_code"):
        lines.append(f"Command error: {command['error_code']}")
    if command.get("safe_error_summary"):
        lines.append(f"Summary: {command['safe_error_summary']}")
    if command.get("safe_retry_hint"):
        lines.append(f"Retry boundary: {command['safe_retry_hint']}")
    return "\n".join(lines)
