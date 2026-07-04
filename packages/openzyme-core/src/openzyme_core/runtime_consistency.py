from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import TaskStatus

from .repositories import CoreRepositories


@dataclass(frozen=True, slots=True)
class RuntimeConsistencyWarning:
    code: str
    layer: str
    severity: str
    message: str
    attention: str
    task_id: str | None = None
    agent_id: str | None = None
    signal_id: str | None = None
    invocation_id: str | None = None
    task_status: str | None = None
    runtime_status: str | None = None
    recommendation: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "layer": self.layer,
            "severity": self.severity,
            "message": self.message,
            "attention": self.attention,
            "task_id": self.task_id,
            "agent_id": self.agent_id,
            "signal_id": self.signal_id,
            "invocation_id": self.invocation_id,
            "task_status": self.task_status,
            "runtime_status": self.runtime_status,
            "recommendation": self.recommendation,
        }


@dataclass(frozen=True, slots=True)
class RuntimeStateAudit:
    session_id: str
    warnings: tuple[RuntimeConsistencyWarning, ...]
    task_attention: tuple[dict[str, Any], ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "warnings": [warning.to_dict() for warning in self.warnings],
            "task_attention": list(self.task_attention),
            "warning_count": len(self.warnings),
            "needs_attention_count": sum(
                1
                for item in self.task_attention
                if item.get("needs_attention") or item.get("runtime_attention")
            ),
        }


class RuntimeConsistencyService:
    def __init__(self, repositories: CoreRepositories) -> None:
        self.repositories = repositories

    def audit_session(self, session_id: str) -> RuntimeStateAudit:
        tasks = {
            task.task_id: task
            for task in self.repositories.tasks.list_by_session(session_id)
        }
        agents = {
            agent.agent_id: agent
            for agent in self.repositories.agents.list_by_session(session_id)
        }
        signals = self.repositories.runtime_signals.list_by_session(session_id)
        invocations = self.repositories.invocations.list_by_session(session_id)
        task_attention = {
            task_id: {
                "task_id": task_id,
                "task_status": task.status.value,
                "task_failed": task.status is TaskStatus.FAILED,
                "runtime_signal_failed": False,
                "agent_turn_failed": False,
                "runtime_attention": False,
                "needs_attention": False,
                "capability_outcome_ready": False,
                "outcome_unconsumed": False,
                "reasons": [],
            }
            for task_id, task in tasks.items()
        }
        warnings: list[RuntimeConsistencyWarning] = []

        for signal in signals:
            if signal.status is not AgentRuntimeSignalStatus.FAILED:
                continue
            task = tasks.get(signal.task_id or "")
            error_text = f"{signal.error_message or ''}\n{signal.last_error or ''}".lower()
            agent_turn_failed = (
                "max_steps_exceeded" in error_text
                or "step budget" in error_text
                or "max steps" in error_text
            )
            code = "agent_turn_failed" if agent_turn_failed else "runtime_signal_failed"
            layer = "agent_turn" if agent_turn_failed else "runtime_signal"
            warnings.append(
                RuntimeConsistencyWarning(
                    code=code,
                    layer=layer,
                    severity="warning",
                    attention="runtime_attention",
                    task_id=signal.task_id,
                    agent_id=signal.agent_id,
                    signal_id=signal.signal_id,
                    task_status=None if task is None else task.status.value,
                    runtime_status=signal.status.value,
                    message=(
                        "Runtime signal failed; this does not set the business task "
                        "status to failed."
                    ),
                    recommendation=(
                        "Inspect the agent turn and decide whether the agent should "
                        "retry, ask for recovery, or explicitly call task.finish."
                    ),
                )
            )
            if task is not None and not task.status.is_terminal:
                attention = task_attention[task.task_id]
                attention["runtime_signal_failed"] = True
                attention["agent_turn_failed"] = (
                    bool(attention["agent_turn_failed"]) or agent_turn_failed
                )
                attention["runtime_attention"] = True
                attention["needs_attention"] = True
                attention["reasons"].append(code)

        for agent in agents.values():
            if agent.status is not AgentMemberStatus.FAILED or agent.task_id is None:
                continue
            task = tasks.get(agent.task_id)
            if task is None or task.status.is_terminal:
                continue
            warnings.append(
                RuntimeConsistencyWarning(
                    code="agent_turn_failed",
                    layer="agent_turn",
                    severity="warning",
                    attention="runtime_attention",
                    task_id=task.task_id,
                    agent_id=agent.agent_id,
                    task_status=task.status.value,
                    runtime_status=agent.status.value,
                    message=(
                        "Agent failed while the business task remains non-terminal; "
                        "task status is unchanged."
                    ),
                    recommendation=(
                        "Review runtime diagnostics and let an agent explicitly "
                        "recover or finish the task."
                    ),
                )
            )
            attention = task_attention[task.task_id]
            attention["agent_turn_failed"] = True
            attention["runtime_attention"] = True
            attention["needs_attention"] = True
            attention["reasons"].append("agent_turn_failed")

        for invocation in invocations:
            task = tasks.get(invocation.task_id or "")
            assigned_agent = None if task is None else agents.get(task.assigned_ref or "")
            if not invocation.status.is_terminal:
                if task is None:
                    warnings.append(
                        RuntimeConsistencyWarning(
                            code="active_invocation_missing_task",
                            layer="engine_invocation",
                            severity="warning",
                            attention="needs_attention",
                            invocation_id=invocation.invocation_id,
                            task_id=invocation.task_id,
                            runtime_status=invocation.status.value,
                            message="Active engine invocation references a missing task.",
                            recommendation="Investigate orphaned runtime work.",
                        )
                    )
                    continue
                if task.status.is_terminal:
                    warnings.append(
                        RuntimeConsistencyWarning(
                            code="active_invocation_task_terminal",
                            layer="engine_invocation",
                            severity="warning",
                            attention="needs_attention",
                            task_id=task.task_id,
                            invocation_id=invocation.invocation_id,
                            task_status=task.status.value,
                            runtime_status=invocation.status.value,
                            message=(
                                "Active engine invocation remains after the linked "
                                "task reached a terminal business state."
                            ),
                            recommendation=(
                                "Cancel, reconcile, or explain the dangling runtime "
                                "work without changing task status automatically."
                            ),
                        )
                    )
                    task_attention[task.task_id]["runtime_attention"] = True
                    task_attention[task.task_id]["needs_attention"] = True
                    task_attention[task.task_id]["reasons"].append(
                        "active_invocation_task_terminal"
                    )
                if assigned_agent is not None and assigned_agent.status.is_terminal:
                    warnings.append(
                        RuntimeConsistencyWarning(
                            code="active_invocation_agent_terminal",
                            layer="engine_invocation",
                            severity="warning",
                            attention="needs_attention",
                            task_id=task.task_id,
                            agent_id=assigned_agent.agent_id,
                            invocation_id=invocation.invocation_id,
                            task_status=task.status.value,
                            runtime_status=invocation.status.value,
                            message=(
                                "Active engine invocation is still running while the "
                                "assigned agent is terminal."
                            ),
                            recommendation=(
                                "Surface runtime attention for operator or master "
                                "follow-up; do not infer task failure."
                            ),
                        )
                    )
                    task_attention[task.task_id]["runtime_attention"] = True
                    task_attention[task.task_id]["needs_attention"] = True
                    task_attention[task.task_id]["reasons"].append(
                        "active_invocation_agent_terminal"
                    )
            elif task is not None and not task.status.is_terminal:
                warnings.append(
                    RuntimeConsistencyWarning(
                        code="terminal_capability_outcome_unconsumed",
                        layer="capability_outcome",
                        severity="info",
                        attention="outcome_unconsumed",
                        task_id=task.task_id,
                        invocation_id=invocation.invocation_id,
                        task_status=task.status.value,
                        runtime_status=invocation.status.value,
                        message=(
                            "Capability outcome is terminal while the linked task "
                            "remains non-terminal; the owner has not consumed the "
                            "outcome into an explicit task.finish or follow-up yet."
                        ),
                        recommendation=(
                            "Use the capability outcome as evidence and wake the "
                            "owner for follow-up; only task.finish may set the "
                            "business terminal state."
                        ),
                    )
                )
                task_attention[task.task_id]["capability_outcome_ready"] = True
                task_attention[task.task_id]["outcome_unconsumed"] = True
                task_attention[task.task_id]["reasons"].append(
                    "terminal_capability_outcome_unconsumed"
                )

        for task in tasks.values():
            if task.status is not TaskStatus.IN_PROGRESS:
                continue
            related_signals = [signal for signal in signals if signal.task_id == task.task_id]
            related_invocations = [
                invocation
                for invocation in invocations
                if invocation.task_id == task.task_id
            ]
            if not related_signals and not related_invocations:
                continue
            failed_signals = all(
                signal.status is AgentRuntimeSignalStatus.FAILED
                for signal in related_signals
            )
            failed_invocations = all(
                invocation.status
                in {EngineInvocationStatus.FAILED, EngineInvocationStatus.CANCELLED}
                for invocation in related_invocations
            )
            if failed_signals and failed_invocations:
                warnings.append(
                    RuntimeConsistencyWarning(
                        code="task_runtime_attention",
                        layer="task_runtime",
                        severity="warning",
                        attention="needs_attention",
                        task_id=task.task_id,
                        task_status=task.status.value,
                        message=(
                            "Task remains in_progress but all associated runtime "
                            "work is terminal failed/cancelled."
                        ),
                        recommendation=(
                            "Mark runtime_attention for recovery; only task.finish "
                            "may set the business terminal state."
                        ),
                    )
                )
                attention = task_attention[task.task_id]
                attention["runtime_attention"] = True
                attention["needs_attention"] = True
                attention["reasons"].append("task_runtime_attention")

        normalized_attention = tuple(
            {
                **item,
                "reasons": list(dict.fromkeys(item["reasons"])),
            }
            for item in task_attention.values()
            if item["task_failed"]
            or item["runtime_attention"]
            or item["outcome_unconsumed"]
        )
        return RuntimeStateAudit(
            session_id=session_id,
            warnings=tuple(warnings),
            task_attention=normalized_attention,
        )


__all__ = [
    "RuntimeConsistencyService",
    "RuntimeConsistencyWarning",
    "RuntimeStateAudit",
]
