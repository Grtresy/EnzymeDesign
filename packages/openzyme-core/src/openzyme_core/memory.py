from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any
from uuid import uuid4

from openzyme_domain import AgentMember
from openzyme_domain import ApprovalRequest
from openzyme_domain import EngineInvocation
from openzyme_domain import InboxMessage
from openzyme_domain import Lane
from openzyme_domain import MemoryEntry
from openzyme_domain import MemoryKind
from openzyme_domain import MemoryScopeKind
from openzyme_domain import Session
from openzyme_domain import Task
from openzyme_domain.control_plane import utc_now_iso

from .repositories import CoreRepositories
from .skills import SkillDocument
from .skills import SkillRegistry


def _new_memory_id() -> str:
    return f"mem_{uuid4().hex[:12]}"


@dataclass(frozen=True, slots=True)
class ScopedMemorySummary:
    scope_kind: MemoryScopeKind
    scope_ref: str
    continuity: MemoryEntry | None
    compaction: MemoryEntry | None
    entries: tuple[MemoryEntry, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "scope_kind": self.scope_kind.value,
            "scope_ref": self.scope_ref,
            "continuity": None if self.continuity is None else self.continuity.to_dict(),
            "compaction": None if self.compaction is None else self.compaction.to_dict(),
            "entries": [entry.to_dict() for entry in self.entries],
        }


@dataclass(frozen=True, slots=True)
class SessionRestoreContext:
    session: Session
    tasks: tuple[Task, ...]
    ready_tasks: tuple[Task, ...]
    lanes: tuple[Lane, ...]
    pending_approvals: tuple[ApprovalRequest, ...]
    inbox: tuple[InboxMessage, ...]
    agents: tuple[AgentMember, ...]
    active_invocations: tuple[EngineInvocation, ...]
    session_memory: ScopedMemorySummary
    lane_memory: ScopedMemorySummary | None
    task_memory: ScopedMemorySummary | None
    skill_documents: tuple[SkillDocument, ...]
    focused_lane_id: str | None
    focused_task_id: str | None

    def to_dict(self) -> dict[str, Any]:
        return {
            "session": self.session.to_dict(),
            "tasks": [task.to_dict() for task in self.tasks],
            "ready_tasks": [task.to_dict() for task in self.ready_tasks],
            "lanes": [lane.to_dict() for lane in self.lanes],
            "pending_approvals": [approval.to_dict() for approval in self.pending_approvals],
            "inbox": [message.to_dict() for message in self.inbox],
            "agents": [agent.to_dict() for agent in self.agents],
            "active_invocations": [invocation.to_dict() for invocation in self.active_invocations],
            "session_memory": self.session_memory.to_dict(),
            "lane_memory": None if self.lane_memory is None else self.lane_memory.to_dict(),
            "task_memory": None if self.task_memory is None else self.task_memory.to_dict(),
            "skill_documents": [skill.to_dict() for skill in self.skill_documents],
            "focused_lane_id": self.focused_lane_id,
            "focused_task_id": self.focused_task_id,
        }


@dataclass(slots=True)
class MemoryService:
    repositories: CoreRepositories
    event_emitter: Any | None = None

    def list_scope_entries(
        self,
        session_id: str,
        scope_kind: MemoryScopeKind,
        scope_ref: str,
    ) -> tuple[MemoryEntry, ...]:
        return tuple(self.repositories.memory.list_by_scope(session_id, scope_kind, scope_ref))

    def summarize_scope(
        self,
        session_id: str,
        scope_kind: MemoryScopeKind,
        scope_ref: str,
    ) -> ScopedMemorySummary:
        entries = self.list_scope_entries(session_id, scope_kind, scope_ref)
        continuity = None
        compaction = None
        for entry in entries:
            if entry.kind is MemoryKind.CONTINUITY:
                continuity = entry
            if entry.kind is MemoryKind.COMPACTION:
                compaction = entry
        return ScopedMemorySummary(
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            continuity=continuity,
            compaction=compaction,
            entries=entries,
        )

    def record_memory(
        self,
        *,
        session_id: str,
        scope_kind: MemoryScopeKind,
        scope_ref: str,
        kind: MemoryKind,
        summary: str,
        source_range: str | None = None,
        importance: int = 5,
        memory_id: str | None = None,
    ) -> MemoryEntry:
        memory = MemoryEntry(
            memory_id=memory_id or _new_memory_id(),
            session_id=session_id,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            kind=kind,
            summary=summary,
            source_range=source_range,
            importance=importance,
            created_at=utc_now_iso(),
        )
        self.repositories.memory.save(memory)
        self._emit(
            "memory.recorded",
            {
                "memory_id": memory.memory_id,
                "scope_kind": memory.scope_kind.value,
                "scope_ref": memory.scope_ref,
                "kind": memory.kind.value,
            },
        )
        if kind is MemoryKind.COMPACTION:
            self._emit(
                "memory.compacted",
                {
                    "memory_id": memory.memory_id,
                    "scope_kind": memory.scope_kind.value,
                    "scope_ref": memory.scope_ref,
                },
            )
        return memory

    def record_continuity(
        self,
        *,
        session_id: str,
        scope_kind: MemoryScopeKind,
        scope_ref: str,
        summary: str,
        source_range: str | None = None,
        importance: int = 6,
        memory_id: str | None = None,
    ) -> MemoryEntry:
        return self.record_memory(
            session_id=session_id,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            kind=MemoryKind.CONTINUITY,
            summary=summary,
            source_range=source_range,
            importance=importance,
            memory_id=memory_id,
        )

    def compact_scope(
        self,
        *,
        session_id: str,
        scope_kind: MemoryScopeKind,
        scope_ref: str,
        summary: str,
        source_range: str | None = None,
        importance: int = 8,
        memory_id: str | None = None,
    ) -> MemoryEntry:
        return self.record_memory(
            session_id=session_id,
            scope_kind=scope_kind,
            scope_ref=scope_ref,
            kind=MemoryKind.COMPACTION,
            summary=summary,
            source_range=source_range,
            importance=importance,
            memory_id=memory_id,
        )

    def render_compaction_summary(
        self,
        restore_context: SessionRestoreContext,
        *,
        recent_output: str | None = None,
        recent_tool_result: Any | None = None,
    ) -> str:
        ready_task_ids = ", ".join(task.task_id for task in restore_context.ready_tasks) or "none"
        approval_ids = ", ".join(approval.approval_id for approval in restore_context.pending_approvals) or "none"
        invocation_ids = ", ".join(invocation.invocation_id for invocation in restore_context.active_invocations) or "none"
        skill_keys = ", ".join(skill.skill_key for skill in restore_context.skill_documents) or "none"
        focus_bits: list[str] = []
        if restore_context.focused_task_id is not None:
            focus_bits.append(f"task={restore_context.focused_task_id}")
        if restore_context.focused_lane_id is not None:
            focus_bits.append(f"lane={restore_context.focused_lane_id}")
        focus = ", ".join(focus_bits) or "none"
        continuity = restore_context.session_memory.continuity.summary if restore_context.session_memory.continuity else "none"
        recent_tool_summary = "none"
        if recent_tool_result is not None:
            recent_tool_summary = f"{recent_tool_result.tool_name}:{recent_tool_result.content}"
        lines = [
            f"Session {restore_context.session.session_id}: {restore_context.session.title}",
            f"Objective: {restore_context.session.objective}",
            f"Focus: {focus}",
            f"Session continuity: {continuity}",
            f"Ready tasks: {ready_task_ids}",
            f"Pending approvals: {approval_ids}",
            f"Active invocations: {invocation_ids}",
            f"Active skills: {skill_keys}",
            f"Recent output: {recent_output or 'none'}",
            f"Recent tool activity: {recent_tool_summary}",
        ]
        if restore_context.lane_memory and restore_context.lane_memory.continuity is not None:
            lines.append(f"Lane continuity: {restore_context.lane_memory.continuity.summary}")
        if restore_context.task_memory and restore_context.task_memory.entries:
            lines.append(f"Task memory entries: {', '.join(entry.memory_id for entry in restore_context.task_memory.entries)}")
        return "\n".join(lines)

    def build_restore_context(
        self,
        session_id: str,
        *,
        lane_id: str | None = None,
        task_id: str | None = None,
        skill_keys: tuple[str, ...] = (),
        skill_registry: SkillRegistry | None = None,
    ) -> SessionRestoreContext:
        session = self.repositories.sessions.get(session_id)
        if session is None:
            raise ValueError(f"session {session_id!r} does not exist")
        if task_id is not None:
            task = self.repositories.tasks.get(task_id)
            if task is None:
                raise ValueError(f"task {task_id!r} does not exist")
            if task.session_id != session_id:
                raise ValueError(f"task {task_id!r} belongs to session {task.session_id!r}, not {session_id!r}")
            if lane_id is None:
                lane_id = task.lane_id
        if lane_id is not None:
            lane = self.repositories.lanes.get(lane_id)
            if lane is None:
                raise ValueError(f"lane {lane_id!r} does not exist")
            if lane.session_id != session_id:
                raise ValueError(f"lane {lane_id!r} belongs to session {lane.session_id!r}, not {session_id!r}")
        session_memory = self.summarize_scope(session_id, MemoryScopeKind.SESSION, session_id)
        lane_memory = None if lane_id is None else self.summarize_scope(session_id, MemoryScopeKind.LANE, lane_id)
        task_memory = None if task_id is None else self.summarize_scope(session_id, MemoryScopeKind.TASK, task_id)
        registry = skill_registry
        skill_documents: tuple[SkillDocument, ...] = ()
        if skill_keys:
            registry = registry or SkillRegistry()
            skill_documents = registry.load_skills(skill_keys)
        return SessionRestoreContext(
            session=session,
            tasks=tuple(self.repositories.tasks.list_by_session(session_id)),
            ready_tasks=tuple(self.repositories.tasks.list_ready_by_session(session_id, lane_id=lane_id)),
            lanes=tuple(self.repositories.lanes.list_by_session(session_id)),
            pending_approvals=tuple(self.repositories.approvals.list_pending_by_session(session_id)),
            inbox=tuple(self.repositories.inbox.list_by_session(session_id)),
            agents=tuple(self.repositories.agents.list_by_session(session_id)),
            active_invocations=tuple(self.repositories.invocations.list_active_by_session(session_id)),
            session_memory=session_memory,
            lane_memory=lane_memory,
            task_memory=task_memory,
            skill_documents=skill_documents,
            focused_lane_id=lane_id,
            focused_task_id=task_id,
        )

    def _emit(self, event_type: str, payload: dict[str, object]) -> None:
        if self.event_emitter is not None:
            self.event_emitter(event_type, payload)


def register_memory_tools(registry: Any) -> None:
    from .harness import SessionRuntimeContext
    from .harness import ToolInvocation
    from .harness import ToolResult

    def compact_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        service = MemoryService(context.repositories, event_emitter=lambda event_type, payload: context.emit(event_type, payload))
        scope_kind = MemoryScopeKind(str(invocation.arguments.get("scope_kind", "session")))
        task_id = None if "task_id" not in invocation.arguments else str(invocation.arguments["task_id"])
        lane_id = None if "lane_id" not in invocation.arguments else str(invocation.arguments["lane_id"])
        if task_id is not None and lane_id is None:
            task = context.repositories.tasks.get(task_id)
            if task is None:
                raise ValueError(f"task {task_id!r} does not exist")
            lane_id = task.lane_id
        scope_ref = invocation.arguments.get("scope_ref")
        if scope_ref is None:
            if scope_kind is MemoryScopeKind.SESSION:
                scope_ref = context.snapshot.session.session_id
            elif scope_kind is MemoryScopeKind.LANE:
                scope_ref = lane_id or context.restore_focus.lane_id
            else:
                scope_ref = task_id or context.restore_focus.task_id
        if scope_ref is None:
            raise ValueError(f"scope_ref is required for scope_kind={scope_kind.value!r}")
        restore_context = service.build_restore_context(
            context.snapshot.session.session_id,
            lane_id=lane_id or context.restore_focus.lane_id,
            task_id=task_id or context.restore_focus.task_id,
            skill_keys=context.active_skill_keys,
            skill_registry=context.skill_registry,
        )
        summary = invocation.arguments.get("summary")
        if summary is None:
            summary = service.render_compaction_summary(restore_context)
        memory = service.compact_scope(
            session_id=context.snapshot.session.session_id,
            scope_kind=scope_kind,
            scope_ref=str(scope_ref),
            summary=str(summary),
            source_range=f"tool:{invocation.call_id}",
        )
        context.refresh()
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(memory.to_dict(), sort_keys=True),
            task_id=task_id or invocation.task_id,
            lane_id=lane_id or invocation.lane_id,
        )

    registry.register("memory.compact", compact_handler)


__all__ = ["MemoryService", "ScopedMemorySummary", "SessionRestoreContext", "register_memory_tools"]
