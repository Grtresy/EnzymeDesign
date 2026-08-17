from __future__ import annotations

import json
from typing import Any

from openzyme_domain import ScientificOperationDispositionKind

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .scientific_attempts import ScientificAttemptError
from .scientific_attempts import ScientificAttemptService


def _actor(context: SessionRuntimeContext) -> str:
    if context.agent_id:
        return context.agent_id
    if context.actor_kind:
        return f"{context.actor_kind}:session"
    return "harness:session"


def _service(context: SessionRuntimeContext) -> ScientificAttemptService:
    return ScientificAttemptService(
        context.repositories,
        workflow_contract_registry=context.scientific_workflow_contract_registry,
    )


def _success(
    invocation: ToolInvocation,
    *,
    payload: dict[str, Any],
    status: str,
    summary: str,
    terminal_action: str | None = None,
    terminates_turn: bool = False,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=status,
        summary=summary,
        details=payload,
        terminal_action=terminal_action,
        terminates_turn=terminates_turn,
    )


def _failure(
    invocation: ToolInvocation,
    error: ScientificAttemptError,
) -> ToolResult:
    inspectable_state = error.error_code in {
        "attempt_already_closed",
        "attempt_closure_already_requested",
        "attempt_not_active",
    }
    details = {
        **error.details,
        "attempt_id": error.details.get(
            "attempt_id",
            invocation.arguments.get("attempt_id"),
        ),
        "selection_id": error.details.get(
            "selection_id",
            invocation.arguments.get("selection_id"),
        ),
        "retryable": error.retryable,
        "precondition_rejected": True,
        "effect_certainty": "no_effect",
        "retry_eligibility": ("same_phase_safe" if error.retryable else "terminal"),
        "recoverability": (
            "agent_can_retry"
            if error.retryable
            else ("agent_can_replan" if inspectable_state else "terminal")
        ),
    }
    payload = {
        "error_code": error.error_code,
        "message": str(error),
        "hint": error.hint,
        "details": details,
        "retryable": error.retryable,
    }
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(payload, sort_keys=True),
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status="scientific_command_rejected",
        summary=str(error),
        error_code=error.error_code,
        hint=error.hint,
        details=details,
    )


def _execute(
    invocation: ToolInvocation,
    callback: Any,
    *,
    status: str,
    summary: str,
    terminal_action: str | None = None,
    terminates_turn: bool = False,
) -> ToolResult:
    try:
        record = callback()
    except ScientificAttemptError as exc:
        return _failure(invocation, exc)
    payload = record if isinstance(record, dict) else record.to_dict()
    return _success(
        invocation,
        payload=payload,
        status=status,
        summary=summary,
        terminal_action=terminal_action,
        terminates_turn=terminates_turn,
    )


def register_scientific_attempt_tools(registry: ToolRegistry) -> None:
    def inspect_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        attempt_id = arguments.get("attempt_id")
        selection_id = arguments.get("selection_id")
        cursor = arguments.get("cursor")
        task_scope = (
            context.restore_focus.task_id or invocation.task_id
            if context.actor_kind == "teammate"
            else None
        )
        service = _service(context)
        try:
            if attempt_id is None and selection_id is None and cursor is None:
                payload = service.project_session(
                    context.snapshot.session.session_id,
                    task_id=task_scope,
                    limit=arguments.get("limit", 50),
                )
                return _success(
                    invocation,
                    payload=payload,
                    status="scientific_attempts_projected",
                    summary=(
                        f"Projected {len(payload['attempts'])} bounded scientific "
                        "attempt summary item(s)."
                    ),
                )
            if attempt_id is None or selection_id is None:
                raise ScientificAttemptError(
                    "scientific_inspection_filter_incomplete",
                    "detailed scientific inspection requires exact attempt and selection ids",
                    details={"mutation_applied": False},
                )
            payload = service.inspect_selection(
                session_id=context.snapshot.session.session_id,
                task_id=task_scope,
                attempt_id=str(attempt_id),
                selection_id=str(selection_id),
                limit=arguments.get("limit", 20),
                cursor=None if cursor is None else str(cursor),
            )
            return _success(
                invocation,
                payload=payload,
                status="scientific_selection_projected",
                summary=(
                    f"Projected {payload['page']['returned_count']} exact scientific "
                    "selection occurrence(s)."
                ),
            )
        except ScientificAttemptError as exc:
            return _failure(invocation, exc)

    def create_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        task_id = str(
            context.restore_focus.task_id or invocation.task_id or ""
        )
        return _execute(
            invocation,
            lambda: _service(context).request_authorized_attempt_admission(
                envelope_id=str(arguments["envelope_id"]),
                session_id=context.snapshot.session.session_id,
                task_id=task_id,
                actor_ref=_actor(context),
                idempotency_key=str(arguments["idempotency_key"]),
            ),
            status="scientific_attempt_admission_requested",
            summary=(
                "Recorded a fresh-attempt admission request; the Host will "
                "finalize it after this bounded writer turn retires."
            ),
            terminal_action="attempt.create",
            terminates_turn=True,
        )

    def begin_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        expected = arguments.get("expected_head_state_version")
        return _execute(
            invocation,
            lambda: _service(context).begin_selection(
                attempt_id=str(arguments["attempt_id"]),
                actor_ref=_actor(context),
                idempotency_key=str(arguments["idempotency_key"]),
                expected_head_state_version=(
                    None if expected is None else int(expected)
                ),
                parent_selection_id=(
                    None
                    if arguments.get("parent_selection_id") is None
                    else str(arguments["parent_selection_id"])
                ),
            ),
            status="scientific_selection_started",
            summary="Started an immutable scientific selection revision.",
        )

    def disposition_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        return _execute(
            invocation,
            lambda: _service(context).disposition_operation(
                selection_id=str(arguments["selection_id"]),
                operation_id=str(arguments["operation_id"]),
                kind=ScientificOperationDispositionKind(str(arguments["kind"])),
                workflow_role=(
                    None
                    if arguments.get("workflow_role") is None
                    else str(arguments["workflow_role"])
                ),
                reason_code=str(arguments["reason_code"]),
                replacement_operation_id=(
                    None
                    if arguments.get("replacement_operation_id") is None
                    else str(arguments["replacement_operation_id"])
                ),
                actor_ref=_actor(context),
                idempotency_key=str(arguments["idempotency_key"]),
            ),
            status="scientific_operation_dispositioned",
            summary="Recorded the agent-selected disposition for one occurrence.",
        )

    def adopt_operation_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        return _execute(
            invocation,
            lambda: _service(context).adopt_operation(
                selection_id=str(arguments["selection_id"]),
                operation_id=str(arguments["operation_id"]),
                workflow_role=str(arguments["workflow_role"]),
                reason_code=str(arguments["reason_code"]),
                actor_ref=_actor(context),
                idempotency_key=str(arguments["idempotency_key"]),
            ),
            status="scientific_operation_adopted",
            summary=(
                "Atomically recorded one adopted disposition and matching "
                "terminal-known effect adoption."
            ),
        )

    def seal_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        return _execute(
            invocation,
            lambda: _service(context).seal_selection(
                selection_id=str(arguments["selection_id"]),
                actor_ref=_actor(context),
                idempotency_key=str(arguments["idempotency_key"]),
                expected_universe_digest=str(arguments["expected_universe_digest"]),
            ),
            status="scientific_selection_sealed",
            summary="Sealed the complete selected scientific chain.",
        )

    def close_handler(
        context: SessionRuntimeContext,
        invocation: ToolInvocation,
    ) -> ToolResult:
        arguments = invocation.arguments
        return _execute(
            invocation,
            lambda: _service(context).request_attempt_closure(
                attempt_id=str(arguments["attempt_id"]),
                selection_id=str(arguments["selection_id"]),
                actor_ref=_actor(context),
                idempotency_key=str(arguments["idempotency_key"]),
            ),
            status="scientific_attempt_closure_requested",
            summary=(
                "Recorded closure intent; the Host finalizer must establish exact "
                "post-turn quiescence without changing business task status."
            ),
            terminal_action="scientific.attempt.close",
            terminates_turn=True,
        )

    registry.register("scientific.attempt.inspect", inspect_handler)
    registry.register("attempt.create", create_handler)
    registry.register("scientific.selection.begin", begin_handler)
    registry.register("scientific.operation.disposition", disposition_handler)
    registry.register(
        "scientific.operation.adopt",
        adopt_operation_handler,
    )
    registry.register("scientific.selection.seal", seal_handler)
    registry.register("scientific.attempt.close", close_handler)


__all__ = ["register_scientific_attempt_tools"]
