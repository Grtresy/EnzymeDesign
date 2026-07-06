from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ApprovalRequestStatus
from openzyme_domain import ControlledOperationStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import TaskStatus
from openzyme_runtime import S12_ROUTE_POLICIES
from openzyme_runtime import ToolGovernance
from openzyme_runtime import ToolInvocation
from openzyme_runtime import ToolResult
from openzyme_runtime import ToolSideEffect

from .artifact_projection import project_artifact_for_agent
from .harness import SessionRuntimeContext
from .harness import ToolRegistry
from .projections import SessionProjectionBuilder
from .runtime_consistency import RuntimeConsistencyService
from .task_board import TaskBoardService


_DEFAULT_SECTIONS = (
    "session",
    "tasks",
    "agents",
    "inbox",
    "runtime_signals",
    "artifacts",
    "capabilities",
    "operations",
    "approvals",
    "outcomes",
    "diagnostics",
    "affordances",
)
_KNOWN_SECTIONS = set(_DEFAULT_SECTIONS)


def _limit(arguments: dict[str, Any]) -> int:
    value = arguments.get("limit", 20)
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return 20
    return min(max(parsed, 1), 100)


def _sections(arguments: dict[str, Any]) -> tuple[str, ...]:
    requested = arguments.get("sections")
    if requested is None:
        return _DEFAULT_SECTIONS
    if not isinstance(requested, list | tuple):
        return _DEFAULT_SECTIONS
    sections = tuple(str(section) for section in requested if str(section) in _KNOWN_SECTIONS)
    return sections or _DEFAULT_SECTIONS


def _status_counts(items: list[Any], status_getter: Any) -> dict[str, int]:
    counts: dict[str, int] = {}
    for item in items:
        status = str(status_getter(item))
        counts[status] = counts.get(status, 0) + 1
    return dict(sorted(counts.items()))


def _artifact_state(artifact: SessionArtifactRecord) -> dict[str, Any]:
    metadata = dict(artifact.metadata or {})
    digest = (
        metadata.get("sealed_digest")
        or metadata.get("content_digest")
        or metadata.get("source_tree_digest")
    )
    return {
        "artifact_id": artifact.artifact_id,
        "kind": artifact.kind.value,
        "relative_path": artifact.relative_path,
        "title": artifact.title,
        "task_id": artifact.task_id,
        "lane_id": artifact.lane_id,
        "invocation_id": artifact.invocation_id,
        "run_id": artifact.run_id,
        "digest": digest,
        "sealed": bool(metadata.get("sealed_digest") or metadata.get("sealed_at")),
        "readiness": metadata.get("readiness") or metadata.get("status") or "available",
        "path_authorization": "catalog_authorized",
        "source": metadata.get("source") or metadata.get("producer"),
        "format": metadata.get("format"),
        "provider": metadata.get("provider"),
        "external_id": metadata.get("external_id"),
        "safe_projection": project_artifact_for_agent(artifact),
    }


def _project_tool_affordance(
    context: SessionRuntimeContext,
    *,
    sections: tuple[str, ...],
) -> dict[str, Any] | None:
    if "affordances" not in sections:
        return None
    pre_step = context.current_step_context
    if pre_step is None:
        return {
            "tool_surface": {
                "visible_tools": [],
                "note": "No active AgentStepContext is available; call during an agent step for visible tool governance.",
            },
            "route_policies": _route_policy_facts(),
        }
    router = context.current_tool_router
    if router is None:
        return {
            "tool_surface": {
                "visible_tools": [],
                "note": "No active ToolRouter is available; call during an agent step for visible tool governance.",
            },
            "route_policies": _route_policy_facts(),
        }
    tools: list[dict[str, Any]] = []
    for spec in router.model_visible_specs(pre_step):
        governance = router.governance(pre_step, spec.tool_name) or ToolGovernance(
            side_effect=ToolSideEffect.WRITE
        )
        tools.append(
            {
                "tool_name": spec.tool_name,
                "description": spec.description,
                "input_schema": spec.input_schema,
                "governance": {
                    "role_scope": list(governance.role_scope),
                    "supports_parallel": governance.supports_parallel,
                    "side_effect": governance.side_effect.value,
                    "approval_required": governance.approval_required,
                    "result_budget_policy": governance.result_budget_policy,
                },
            }
        )
    return {
        "tool_surface": {
            "visible_tools": tools,
            "tool_count": len(tools),
        },
        "route_policies": _route_policy_facts(),
    }


def _route_policy_facts() -> list[dict[str, Any]]:
    facts: list[dict[str, Any]] = []
    for policy_id, policy in sorted(S12_ROUTE_POLICIES.items()):
        facts.append(
            {
                "route_policy_id": policy_id,
                "sdk_module": policy.get("sdk_module"),
                "function_name": policy.get("function_name"),
                "selected_backend": policy.get("selected_backend"),
                "backend_category": policy.get("backend_category"),
                "route_reason": policy.get("route_reason"),
                "resource_class": policy.get("resource_class"),
                "approval_requirement": dict(policy.get("approval_requirement") or {}),
                "status": policy.get("status"),
                "error_code": policy.get("error_code"),
                "evidence_ref": policy.get("evidence_ref"),
                "parameter_inventory_ref": policy.get("parameter_inventory_ref"),
            }
        )
    return facts


def _capability_outcome_status(invocation_status: EngineInvocationStatus) -> str:
    if invocation_status.is_terminal:
        return "ready"
    if invocation_status is EngineInvocationStatus.WAITING_APPROVAL:
        return "waiting_approval"
    return "pending"


@dataclass(slots=True)
class WorldInspectionService:
    context: SessionRuntimeContext

    def inspect(
        self,
        *,
        sections: tuple[str, ...] = _DEFAULT_SECTIONS,
        task_id: str | None = None,
        agent_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        session_id = self.context.snapshot.session.session_id
        task_board = TaskBoardService(self.context.repositories).build_projection(session_id)
        tasks = self.context.repositories.tasks.list_by_session(session_id)
        agents = self.context.repositories.agents.list_by_session(session_id)
        signals = self.context.repositories.runtime_signals.list_by_session(session_id)
        approvals = self.context.repositories.approvals.list_by_session(session_id)
        invocations = self.context.repositories.invocations.list_by_session(session_id)
        operations = self.context.repositories.controlled_operations.list_by_session(session_id)
        artifacts = self.context.repositories.artifacts.list_by_session(session_id)
        runtime_audit = RuntimeConsistencyService(self.context.repositories).audit_session(session_id)

        payload: dict[str, Any] = {
            "schema_version": "world.inspection.v1",
            "mode": "facts_only",
            "strategy_policy": {
                "harness_recommends_actions": False,
                "completion_decider": "agent_via_task.finish",
                "capability_terminal_means": "outcome_ready_evidence",
            },
            "filters": {
                "sections": list(sections),
                "task_id": task_id,
                "agent_id": agent_id,
                "limit": limit,
            },
        }

        if "session" in sections:
            payload["session"] = {
                **self.context.snapshot.session.to_dict(),
                "focus": {
                    "agent_id": self.context.agent_id,
                    "actor_kind": self.context.actor_kind,
                    "actor_role": self.context.actor_role,
                    "task_id": self.context.restore_focus.task_id,
                    "lane_id": self.context.restore_focus.lane_id,
                    "correlation_id": self.context.correlation_id,
                    "signal_id": self.context.signal_id,
                    "wakeup_reason": self.context.wakeup_reason,
                },
            }
        if "tasks" in sections:
            payload["tasks"] = {
                "task_board": task_board.to_dict(),
                "status_counts": _status_counts(tasks, lambda task: task.status.value),
                "assigned_task": self._find_task(task_id or self.context.restore_focus.task_id),
                "delegated_tasks": [
                    task.to_dict()
                    for task in tasks
                    if task.assigned_ref and task.assigned_ref.startswith("agent:")
                ][:limit],
                "terminal_statuses": [
                    status.value for status in TaskStatus if status.is_terminal
                ],
            }
        if "agents" in sections:
            payload["agents"] = [
                {
                    **agent.to_dict(),
                    "pending_signal_count": sum(
                        1
                        for signal in signals
                        if signal.agent_id == agent.agent_id
                        and signal.status is AgentRuntimeSignalStatus.PENDING
                    ),
                    "unread_inbox_count": len(
                        self.context.repositories.inbox.list_unread_for_recipient(
                            session_id, agent.agent_id
                        )
                    ),
                }
                for agent in agents
                if agent_id is None or agent.agent_id == agent_id
            ][:limit]
        if "inbox" in sections:
            messages = self.context.repositories.inbox.list_by_session(session_id)
            payload["inbox"] = [
                message.to_dict()
                for message in messages
                if (
                    agent_id is None
                    or message.sender == agent_id
                    or message.recipient == agent_id
                )
            ][:limit]
        if "runtime_signals" in sections:
            payload["runtime_signals"] = {
                "items": [
                    signal.to_dict()
                    for signal in signals
                    if (
                        (task_id is None or signal.task_id == task_id)
                        and (agent_id is None or signal.agent_id == agent_id)
                    )
                ][:limit],
                "status_counts": _status_counts(signals, lambda signal: signal.status.value),
            }
        if "artifacts" in sections:
            payload["artifacts"] = {
                "items": [
                    _artifact_state(artifact)
                    for artifact in artifacts
                    if task_id is None or artifact.task_id == task_id
                ][:limit],
                "kind_counts": _status_counts(artifacts, lambda artifact: artifact.kind.value),
            }
        if "capabilities" in sections:
            capabilities = SessionProjectionBuilder(self.context.repositories)._build_capabilities_projection(session_id)
            payload["capabilities"] = capabilities
        if "operations" in sections:
            payload["operations"] = {
                "items": [
                    {
                        **operation.to_dict(),
                        "engine_invocation_id": f"inv_sandbox_adapter_{operation.operation_id}",
                        "engine_invocation_status": self._operation_invocation_status(
                            operation.operation_id
                        ),
                    }
                    for operation in operations
                    if task_id is None or operation.task_id == task_id
                ][:limit],
                "status_counts": _status_counts(operations, lambda operation: operation.status.value),
                "terminal_statuses": [
                    status.value
                    for status in ControlledOperationStatus
                    if status.is_terminal
                ],
            }
        if "approvals" in sections:
            payload["approvals"] = {
                "pending": [
                    approval.to_dict()
                    for approval in approvals
                    if approval.status is ApprovalRequestStatus.PENDING
                    and (task_id is None or approval.task_id == task_id)
                ][:limit],
                "items": [
                    approval.to_dict()
                    for approval in approvals
                    if task_id is None or approval.task_id == task_id
                ][:limit],
                "status_counts": _status_counts(approvals, lambda approval: approval.status.value),
            }
        if "outcomes" in sections:
            payload["outcomes"] = [
                {
                    "invocation_id": invocation.invocation_id,
                    "engine_name": invocation.engine_name,
                    "task_id": invocation.task_id,
                    "lane_id": invocation.lane_id,
                    "status": invocation.status.value,
                    "outcome_status": _capability_outcome_status(invocation.status),
                    "output_ref": invocation.output_ref,
                    "approval_id": invocation.approval_id,
                    "finished_at": invocation.finished_at,
                    "consumption": (
                        "task_terminal"
                        if invocation.task_id
                        and (
                            task := self.context.repositories.tasks.get(invocation.task_id)
                        )
                        is not None
                        and task.status.is_terminal
                        else "unconsumed"
                        if invocation.status.is_terminal
                        else "not_ready"
                    ),
                }
                for invocation in invocations
                if task_id is None or invocation.task_id == task_id
            ][:limit]
        if "diagnostics" in sections:
            payload["diagnostics"] = runtime_audit.to_dict()

        affordances = _project_tool_affordance(self.context, sections=sections)
        if affordances is not None:
            payload["affordances"] = affordances

        return payload

    def _find_task(self, task_id: str | None) -> dict[str, Any] | None:
        if task_id is None:
            return None
        task = self.context.repositories.tasks.get(task_id)
        if task is None:
            return None
        return task.to_dict()

    def _operation_invocation_status(self, operation_id: str) -> str | None:
        invocation = self.context.repositories.invocations.get(
            f"inv_sandbox_adapter_{operation_id}"
        )
        return None if invocation is None else invocation.status.value


def register_world_inspection_tools(registry: ToolRegistry) -> None:
    def inspect_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        arguments = invocation.arguments
        payload = WorldInspectionService(context).inspect(
            sections=_sections(arguments),
            task_id=None
            if arguments.get("task_id") is None
            else str(arguments.get("task_id")),
            agent_id=None
            if arguments.get("agent_id") is None
            else str(arguments.get("agent_id")),
            limit=_limit(arguments),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
            status="world_inspected",
            summary="World facts inspected.",
            details={
                "sections": payload["filters"]["sections"],
                "facts_only": True,
            },
        )

    registry.register("world.inspect", inspect_handler)


__all__ = ["WorldInspectionService", "register_world_inspection_tools"]
