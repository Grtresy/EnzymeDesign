from __future__ import annotations

from typing import Any

from openzyme_domain import ControlledOperation
from openzyme_domain import ControlledOperationExecution
from openzyme_domain import ControlledOperationExecutionLifecycle
from openzyme_domain import ControlledOperationOwnerMode
from openzyme_domain import ControlledOperationResultRef
from openzyme_domain import SessionArtifactRecord
from openzyme_domain import TaskEvidenceKind
from openzyme_domain import TaskEvidenceRef
from openzyme_runtime import sanitize_public_diagnostic_payload
from openzyme_runtime import sanitize_public_diagnostic_text

from .repositories import CoreRepositories


_PUBLIC_ARTIFACT_REF_LIMIT = 128


def _recovery_action(execution: ControlledOperationExecution) -> str:
    lifecycle = execution.lifecycle_state
    if lifecycle is ControlledOperationExecutionLifecycle.AWAITING_APPROVAL:
        return "await_exact_approval"
    if lifecycle in {
        ControlledOperationExecutionLifecycle.READY,
        ControlledOperationExecutionLifecycle.CLAIMED,
    }:
        return "progress_same_execution"
    if lifecycle in {
        ControlledOperationExecutionLifecycle.DISPATCHING,
        ControlledOperationExecutionLifecycle.RECONCILE_REQUIRED,
    }:
        return "reconcile_exact_handle"
    if lifecycle is ControlledOperationExecutionLifecycle.WAITING_EXTERNAL:
        return "poll_exact_handle"
    if lifecycle is ControlledOperationExecutionLifecycle.RESULT_STAGING:
        return "materialize_existing_outcome"
    if lifecycle is ControlledOperationExecutionLifecycle.RESULT_READY:
        return "deliver_existing_result"
    return "none"


def _bounded_artifact_ids(envelope: dict[str, Any]) -> list[str]:
    values = envelope.get("output_artifact_ids")
    if not isinstance(values, list | tuple):
        values = envelope.get("registered_artifact_ids")
    if not isinstance(values, list | tuple):
        return []
    return [
        str(value)
        for value in values[:_PUBLIC_ARTIFACT_REF_LIMIT]
        if isinstance(value, str) and value
    ]


def project_controlled_operation_execution(
    repositories: CoreRepositories,
    execution: ControlledOperationExecution,
) -> dict[str, Any]:
    """Return bounded execution facts without private ownership or backend locators."""

    events = repositories.controlled_operation_execution_events.list_by_execution(
        execution.execution_id
    )
    latest_event = events[-1] if events else None
    result_handle = repositories.controlled_operation_results.get_by_execution_id(
        execution.execution_id
    )
    result = None
    if result_handle is not None:
        session = repositories.sessions.get(result_handle.session_id)
        if session is None:
            raise RuntimeError("controlled-operation result session is missing")
        digest_hex = result_handle.result_digest.removeprefix("sha256:")
        canonical_digest = (
            result_handle.result_digest.startswith("sha256:")
            and len(digest_hex) == 64
            and all(character in "0123456789abcdef" for character in digest_hex)
        )
        task_evidence_ref = None
        if execution.task_id is not None and canonical_digest:
            controlled_result_ref = ControlledOperationResultRef(
                result_handle_id=result_handle.result_handle_id,
                project_id=session.project_id,
                session_id=result_handle.session_id,
                task_id=execution.task_id,
                execution_id=result_handle.execution_id,
                operation_id=result_handle.operation_id,
                dispatch_generation=result_handle.dispatch_generation,
                terminal_outcome=result_handle.terminal_outcome.value,
                result_digest=result_handle.result_digest,
            )
            task_evidence_ref = TaskEvidenceRef(
                kind=TaskEvidenceKind.CONTROLLED_OPERATION_RESULT,
                project_id=session.project_id,
                session_id=result_handle.session_id,
                task_id=execution.task_id,
                owner_id=result_handle.result_handle_id,
                owner_digest=result_handle.result_digest,
                controlled_operation_result_ref=controlled_result_ref,
            ).to_dict()
        result = {
            "result_handle_id": result_handle.result_handle_id,
            "terminal_outcome": result_handle.terminal_outcome.value,
            "result_digest": result_handle.result_digest,
            "artifact_set_digest": result_handle.artifact_set_digest,
            "origin": result_handle.origin,
            "artifact_ids": _bounded_artifact_ids(
                result_handle.bounded_result_envelope
            ),
            "created_at": result_handle.created_at,
            "task_evidence_ref": task_evidence_ref,
        }
    payload: dict[str, Any] = {
        "schema_version": "controlled_operation_execution.public@1",
        "execution_id": execution.execution_id,
        "operation_id": execution.operation_id,
        "session_id": execution.session_id,
        "task_id": execution.task_id,
        "lane_id": execution.lane_id,
        "approval_id": execution.approval_id,
        "owner_mode": execution.owner_mode.value,
        "lifecycle_state": execution.lifecycle_state.value,
        "safe_phase": None if latest_event is None else latest_event.phase.value,
        "effect_certainty": execution.effect_certainty.value,
        "retry_eligibility": execution.retry_eligibility.value,
        "terminal_outcome": (
            None
            if execution.terminal_outcome is None
            else execution.terminal_outcome.value
        ),
        "dispatch_generation": execution.dispatch_generation,
        "recovery_action": _recovery_action(execution),
        "error_code": execution.error_code,
        "safe_error_summary": (
            None
            if execution.safe_error_summary is None
            else sanitize_public_diagnostic_text(execution.safe_error_summary)
        ),
        "result": result,
        "created_at": execution.created_at,
        "updated_at": execution.updated_at,
        "terminal_at": execution.terminal_at,
    }
    sanitized = sanitize_public_diagnostic_payload(payload)
    if not isinstance(sanitized, dict):  # pragma: no cover - structural invariant
        raise TypeError("controlled operation execution projection must be an object")
    return sanitized


def project_controlled_operation_summary(
    repositories: CoreRepositories,
    operation: ControlledOperation,
) -> dict[str, Any]:
    execution = None
    if operation.owner_mode is ControlledOperationOwnerMode.DURABLE_ASYNC_V1:
        canonical = repositories.controlled_operation_executions.get_by_operation_id(
            operation.operation_id
        )
        execution = (
            None
            if canonical is None
            else project_controlled_operation_execution(repositories, canonical)
        )
    payload: dict[str, Any] = {
        "operation_id": operation.operation_id,
        "logical_operation_key": operation.logical_operation_key,
        "operation_digest": operation.operation_digest,
        "status": operation.status.value,
        "owner_mode": operation.owner_mode.value,
        "approval_id": operation.approval_id,
        "approval_state": operation.approval_state,
        "sandbox_workspace_id": operation.sandbox_workspace_id,
        "sandbox_run_id": operation.sandbox_run_id,
        "backend_category": operation.backend_category,
        "route_policy_id": operation.route_policy_id,
        "selected_backend": operation.selected_backend,
        "input_artifact_ids": list(operation.input_artifact_ids),
        "input_artifact_digests": list(operation.input_artifact_digests),
        "resource_estimate": operation.resource_estimate or {},
        "expected_outputs_summary": operation.expected_outputs_summary or {},
        "source_snapshot_artifact_id": operation.source_snapshot_artifact_id,
        "source_snapshot_digest": operation.source_snapshot_digest,
        "error_code": operation.error_code,
        "execution": execution,
        "created_at": operation.created_at,
        "updated_at": operation.updated_at,
    }
    sanitized = sanitize_public_diagnostic_payload(payload)
    if not isinstance(sanitized, dict):  # pragma: no cover - structural invariant
        raise TypeError("controlled operation projection must be an object")
    return sanitized


def is_controlled_operation_artifact_public(
    repositories: CoreRepositories,
    artifact: SessionArtifactRecord,
) -> bool:
    """Hide durable staging rows until their exact result set is promoted."""

    operation_id = str(
        dict(artifact.metadata or {}).get("controlled_operation_id") or ""
    )
    if not operation_id:
        return True
    operation = repositories.controlled_operations.get(operation_id)
    if (
        operation is None
        or operation.owner_mode is not ControlledOperationOwnerMode.DURABLE_ASYNC_V1
    ):
        return True
    execution = repositories.controlled_operation_executions.get_by_operation_id(
        operation_id
    )
    if execution is None:
        return False
    return repositories.controlled_operation_result_artifacts.is_promoted(
        artifact.artifact_id
    )


__all__ = [
    "project_controlled_operation_execution",
    "project_controlled_operation_summary",
    "is_controlled_operation_artifact_public",
]
