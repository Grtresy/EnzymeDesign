from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import TYPE_CHECKING

from openzyme_domain import AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
from openzyme_domain import AgentMemberStatus
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import EngineInvocationStatus
from openzyme_domain import FailureActorKind
from openzyme_domain import FailureRecoverability
from openzyme_domain import ScientificSelectionState
from openzyme_domain import TaskStatus

from .repositories import CoreRepositories
from .scientific_attempt_repositories import ScientificSelectionIntegrityError
from .scientific_attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .scientific_attempt_lifecycle import ScientificAttemptLifecycleResolver

if TYPE_CHECKING:
    from .scientific_workflow_contracts import (
        ScientificWorkflowContractRegistry,
    )


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
    def __init__(
        self,
        repositories: CoreRepositories,
        *,
        scientific_workflow_contract_registry: (
            ScientificWorkflowContractRegistry | None
        ) = None,
    ) -> None:
        self.repositories = repositories
        self.scientific_workflow_contract_registry = (
            scientific_workflow_contract_registry
        )

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
        failure_observations = self.repositories.failure_observations.list_by_session(
            session_id
        )
        runtime_failures_by_signal_attempt: dict[
            tuple[str, str], list[Any]
        ] = {}
        for failure in failure_observations:
            if (
                failure.source_kind == "runtime_signal"
                and failure.phase == "runtime"
            ):
                runtime_failures_by_signal_attempt.setdefault(
                    (failure.source_ref, failure.source_version),
                    [],
                ).append(failure)
        attempts = self.repositories.scientific_attempts.list_by_session(session_id)
        attempt_lifecycles = ScientificAttemptLifecycleResolver(
            self.repositories
        )
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
                "failure_observation_ids": [],
                "scientific_attempt_ids": [],
            }
            for task_id, task in tasks.items()
        }
        warnings: list[RuntimeConsistencyWarning] = []

        for failure in failure_observations:
            task = tasks.get(failure.task_id or "")
            requires_attention = (
                failure.actor_kind is FailureActorKind.SYSTEM
                or failure.recoverability
                in {
                    FailureRecoverability.RECONCILIATION_REQUIRED,
                    FailureRecoverability.AUTHORIZATION_REQUIRED,
                    FailureRecoverability.AGENT_CAN_REPLAN,
                    FailureRecoverability.RUNTIME_RETRY,
                    FailureRecoverability.TERMINAL,
                }
            )
            if task is None or task.status.is_terminal or not requires_attention:
                continue
            code = (
                "system_runtime_failure"
                if failure.actor_kind is FailureActorKind.SYSTEM
                else "failure_reconciliation_required"
            )
            warnings.append(
                RuntimeConsistencyWarning(
                    code=code,
                    layer="failure_observation",
                    severity="warning",
                    attention="runtime_attention",
                    task_id=task.task_id,
                    agent_id=failure.agent_id,
                    task_status=task.status.value,
                    runtime_status=failure.recoverability.value,
                    message=(
                        "The system recorded a runtime failure without an agent "
                        "decision; the business task status remains unchanged."
                        if failure.actor_kind is FailureActorKind.SYSTEM
                        else "A canonical failure requires explicit reconciliation."
                    ),
                    recommendation=(
                        "Restore runtime authority and let the agent inspect the "
                        "structured failure before choosing recovery or refusal."
                    ),
                )
            )
            attention = task_attention[task.task_id]
            attention["runtime_attention"] = True
            attention["needs_attention"] = True
            attention["reasons"].append(code)
            attention["failure_observation_ids"].append(failure.failure_id)

        for attempt in attempts:
            task = tasks.get(attempt.task_id)
            try:
                lifecycle = attempt_lifecycles.resolve(attempt)
            except ScientificAttemptLifecycleIntegrityError as exc:
                warnings.append(
                    RuntimeConsistencyWarning(
                        code=exc.error_code,
                        layer="scientific_attempt",
                        severity="warning",
                        attention="runtime_attention",
                        task_id=attempt.task_id,
                        task_status=(
                            None if task is None else task.status.value
                        ),
                        runtime_status=exc.reason_code,
                        message=(
                            "Scientific attempt lifecycle records are "
                            "inconsistent."
                        ),
                        recommendation=(
                            "Repair canonical attempt, request, and closure "
                            "identity before any recovery or mutation."
                        ),
                    )
                )
                if task is not None:
                    attention = task_attention[task.task_id]
                    attention["runtime_attention"] = True
                    attention["needs_attention"] = True
                    attention["reasons"].append(exc.error_code)
                    attention["scientific_attempt_ids"].append(
                        attempt.attempt_id
                    )
                continue
            if task is None:
                warnings.append(
                    RuntimeConsistencyWarning(
                        code="scientific_attempt_missing_task",
                        layer="scientific_attempt",
                        severity="warning",
                        attention="needs_attention",
                        task_id=attempt.task_id,
                        runtime_status=lifecycle.effective_status.value,
                        message="Scientific attempt references a missing business task.",
                        recommendation=(
                            "Repair the control-plane identity before selecting or "
                            "closing scientific evidence."
                        ),
                    )
                )
                continue
            try:
                resolved_head = (
                    self.repositories.scientific_selections.resolve_head(
                        attempt.attempt_id
                    )
                )
            except ScientificSelectionIntegrityError as exc:
                warnings.append(
                    RuntimeConsistencyWarning(
                        code=exc.error_code,
                        layer="scientific_attempt",
                        severity="warning",
                        attention="runtime_attention",
                        task_id=task.task_id,
                        task_status=task.status.value,
                        runtime_status=exc.reason_code,
                        message=(
                            "Scientific selection head does not resolve to one "
                            "canonical selection."
                        ),
                        recommendation=(
                            "Inspect canonical selection integrity before any "
                            "further selection mutation."
                        ),
                    )
                )
                attention = task_attention[task.task_id]
                attention["runtime_attention"] = True
                attention["needs_attention"] = True
                attention["reasons"].append(exc.error_code)
                attention["scientific_attempt_ids"].append(attempt.attempt_id)
                continue
            if (
                not lifecycle.is_closed
                and resolved_head is not None
                and self.scientific_workflow_contract_registry is not None
            ):
                from .scientific_attempts import ScientificAttemptService

                evaluation = ScientificAttemptService(
                    self.repositories,
                    workflow_contract_registry=(
                        self.scientific_workflow_contract_registry
                    ),
                ).evaluate_selection(
                    attempt_id=attempt.attempt_id,
                    selection_id=resolved_head.head.selection_id,
                )
                relevant_issues = tuple(
                    issue
                    for issue in evaluation.issues
                    if (
                        issue.blocks_closure
                        if resolved_head.selection.state
                        is ScientificSelectionState.SEALED
                        else issue.blocks_seal
                    )
                )
                for issue_code in tuple(
                    dict.fromkeys(
                        issue.code for issue in relevant_issues
                    )
                )[:20]:
                    warnings.append(
                        RuntimeConsistencyWarning(
                            code=issue_code,
                            layer="scientific_selection",
                            severity="warning",
                            attention="runtime_attention",
                            task_id=task.task_id,
                            task_status=task.status.value,
                            runtime_status=(
                                resolved_head.selection.state.value
                            ),
                            message=(
                                "Scientific selection readiness has a canonical "
                                "blocking issue."
                            ),
                        )
                    )
                    attention = task_attention[task.task_id]
                    attention["runtime_attention"] = True
                    attention["needs_attention"] = True
                    attention["reasons"].append(issue_code)
                    attention["scientific_attempt_ids"].append(
                        attempt.attempt_id
                    )
            if lifecycle.is_closed and not task.status.is_terminal:
                warnings.append(
                    RuntimeConsistencyWarning(
                        code="scientific_attempt_outcome_unconsumed",
                        layer="scientific_attempt",
                        severity="info",
                        attention="outcome_unconsumed",
                        task_id=task.task_id,
                        task_status=task.status.value,
                        runtime_status="closed",
                        message=(
                            "Scientific attempt is closed while the business task "
                            "remains non-terminal; closure is evidence, not task.finish."
                        ),
                        recommendation=(
                            "Let the owning agent consume the closed outcome and "
                            "explicitly finish, continue, or refuse the task."
                        ),
                    )
                )
                attention = task_attention[task.task_id]
                attention["capability_outcome_ready"] = True
                attention["outcome_unconsumed"] = True
                attention["reasons"].append(
                    "scientific_attempt_outcome_unconsumed"
                )
                attention["scientific_attempt_ids"].append(attempt.attempt_id)
            elif (
                not lifecycle.is_closed
                and resolved_head is not None
                and resolved_head.selection.state
                is ScientificSelectionState.SEALED
            ):
                warnings.append(
                    RuntimeConsistencyWarning(
                        code="scientific_selection_sealed_unclosed",
                        layer="scientific_attempt",
                        severity="warning",
                        attention="runtime_attention",
                        task_id=task.task_id,
                        task_status=task.status.value,
                        runtime_status=resolved_head.selection.state.value,
                        message=(
                            "Scientific selection is sealed but the exact attempt "
                            "closure has not been recorded."
                        ),
                        recommendation=(
                            "Retire writers, issue exact quiescence, then explicitly "
                            "close the attempt; do not infer success."
                        ),
                    )
                )
                attention = task_attention[task.task_id]
                attention["runtime_attention"] = True
                attention["needs_attention"] = True
                attention["reasons"].append(
                    "scientific_selection_sealed_unclosed"
                )
                attention["scientific_attempt_ids"].append(attempt.attempt_id)

        for signal in signals:
            if signal.status is not AgentRuntimeSignalStatus.FAILED:
                continue
            task = tasks.get(signal.task_id or "")
            structured_failures = runtime_failures_by_signal_attempt.get(
                (signal.signal_id, f"attempt:{signal.attempt_count}"),
                [],
            )
            budget_failure = next(
                (
                    failure
                    for failure in structured_failures
                    if failure.error_code
                    == AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
                ),
                None,
            )
            if budget_failure is not None:
                agent_turn_failed = True
                code = AGENT_TURN_BUDGET_EXHAUSTED_ERROR_CODE
            elif structured_failures:
                agent_turn_failed = False
                code = "runtime_signal_failed"
            else:
                # Frozen signals predate canonical runtime failure observations.
                # Text matching is read-only compatibility, never a new-write
                # classification source.
                error_text = (
                    f"{signal.error_message or ''}\n"
                    f"{signal.last_error or ''}"
                ).lower()
                agent_turn_failed = (
                    "max_steps_exceeded" in error_text
                    or "step budget" in error_text
                    or "max steps" in error_text
                )
                code = (
                    "agent_turn_failed"
                    if agent_turn_failed
                    else "runtime_signal_failed"
                )
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
                        "The bounded agent turn exhausted its step budget; the "
                        "exact signal is terminal while the business task remains "
                        "unchanged."
                        if budget_failure is not None
                        else (
                            "Runtime signal failed; this does not set the business "
                            "task status to failed."
                        )
                    ),
                    recommendation=(
                        "Inspect the canonical failure and current selection facts, "
                        "then explicitly replan in a new turn; do not replay the "
                        "terminal signal."
                        if budget_failure is not None
                        else (
                            "Inspect the agent turn and decide whether the agent "
                            "should retry, ask for recovery, or explicitly call "
                            "task.finish."
                        )
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
                "failure_observation_ids": list(
                    dict.fromkeys(item["failure_observation_ids"])
                ),
                "scientific_attempt_ids": list(
                    dict.fromkeys(item["scientific_attempt_ids"])
                ),
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
