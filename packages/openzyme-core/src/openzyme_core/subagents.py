from __future__ import annotations

import json
from uuid import uuid4

from openzyme_domain import Task
from openzyme_domain import TaskStatus

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .agent_identity import create_agent_member
from .agent_identity import display_name_for_agent
from .agent_identity import AgentIdentityError
from .agent_identity import handle_for_agent
from .agent_identity import require_canonical_agent_id
from .agent_identity import resolve_agent_reference
from .protocols import ProtocolService
from .task_board import TaskBoardService
from .teammate_roster import TEAMMATE_ROLE_NAMES
from .teammate_roster import is_valid_teammate_role
from .teammate_roster import teammate_role_for_task_kind
from .workflow_knowledge import is_workflow_ref


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid4().hex[:12]}"


def default_agent_role_for_task(task: Task) -> str:
    role = teammate_role_for_task_kind(task.kind)
    if role is None:
        raise ValueError(
            f"Task kind {task.kind!r} does not imply a teammate role. "
            f"Choose one of: {', '.join(TEAMMATE_ROLE_NAMES)}."
        )
    return role


def _protocol_service(context: SessionRuntimeContext) -> ProtocolService:
    return ProtocolService(
        context.repositories,
        event_emitter=lambda event_type, payload: context.emit(event_type, payload),
        signal_notifier=context.signal_notifier,
    )


def _workflow_selection_error(
    invocation: ToolInvocation,
    task: Task,
    *,
    error_code: str,
    summary: str,
    hint: str,
    details: dict[str, object],
) -> ToolResult:
    payload = {
        "task_id": task.task_id,
        "status": "workflow_selection_rejected",
        "error_code": error_code,
        **details,
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=task.task_id,
        lane_id=task.lane_id,
        status="workflow_selection_rejected",
        summary=summary,
        error_code=error_code,
        hint=hint,
        details=details,
    )


def register_subagent_tools(registry: ToolRegistry) -> None:
    def delegate_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        arguments = invocation.arguments
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        task = service.get_task(str(arguments["task_id"]))
        if task is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"task {arguments['task_id']!r} does not exist",
                task_id=None,
                lane_id=None,
            )
        try:
            agent_role = str(arguments.get("agent_role") or default_agent_role_for_task(task))
        except ValueError as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=str(exc),
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        if not is_valid_teammate_role(agent_role):
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=(
                    f"Unknown teammate role {agent_role!r}. "
                    f"Choose one of: {', '.join(TEAMMATE_ROLE_NAMES)}."
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
            )
        open_blockers = service.open_blocker_ids(task)
        if open_blockers:
            summary = (
                f"Task {task.task_id} is blocked by unfinished task(s): "
                f"{', '.join(open_blockers)}."
            )
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(
                    {
                        "task": task.to_dict(),
                        "status": "task_not_ready",
                        "error_code": "task_blocked",
                        "blocked_by_open_task_ids": list(open_blockers),
                    },
                    sort_keys=True,
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="task_not_ready",
                summary=summary,
                error_code="task_blocked",
                hint=(
                    "Complete the blocker task(s), update this task with the "
                    "upstream outputs, then delegate it."
                ),
                details={"blocked_by_open_task_ids": list(open_blockers)},
            )
        if task.assigned_ref is not None:
            summary = f"Task {task.task_id} is already assigned to {task.assigned_ref}."
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(
                    {
                        "task": task.to_dict(),
                        "status": "task_not_ready",
                        "error_code": "task_already_assigned",
                        "assigned_ref": task.assigned_ref,
                    },
                    sort_keys=True,
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="task_not_ready",
                summary=summary,
                error_code="task_already_assigned",
                hint=(
                    "Use protocol.send or task.update for an already assigned "
                    "task instead of delegating it again."
                ),
                details={"assigned_ref": task.assigned_ref},
            )
        if task.status is not TaskStatus.TODO:
            summary = f"Task {task.task_id} is not ready for delegation because its status is {task.status.value}."
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=json.dumps(
                    {
                        "task": task.to_dict(),
                        "status": "task_not_ready",
                        "error_code": "task_status_not_ready",
                    },
                    sort_keys=True,
                ),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="task_not_ready",
                summary=summary,
                error_code="task_status_not_ready",
                hint="Only TODO, unassigned, unblocked tasks can be delegated.",
                details={"task_status": task.status.value},
            )
        raw_workflow_refs = arguments.get("workflow_refs")
        if raw_workflow_refs is None:
            workflow_refs: tuple[str, ...] = ()
        elif not isinstance(raw_workflow_refs, list) or not all(
            isinstance(item, str) and is_workflow_ref(item)
            for item in raw_workflow_refs
        ):
            return _workflow_selection_error(
                invocation,
                task,
                error_code="workflow_refs_invalid",
                summary=(
                    "task.delegate workflow_refs must be an array of exact "
                    "authorized workflow references."
                ),
                hint=(
                    "Omit workflow_refs or pass [] for no binding; otherwise pass "
                    "exact workflow refs from the current explicit focus."
                ),
                details={"workflow_refs": raw_workflow_refs},
            )
        else:
            workflow_refs = tuple(raw_workflow_refs)
        if len(workflow_refs) != len(set(workflow_refs)):
            return _workflow_selection_error(
                invocation,
                task,
                error_code="workflow_refs_duplicate",
                summary="task.delegate workflow_refs contain duplicates.",
                hint="Pass each explicitly selected workflow reference at most once.",
                details={"workflow_refs": list(workflow_refs)},
            )
        authorized_workflow_refs = tuple(
            key for key in context.active_skill_keys if is_workflow_ref(key)
        )
        unauthorized_workflow_refs = tuple(
            ref for ref in workflow_refs if ref not in authorized_workflow_refs
        )
        if unauthorized_workflow_refs:
            return _workflow_selection_error(
                invocation,
                task,
                error_code="workflow_ref_not_authorized",
                summary=(
                    "task.delegate can bind only an explicit subset of the "
                    "caller's authorized workflow refs."
                ),
                hint=(
                    "Use a workflow ref from the current explicit focus, or omit "
                    "workflow_refs to delegate without a workflow binding."
                ),
                details={
                    "workflow_refs": list(workflow_refs),
                    "unauthorized_workflow_refs": list(unauthorized_workflow_refs),
                    "authorized_workflow_refs": list(authorized_workflow_refs),
                },
            )
        workflow_manifests: list[dict[str, object]] = []
        if workflow_refs:
            from .teammates import validate_teammate_workflow_requirements

            try:
                workflow_packs = validate_teammate_workflow_requirements(
                    context,
                    role=agent_role,
                    workflow_refs=workflow_refs,
                )
            except (KeyError, ValueError) as exc:
                reason = str(exc)
                if "digest drift" in reason:
                    error_code = "workflow_manifest_drift"
                    summary = (
                        "The selected workflow manifest or knowledge digest drifted."
                    )
                    hint = (
                        "Re-select the current versioned workflow ref before "
                        "delegating this task."
                    )
                elif "workflow requirements unavailable" in reason:
                    error_code = "workflow_role_incompatible"
                    summary = (
                        f"The selected workflow cannot run on teammate role "
                        f"{agent_role!r}."
                    )
                    hint = (
                        "Choose a compatible teammate role/tool surface, or "
                        "delegate without this workflow binding."
                    )
                else:
                    error_code = "workflow_binding_invalid"
                    summary = "The selected workflow binding could not be resolved."
                    hint = (
                        "Re-select a registered versioned workflow ref, then retry "
                        "the delegation."
                    )
                return _workflow_selection_error(
                    invocation,
                    task,
                    error_code=error_code,
                    summary=summary,
                    hint=hint,
                    details={
                        "workflow_refs": list(workflow_refs),
                        "agent_role": agent_role,
                        "reason": reason,
                    },
                )
            workflow_manifests = [pack.manifest.to_dict() for pack in workflow_packs]
        if "agent_id" in arguments:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content="task.delegate no longer accepts agent_id; use agent_ref for an existing teammate or agent_role to create one.",
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="agent_id_not_supported",
                summary="task.delegate rejected role/identity mixing.",
                error_code="agent_id_not_supported",
                hint="Pass agent_role for capability selection and optional agent_ref such as @ada for an existing teammate.",
            )
        try:
            raw_agent_ref = arguments.get("agent_ref")
            agent_ref = None if raw_agent_ref is None else str(raw_agent_ref).strip()
            if agent_ref == "":
                agent_ref = None
            elif is_valid_teammate_role(agent_ref):
                if agent_ref != agent_role:
                    return ToolResult(
                        call_id=invocation.call_id,
                        tool_name=invocation.tool_name,
                        ok=False,
                        content=json.dumps(
                            {
                                "agent_ref": raw_agent_ref,
                                "agent_role": agent_role,
                                "status": "agent_ref_role_mismatch",
                            },
                            sort_keys=True,
                        ),
                        task_id=task.task_id,
                        lane_id=task.lane_id,
                        status="agent_ref_role_mismatch",
                        summary=(
                            f"agent_ref {raw_agent_ref!r} is a role alias, "
                            f"not an existing teammate reference for role {agent_role!r}."
                        ),
                        error_code="agent_ref_role_mismatch",
                        hint=(
                            "Omit agent_ref to create a new teammate for agent_role, "
                            "or pass an existing canonical agent_id, handle, or nickname."
                        ),
                    )
                agent_ref = None
            if agent_ref is None:
                agent = create_agent_member(
                    context.repositories,
                    session_id=task.session_id,
                    role=agent_role,  # type: ignore[arg-type]
                    lane_id=task.lane_id,
                    task_id=task.task_id,
                )
            else:
                resolution = resolve_agent_reference(
                    context.repositories,
                    session_id=task.session_id,
                    reference=str(agent_ref),
                )
                if resolution.agent is None:
                    return ToolResult(
                        call_id=invocation.call_id,
                        tool_name=invocation.tool_name,
                        ok=False,
                        content=json.dumps(
                            {
                                "agent_ref": agent_ref,
                                "resolution": resolution.resolution,
                                "status": "agent_ref_not_found",
                            },
                            sort_keys=True,
                        ),
                        task_id=task.task_id,
                        lane_id=task.lane_id,
                        status="agent_ref_not_found",
                        summary=f"agent_ref {agent_ref!r} did not resolve to an existing teammate.",
                        error_code="agent_ref_not_found",
                        hint="Use a canonical agent_id, handle such as @ada, or visible nickname for an existing teammate.",
                    )
                agent = resolution.agent
                if agent.role != agent_role:
                    return ToolResult(
                        call_id=invocation.call_id,
                        tool_name=invocation.tool_name,
                        ok=False,
                        content=json.dumps(
                            {
                                "agent_ref": agent_ref,
                                "agent_id": agent.agent_id,
                                "agent_role": agent.role,
                                "requested_role": agent_role,
                            },
                            sort_keys=True,
                        ),
                        task_id=task.task_id,
                        lane_id=task.lane_id,
                        status="agent_role_mismatch",
                        summary=(
                            f"agent_ref {agent_ref!r} resolved to role {agent.role!r}, "
                            f"not requested role {agent_role!r}."
                        ),
                        error_code="agent_role_mismatch",
                    )
                require_canonical_agent_id(agent.agent_id)
        except AgentIdentityError as exc:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=str(exc),
                task_id=task.task_id,
                lane_id=task.lane_id,
                status="invalid_agent_identity",
                summary=str(exc),
                error_code="invalid_agent_identity",
            )
        agent_id = agent.agent_id
        correlation_id = str(arguments.get("correlation_id") or _new_id("corr"))
        instructions = str(
            arguments.get("instructions") or task.description or task.subject
        )
        protocol = _protocol_service(context)
        payload_ref = protocol.persist_payload(
            session_id=task.session_id,
            document_kind="delegation_request",
            payload={
                "task_id": task.task_id,
                "instructions": instructions,
                "role": agent_role,
                "agent_id": agent_id,
                "nickname": agent.nickname,
                "display_name": display_name_for_agent(agent),
                "handle": handle_for_agent(agent),
                "workflow_refs": list(workflow_refs),
                "workflow_manifests": workflow_manifests,
            },
        )
        task = service.claim_task(
            task.task_id,
            assigned_ref=agent_id,
        )
        delegation = protocol.delegate(
            session_id=task.session_id,
            agent_id=agent_id,
            name=display_name_for_agent(agent),
            role=agent_role,
            payload_ref=payload_ref,
            task_id=task.task_id,
            lane_id=task.lane_id,
            correlation_id=correlation_id,
            nickname=agent.nickname,
            display_name=display_name_for_agent(agent),
            handle=handle_for_agent(agent),
        )
        signals = [
            signal.to_dict()
            for signal in context.repositories.runtime_signals.list_by_session(
                task.session_id
            )
            if signal.agent_id == agent_id
            and signal.correlation_id == correlation_id
            and signal.source_ref == delegation.request_message.message_id
        ]
        status = "wakeup_queued" if signals else "wakeup_not_created"
        ok = bool(signals)
        payload = {
            "task": task.to_dict(),
            "agent": delegation.agent.to_dict(),
            "agent_ref": handle_for_agent(delegation.agent),
            "correlation_id": correlation_id,
            "delegation_message_id": delegation.request_message.message_id,
            "signals": signals,
            "wakeup_queued": ok,
            "status": status,
        }
        summary = (
            f"Delegation queued for {agent_id} with {len(signals)} wakeup signal(s)."
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(payload, sort_keys=True),
            task_id=task.task_id,
            lane_id=task.lane_id,
            status=status,
            summary=summary,
            error_code=None if ok else "wakeup_signal_missing",
            hint=None
            if ok
            else "The delegation was persisted, but no runtime wakeup signal was created.",
            details={
                "agent_id": agent_id,
                "correlation_id": correlation_id,
                "signal_count": len(signals),
            },
        )

    registry.register("task.delegate", delegate_task_handler)


__all__ = [
    "default_agent_role_for_task",
    "register_subagent_tools",
]
