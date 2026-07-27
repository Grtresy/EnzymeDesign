from __future__ import annotations

import hashlib
from typing import Any

from openzyme_domain import AgentRuntimeSignal
from openzyme_domain import AgentRuntimeSignalReason
from openzyme_domain import AgentRuntimeSignalStatus
from openzyme_domain import ExternalEffectCertainty
from openzyme_domain import FailureRecoverability
from openzyme_domain import FailureRecoveryDispositionKind
from openzyme_domain import RetryEligibility
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso


def _recovery_signal_id(disposition_id: str) -> str:
    digest = hashlib.sha256(disposition_id.encode("utf-8")).hexdigest()[:24]
    return f"sig_failure_recovery_{digest}"


def _require_exact_recovery_signal(
    signal: AgentRuntimeSignal,
    *,
    disposition_id: str,
    session_id: str,
    agent_id: str,
    task_id: str | None,
    lane_id: str | None,
) -> None:
    expected = {
        "signal_id": _recovery_signal_id(disposition_id),
        "session_id": session_id,
        "agent_id": agent_id,
        "task_id": task_id,
        "lane_id": lane_id,
        "correlation_id": f"recovery:{disposition_id}",
        "reason": AgentRuntimeSignalReason.RECOVERY_REQUIRED,
        "source_ref": disposition_id,
    }
    actual = {
        "signal_id": signal.signal_id,
        "session_id": signal.session_id,
        "agent_id": signal.agent_id,
        "task_id": signal.task_id,
        "lane_id": signal.lane_id,
        "correlation_id": signal.correlation_id,
        "reason": signal.reason,
        "source_ref": signal.source_ref,
    }
    if actual != expected:
        raise RuntimeError(
            "failure recovery disposition has a conflicting source-bound "
            "runtime signal identity"
        )


def resolve_exact_failure_recovery_disposition_failure(
    repositories: Any,
    disposition: Any,
    *,
    session_id: str,
) -> Any | None:
    failure = repositories.failure_observations.get(
        disposition.failure_id
    )
    observed_condition_ids = (
        None
        if failure is None
        else failure.facts.get("blocked_by_open_task_ids")
    )
    if (
        failure is None
        or disposition.session_id != session_id
        or disposition.disposition
        is not FailureRecoveryDispositionKind.DEFER_UNTIL_TASK_DEPENDENCIES_COMPLETE
        or failure.session_id != session_id
        or failure.agent_id != disposition.agent_id
        or failure.source_kind != "tool_invocation"
        or failure.error_code != "task_blocked"
        or failure.recoverability
        is not FailureRecoverability.AGENT_CAN_REPLAN
        or failure.effect_certainty
        is not ExternalEffectCertainty.TERMINAL_KNOWN
        or failure.retry_eligibility is not RetryEligibility.TERMINAL
        or failure.facts.get("tool_name") != "task.delegate"
        or not failure.task_id
        or not disposition.condition_task_ids
        or not isinstance(observed_condition_ids, list | tuple)
        or any(
            not isinstance(task_id, str)
            for task_id in observed_condition_ids
        )
        or tuple(
            sorted(
                task_id.strip()
                for task_id in observed_condition_ids
            )
        )
        != tuple(sorted(disposition.condition_task_ids))
    ):
        return None
    target = repositories.tasks.get(failure.task_id)
    if target is None or target.session_id != session_id:
        return None
    return failure


def reconcile_satisfied_failure_recovery_dispositions(
    context: Any,
    *,
    session_id: str | None = None,
    notify: bool = True,
) -> tuple[AgentRuntimeSignal, ...]:
    """Materialize one exact wakeup for each satisfied durable disposition."""

    resolved_session_id = (
        session_id or context.snapshot.session.session_id
    )
    if context.snapshot.session.session_id != resolved_session_id:
        raise ValueError(
            "failure recovery reconciliation crossed its session snapshot"
        )
    created: list[AgentRuntimeSignal] = []
    for disposition in (
        context.repositories.failure_recovery_dispositions.list_by_session(
            resolved_session_id
        )
    ):
        if (
            disposition.disposition
            is not FailureRecoveryDispositionKind.DEFER_UNTIL_TASK_DEPENDENCIES_COMPLETE
        ):
            continue
        failure = resolve_exact_failure_recovery_disposition_failure(
            context.repositories,
            disposition,
            session_id=resolved_session_id,
        )
        if failure is None:
            continue
        existing = context.repositories.runtime_signals.find_source_signal(
            session_id=resolved_session_id,
            agent_id=disposition.agent_id,
            reason=AgentRuntimeSignalReason.RECOVERY_REQUIRED,
            source_ref=disposition.disposition_id,
        )
        if existing is not None:
            _require_exact_recovery_signal(
                existing,
                disposition_id=disposition.disposition_id,
                session_id=resolved_session_id,
                agent_id=disposition.agent_id,
                task_id=failure.task_id,
                lane_id=failure.lane_id,
            )
            continue
        condition_tasks = tuple(
            context.repositories.tasks.get(task_id)
            for task_id in disposition.condition_task_ids
        )
        if (
            not condition_tasks
            or any(task is None for task in condition_tasks)
            or any(
                task.session_id != resolved_session_id
                for task in condition_tasks
                if task is not None
            )
            or any(
                task.status is not TaskStatus.COMPLETED
                for task in condition_tasks
                if task is not None
            )
        ):
            continue
        signal = AgentRuntimeSignal(
            signal_id=_recovery_signal_id(disposition.disposition_id),
            session_id=resolved_session_id,
            agent_id=disposition.agent_id,
            task_id=failure.task_id,
            lane_id=failure.lane_id,
            correlation_id=f"recovery:{disposition.disposition_id}",
            reason=AgentRuntimeSignalReason.RECOVERY_REQUIRED,
            source_ref=disposition.disposition_id,
            status=AgentRuntimeSignalStatus.PENDING,
            created_at=utc_now_iso(),
        )
        with context.repositories.atomic(
            prefix="failure_recovery_wakeup"
        ):
            raced = (
                context.repositories.runtime_signals.find_source_signal(
                    session_id=resolved_session_id,
                    agent_id=disposition.agent_id,
                    reason=AgentRuntimeSignalReason.RECOVERY_REQUIRED,
                    source_ref=disposition.disposition_id,
                )
            )
            if raced is not None:
                _require_exact_recovery_signal(
                    raced,
                    disposition_id=disposition.disposition_id,
                    session_id=resolved_session_id,
                    agent_id=disposition.agent_id,
                    task_id=failure.task_id,
                    lane_id=failure.lane_id,
                )
                continue
            saved = context.repositories.runtime_signals.insert_if_absent(
                signal
            )
            _require_exact_recovery_signal(
                saved,
                disposition_id=disposition.disposition_id,
                session_id=resolved_session_id,
                agent_id=disposition.agent_id,
                task_id=failure.task_id,
                lane_id=failure.lane_id,
            )
            context.emit(
                "failure.recovery.wakeup_queued",
                {
                    "disposition_id": disposition.disposition_id,
                    "failure_id": disposition.failure_id,
                    "signal_id": saved.signal_id,
                    "agent_id": saved.agent_id,
                    "task_id": saved.task_id,
                    "lane_id": saved.lane_id,
                    "condition_task_ids": list(
                        disposition.condition_task_ids
                    ),
                    "reason": saved.reason.value,
                    "source_ref": saved.source_ref,
                },
            )
            created.append(saved)
    if created and notify:
        notifier = context.signal_notifier
        if notifier is not None and hasattr(notifier, "notify"):
            notifier.notify(resolved_session_id)
    return tuple(created)


__all__ = [
    "reconcile_satisfied_failure_recovery_dispositions",
    "resolve_exact_failure_recovery_disposition_failure",
]
