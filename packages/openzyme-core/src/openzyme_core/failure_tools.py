from __future__ import annotations

import hashlib
import json

from openzyme_domain import FailureHypothesis
from openzyme_domain import FailureHypothesisConfidence
from openzyme_domain import FailureRecoveryDisposition
from openzyme_domain import FailureRecoveryDispositionKind
from openzyme_domain import TaskStatus
from openzyme_domain import utc_now_iso
from openzyme_runtime import sanitize_public_diagnostic_text

from .failure_repositories import project_failure_observation
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult


def _digest(value: str) -> str:
    return "sha256:" + hashlib.sha256(value.encode("utf-8")).hexdigest()


def _hypothesis_id(
    *,
    session_id: str,
    agent_id: str,
    idempotency_key: str,
) -> str:
    digest = _digest(
        json.dumps(
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return "failure_hypothesis_" + digest.removeprefix("sha256:")[:20]


def _disposition_id(
    *,
    session_id: str,
    agent_id: str,
    idempotency_key: str,
) -> str:
    digest = _digest(
        json.dumps(
            {
                "session_id": session_id,
                "agent_id": agent_id,
                "idempotency_key": idempotency_key,
            },
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
        )
    )
    return "failure_recovery_" + digest.removeprefix("sha256:")[:20]


def _agent_id(context: SessionRuntimeContext, *, record_kind: str) -> str:
    agent_id = str(context.agent_id or "")
    if not agent_id.startswith("agent:"):
        raise ValueError(
            f"{record_kind} require the canonical identity of a live agent"
        )
    if (
        context.repositories.agents.get(
            context.snapshot.session.session_id,
            agent_id,
        )
        is None
    ):
        raise ValueError(
            f"{record_kind} require a canonical agent in the current session"
        )
    return agent_id


def _recovery_target_is_current(
    context: SessionRuntimeContext,
    *,
    failure_id: str,
) -> bool:
    obligation = context.turn_recovery_obligation
    if obligation is None:
        return False
    if (
        obligation.failure_id == failure_id
        and obligation.tool_name == "task.delegate"
        and obligation.error_code == "task_blocked"
        and obligation.recoverability == "agent_can_replan"
        and obligation.effect_certainty == "terminal_known"
    ):
        failure = context.repositories.failure_observations.get(failure_id)
        return bool(
            failure is not None
            and failure.source_ref == obligation.call_id
        )
    if not (
        obligation.tool_name == "failure.recovery.record"
        and obligation.error_code == "invalid_tool_arguments"
        and obligation.recoverability == "agent_can_retry"
        and obligation.effect_certainty == "no_effect"
    ):
        return False
    failed_retry = context.repositories.failure_observations.get(
        obligation.failure_id
    )
    return bool(
        failed_retry is not None
        and failed_retry.session_id == context.snapshot.session.session_id
        and failed_retry.agent_id == context.agent_id
        and failed_retry.source_kind == "tool_invocation"
        and failed_retry.source_ref == obligation.call_id
        and failed_retry.error_code == obligation.error_code
        and failed_retry.recoverability.value == "agent_can_retry"
        and failed_retry.effect_certainty.value == "no_effect"
        and failed_retry.retry_eligibility.value == "same_phase_safe"
        and failed_retry.facts.get("tool_name") == "failure.recovery.record"
    )


def _open_dependency_ids(
    context: SessionRuntimeContext,
    *,
    task_id: str,
) -> tuple[str, ...]:
    task = context.repositories.tasks.get(task_id)
    if task is None:
        raise ValueError("blocked delegation target no longer exists")
    if task.session_id != context.snapshot.session.session_id:
        raise ValueError("blocked delegation target belongs to another session")
    if task.status is not TaskStatus.TODO or task.assigned_ref is not None:
        raise ValueError(
            "blocked delegation target is no longer an unassigned todo task"
        )
    open_ids: list[str] = []
    for blocker_id in task.blocked_by:
        blocker = context.repositories.tasks.get(blocker_id)
        if blocker is None or blocker.session_id != task.session_id:
            raise ValueError(
                "blocked delegation dependency is missing or cross-session"
            )
        if blocker.status is TaskStatus.COMPLETED:
            continue
        if blocker.status not in {TaskStatus.TODO, TaskStatus.IN_PROGRESS}:
            raise ValueError(
                "blocked delegation dependency reached a terminal non-completed "
                "state; defer-until-complete is no longer appropriate"
            )
        open_ids.append(blocker_id)
    return tuple(sorted(open_ids))


def _success(
    invocation: ToolInvocation,
    *,
    payload: dict[str, object],
    status: str,
    summary: str,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        content=json.dumps(payload, ensure_ascii=False, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=status,
        summary=summary,
        details=payload,
    )


def register_failure_tools(registry: ToolRegistry) -> None:
    def get_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        failure_id = str(invocation.arguments["failure_id"])
        failure = context.repositories.failure_observations.get(failure_id)
        if failure is None or failure.session_id != context.snapshot.session.session_id:
            raise ValueError(
                "failure_id does not resolve to a failure in the current session"
            )
        payload = project_failure_observation(context.repositories, failure)
        return _success(
            invocation,
            payload=payload,
            status="failure_observation_projected",
            summary=f"Projected failure observation {failure_id}.",
        )

    def hypothesis_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        session_id = context.snapshot.session.session_id
        agent_id = _agent_id(
            context,
            record_kind="failure hypotheses",
        )
        failure_id = str(arguments["failure_id"])
        failure = context.repositories.failure_observations.get(failure_id)
        if failure is None or failure.session_id != session_id:
            raise ValueError(
                "failure_id does not resolve to a failure in the current session"
            )
        hypothesis = sanitize_public_diagnostic_text(
            str(arguments["hypothesis"])
        ).strip()
        if not hypothesis:
            raise ValueError("hypothesis must be non-empty")
        confidence = FailureHypothesisConfidence(str(arguments["confidence"]))
        evidence_refs = tuple(
            sanitize_public_diagnostic_text(str(value)).strip()
            for value in arguments.get("evidence_refs", ())
        )
        idempotency_key = str(arguments["idempotency_key"]).strip()
        if not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        record = FailureHypothesis(
            hypothesis_id=_hypothesis_id(
                session_id=session_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
            ),
            failure_id=failure_id,
            session_id=session_id,
            agent_id=agent_id,
            hypothesis=hypothesis,
            confidence=confidence,
            evidence_refs=evidence_refs,
            idempotency_digest=_digest(idempotency_key),
            created_at=utc_now_iso(),
        )
        saved = context.repositories.failure_hypotheses.add(record)
        context.emit(
            "failure.hypothesis.recorded",
            {
                "hypothesis_id": saved.hypothesis_id,
                "failure_id": saved.failure_id,
                "agent_id": saved.agent_id,
                "confidence": saved.confidence.value,
                "evidence_refs": list(saved.evidence_refs),
            },
        )
        return _success(
            invocation,
            payload=saved.to_dict(),
            status="failure_hypothesis_recorded",
            summary=(
                f"Recorded agent-attributed hypothesis {saved.hypothesis_id} "
                f"for failure {saved.failure_id}."
            ),
        )

    def recovery_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        session_id = context.snapshot.session.session_id
        agent_id = _agent_id(
            context,
            record_kind="failure recovery dispositions",
        )
        failure_id = str(arguments["failure_id"]).strip()
        if not _recovery_target_is_current(
            context,
            failure_id=failure_id,
        ):
            raise ValueError(
                "failure_id is not the exact current blocked-delegation "
                "recovery obligation or a corrected retry of this tool"
            )
        failure = context.repositories.failure_observations.get(failure_id)
        if (
            failure is None
            or failure.session_id != session_id
            or failure.agent_id != agent_id
        ):
            raise ValueError(
                "failure_id does not resolve to this agent's failure in the "
                "current session"
            )
        if not (
            failure.source_kind == "tool_invocation"
            and failure.error_code == "task_blocked"
            and failure.recoverability.value == "agent_can_replan"
            and failure.effect_certainty.value == "terminal_known"
            and failure.retry_eligibility.value == "terminal"
            and failure.facts.get("tool_name") == "task.delegate"
            and failure.task_id
        ):
            raise ValueError(
                "failure recovery disposition supports only a terminal-known "
                "task.delegate task_blocked observation"
            )
        disposition = FailureRecoveryDispositionKind(
            str(arguments["disposition"])
        )
        condition_values = arguments["condition_task_ids"]
        if not isinstance(condition_values, list | tuple):
            raise ValueError("condition_task_ids must be an array")
        if any(not isinstance(value, str) for value in condition_values):
            raise ValueError("condition_task_ids must contain only strings")
        condition_task_ids = tuple(
            sorted(
                sanitize_public_diagnostic_text(value).strip()
                for value in condition_values
            )
        )
        if (
            not condition_task_ids
            or any(not value for value in condition_task_ids)
            or len(set(condition_task_ids)) != len(condition_task_ids)
        ):
            raise ValueError(
                "condition_task_ids must contain unique non-empty task ids"
            )
        observed_values = failure.facts.get("blocked_by_open_task_ids")
        if not isinstance(observed_values, list | tuple):
            raise ValueError(
                "blocked delegation failure lacks a closed blocker set"
            )
        if any(not isinstance(value, str) for value in observed_values):
            raise ValueError(
                "blocked delegation failure contains a malformed blocker set"
            )
        observed_task_ids = tuple(
            sorted(value.strip() for value in observed_values)
        )
        current_task_ids = _open_dependency_ids(
            context,
            task_id=failure.task_id,
        )
        if (
            condition_task_ids != observed_task_ids
            or condition_task_ids != current_task_ids
        ):
            raise ValueError(
                "condition_task_ids do not exactly match both the observed and "
                "current open task dependencies"
            )
        rationale = sanitize_public_diagnostic_text(
            str(arguments["rationale"])
        ).strip()
        if not rationale:
            raise ValueError("rationale must be non-empty")
        if len(rationale) > 2_000:
            raise ValueError("rationale exceeds 2000 characters")
        idempotency_key = str(arguments["idempotency_key"]).strip()
        if not idempotency_key:
            raise ValueError("idempotency_key must be non-empty")
        record = FailureRecoveryDisposition(
            disposition_id=_disposition_id(
                session_id=session_id,
                agent_id=agent_id,
                idempotency_key=idempotency_key,
            ),
            failure_id=failure_id,
            session_id=session_id,
            agent_id=agent_id,
            disposition=disposition,
            condition_task_ids=condition_task_ids,
            rationale=rationale,
            idempotency_digest=_digest(idempotency_key),
            created_at=utc_now_iso(),
        )
        saved = context.repositories.failure_recovery_dispositions.add(record)
        context.emit(
            "failure.recovery.disposition_recorded",
            {
                "disposition_id": saved.disposition_id,
                "failure_id": saved.failure_id,
                "agent_id": saved.agent_id,
                "disposition": saved.disposition.value,
                "condition_task_ids": list(saved.condition_task_ids),
                "retry_authorized": False,
                "task_status_changed": False,
                "scientific_state_changed": False,
            },
        )
        return _success(
            invocation,
            payload=saved.to_dict(),
            status="failure_recovery_disposition_recorded",
            summary=(
                f"Recorded no-authority recovery disposition "
                f"{saved.disposition_id} for failure {saved.failure_id}."
            ),
        )

    registry.register("failure.get", get_handler)
    registry.register("failure.hypothesis.record", hypothesis_handler)
    registry.register("failure.recovery.record", recovery_handler)


__all__ = ["register_failure_tools"]
