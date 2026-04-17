from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import json
from typing import Any

from openzyme_domain import Task
from openzyme_domain import TaskPriority
from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import CoreRepositories

_UNSET = object()
_PRIORITY_ORDER = {
    TaskPriority.URGENT: 0,
    TaskPriority.HIGH: 1,
    TaskPriority.NORMAL: 2,
    TaskPriority.LOW: 3,
}


class TaskBoardBucket(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class TaskMutation:
    subject: str | object = _UNSET
    description: str | object = _UNSET
    status: TaskStatus | object = _UNSET
    priority: TaskPriority | object = _UNSET
    kind: str | object = _UNSET
    assigned_ref: str | None | object = _UNSET
    blocked_by: tuple[str, ...] | object = _UNSET
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
    items: tuple[TaskBoardItem, ...]
    ready_tasks: tuple[TaskBoardItem, ...]
    blocked_tasks: tuple[TaskBoardItem, ...]
    next_task_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
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
        blocked_by: tuple[str, ...] = (),
    ) -> Task:
        task = Task.create(
            task_id=task_id,
            session_id=session_id,
            subject=subject,
            description=description,
            priority=priority,
            kind=kind,
            status=status,
            assigned_ref=assigned_ref,
            blocked_by=blocked_by,
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
            assigned_ref=task.assigned_ref if mutation.assigned_ref is _UNSET else mutation.assigned_ref,
            created_at=task.created_at,
            updated_at=utc_now_iso() if mutation.updated_at is _UNSET else str(mutation.updated_at),
            blocked_by=task.blocked_by if mutation.blocked_by is _UNSET else mutation.blocked_by,
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

    def list_tasks(self, session_id: str) -> list[Task]:
        return self.repositories.tasks.list_by_session(session_id)

    def list_ready_tasks(self, session_id: str) -> list[Task]:
        return self.repositories.tasks.list_ready_by_session(session_id)

    def select_next_task(self, session_id: str) -> Task | None:
        ready_tasks = self.list_ready_tasks(session_id)
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

    def build_projection(self, session_id: str) -> TaskBoardProjection:
        tasks = self.list_tasks(session_id)
        items = tuple(self._build_items(tasks))
        ready_tasks = tuple(item for item in items if item.bucket is TaskBoardBucket.READY)
        blocked_tasks = tuple(item for item in items if item.bucket is TaskBoardBucket.BLOCKED)
        next_task = self.select_next_task(session_id)
        return TaskBoardProjection(
            session_id=session_id,
            items=items,
            ready_tasks=ready_tasks,
            blocked_tasks=blocked_tasks,
            next_task_id=None if next_task is None else next_task.task_id,
        )

    def _build_items(self, tasks: list[Task]) -> list[TaskBoardItem]:
        task_map = {task.task_id: task for task in tasks}
        items: list[TaskBoardItem] = []
        for task in tasks:
            open_blockers = tuple(
                blocker_id
                for blocker_id in task.blocked_by
                if blocker_id in task_map and not task_map[blocker_id].status.is_terminal
            )
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
        task = service.create_task(
            session_id=context.snapshot.session.session_id,
            task_id=str(arguments["task_id"]),
            subject=str(arguments["subject"]),
            description=str(arguments["description"]),
            priority=TaskPriority(str(arguments.get("priority", TaskPriority.NORMAL.value))),
            kind=str(arguments.get("kind", "general")),
            status=TaskStatus(str(arguments.get("status", TaskStatus.TODO.value))),
            assigned_ref=arguments.get("assigned_ref"),
            blocked_by=tuple(str(item) for item in arguments.get("blocked_by", ())),
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
        mutation = TaskMutation(
            subject=arguments["subject"] if "subject" in arguments else _UNSET,
            description=arguments["description"] if "description" in arguments else _UNSET,
            status=TaskStatus(str(arguments["status"])) if "status" in arguments else _UNSET,
            priority=TaskPriority(str(arguments["priority"])) if "priority" in arguments else _UNSET,
            kind=arguments["kind"] if "kind" in arguments else _UNSET,
            assigned_ref=arguments["assigned_ref"] if "assigned_ref" in arguments else _UNSET,
            blocked_by=tuple(str(item) for item in arguments["blocked_by"]) if "blocked_by" in arguments else _UNSET,
            updated_at=str(arguments["updated_at"]) if "updated_at" in arguments else _UNSET,
        )
        task = service.update_task(str(arguments["task_id"]), mutation)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(task.to_dict(), sort_keys=True),
            task_id=task.task_id,
            lane_id=invocation.lane_id,
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
        projection = service.build_projection(context.snapshot.session.session_id)
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
        task = service.select_next_task(context.snapshot.session.session_id)
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
    registry.register("task.get", get_task_handler)
    registry.register("task.list", list_tasks_handler)
    registry.register("task.next", next_task_handler)
