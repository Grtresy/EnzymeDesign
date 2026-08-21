from __future__ import annotations

import json
from typing import Any


def render_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def render_v3_workspace_v2(workspace: dict[str, Any]) -> str:
    """Render the closed Kernel shell and namespaced extension identities."""

    if workspace.get("schema_version") != "file_workspace_public@2":
        raise ValueError("unsupported workspace schema")
    if set(workspace) != {"schema_version", "release", "core", "extensions"}:
        raise ValueError("file_workspace_public@2 root is not closed")
    core = dict(workspace["core"])
    session = dict(core["session"])
    runtime = dict(core["runtime"])
    workspace_state = dict(core["workspace"])
    operations = dict(core["operations"])
    failures = dict(core["failures"])
    reflection = dict(core["tool_reflection"])
    extensions = dict(workspace["extensions"])
    affordances = list(reflection["affordances"])
    blocked = [
        item
        for item in affordances
        if str(item.get("state", "")).startswith("blocked_")
        or item.get("state") == "temporarily_unavailable"
    ]
    lines = [
        f"Session {session['session_id']}",
        f"Status: {session.get('status', 'unknown')}",
        f"Objective: {session.get('objective', '')}",
        f"Tasks: {len(core['tasks'])}",
        f"Lanes: {len(core['lanes'])}",
        f"Agents: {len(core['agents'])}",
        f"Pending/recorded approvals: {len(core['approvals'])}",
        f"Authority leases: {len(core['authority_leases'])}",
        f"Workspace generations: {len(workspace_state['generations'])}",
        f"Workspace runtime bindings: {len(workspace_state['runtime_bindings'])}",
        f"Publications: {len(core['publications'])}",
        f"Controlled operations: {len(operations['controlled'])}",
        f"Runtime signals: {len(runtime['signals'])}",
        f"Failures: {len(failures['observations'])}",
        f"Available tools: {len(reflection['available_tool_names'])}",
        f"Blocked tools: {len(blocked)}",
        f"Extension sections: {len(extensions)}",
    ]
    if core["tasks"]:
        lines.append("Task board")
        for task in core["tasks"]:
            lines.append(
                f"- {task['task_id']}: {task['subject']} [{task['status']}]"
            )
    if workspace_state["generations"]:
        lines.append("Workspace generations")
        for generation in workspace_state["generations"]:
            lines.append(
                f"- {generation['workspace_id']} generation={generation['generation']} "
                f"status={generation['status']} provider={generation['provider_id']}"
            )
    if core["publications"]:
        lines.append("Immutable publications")
        for publication in core["publications"]:
            lines.append(
                f"- {publication['publication_ref']} commit={publication['commit']} "
                f"tree={publication['tree']}"
            )
    if blocked:
        lines.append("Unavailable tool affordances")
        for affordance in blocked:
            blockers = ",".join(
                str(item.get("code", "unknown"))
                for item in affordance.get("blockers", [])
            )
            lines.append(
                f"- {affordance['tool_name']}: {affordance['state']} ({blockers})"
            )
    if extensions:
        lines.append("Extension sections")
        for section_id, section in sorted(extensions.items()):
            lines.append(
                f"- {section_id}: contract={section['section_contract_digest']} "
                f"projection={section['projection_digest']}"
            )
    return "\n".join(lines)


__all__ = ["render_json", "render_v3_workspace_v2"]
