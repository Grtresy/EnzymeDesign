from __future__ import annotations

from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Callable
from typing import Protocol

from openzyme_core import RuntimeCommandExecutionResult
from openzyme_domain import RuntimeCommandRecord
from openzyme_domain import RuntimeCommandStatus
from openzyme_runtime import llm_debug_context

from .v3_service import V3RuntimeDrainResult


class RuntimeDrainService(Protocol):
    def drain_runtime(
        self,
        *,
        session_id: str,
        max_signals: int,
        max_steps_per_agent: int,
        auto_enqueue_ready_tasks: bool,
        worker_id: str,
    ) -> V3RuntimeDrainResult: ...


@dataclass(slots=True)
class HostRuntimeCommandExecutor:
    """Execute one admitted drain command outside its claim transaction."""

    service_scope: Callable[[], AbstractContextManager[RuntimeDrainService]]
    worker_id: str

    def __call__(
        self,
        command: RuntimeCommandRecord,
    ) -> RuntimeCommandExecutionResult:
        with llm_debug_context(
            request_path="command:v3-runtime-drain",
            session_id=command.session_id,
            actor="runtime-command-worker",
        ):
            with self.service_scope() as service:
                result = service.drain_runtime(
                    session_id=command.session_id,
                    max_signals=command.max_signals,
                    max_steps_per_agent=command.max_steps_per_agent,
                    auto_enqueue_ready_tasks=command.auto_enqueue_ready_tasks,
                    worker_id=f"{self.worker_id}:scheduler",
                )
        if not isinstance(result, V3RuntimeDrainResult):
            raise TypeError("runtime drain service returned an invalid result")
        core_receipt = result.core_receipt
        projection_outcome = result.projection_outcome
        bounded_summary = result.bounded_outcome_summary
        if projection_outcome.status == "failed":
            return RuntimeCommandExecutionResult(
                status=RuntimeCommandStatus.FAILED,
                bounded_outcome_summary=bounded_summary,
                error_code=projection_outcome.error_code,
                safe_error_summary=projection_outcome.safe_summary,
                safe_retry_hint=result.safe_retry_hint,
            )
        scheduler_status = core_receipt.scheduler_status
        if scheduler_status == RuntimeCommandStatus.LOCKED.value:
            return RuntimeCommandExecutionResult(
                status=RuntimeCommandStatus.LOCKED,
                bounded_outcome_summary=bounded_summary,
                error_code="session_runtime_locked",
                safe_error_summary=(
                    "The session runtime lease is held by another valid owner."
                ),
                safe_retry_hint=(
                    result.safe_retry_hint
                    or "Submit a new drain command after the active session "
                    "runtime lease has been released."
                ),
            )
        if scheduler_status == "failed":
            return RuntimeCommandExecutionResult(
                status=RuntimeCommandStatus.FAILED,
                bounded_outcome_summary=bounded_summary,
                error_code="runtime_scheduler_batch_failed",
                safe_error_summary="The bounded runtime scheduler batch failed.",
                safe_retry_hint=(
                    "Inspect current session facts before submitting a new command."
                ),
            )
        return RuntimeCommandExecutionResult(
            status=RuntimeCommandStatus.COMPLETED,
            bounded_outcome_summary=bounded_summary,
        )


__all__ = ["HostRuntimeCommandExecutor", "RuntimeDrainService"]
