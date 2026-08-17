from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any
from uuid import uuid4

from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import ScientificAttemptLifecyclePhase
from openzyme_domain import TaskEvidenceRef
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .agent_identity import AgentIdentityError
from .agent_identity import is_teammate_role_alias
from .agent_identity import resolve_agent_reference
from .repositories import CoreRepositories
from .repositories import TaskWriteIntent
from .revision_path_handoffs import RevisionPathHandoffError
from .revision_path_handoffs import TaskEvidenceReferenceService
from .scientific_attempt_lifecycle import (
    ScientificAttemptLifecycleIntegrityError,
)
from .scientific_attempt_lifecycle import ScientificAttemptLifecycleResolver
from .task_evidence import task_finish_evidence_contract_details

_UNSET = object()
_PRIORITY_ORDER = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}
_PSEUDO_EMPTY_ASSIGNED_REFS = {"", "none", "null"}
_TASK_FINISH_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.BLOCKED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}
_TASK_TOOL_MUTATION_STATUSES = {
    TaskStatus.TODO,
    TaskStatus.IN_PROGRESS,
}


class TaskExitStatusRequiresFinish(ValueError):
    """Raised when a generic task mutation attempts a business exit."""

    def __init__(self, *, operation: str, status: TaskStatus) -> None:
        self.operation = operation
        self.status = status
        super().__init__(
            f"{operation} cannot set business exit status {status.value!r}; "
            "use task.finish"
        )


def _normalize_assigned_ref(
    repositories: CoreRepositories,
    *,
    session_id: str,
    value: Any,
) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.lower() in _PSEUDO_EMPTY_ASSIGNED_REFS:
            return None
        if is_teammate_role_alias(normalized):
            raise AgentIdentityError(
                f"{normalized!r} is a role alias, not a canonical assigned_ref"
            )
        if normalized.startswith("@"):
            resolution = resolve_agent_reference(
                repositories,
                session_id=session_id,
                reference=normalized,
            )
            if resolution.agent is None:
                raise AgentIdentityError(
                    f"assigned_ref {normalized!r} did not resolve to an agent"
                )
            return resolution.agent.agent_id
        resolution = resolve_agent_reference(
            repositories,
            session_id=session_id,
            reference=normalized,
        )
        if resolution.agent is not None:
            return resolution.agent.agent_id
        return normalized
    return str(value)


def _finish_error_result(
    invocation: ToolInvocation,
    *,
    status: str,
    summary: str,
    hint: str | None = None,
    details: dict[str, Any] | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=summary,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=status,
        summary=summary,
        error_code=status,
        hint=hint,
        details=details,
    )


def _scientific_attempt_completion_guard(
    repositories: CoreRepositories,
    *,
    invocation: ToolInvocation,
    task: Task,
) -> ToolResult | None:
    attempts = [
        attempt
        for attempt in repositories.scientific_attempts.list_by_session(task.session_id)
        if attempt.task_id == task.task_id
    ]
    if not attempts:
        return None
    resolver = ScientificAttemptLifecycleResolver(repositories)
    try:
        lifecycles = [resolver.resolve(attempt) for attempt in attempts]
    except ScientificAttemptLifecycleIntegrityError as exc:
        return _finish_error_result(
            invocation,
            status=exc.error_code,
            summary=(
                "task.finish(completed) refused because bound scientific "
                "attempt lifecycle evidence is inconsistent."
            ),
            hint="Inspect and repair the canonical attempt lifecycle before retrying.",
            details={
                "task_id": task.task_id,
                **exc.details,
                "effect_certainty": "no_effect",
            },
        )
    blocking = [
        lifecycle
        for lifecycle in lifecycles
        if lifecycle.phase
        in {
            ScientificAttemptLifecyclePhase.OPEN,
            ScientificAttemptLifecyclePhase.CLOSURE_REQUESTED,
        }
    ]
    closed = [
        lifecycle
        for lifecycle in lifecycles
        if lifecycle.phase is ScientificAttemptLifecyclePhase.CLOSED
    ]
    if not blocking and closed:
        return None
    return _finish_error_result(
        invocation,
        status="scientific_attempt_task_not_closed",
        summary=(
            "task.finish(completed) refused: the task requires an immutable "
            "scientific attempt closure before explicit completion."
        ),
        hint=(
            "Call scientific.attempt.close as the canonical task assignee, "
            "await Host finalization, then retry task.finish(completed)."
        ),
        details={
            "task_id": task.task_id,
            "attempt_lifecycles": [
                {
                    "attempt_id": lifecycle.attempt.attempt_id,
                    "phase": lifecycle.phase.value,
                }
                for lifecycle in lifecycles
            ],
            "open_attempt_ids": [
                lifecycle.attempt.attempt_id for lifecycle in blocking
            ],
            "closed_attempt_ids": [
                lifecycle.attempt.attempt_id for lifecycle in closed
            ],
            "effect_certainty": "no_effect",
            "retryable": True,
        },
    )


def _coerce_evidence_refs(
    value: Any,
) -> tuple[tuple[TaskEvidenceRef, ...], str | None]:
    if value is None:
        return (), None
    if not isinstance(value, list | tuple):
        return (), "evidence_refs must be an array of TaskEvidenceRef@1 objects."
    if len(value) > 64:
        return (), "evidence_refs cannot contain more than 64 entries."
    refs: list[TaskEvidenceRef] = []
    for item in value:
        if not isinstance(item, dict):
            return (), (
                "evidence_refs must contain only TaskEvidenceRef@1 objects; "
                "legacy strings and aliases are invalid."
            )
        try:
            refs.append(TaskEvidenceRef.from_dict(item))
        except (TypeError, ValueError) as exc:
            return (), f"invalid TaskEvidenceRef@1: {exc}"
    return tuple(refs), None


def _validate_evidence_refs(
    repositories: CoreRepositories,
    *,
    task_id: str,
    evidence_refs: tuple[TaskEvidenceRef, ...],
) -> str | None:
    service = TaskEvidenceReferenceService(repositories)
    for ref in evidence_refs:
        try:
            service.require_for_task(ref, task_id=task_id)
        except RevisionPathHandoffError as exc:
            return str(exc)
    return None


def _evidence_ref_payload(ref: TaskEvidenceRef) -> dict[str, Any]:
    return ref.to_dict()


def _can_finish_task(context: SessionRuntimeContext, task: Task) -> bool:
    if is_teammate_role_alias(context.agent_id) or is_teammate_role_alias(
        task.assigned_ref
    ):
        return False
    if context.agent_id == task.assigned_ref and context.agent_id is not None:
        return True
    if context.actor_kind == "master" or context.agent_id == "agent:master":
        return True
    if context.actor_kind in {None, "harness"} and context.agent_id is None:
        return True
    return False


def _finish_terminates_current_turn(context: SessionRuntimeContext, task: Task) -> bool:
    if context.agent_id is None:
        return False
    if context.actor_kind == "master" or context.agent_id == "agent:master":
        return False
    if is_teammate_role_alias(context.agent_id):
        return False
    return context.agent_id == task.assigned_ref


def _already_satisfied_task_finish_result(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    task: Task,
) -> ToolResult | None:
    arguments = invocation.arguments
    requested_status = str(arguments.get("status") or "").strip()
    if requested_status != task.status.value:
        return None
    evidence_refs, evidence_error = _coerce_evidence_refs(
        arguments.get("evidence_refs")
    )
    if evidence_error is not None:
        return None
    requested_payload = {
        "task_id": task.task_id,
        "status": requested_status,
        "summary": str(arguments.get("summary") or "").strip(),
        "evidence_refs": [_evidence_ref_payload(ref) for ref in evidence_refs],
        "failure_summary": (
            None
            if arguments.get("failure_summary") is None
            else str(arguments["failure_summary"]).strip()
        ),
        "failure_ref": (
            None
            if arguments.get("failure_ref") is None
            else str(arguments["failure_ref"]).strip()
        ),
        "blocked_reason": (
            None
            if arguments.get("blocked_reason") is None
            else str(arguments["blocked_reason"]).strip()
        ),
        "recovery_hint": (
            None
            if arguments.get("recovery_hint") is None
            else str(arguments["recovery_hint"]).strip()
        ),
        "next_owner": (
            None
            if arguments.get("next_owner") is None
            else str(arguments["next_owner"]).strip()
        ),
    }
    finish_record = next(
        (
            record
            for record in reversed(
                context.repositories.revision_path_handoffs.list_task_finishes(
                    task.task_id
                )
            )
            if all(
                record.get(key) == value
                for key, value in requested_payload.items()
            )
        ),
        None,
    )
    if finish_record is None:
        return None
    payload = {
        "task": task.to_dict(),
        **finish_record,
    }
    terminates_turn = _finish_terminates_current_turn(context, task)
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=True,
        content=json.dumps(payload, sort_keys=True),
        task_id=task.task_id,
        lane_id=invocation.lane_id,
        status="task_already_satisfied",
        summary=(
            f"task.finish already established {task.status.value} for "
            f"{task.task_id} with the same canonical finish payload."
        ),
        details={
            "task_id": task.task_id,
            "task_status": task.status.value,
            "finish_ref": finish_record["finish_ref"],
            "evidence_refs": [_evidence_ref_payload(ref) for ref in evidence_refs],
            "next_owner": requested_payload["next_owner"],
            "terminates_current_turn": terminates_turn,
            "already_satisfied": True,
        },
        terminal_action="task.finish",
        terminates_turn=terminates_turn,
    )


class TaskBoardBucket(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TaskMutation:
    subject: str | object = _UNSET
    description: str | object = _UNSET
    status: TaskStatus | object = _UNSET
    priority: TaskPriority | object = _UNSET
    kind: str | object = _UNSET
    assigned_ref: str | None | object = _UNSET
    lane_id: str | None | object = _UNSET
    blocked_by: tuple[str, ...] | object = _UNSET
    failure_summary: str | None | object = _UNSET
    failure_ref: str | None | object = _UNSET
    updated_at: str | object = _UNSET


@dataclass(frozen=True, slots=True)
class TaskFinishCommand:
    status: TaskStatus
    finished_by: str
    summary: str = ""
    evidence_refs: tuple[TaskEvidenceRef, ...] = ()
    failure_summary: str | None = None
    failure_ref: str | None = None
    blocked_reason: str | None = None
    recovery_hint: str | None = None
    next_owner: str | None = None
    correlation_id: str | None = None
    signal_id: str | None = None


@dataclass(frozen=True, slots=True)
class TaskFinishOutcome:
    task: Task
    finish_ref: str
    payload: dict[str, Any]


@dataclass(frozen=True, slots=True)
class TaskBoardItem:
    task: Task
    bucket: TaskBoardBucket
    blocked_by_open_task_ids: tuple[str, ...]
    is_ready: bool

    def to_dict(self) -> dict[str, Any]:
        return {
            "task": self.task.to_dict(),
            "bucket": self.bucket.value,
            "blocked_by_open_task_ids": list(self.blocked_by_open_task_ids),
            "is_ready": self.is_ready,
        }


@dataclass(frozen=True, slots=True)
class TaskBoardProjection:
    session_id: str
    lane_id: str | None
    items: tuple[TaskBoardItem, ...]
    ready_tasks: tuple[TaskBoardItem, ...]
    blocked_tasks: tuple[TaskBoardItem, ...]
    next_task_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "lane_id": self.lane_id,
            "items": [item.to_dict() for item in self.items],
            "ready_tasks": [item.to_dict() for item in self.ready_tasks],
            "blocked_tasks": [item.to_dict() for item in self.blocked_tasks],
            "next_task_id": self.next_task_id,
        }


@dataclass(slots=True)
class TaskBoardService:
    repositories: CoreRepositories
    event_emitter: Any | None = None

    def create_task(
        self,
        *,
        session_id: str,
        task_id: str,
        subject: str,
        description: str,
        priority: TaskPriority = TaskPriority.NORMAL,
        kind: str = "general",
        status: TaskStatus = TaskStatus.TODO,
        assigned_ref: str | None = None,
        lane_id: str | None = None,
        blocked_by: tuple[str, ...] = (),
        failure_summary: str | None = None,
        failure_ref: str | None = None,
    ) -> Task:
        if status in _TASK_FINISH_STATUSES:
            raise TaskExitStatusRequiresFinish(operation="task.create", status=status)
        task = Task.create(
            task_id=task_id,
            session_id=session_id,
            subject=subject,
            description=description,
            priority=priority,
            kind=kind,
            status=status,
            assigned_ref=_normalize_assigned_ref(
                self.repositories,
                session_id=session_id,
                value=assigned_ref,
            ),
            lane_id=lane_id,
            blocked_by=blocked_by,
            failure_summary=failure_summary,
            failure_ref=failure_ref,
        )
        self.repositories.tasks.validate_dependencies(task)
        self.repositories.tasks.save(task, intent=TaskWriteIntent.EDIT)
        self._emit(
            "task.created", {"task_id": task.task_id, "session_id": task.session_id}
        )
        self._emit_task_state(task)
        if task.assigned_ref is not None:
            self._emit(
                "task.assigned",
                {"task_id": task.task_id, "assigned_ref": task.assigned_ref},
            )
        return task

    def edit_task(self, task_id: str, mutation: TaskMutation) -> Task:
        if mutation.status is not _UNSET and mutation.status in _TASK_FINISH_STATUSES:
            raise TaskExitStatusRequiresFinish(
                operation="task.edit",
                status=mutation.status,
            )
        return self._apply_mutation(task_id, mutation)

    def update_task(self, task_id: str, mutation: TaskMutation) -> Task:
        """Compatibility alias for the guarded non-terminal edit command."""

        return self.edit_task(task_id, mutation)

    def block_for_approval(self, task_id: str) -> Task:
        """Apply the documented mechanical waiting-approval transition."""

        return self._apply_mutation(
            task_id,
            TaskMutation(status=TaskStatus.BLOCKED),
            write_intent=TaskWriteIntent.MECHANICAL,
        )

    def claim_task(self, task_id: str, *, assigned_ref: str) -> Task:
        """Apply the documented mechanical task-claim transition."""

        return self._apply_mutation(
            task_id,
            TaskMutation(
                assigned_ref=assigned_ref,
                status=TaskStatus.IN_PROGRESS,
            ),
            write_intent=TaskWriteIntent.MECHANICAL,
        )

    def resume_after_approval(self, task_id: str) -> Task:
        """Apply the documented mechanical approval-resume transition."""

        return self._apply_mutation(
            task_id,
            TaskMutation(status=TaskStatus.IN_PROGRESS),
            write_intent=TaskWriteIntent.MECHANICAL,
        )

    def _apply_mutation(
        self,
        task_id: str,
        mutation: TaskMutation,
        *,
        write_intent: TaskWriteIntent = TaskWriteIntent.EDIT,
        emit: bool = True,
    ) -> Task:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        updated = Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject
            if mutation.subject is _UNSET
            else str(mutation.subject),
            description=task.description
            if mutation.description is _UNSET
            else str(mutation.description),
            status=task.status if mutation.status is _UNSET else mutation.status,
            priority=task.priority
            if mutation.priority is _UNSET
            else mutation.priority,
            kind=task.kind if mutation.kind is _UNSET else str(mutation.kind),
            assigned_ref=task.assigned_ref
            if mutation.assigned_ref is _UNSET
            else _normalize_assigned_ref(
                self.repositories,
                session_id=task.session_id,
                value=mutation.assigned_ref,
            ),
            created_at=task.created_at,
            updated_at=utc_now_iso()
            if mutation.updated_at is _UNSET
            else str(mutation.updated_at),
            lane_id=task.lane_id if mutation.lane_id is _UNSET else mutation.lane_id,
            blocked_by=task.blocked_by
            if mutation.blocked_by is _UNSET
            else mutation.blocked_by,
            failure_summary=task.failure_summary
            if mutation.failure_summary is _UNSET
            else mutation.failure_summary,
            failure_ref=task.failure_ref
            if mutation.failure_ref is _UNSET
            else mutation.failure_ref,
        )
        self.repositories.tasks.validate_dependencies(updated)
        self.repositories.tasks.save(updated, intent=write_intent)
        if emit:
            self._emit_task_mutation(task, updated)
        return updated

    def _emit_task_mutation(self, task: Task, updated: Task) -> None:
        self._emit(
            "task.updated",
            {
                "task_id": updated.task_id,
                "status": updated.status.value,
                "priority": updated.priority.value,
                "assigned_ref": updated.assigned_ref,
            },
        )
        if updated.assigned_ref != task.assigned_ref:
            self._emit(
                "task.assigned",
                {"task_id": updated.task_id, "assigned_ref": updated.assigned_ref},
            )
        self._emit_task_state(updated)

    def finish_task(
        self,
        task_id: str,
        command: TaskFinishCommand,
    ) -> TaskFinishOutcome:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        if task.status in _TASK_FINISH_STATUSES:
            raise ValueError(
                f"task {task_id!r} already reached business exit "
                f"{task.status.value}; explicitly resume or reopen it first"
            )
        if command.status not in _TASK_FINISH_STATUSES:
            raise ValueError(
                "task.finish status must be one of: "
                + ", ".join(sorted(item.value for item in _TASK_FINISH_STATUSES))
            )
        summary = command.summary.strip()
        failure_summary = (
            None if command.failure_summary is None else command.failure_summary.strip()
        )
        failure_ref = (
            None if command.failure_ref is None else command.failure_ref.strip()
        )
        blocked_reason = (
            None if command.blocked_reason is None else command.blocked_reason.strip()
        )
        recovery_hint = (
            None if command.recovery_hint is None else command.recovery_hint.strip()
        )
        next_owner = None if command.next_owner is None else command.next_owner.strip()
        if command.status is TaskStatus.COMPLETED and not summary:
            raise ValueError("task.finish(completed) requires a non-empty summary")
        if command.status is TaskStatus.FAILED and not (failure_summary or failure_ref):
            raise ValueError(
                "task.finish(failed) requires failure_summary or failure_ref"
            )
        if command.status is TaskStatus.BLOCKED and not (
            blocked_reason or recovery_hint
        ):
            raise ValueError(
                "task.finish(blocked) requires blocked_reason or recovery_hint"
            )
        if next_owner is not None and next_owner not in {
            "master",
            "user",
            "teammate",
        }:
            raise ValueError("task.finish next_owner must be master, user, or teammate")
        evidence_error = _validate_evidence_refs(
            self.repositories,
            task_id=task.task_id,
            evidence_refs=command.evidence_refs,
        )
        if evidence_error is not None:
            raise ValueError(evidence_error)
        finished_by = command.finished_by.strip()
        if not finished_by:
            raise ValueError("task.finish requires a non-empty finished_by actor")

        now = utc_now_iso()
        finish_ref = f"task_finish_{uuid4().hex[:12]}"
        session = self.repositories.sessions.get(task.session_id)
        if session is None:
            raise ValueError("task session does not exist")
        finish_payload = {
            "task_id": task.task_id,
            "status": command.status.value,
            "summary": summary,
            "evidence_refs": [
                _evidence_ref_payload(ref) for ref in command.evidence_refs
            ],
            "failure_summary": failure_summary,
            "failure_ref": failure_ref,
            "blocked_reason": blocked_reason,
            "recovery_hint": recovery_hint,
            "next_owner": next_owner,
            "finished_by": finished_by,
            "correlation_id": command.correlation_id,
            "signal_id": command.signal_id,
        }
        previous_task = task
        with self.repositories.atomic(prefix="task_finish"):
            current_task = self.repositories.tasks.get(task.task_id)
            if current_task != previous_task or (
                current_task is not None
                and current_task.status in _TASK_FINISH_STATUSES
            ):
                raise ValueError(
                    "task changed before the atomic finish boundary; refresh and retry"
                )
            evidence_error = _validate_evidence_refs(
                self.repositories,
                task_id=task.task_id,
                evidence_refs=command.evidence_refs,
            )
            if evidence_error is not None:
                raise ValueError(evidence_error)
            self.repositories.revision_path_handoffs.add_task_finish(
                finish_ref=finish_ref,
                project_id=session.project_id,
                session_id=task.session_id,
                task_id=task.task_id,
                terminal_status=command.status.value,
                summary=summary,
                failure_summary=failure_summary,
                failure_ref=failure_ref,
                blocked_reason=blocked_reason,
                recovery_hint=recovery_hint,
                next_owner=next_owner,
                finished_by=finished_by,
                correlation_id=command.correlation_id,
                signal_id=command.signal_id,
                evidence_refs=tuple(
                    ref
                    for ref in command.evidence_refs
                    if isinstance(ref, TaskEvidenceRef)
                ),
                created_at=now,
            )
            task = self._apply_mutation(
                task.task_id,
                TaskMutation(
                    status=command.status,
                    failure_summary=(
                        failure_summary
                        if command.status is TaskStatus.FAILED
                        else _UNSET
                    ),
                    failure_ref=(
                        failure_ref if command.status is TaskStatus.FAILED else _UNSET
                    ),
                ),
                write_intent=TaskWriteIntent.FINISH,
                emit=False,
            )
        self._emit_task_mutation(previous_task, task)
        self._emit(
            "task.finished",
            {
                "task_id": task.task_id,
                "status": task.status.value,
                "summary": summary,
                "finish_ref": finish_ref,
                "evidence_refs": [
                    _evidence_ref_payload(ref) for ref in command.evidence_refs
                ],
                "next_owner": next_owner,
            },
        )
        return TaskFinishOutcome(
            task=task,
            finish_ref=finish_ref,
            payload=finish_payload,
        )

    def get_task(self, task_id: str) -> Task | None:
        return self.repositories.tasks.get(task_id)

    def list_tasks(self, session_id: str, *, lane_id: str | None = None) -> list[Task]:
        if lane_id is None:
            return self.repositories.tasks.list_by_session(session_id)
        return self.repositories.tasks.list_by_lane(session_id, lane_id)

    def list_ready_tasks(
        self, session_id: str, *, lane_id: str | None = None
    ) -> list[Task]:
        return self.repositories.tasks.list_ready_by_session(
            session_id, lane_id=lane_id
        )

    def open_blocker_ids(self, task: Task) -> tuple[str, ...]:
        blockers: list[str] = []
        for blocker_id in task.blocked_by:
            blocker = self.repositories.tasks.get(blocker_id)
            if blocker is None or blocker.status is not TaskStatus.COMPLETED:
                blockers.append(blocker_id)
        return tuple(blockers)

    def select_next_task(
        self, session_id: str, *, lane_id: str | None = None
    ) -> Task | None:
        ready_tasks = self.list_ready_tasks(session_id, lane_id=lane_id)
        if not ready_tasks:
            return None
        return sorted(
            ready_tasks,
            key=lambda task: (
                _PRIORITY_ORDER[task.priority],
                task.created_at,
                task.task_id,
            ),
        )[0]

    def build_projection(
        self, session_id: str, *, lane_id: str | None = None
    ) -> TaskBoardProjection:
        tasks = self.list_tasks(session_id, lane_id=lane_id)
        items = tuple(self._build_items(tasks))
        ready_tasks = tuple(
            item for item in items if item.bucket is TaskBoardBucket.READY
        )
        blocked_tasks = tuple(
            item for item in items if item.bucket is TaskBoardBucket.BLOCKED
        )
        next_task = self.select_next_task(session_id, lane_id=lane_id)
        return TaskBoardProjection(
            session_id=session_id,
            lane_id=lane_id,
            items=items,
            ready_tasks=ready_tasks,
            blocked_tasks=blocked_tasks,
            next_task_id=None if next_task is None else next_task.task_id,
        )

    def _build_items(self, tasks: list[Task]) -> list[TaskBoardItem]:
        items: list[TaskBoardItem] = []
        for task in tasks:
            open_blockers = self.open_blocker_ids(task)
            bucket = _bucket_for_task(task, open_blockers)
            items.append(
                TaskBoardItem(
                    task=task,
                    bucket=bucket,
                    blocked_by_open_task_ids=open_blockers,
                    is_ready=bucket is TaskBoardBucket.READY,
                )
            )
        return sorted(
            items,
            key=lambda item: (
                _PRIORITY_ORDER[item.task.priority],
                item.task.created_at,
                item.task.task_id,
            ),
        )

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)

    def _emit_task_state(self, task: Task) -> None:
        projection = self.build_projection(task.session_id)
        item = next(
            (
                candidate
                for candidate in projection.items
                if candidate.task.task_id == task.task_id
            ),
            None,
        )
        if item is None:
            return
        if item.bucket is TaskBoardBucket.READY:
            self._emit(
                "task.ready",
                {"task_id": task.task_id, "blocked_by_open_task_ids": []},
            )
        if item.bucket is TaskBoardBucket.BLOCKED:
            self._emit(
                "task.blocked",
                {
                    "task_id": task.task_id,
                    "blocked_by_open_task_ids": list(item.blocked_by_open_task_ids),
                },
            )


def _bucket_for_task(task: Task, open_blockers: tuple[str, ...]) -> TaskBoardBucket:
    if task.status is TaskStatus.COMPLETED:
        return TaskBoardBucket.COMPLETED
    if task.status is TaskStatus.FAILED:
        return TaskBoardBucket.FAILED
    if task.status is TaskStatus.CANCELLED:
        return TaskBoardBucket.CANCELLED
    if task.status is TaskStatus.IN_PROGRESS:
        return TaskBoardBucket.IN_PROGRESS
    if task.status is TaskStatus.BLOCKED or open_blockers:
        return TaskBoardBucket.BLOCKED
    return TaskBoardBucket.READY


def register_task_board_tools(registry: ToolRegistry) -> None:
    def create_task_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        arguments = invocation.arguments
        task_id = str(arguments.get("task_id") or f"task_{uuid4().hex[:12]}")
        requested_status = TaskStatus(
            str(arguments.get("status", TaskStatus.TODO.value))
        )
        if requested_status not in _TASK_TOOL_MUTATION_STATUSES:
            return _finish_error_result(
                invocation,
                status="task_terminal_status_requires_finish",
                summary=(
                    "task.create cannot create a completed, blocked, failed, or "
                    "cancelled task. Create a non-terminal task, then use "
                    "task.finish for the explicit business exit."
                ),
                details={
                    "task_id": task_id,
                    "requested_status": requested_status.value,
                    "allowed_statuses": sorted(
                        status.value for status in _TASK_TOOL_MUTATION_STATUSES
                    ),
                    "finish_statuses": sorted(
                        status.value for status in _TASK_FINISH_STATUSES
                    ),
                },
            )
        task = service.create_task(
            session_id=context.snapshot.session.session_id,
            task_id=task_id,
            subject=str(arguments["subject"]),
            description=str(arguments.get("description") or ""),
            priority=TaskPriority(
                str(arguments.get("priority", TaskPriority.NORMAL.value))
            ),
            kind=str(arguments.get("kind", "general")),
            status=requested_status,
            assigned_ref=arguments.get("assigned_ref"),
            lane_id=invocation.lane_id
            if "lane_id" not in arguments
            else arguments.get("lane_id"),
            blocked_by=tuple(str(item) for item in arguments.get("blocked_by", ())),
            failure_summary=arguments.get("failure_summary"),
            failure_ref=arguments.get("failure_ref"),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(task.to_dict(), sort_keys=True),
            task_id=task.task_id,
            lane_id=invocation.lane_id,
        )

    def update_task_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        arguments = invocation.arguments
        task_id = str(arguments["task_id"])
        requested_status = (
            None if "status" not in arguments else TaskStatus(str(arguments["status"]))
        )
        if (
            requested_status is not None
            and requested_status not in _TASK_TOOL_MUTATION_STATUSES
        ):
            return _finish_error_result(
                invocation,
                status="task_terminal_status_requires_finish",
                summary=(
                    "task.update cannot set completed, blocked, failed, or "
                    "cancelled. Use task.finish for explicit business exits."
                ),
                details={
                    "task_id": task_id,
                    "requested_status": requested_status.value,
                    "allowed_statuses": sorted(
                        status.value for status in _TASK_TOOL_MUTATION_STATUSES
                    ),
                    "finish_statuses": sorted(
                        status.value for status in _TASK_FINISH_STATUSES
                    ),
                },
            )
        mutation = TaskMutation(
            subject=arguments["subject"] if "subject" in arguments else _UNSET,
            description=arguments["description"]
            if "description" in arguments
            else _UNSET,
            status=TaskStatus(str(arguments["status"]))
            if "status" in arguments
            else _UNSET,
            priority=TaskPriority(str(arguments["priority"]))
            if "priority" in arguments
            else _UNSET,
            kind=arguments["kind"] if "kind" in arguments else _UNSET,
            assigned_ref=arguments["assigned_ref"]
            if "assigned_ref" in arguments
            else _UNSET,
            lane_id=arguments["lane_id"] if "lane_id" in arguments else _UNSET,
            blocked_by=tuple(str(item) for item in arguments["blocked_by"])
            if "blocked_by" in arguments
            else _UNSET,
            failure_summary=arguments["failure_summary"]
            if "failure_summary" in arguments
            else _UNSET,
            failure_ref=arguments["failure_ref"]
            if "failure_ref" in arguments
            else _UNSET,
            updated_at=str(arguments["updated_at"])
            if "updated_at" in arguments
            else _UNSET,
        )
        task = service.edit_task(task_id, mutation)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(task.to_dict(), sort_keys=True),
            task_id=task.task_id,
            lane_id=invocation.lane_id,
        )

    def finish_task_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        arguments = invocation.arguments
        task_id = str(arguments["task_id"])
        stale_file_fields = sorted(
            {"produced_durable_files", "workspace_checkpoint_id"}.intersection(
                arguments
            )
        )
        if stale_file_fields:
            return _finish_error_result(
                invocation,
                status="legacy_task_finish_file_fields_forbidden",
                summary=(
                    "task.finish no longer accepts checkpoint or mutable workspace "
                    "file fields; use the closed TaskEvidenceRef@1 union."
                ),
                details={"task_id": task_id, "forbidden_fields": stale_file_fields},
            )
        task = service.get_task(task_id)
        if task is None:
            return _finish_error_result(
                invocation,
                status="task_not_found",
                summary=f"task.finish failed: task {task_id!r} does not exist.",
                details={"task_id": task_id},
            )
        if task.session_id != context.snapshot.session.session_id:
            return _finish_error_result(
                invocation,
                status="task_not_in_session",
                summary=f"task.finish failed: task {task_id!r} is outside the current session.",
                details={
                    "task_id": task_id,
                    "task_session_id": task.session_id,
                    "session_id": context.snapshot.session.session_id,
                },
            )
        if not _can_finish_task(context, task):
            return _finish_error_result(
                invocation,
                status="task_finish_forbidden",
                summary=(
                    "task.finish refused: only the assigned task owner, master, "
                    "or a harness-authorized actor can finish this task."
                ),
                details={
                    "task_id": task_id,
                    "assigned_ref": task.assigned_ref,
                    "agent_id": context.agent_id,
                    "actor_kind": context.actor_kind,
                },
            )
        if task.status in _TASK_FINISH_STATUSES:
            already_satisfied = _already_satisfied_task_finish_result(
                context,
                invocation,
                task,
            )
            if already_satisfied is not None:
                return already_satisfied
            return _finish_error_result(
                invocation,
                status="task_already_terminal",
                summary=(
                    f"task.finish refused: task {task_id!r} already reached business "
                    f"exit {task.status.value} and no resume/reopen mechanism was requested."
                ),
                hint="Use an explicit resume/reopen workflow before finishing the task again.",
                details={"task_id": task_id, "current_status": task.status.value},
            )
        status = TaskStatus(str(arguments["status"]))
        if status not in _TASK_FINISH_STATUSES:
            return _finish_error_result(
                invocation,
                status="invalid_task_finish_status",
                summary=(
                    "task.finish status must be one of: "
                    + ", ".join(sorted(item.value for item in _TASK_FINISH_STATUSES))
                ),
                details={"requested_status": status.value},
            )
        summary = str(arguments.get("summary") or "").strip()
        failure_summary = (
            None
            if arguments.get("failure_summary") is None
            else str(arguments.get("failure_summary")).strip()
        )
        failure_ref = (
            None
            if arguments.get("failure_ref") is None
            else str(arguments.get("failure_ref")).strip()
        )
        blocked_reason = (
            None
            if arguments.get("blocked_reason") is None
            else str(arguments.get("blocked_reason")).strip()
        )
        recovery_hint = (
            None
            if arguments.get("recovery_hint") is None
            else str(arguments.get("recovery_hint")).strip()
        )
        next_owner = (
            None
            if arguments.get("next_owner") is None
            else str(arguments.get("next_owner")).strip()
        )
        if status is TaskStatus.COMPLETED and not summary:
            return _finish_error_result(
                invocation,
                status="task_finish_summary_required",
                summary="task.finish(completed) requires a non-empty summary.",
                details={"task_id": task_id, "requested_status": status.value},
            )
        if status is TaskStatus.COMPLETED:
            completion_guard = _scientific_attempt_completion_guard(
                context.repositories,
                invocation=invocation,
                task=task,
            )
            if completion_guard is not None:
                return completion_guard
        if status is TaskStatus.FAILED and not (failure_summary or failure_ref):
            return _finish_error_result(
                invocation,
                status="task_finish_failure_required",
                summary="task.finish(failed) requires failure_summary or failure_ref.",
                details={"task_id": task_id, "requested_status": status.value},
            )
        if status is TaskStatus.BLOCKED and not (blocked_reason or recovery_hint):
            return _finish_error_result(
                invocation,
                status="task_finish_blocked_reason_required",
                summary="task.finish(blocked) requires blocked_reason or recovery_hint.",
                details={"task_id": task_id, "requested_status": status.value},
            )
        if next_owner is not None and next_owner not in {"master", "user", "teammate"}:
            return _finish_error_result(
                invocation,
                status="invalid_task_finish_next_owner",
                summary="task.finish next_owner must be master, user, or teammate.",
                details={"task_id": task_id, "next_owner": next_owner},
            )
        evidence_refs, evidence_error = _coerce_evidence_refs(
            arguments.get("evidence_refs")
        )
        if evidence_error is not None:
            return _finish_error_result(
                invocation,
                status="invalid_task_finish_evidence_refs",
                summary=evidence_error,
                details={
                    "task_id": task_id,
                    **task_finish_evidence_contract_details(),
                },
            )
        evidence_validation_error = _validate_evidence_refs(
            context.repositories,
            task_id=task_id,
            evidence_refs=evidence_refs,
        )
        if evidence_validation_error is not None:
            return _finish_error_result(
                invocation,
                status="invalid_task_finish_evidence_refs",
                summary=evidence_validation_error,
                details={
                    "task_id": task_id,
                    "evidence_refs": [
                        _evidence_ref_payload(ref) for ref in evidence_refs
                    ],
                    **task_finish_evidence_contract_details(),
                },
            )
        finish_outcome = service.finish_task(
            task.task_id,
            TaskFinishCommand(
                status=status,
                summary=summary,
                evidence_refs=evidence_refs,
                failure_summary=failure_summary,
                failure_ref=failure_ref,
                blocked_reason=blocked_reason,
                recovery_hint=recovery_hint,
                next_owner=next_owner,
                finished_by=context.agent_id or context.actor_kind or "harness",
                correlation_id=context.correlation_id,
                signal_id=context.signal_id,
            ),
        )
        task = finish_outcome.task
        finish_ref = finish_outcome.finish_ref
        finish_payload = finish_outcome.payload
        payload = {
            "task": task.to_dict(),
            "finish_ref": finish_ref,
            **finish_payload,
        }
        terminates_turn = _finish_terminates_current_turn(context, task)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=task.task_id,
            lane_id=invocation.lane_id,
            status=status.value,
            summary=summary or failure_summary or blocked_reason or recovery_hint,
            details={
                "task_id": task.task_id,
                "task_status": task.status.value,
                "finish_ref": finish_ref,
                "evidence_refs": [
                    _evidence_ref_payload(ref) for ref in evidence_refs
                ],
                "next_owner": next_owner,
                "terminates_current_turn": terminates_turn,
            },
            terminal_action="task.finish",
            terminates_turn=terminates_turn,
        )

    def get_task_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        task = service.get_task(str(invocation.arguments["task_id"]))
        if task is not None and task.session_id != context.snapshot.session.session_id:
            task = None
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(
                None if task is None else task.to_dict(), sort_keys=True
            ),
            task_id=None if task is None else task.task_id,
            lane_id=invocation.lane_id,
            status="task_not_found" if task is None else "task_projected",
            summary=(
                f"No task matched {invocation.arguments['task_id']!r}."
                if task is None
                else f"Projected task {task.task_id}."
            ),
            details={
                "task_id": str(invocation.arguments["task_id"]),
                "found": task is not None,
            },
        )

    def list_tasks_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        lane_id = invocation.arguments.get("lane_id", invocation.lane_id)
        projection = service.build_projection(
            context.snapshot.session.session_id, lane_id=lane_id
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(projection.to_dict(), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def next_task_handler(
        context: SessionRuntimeContext, invocation: ToolInvocation
    ) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        lane_id = invocation.arguments.get("lane_id", invocation.lane_id)
        task = service.select_next_task(
            context.snapshot.session.session_id, lane_id=lane_id
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(
                None if task is None else task.to_dict(), sort_keys=True
            ),
            task_id=None if task is None else task.task_id,
            lane_id=invocation.lane_id,
            status="no_ready_task" if task is None else "next_task_projected",
            summary=(
                "No ready task matched the current session/lane."
                if task is None
                else f"Projected next ready task {task.task_id}."
            ),
            details={
                "found": task is not None,
                "lane_id": lane_id,
                "task_id": None if task is None else task.task_id,
            },
        )

    registry.register("task.create", create_task_handler)
    registry.register("task.update", update_task_handler)
    registry.register("task.finish", finish_task_handler)
    registry.register("task.get", get_task_handler)
    registry.register("task.list", list_tasks_handler)
    registry.register("task.next", next_task_handler)
