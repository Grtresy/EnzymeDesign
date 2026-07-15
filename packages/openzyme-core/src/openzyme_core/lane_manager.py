from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import uuid4

from openzyme_domain import Lane
from openzyme_domain import LaneStatus
from openzyme_domain import Task
from openzyme_domain.control_plane import utc_now_iso

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult
from .repositories import CoreRepositories
from .repositories import TaskWriteIntent
from .repositories import LaneLifecycleEventRecord


def _new_event_id() -> str:
    return f"lane_evt_{uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class LaneProjectionItem:
    lane: Lane
    tasks: tuple[Task, ...]
    ready_task_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "lane": self.lane.to_dict(),
            "tasks": [task.to_dict() for task in self.tasks],
            "ready_task_ids": list(self.ready_task_ids),
        }


@dataclass(frozen=True, slots=True)
class LaneProjection:
    session_id: str
    lanes: tuple[LaneProjectionItem, ...]
    unassigned_tasks: tuple[Task, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "session_id": self.session_id,
            "lanes": [item.to_dict() for item in self.lanes],
            "unassigned_tasks": [task.to_dict() for task in self.unassigned_tasks],
        }


@dataclass(slots=True)
class LaneManager:
    repositories: CoreRepositories
    event_emitter: Any | None = None

    def create_lane(
        self,
        *,
        session_id: str,
        lane_id: str,
        name: str,
        cwd: str,
        branch_name: str | None = None,
    ) -> Lane:
        now = utc_now_iso()
        lane = Lane(
            lane_id=lane_id,
            session_id=session_id,
            name=name,
            status=LaneStatus.IDLE,
            cwd=cwd,
            branch_name=branch_name,
            claimed_ref=None,
            created_at=now,
            updated_at=now,
        )
        self.repositories.lanes.save(lane)
        self._record("lane.created", lane=lane, task_id=None, payload={"name": lane.name, "cwd": lane.cwd})
        return lane

    def claim_lane(self, lane_id: str, *, claimed_ref: str) -> Lane:
        lane = self._require_lane(lane_id)
        updated = Lane(
            lane_id=lane.lane_id,
            session_id=lane.session_id,
            name=lane.name,
            status=LaneStatus.CLAIMED,
            cwd=lane.cwd,
            branch_name=lane.branch_name,
            claimed_ref=claimed_ref,
            created_at=lane.created_at,
            updated_at=utc_now_iso(),
        )
        self.repositories.lanes.save(updated)
        self._record(
            "lane.claimed",
            lane=updated,
            task_id=None,
            payload={"claimed_ref": claimed_ref},
        )
        return updated

    def keep_lane(self, lane_id: str) -> Lane:
        lane = self._require_lane(lane_id)
        updated = Lane(
            lane_id=lane.lane_id,
            session_id=lane.session_id,
            name=lane.name,
            status=LaneStatus.RELEASED,
            cwd=lane.cwd,
            branch_name=lane.branch_name,
            claimed_ref=None,
            created_at=lane.created_at,
            updated_at=utc_now_iso(),
        )
        self.repositories.lanes.save(updated)
        self._record("lane.released", lane=updated, task_id=None, payload={})
        return updated

    def remove_lane(self, lane_id: str) -> Lane:
        lane = self._require_lane(lane_id)
        for task in self.repositories.tasks.list_by_lane(lane.session_id, lane.lane_id):
            if task.status.is_terminal:
                continue
            updated_task = self._copy_task(task, lane_id=None)
            self.repositories.tasks.save(
                updated_task,
                intent=TaskWriteIntent.EDIT,
            )
            self._record(
                "task.unbound_from_lane",
                lane=lane,
                task_id=task.task_id,
                payload={"task_id": task.task_id},
            )
            self._emit("task.unbound_from_lane", {"task_id": task.task_id, "lane_id": lane.lane_id})
        updated = Lane(
            lane_id=lane.lane_id,
            session_id=lane.session_id,
            name=lane.name,
            status=LaneStatus.REMOVED,
            cwd=lane.cwd,
            branch_name=lane.branch_name,
            claimed_ref=None,
            created_at=lane.created_at,
            updated_at=utc_now_iso(),
        )
        self.repositories.lanes.save(updated)
        self._record("lane.removed", lane=updated, task_id=None, payload={})
        return updated

    def bind_task_to_lane(self, task_id: str, lane_id: str) -> Task:
        task = self._require_task(task_id)
        lane = self._require_lane(lane_id)
        if lane.status is LaneStatus.REMOVED:
            raise ValueError(f"lane {lane_id!r} has been removed")
        updated = self._copy_task(task, lane_id=lane.lane_id)
        self.repositories.tasks.save(updated, intent=TaskWriteIntent.EDIT)
        self._record(
            "task.bound_to_lane",
            lane=lane,
            task_id=task.task_id,
            payload={"task_id": task.task_id},
        )
        self._emit("task.bound_to_lane", {"task_id": task.task_id, "lane_id": lane.lane_id})
        return updated

    def unbind_task_from_lane(self, task_id: str) -> Task:
        task = self._require_task(task_id)
        if task.lane_id is None:
            return task
        lane = self._require_lane(task.lane_id)
        updated = self._copy_task(task, lane_id=None)
        self.repositories.tasks.save(updated, intent=TaskWriteIntent.EDIT)
        self._record(
            "task.unbound_from_lane",
            lane=lane,
            task_id=task.task_id,
            payload={"task_id": task.task_id},
        )
        self._emit("task.unbound_from_lane", {"task_id": task.task_id, "lane_id": lane.lane_id})
        return updated

    def build_projection(self, session_id: str) -> LaneProjection:
        lane_items: list[LaneProjectionItem] = []
        for lane in self.repositories.lanes.list_by_session(session_id):
            tasks = tuple(self.repositories.tasks.list_by_lane(session_id, lane.lane_id))
            ready_task_ids = tuple(
                task.task_id for task in self.repositories.tasks.list_ready_by_session(session_id, lane_id=lane.lane_id)
            )
            lane_items.append(LaneProjectionItem(lane=lane, tasks=tasks, ready_task_ids=ready_task_ids))
        unassigned = tuple(self.repositories.tasks.list_unassigned_by_session(session_id))
        return LaneProjection(session_id=session_id, lanes=tuple(lane_items), unassigned_tasks=unassigned)

    def _copy_task(self, task: Task, *, lane_id: str | None) -> Task:
        return Task(
            task_id=task.task_id,
            session_id=task.session_id,
            subject=task.subject,
            description=task.description,
            status=task.status,
            priority=task.priority,
            kind=task.kind,
            assigned_ref=task.assigned_ref,
            created_at=task.created_at,
            updated_at=utc_now_iso(),
            lane_id=lane_id,
            blocked_by=task.blocked_by,
        )

    def _require_lane(self, lane_id: str) -> Lane:
        lane = self.repositories.lanes.get(lane_id)
        if lane is None:
            raise ValueError(f"lane {lane_id!r} does not exist")
        return lane

    def _require_task(self, task_id: str) -> Task:
        task = self.repositories.tasks.get(task_id)
        if task is None:
            raise ValueError(f"task {task_id!r} does not exist")
        return task

    def _record(self, event_type: str, *, lane: Lane, task_id: str | None, payload: dict[str, object]) -> None:
        event = LaneLifecycleEventRecord(
            event_id=_new_event_id(),
            session_id=lane.session_id,
            lane_id=lane.lane_id,
            task_id=task_id,
            event_type=event_type,
            created_at=utc_now_iso(),
            payload=payload,
        )
        self.repositories.lane_events.save(event)
        self._emit(event_type, {"lane_id": lane.lane_id, "task_id": task_id, **payload})

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


def register_lane_tools(registry: ToolRegistry) -> None:
    def create_lane_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        lane = manager.create_lane(
            session_id=context.snapshot.session.session_id,
            lane_id=str(invocation.arguments["lane_id"]),
            name=str(invocation.arguments["name"]),
            cwd=str(invocation.arguments["cwd"]),
            branch_name=None if "branch_name" not in invocation.arguments else str(invocation.arguments["branch_name"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(lane.to_dict(), sort_keys=True),
            lane_id=lane.lane_id,
        )

    def claim_lane_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        lane = manager.claim_lane(
            str(invocation.arguments["lane_id"]),
            claimed_ref=str(invocation.arguments.get("claimed_ref", "harness")),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(lane.to_dict(), sort_keys=True),
            lane_id=lane.lane_id,
        )

    def keep_lane_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        lane = manager.keep_lane(str(invocation.arguments["lane_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(lane.to_dict(), sort_keys=True),
            lane_id=lane.lane_id,
        )

    def remove_lane_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        lane = manager.remove_lane(str(invocation.arguments["lane_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(lane.to_dict(), sort_keys=True),
            lane_id=lane.lane_id,
        )

    def bind_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        task = manager.bind_task_to_lane(
            str(invocation.arguments["task_id"]),
            str(invocation.arguments["lane_id"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(task.to_dict(), sort_keys=True),
            task_id=task.task_id,
            lane_id=task.lane_id,
        )

    def unbind_task_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        task = manager.unbind_task_from_lane(str(invocation.arguments["task_id"]))
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(task.to_dict(), sort_keys=True),
            task_id=task.task_id,
            lane_id=task.lane_id,
        )

    def list_lane_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        manager = LaneManager(context.repositories, event_emitter=context.emit)
        projection = manager.build_projection(context.snapshot.session.session_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(projection.to_dict(), sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    registry.register("lane.create", create_lane_handler)
    registry.register("lane.claim", claim_lane_handler)
    registry.register("lane.keep", keep_lane_handler)
    registry.register("lane.remove", remove_lane_handler)
    registry.register("lane.bind_task", bind_task_handler)
    registry.register("lane.unbind_task", unbind_task_handler)
    registry.register("lane.list", list_lane_handler)
