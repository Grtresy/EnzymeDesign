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
    if workspace.get("schema_version") != "file_workspace_public@1":
        raise ValueError("unsupported workspace schema")
    session = workspace["session"]
    task_items = workspace.get("task_board", {}).get("items", [])
    lanes = workspace.get("lane_board", {}).get("lanes", [])
    approvals = workspace.get("pending_approvals", [])
    reports = workspace.get("reports", [])
    statuses = workspace.get("workspace_status", [])
    private_revisions = workspace.get("private_revisions", [])
    publications = workspace.get("published_revisions", [])
    scientific = workspace.get("scientific_deliverables", [])
    jobs = workspace.get("external_jobs", [])
    results = workspace.get("external_job_results", [])
    leases = workspace.get("capability_leases", [])
    lines = [
        f"Session {session['session_id']}",
        f"Status: {session['status']}",
        f"Objective: {session['objective']}",
        f"Tasks: {len(task_items)}",
        f"Lanes: {len(lanes)}",
        f"Pending approvals: {len(approvals)}",
        f"Reports: {len(reports)}",
        f"Workspace states: {len(statuses)}",
        f"Private revisions: {len(private_revisions)}",
        f"Publications: {len(publications)}",
        f"Scientific deliverables: {len(scientific)}",
        f"External jobs/results: {len(jobs)}/{len(results)}",
        f"Capability leases: {len(leases)}",
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
    if statuses:
        lines.append("Workspace status")
        for status in statuses:
            lines.append(
                f"- {status['workspace_id']} generation={status['workspace_generation']} "
                f"dirty={status['dirty_state']} head={status.get('head_commit')}"
            )
            for path in status.get("changed_paths", []):
                lines.append(f"  - {path}")
    if publications:
        lines.append("Immutable publications")
        for publication in publications:
            lines.append(
                f"- {publication['publication_ref']} commit={publication['commit']} "
                f"manifest={publication['manifest_digest']}"
            )
    if scientific:
        lines.append("Scientific deliverables")
        for deliverable in scientific:
            lines.append(
                f"- {deliverable['path']} role={deliverable['scientific_role']} "
                f"digest={deliverable['content_digest']}"
            )
    if jobs or results:
        lines.append("External execution")
        for job in jobs:
            lines.append(
                f"- job {job['handle_id']} backend={job['backend']} "
                f"source={job['source_commit']}"
            )
        for result in results:
            lines.append(
                f"- result {result['result_id']} state={result['terminal_state']} "
                f"digest={result['result_digest']}"
            )
    if leases:
        lines.append("Capability leases")
        for lease in leases:
            lines.append(
                f"- {lease['lease_id']} owner={lease['agent_member_id']} "
                f"status={lease['status']} fence={lease['state_version']}"
            )
    owner = workspace.get("executor_owner_workspace")
    if owner:
        lines.append("Owning executor workspace")
        lines.append(
            f"- {owner['login_alias']}:{owner['workspace_path']} "
            f"generation={owner['workspace_generation']}"
        )
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
