from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from typing import Any
from typing import Protocol

from openzyme_domain import TaskStatus
from openzyme_domain.control_plane import utc_now_iso


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    engine_name: str
    tool_names: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    requires_approval: bool
    supports_background: bool
    idempotency_key_shape: str
    produces_artifact_types: tuple[str, ...]
    capability_key: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "engine_name": self.engine_name,
            "tool_names": list(self.tool_names),
            "input_schema": self.input_schema,
            "output_schema": self.output_schema,
            "requires_approval": self.requires_approval,
            "supports_background": self.supports_background,
            "idempotency_key_shape": self.idempotency_key_shape,
            "produces_artifact_types": list(self.produces_artifact_types),
            "capability_key": self.capability_key,
        }


class CapabilityEngine(Protocol):
    @property
    def descriptor(self) -> EngineDescriptor: ...

    def register_tools(self, registry: Any) -> None: ...


@dataclass(slots=True)
class EngineRegistry:
    _engines: dict[str, CapabilityEngine]

    def __init__(self) -> None:
        self._engines = {}

    def register(self, engine: CapabilityEngine) -> None:
        self._engines[engine.descriptor.engine_name] = engine

    def get(self, engine_name: str) -> CapabilityEngine | None:
        return self._engines.get(engine_name)

    def require(self, engine_name: str) -> CapabilityEngine:
        engine = self.get(engine_name)
        if engine is None:
            raise KeyError(f"unknown engine: {engine_name}")
        return engine

    def list_descriptors(self) -> tuple[EngineDescriptor, ...]:
        return tuple(engine.descriptor for engine in self._engines.values())

    def list_engines(self) -> tuple[CapabilityEngine, ...]:
        return tuple(self._engines.values())


@dataclass(slots=True)
class DeepResearchTaskPlanner:
    engine_tool_name: str = "deep_research.start"

    def plan_task(self, context: Any) -> Any | None:
        from .harness import HarnessStep
        from .harness import RestoreFocus
        from .harness import ToolInvocation

        ready_tasks = [task for task in context.snapshot.ready_tasks if task.kind == "research"]
        if not ready_tasks:
            return None
        active_task_ids = {
            invocation.task_id
            for invocation in context.snapshot.active_invocations
            if invocation.engine_name == "deep_research" and invocation.task_id is not None
        }
        task = next((candidate for candidate in ready_tasks if candidate.task_id not in active_task_ids), None)
        if task is None:
            return None
        brief = self._build_brief(context, task)
        return HarnessStep(
            tool_invocations=(
                ToolInvocation(
                    call_id=f"call_research_{task.task_id}",
                    tool_name=self.engine_tool_name,
                    arguments={"task_id": task.task_id, "brief": brief},
                    task_id=task.task_id,
                    lane_id=task.lane_id,
                ),
            ),
            task_updates=(
                replace(
                    task,
                    status=TaskStatus.IN_PROGRESS,
                    updated_at=utc_now_iso(),
                ),
            ),
            next_focus=RestoreFocus(task_id=task.task_id, lane_id=task.lane_id),
        )

    def _build_brief(self, context: Any, task: Any) -> str:
        continuity = None
        if getattr(context, "restore_context", None) is not None:
            continuity_entry = context.restore_context.session_memory.continuity
            continuity = None if continuity_entry is None else continuity_entry.summary
        lines = [
            f"Session objective: {context.snapshot.session.objective}",
            f"Task subject: {task.subject}",
            f"Task description: {task.description}",
        ]
        if continuity:
            lines.append(f"Session continuity: {continuity}")
        return "\n".join(lines)


__all__ = ["CapabilityEngine", "DeepResearchTaskPlanner", "EngineDescriptor", "EngineRegistry"]
