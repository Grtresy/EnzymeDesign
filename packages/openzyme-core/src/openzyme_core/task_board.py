from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any
from uuid import uuid4

from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_domain import ArtifactKind
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import CoreRepositories
from .repositories import EngineDocumentRecord

_UNSET = object()
_PRIORITY_ORDER = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}
_PSEUDO_EMPTY_ASSIGNED_REFS = {"", "none", "null"}
_TEAMMATE_ASSIGNED_REF_ALIASES = {
    "researcher": "agent:researcher",
    "executor": "agent:executor",
    "reporter": "agent:reporter",
}
_TASK_FINISH_STATUSES = {
    TaskStatus.COMPLETED,
    TaskStatus.BLOCKED,
    TaskStatus.FAILED,
    TaskStatus.CANCELLED,
}
_EVIDENCE_REF_KINDS = {
    "artifact",
    "document",
    "invocation",
    "message",
    "protocol",
    "report",
    "run",
    "sandbox_run",
}


def _normalize_assigned_ref(value: Any) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        normalized = value.strip()
        if normalized.lower() in _PSEUDO_EMPTY_ASSIGNED_REFS:
            return None
        if normalized.lower() in _TEAMMATE_ASSIGNED_REF_ALIASES:
            return _TEAMMATE_ASSIGNED_REF_ALIASES[normalized.lower()]
        return normalized
    return str(value)


def _session_requires_structure_artifact(context: SessionRuntimeContext) -> bool:
    objective = context.snapshot.session.objective.lower()
    return (
        ("structure" in objective or "pdb" in objective)
        and (
            "artifact" in objective
            or "execution" in objective
            or "fpocket" in objective
        )
    )


def _session_has_structure_artifact(context: SessionRuntimeContext) -> bool:
    return any(
        artifact.kind is ArtifactKind.STRUCTURE
        for artifact in context.repositories.artifacts.list_by_session(
            context.snapshot.session.session_id
        )
    )


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


def _coerce_evidence_refs(value: Any) -> tuple[tuple[str, ...], str | None]:
    if value is None:
        return (), None
    if not isinstance(value, list | tuple):
        return (), "evidence_refs must be an array of strings."
    refs: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            return (), "evidence_refs must contain non-empty strings."
        refs.append(item.strip())
    return tuple(refs), None


def _validate_evidence_refs(
    repositories: CoreRepositories,
    *,
    session_id: str,
    evidence_refs: tuple[str, ...],
) -> str | None:
    for ref in evidence_refs:
        kind, sep, record_id = ref.partition(":")
        if not sep or not kind or not record_id:
            return (
                f"Evidence ref {ref!r} must use '<kind>:<id>' format. "
                f"Known kinds: {', '.join(sorted(_EVIDENCE_REF_KINDS))}."
            )
        if kind not in _EVIDENCE_REF_KINDS:
            return (
                f"Evidence ref {ref!r} uses unknown kind {kind!r}. "
                f"Known kinds: {', '.join(sorted(_EVIDENCE_REF_KINDS))}."
            )
        if kind == "artifact":
            artifact = repositories.artifacts.get(record_id)
            if artifact is None or artifact.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a session artifact."
        elif kind == "document":
            document = repositories.engine_documents.get(record_id)
            if document is None or document.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a session document."
        elif kind == "invocation":
            invocation = repositories.invocations.get(record_id)
            if invocation is None or invocation.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a session invocation."
        elif kind == "message":
            message = repositories.inbox.get(record_id)
            if message is None or message.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a session message."
        elif kind == "protocol":
            if not any(
                message.correlation_id == record_id
                for message in repositories.inbox.list_by_session(session_id)
            ):
                return f"Evidence ref {ref!r} does not resolve to a protocol thread."
        elif kind == "report":
            report = repositories.reports.get(record_id)
            if report is None or report.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a session report."
        elif kind == "run":
            run = repositories.runs.get(record_id)
            if run is None or run.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a session run."
        elif kind == "sandbox_run":
            sandbox_run = repositories.sandbox_runs.get(record_id)
            if sandbox_run is None or sandbox_run.session_id != session_id:
                return f"Evidence ref {ref!r} does not resolve to a sandbox run."
    return None


def _can_finish_task(context: SessionRuntimeContext, task: Task) -> bool:
    if context.agent_id == task.assigned_ref and context.agent_id is not None:
        return True
    if context.actor_kind == "master" or context.agent_id == "agent:master":
        return True
    if context.actor_kind in {None, "harness"} and context.agent_id is None:
        return True
    return False


def _required_structure_artifact_error(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    *,
    task: Task,
    retry_tool: str,
) -> ToolResult | None:
    if (
        task.status is not TaskStatus.COMPLETED
        and task.kind == "research"
        and str(task.assigned_ref or "").startswith("agent:researcher")
        and _session_requires_structure_artifact(context)
        and not _session_has_structure_artifact(context)
    ):
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=False,
            content=(
                "Cannot complete this research task yet: the session objective "
                "requires a real structure artifact for execution, but no "
                "structure artifact is present in the workspace."
            ),
            task_id=task.task_id,
            lane_id=invocation.lane_id,
            status="required_structure_artifact_missing",
            summary="Download a real structure artifact before completing research.",
            error_code="required_structure_artifact_missing",
            hint=(
                "Use rcsb_pdb.download_structure with a validated PDB ID, then "
                f"retry {retry_tool}(status='completed')."
            ),
        )
    return None


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
        task = Task.create(
            task_id=task_id,
            session_id=session_id,
            subject=subject,
            description=description,
            priority=priority,
            kind=kind,
            status=status,
            assigned_ref=_normalize_assigned_ref(assigned_ref),
            lane_id=lane_id,
            blocked_by=blocked_by,
            failure_summary=failure_summary,
            failure_ref=failure_ref,
        )
        self.repositories.tasks.save(task)
        self._emit("task.created", {"task_id": task.task_id, "session_id": task.session_id})
        self._emit_task_state(task)
        if task.assigned_ref is not None:
            self._emit(
                "task.assigned",
                {"task_id": task.task_id, "assigned_ref": task.assigned_ref},
            )
        return task

    def update_task(self, task_id: str, mutation: TaskMutation) -> Task:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        updated = Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject if mutation.subject is _UNSET else str(mutation.subject),
            description=task.description if mutation.description is _UNSET else str(mutation.description),
            status=task.status if mutation.status is _UNSET else mutation.status,
            priority=task.priority if mutation.priority is _UNSET else mutation.priority,
            kind=task.kind if mutation.kind is _UNSET else str(mutation.kind),
            assigned_ref=task.assigned_ref
            if mutation.assigned_ref is _UNSET
            else _normalize_assigned_ref(mutation.assigned_ref),
            created_at=task.created_at,
            updated_at=utc_now_iso() if mutation.updated_at is _UNSET else str(mutation.updated_at),
            lane_id=task.lane_id if mutation.lane_id is _UNSET else mutation.lane_id,
            blocked_by=task.blocked_by if mutation.blocked_by is _UNSET else mutation.blocked_by,
            failure_summary=task.failure_summary
            if mutation.failure_summary is _UNSET
            else mutation.failure_summary,
            failure_ref=task.failure_ref if mutation.failure_ref is _UNSET else mutation.failure_ref,
        )
        self.repositories.tasks.save(updated)
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
        return updated

    def get_task(self, task_id: str) -> Task | None:
        return self.repositories.tasks.get(task_id)

    def list_tasks(self, session_id: str, *, lane_id: str | None = None) -> list[Task]:
        if lane_id is None:
            return self.repositories.tasks.list_by_session(session_id)
        return self.repositories.tasks.list_by_lane(session_id, lane_id)

    def list_ready_tasks(self, session_id: str, *, lane_id: str | None = None) -> list[Task]:
        return self.repositories.tasks.list_ready_by_session(session_id, lane_id=lane_id)

    def open_blocker_ids(self, task: Task) -> tuple[str, ...]:
        blockers: list[str] = []
        for blocker_id in task.blocked_by:
            blocker = self.repositories.tasks.get(blocker_id)
            if blocker is None or blocker.status is not TaskStatus.COMPLETED:
                blockers.append(blocker_id)
        return tuple(blockers)

    def select_next_task(self, session_id: str, *, lane_id: str | None = None) -> Task | None:
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

    def build_projection(self, session_id: str, *, lane_id: str | None = None) -> TaskBoardProjection:
        tasks = self.list_tasks(session_id, lane_id=lane_id)
        items = tuple(self._build_items(tasks))
        ready_tasks = tuple(item for item in items if item.bucket is TaskBoardBucket.READY)
        blocked_tasks = tuple(item for item in items if item.bucket is TaskBoardBucket.BLOCKED)
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
        item = next((candidate for candidate in projection.items if candidate.task.task_id == task.task_id), None)
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
    def create_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        arguments = invocation.arguments
        task_id = str(arguments.get("task_id") or f"task_{uuid4().hex[:12]}")
        task = service.create_task(
            session_id=context.snapshot.session.session_id,
            task_id=task_id,
            subject=str(arguments["subject"]),
            description=str(arguments.get("description") or ""),
            priority=TaskPriority(str(arguments.get("priority", TaskPriority.NORMAL.value))),
            kind=str(arguments.get("kind", "general")),
            status=TaskStatus(str(arguments.get("status", TaskStatus.TODO.value))),
            assigned_ref=arguments.get("assigned_ref"),
            lane_id=invocation.lane_id if "lane_id" not in arguments else arguments.get("lane_id"),
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

    def update_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        arguments = invocation.arguments
        task_id = str(arguments["task_id"])
        existing = context.repositories.tasks.get(task_id)
        requested_status = (
            None
            if "status" not in arguments
            else TaskStatus(str(arguments["status"]))
        )
        if existing is not None and requested_status is TaskStatus.COMPLETED:
            required_artifact_error = _required_structure_artifact_error(
                context,
                invocation,
                task=existing,
                retry_tool="task.update",
            )
            if required_artifact_error is not None:
                return required_artifact_error
        mutation = TaskMutation(
            subject=arguments["subject"] if "subject" in arguments else _UNSET,
            description=arguments["description"] if "description" in arguments else _UNSET,
            status=TaskStatus(str(arguments["status"])) if "status" in arguments else _UNSET,
            priority=TaskPriority(str(arguments["priority"])) if "priority" in arguments else _UNSET,
            kind=arguments["kind"] if "kind" in arguments else _UNSET,
            assigned_ref=arguments["assigned_ref"] if "assigned_ref" in arguments else _UNSET,
            lane_id=arguments["lane_id"] if "lane_id" in arguments else _UNSET,
            blocked_by=tuple(str(item) for item in arguments["blocked_by"]) if "blocked_by" in arguments else _UNSET,
            failure_summary=arguments["failure_summary"] if "failure_summary" in arguments else _UNSET,
            failure_ref=arguments["failure_ref"] if "failure_ref" in arguments else _UNSET,
            updated_at=str(arguments["updated_at"]) if "updated_at" in arguments else _UNSET,
        )
        task = service.update_task(task_id, mutation)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(task.to_dict(), sort_keys=True),
            task_id=task.task_id,
            lane_id=invocation.lane_id,
        )

    def finish_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        arguments = invocation.arguments
        task_id = str(arguments["task_id"])
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
        if task.status.is_terminal:
            return _finish_error_result(
                invocation,
                status="task_already_terminal",
                summary=(
                    f"task.finish refused: task {task_id!r} is already "
                    f"{task.status.value} and no reopen/retry mechanism was requested."
                ),
                hint="Use an explicit reopen/retry workflow before finishing a terminal task again.",
                details={"task_id": task_id, "current_status": task.status.value},
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
        evidence_refs, evidence_error = _coerce_evidence_refs(arguments.get("evidence_refs"))
        if evidence_error is not None:
            return _finish_error_result(
                invocation,
                status="invalid_task_finish_evidence_refs",
                summary=evidence_error,
                details={"task_id": task_id},
            )
        evidence_validation_error = _validate_evidence_refs(
            context.repositories,
            session_id=context.snapshot.session.session_id,
            evidence_refs=evidence_refs,
        )
        if evidence_validation_error is not None:
            return _finish_error_result(
                invocation,
                status="invalid_task_finish_evidence_refs",
                summary=evidence_validation_error,
                details={"task_id": task_id, "evidence_refs": list(evidence_refs)},
            )
        if status is TaskStatus.COMPLETED:
            required_artifact_error = _required_structure_artifact_error(
                context,
                invocation,
                task=task,
                retry_tool="task.finish",
            )
            if required_artifact_error is not None:
                return required_artifact_error

        now = utc_now_iso()
        finish_ref = f"task_finish_{uuid4().hex[:12]}"
        finish_payload = {
            "task_id": task.task_id,
            "status": status.value,
            "summary": summary,
            "evidence_refs": list(evidence_refs),
            "failure_summary": failure_summary,
            "failure_ref": failure_ref,
            "blocked_reason": blocked_reason,
            "recovery_hint": recovery_hint,
            "next_owner": next_owner,
            "finished_by": context.agent_id or context.actor_kind or "harness",
            "correlation_id": context.correlation_id,
            "signal_id": context.signal_id,
        }
        context.repositories.engine_documents.save(
            EngineDocumentRecord(
                document_id=finish_ref,
                session_id=context.snapshot.session.session_id,
                document_kind="task_finish",
                payload=finish_payload,
                created_at=now,
                updated_at=now,
            )
        )
        task = service.update_task(
            task.task_id,
            TaskMutation(
                status=status,
                failure_summary=failure_summary
                if status is TaskStatus.FAILED
                else _UNSET,
                failure_ref=failure_ref if status is TaskStatus.FAILED else _UNSET,
            ),
        )
        context.emit(
            "task.finished",
            {
                "task_id": task.task_id,
                "status": task.status.value,
                "summary": summary,
                "finish_ref": finish_ref,
                "evidence_refs": list(evidence_refs),
                "next_owner": next_owner,
            },
        )
        payload = {
            "task": task.to_dict(),
            "finish_ref": finish_ref,
            **finish_payload,
        }
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
                "evidence_refs": list(evidence_refs),
                "next_owner": next_owner,
            },
            terminal_action="task.finish",
            terminates_turn=True,
        )

    def get_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        task = service.get_task(str(invocation.arguments["task_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=task is not None,
            content=json.dumps(None if task is None else task.to_dict(), sort_keys=True),
            task_id=None if task is None else task.task_id,
            lane_id=invocation.lane_id,
        )

    def list_tasks_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        lane_id = invocation.arguments.get("lane_id", invocation.lane_id)
        projection = service.build_projection(context.snapshot.session.session_id, lane_id=lane_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(projection.to_dict(), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def next_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = TaskBoardService(context.repositories, event_emitter=context.emit)
        lane_id = invocation.arguments.get("lane_id", invocation.lane_id)
        task = service.select_next_task(context.snapshot.session.session_id, lane_id=lane_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=task is not None,
            content=json.dumps(None if task is None else task.to_dict(), sort_keys=True),
            task_id=None if task is None else task.task_id,
            lane_id=invocation.lane_id,
        )

    registry.register("task.create", create_task_handler)
    registry.register("task.update", update_task_handler)
    registry.register("task.finish", finish_task_handler)
    registry.register("task.get", get_task_handler)
    registry.register("task.list", list_tasks_handler)
    registry.register("task.next", next_task_handler)
