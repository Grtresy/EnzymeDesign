from __future__ import annotations

from dataclasses import dataclass
from typing import Any
from typing import Protocol


@dataclass(frozen=True, slots=True)
class EngineDescriptor:
    engine_name: str
    tool_names: tuple[str, ...]
    input_schema: dict[str, Any]
    output_schema: dict[str, Any]
    requires_approval: bool
    supports_background: bool
    idempotency_key_shape: str
    produces_file_types: tuple[str, ...]
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
            "produces_file_types": list(self.produces_file_types),
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


@dataclass(frozen=True, slots=True)
class EngineDocumentRecord:
    document_id: str
    session_id: str
    document_kind: str
    payload: dict[str, Any]
    created_at: str
    updated_at: str
    invocation_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "document_id": self.document_id,
            "session_id": self.session_id,
            "invocation_id": self.invocation_id,
            "document_kind": self.document_kind,
            "payload": self.payload,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


__all__ = [
    "CapabilityEngine",
    "EngineDescriptor",
    "EngineDocumentRecord",
    "EngineRegistry",
]
