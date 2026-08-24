from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any


def render_json(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=True, indent=2, sort_keys=True)


def render_v3_fact(title: str, fact: object) -> str:
    if not isinstance(fact, Mapping):
        raise ValueError(f"{title} must be one public object")
    return title + "\n" + json.dumps(
        fact,
        ensure_ascii=True,
        indent=2,
        sort_keys=True,
    )


def render_v3_records(title: str, records: object) -> str:
    lines = [title]
    _append_public_records(
        lines,
        "Records",
        records,
        identity_fields=(
            "message_id",
            "task_id",
            "agent_member_id",
            "protocol_ref",
            "approval_id",
            "failure_id",
            "diagnostic_id",
        ),
    )
    if len(lines) == 1:
        lines.append("No records.")
    return "\n".join(lines)


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
    conversation = dict(core["conversation"])
    protocol = dict(core["protocol"])
    resident = session.get("resident_readiness")
    readiness = (
        resident.get("readiness", "unknown")
        if isinstance(resident, Mapping)
        else resident or "unavailable"
    )
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
        f"Workspace readiness: {readiness}",
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
        f"Runtime commands: {len(runtime.get('commands', []))}",
        f"Runtime outcomes: {len(runtime.get('outcomes', []))}",
        f"Conversation messages: {len(conversation['transcript']['messages'])}",
        f"Protocol records: {len(protocol.get('records', []))}",
        f"Inbox messages: {len(protocol.get('inbox', []))}",
        f"Failures: {len(failures['observations'])}",
        f"Available tools: {len(reflection['available_tool_names'])}",
        "Direct tools: "
        + ",".join(reflection["tool_exposure"]["direct_tool_names"]),
        "Deferred tools: "
        + ",".join(reflection["tool_exposure"]["deferred_tool_names"]),
        "Command-scoped expansions: "
        + str(len(reflection["tool_exposure"]["command_expansions"])),
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
                f"- {generation.get('workspace_id', 'workspace')} "
                f"generation={generation.get('generation', 'unknown')} "
                f"status={generation.get('status', 'unknown')} "
                f"provider={generation.get('provider_id', 'undisclosed')}"
            )
    _append_public_records(
        lines,
        "Workspace provisioning",
        workspace_state.get("provisioning", []),
        identity_fields=("intent_id", "workspace_id"),
    )
    _append_public_records(
        lines,
        "Conversation transcript",
        conversation["transcript"]["messages"],
        identity_fields=("message_id",),
    )
    _append_public_records(
        lines,
        "Agents",
        core["agents"],
        identity_fields=("agent_member_id", "agent_id"),
    )
    _append_public_records(
        lines,
        "Delegations and protocol",
        protocol.get("records", []),
        identity_fields=("protocol_ref",),
    )
    _append_public_records(
        lines,
        "Inbox",
        protocol.get("inbox", []),
        identity_fields=("message_id",),
    )
    _append_public_records(
        lines,
        "Approvals",
        core["approvals"],
        identity_fields=("approval_id",),
    )
    _append_public_records(
        lines,
        "Runtime commands",
        runtime.get("commands", []),
        identity_fields=("command_id",),
    )
    _append_public_records(
        lines,
        "Runtime outcomes",
        runtime.get("outcomes", []),
        identity_fields=("outcome_id", "command_id"),
    )
    workflow_authority = runtime["workflow_authority"]
    _append_public_records(
        lines,
        "Workflow authority bindings",
        workflow_authority["bindings"],
        identity_fields=("authority_id",),
    )
    _append_public_records(
        lines,
        "Runtime signal authority links",
        workflow_authority["signal_links"],
        identity_fields=("signal_id",),
    )
    _append_public_records(
        lines,
        "Failures",
        failures["observations"],
        identity_fields=("failure_id", "diagnostic_id"),
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


def _append_public_records(
    lines: list[str],
    title: str,
    records: object,
    *,
    identity_fields: tuple[str, ...],
) -> None:
    if not isinstance(records, (list, tuple)) or not records:
        return
    lines.append(title)
    for record in records:
        if not isinstance(record, Mapping):
            raise ValueError(f"{title} contains a non-object public record")
        identity = next(
            (
                str(record[field])
                for field in identity_fields
                if isinstance(record.get(field), str) and record.get(field)
            ),
            str(record.get("schema_version", "record")),
        )
        lines.append(
            f"- {identity}: "
            + json.dumps(record, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
        )


__all__ = [
    "render_json",
    "render_v3_fact",
    "render_v3_records",
    "render_v3_workspace_v2",
]
