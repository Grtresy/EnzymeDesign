from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import ClassVar

from .identity import JsonValue
from .identity import canonical_json_bytes
from .identity import canonical_sha256_digest
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_identifier


RUNTIME_CONTEXT_SECTION_SCHEMA_VERSION = "runtime_context_section@1"
RUNTIME_TURN_CONTEXT_SCHEMA_VERSION = "runtime_turn_context@1"


class RuntimeContextSectionKind(StrEnum):
    SESSION = "session"
    AGENT = "agent"
    TASK_BOARD = "task_board"
    LANE_WORKSPACE = "lane_workspace"
    INBOX_PROTOCOL = "inbox_protocol"
    APPROVAL_CONTINUATION = "approval_continuation"
    FAILURE = "failure"
    WORKFLOW_AUTHORITY = "workflow_authority"
    CAPABILITY_EXPOSURE = "capability_exposure"
    TRANSCRIPT = "transcript"
    TRUNCATION = "truncation"


@dataclass(frozen=True, slots=True)
class RuntimeContextSection:
    SCHEMA_VERSION: ClassVar[str] = RUNTIME_CONTEXT_SECTION_SCHEMA_VERSION

    kind: RuntimeContextSectionKind
    items: tuple[Mapping[str, JsonValue], ...]
    omitted_count: int = 0
    next_cursor: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.omitted_count, int) or isinstance(self.omitted_count, bool) or self.omitted_count < 0:
            raise ValueError("runtime context omitted_count must be non-negative")
        frozen_items: list[Mapping[str, JsonValue]] = []
        for item in self.items:
            frozen = freeze_json(item, field_name=f"{self.kind.value}.items")
            if not isinstance(frozen, Mapping):
                raise ValueError("runtime context section items must be JSON objects")
            frozen_items.append(frozen)
        object.__setattr__(self, "items", tuple(frozen_items))
        if self.omitted_count:
            if self.next_cursor is None:
                raise ValueError("truncated context section requires a cursor")
            require_identifier(self.next_cursor, field_name="next_cursor")
        elif self.next_cursor is not None:
            raise ValueError("untruncated context section cannot carry a cursor")

    @property
    def section_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    @property
    def byte_size(self) -> int:
        return len(canonical_json_bytes(self.to_dict(include_digest=False)))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "kind": self.kind.value,
            "items": [json_compatible(item) for item in self.items],
            "item_count": len(self.items),
            "omitted_count": self.omitted_count,
            "next_cursor": self.next_cursor,
        }
        if include_digest:
            payload["byte_size"] = self.byte_size
            payload["section_digest"] = self.section_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeContextSection":
        value = dict(payload)
        supplied_digest = value.pop("section_digest", None)
        supplied_size = value.pop("byte_size", None)
        expected = {
            "schema_version", "kind", "items", "item_count", "omitted_count",
            "next_cursor",
        }
        if set(value) != expected or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("runtime context section has an invalid closed schema")
        items_value = value["items"]
        if not isinstance(items_value, list) or any(not isinstance(item, Mapping) for item in items_value):
            raise ValueError("runtime context section items must be an array of objects")
        if value["item_count"] != len(items_value):
            raise ValueError("runtime context section item count mismatch")
        section = cls(
            kind=RuntimeContextSectionKind(str(value["kind"])),
            items=tuple(dict(item) for item in items_value),
            omitted_count=int(value["omitted_count"]),
            next_cursor=None if value["next_cursor"] is None else str(value["next_cursor"]),
        )
        if supplied_size is not None and supplied_size != section.byte_size:
            raise ValueError("runtime context section byte size mismatch")
        if supplied_digest is not None and supplied_digest != section.section_digest:
            raise ValueError("runtime context section digest mismatch")
        return section


@dataclass(frozen=True, slots=True)
class RuntimeTurnContext:
    SCHEMA_VERSION: ClassVar[str] = RUNTIME_TURN_CONTEXT_SCHEMA_VERSION

    context_id: str
    session_id: str
    agent_id: str
    agent_member_id: str
    turn_id: str
    signal_id: str
    request_lineage_id: str
    sections: tuple[RuntimeContextSection, ...]
    max_bytes: int
    created_at: str
    task_id: str | None = None
    lane_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "context_id", "session_id", "agent_id", "agent_member_id", "turn_id",
            "signal_id", "request_lineage_id", "created_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("task_id", "lane_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if not isinstance(self.max_bytes, int) or isinstance(self.max_bytes, bool) or not 1 <= self.max_bytes <= 1_048_576:
            raise ValueError("runtime context max_bytes must be between 1 and 1048576")
        by_kind = {section.kind: section for section in self.sections}
        if len(by_kind) != len(self.sections) or set(by_kind) != set(RuntimeContextSectionKind):
            raise ValueError("runtime context must contain each closed section exactly once")
        ordered = tuple(by_kind[kind] for kind in RuntimeContextSectionKind)
        object.__setattr__(self, "sections", ordered)
        if self.byte_size > self.max_bytes:
            raise ValueError("runtime context exceeds its admitted byte bound")

    @property
    def byte_size(self) -> int:
        return len(canonical_json_bytes(self.to_dict(include_digest=False)))

    @property
    def context_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def section(self, kind: RuntimeContextSectionKind) -> RuntimeContextSection:
        return next(section for section in self.sections if section.kind is kind)

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "context_id": self.context_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_member_id": self.agent_member_id,
            "turn_id": self.turn_id,
            "signal_id": self.signal_id,
            "request_lineage_id": self.request_lineage_id,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "sections": [section.to_dict() for section in self.sections],
            "max_bytes": self.max_bytes,
            "created_at": self.created_at,
        }
        if include_digest:
            payload["byte_size"] = self.byte_size
            payload["context_digest"] = self.context_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeTurnContext":
        value = dict(payload)
        supplied_digest = value.pop("context_digest", None)
        supplied_size = value.pop("byte_size", None)
        expected = {
            "schema_version", "context_id", "session_id", "agent_id",
            "agent_member_id", "turn_id", "signal_id", "request_lineage_id",
            "task_id", "lane_id", "sections", "max_bytes", "created_at",
        }
        if set(value) != expected or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError("runtime turn context has an invalid closed schema")
        sections_value = value["sections"]
        if not isinstance(sections_value, list) or any(not isinstance(item, Mapping) for item in sections_value):
            raise ValueError("runtime turn context sections must be an array of objects")
        context = cls(
            context_id=str(value["context_id"]), session_id=str(value["session_id"]),
            agent_id=str(value["agent_id"]), agent_member_id=str(value["agent_member_id"]),
            turn_id=str(value["turn_id"]), signal_id=str(value["signal_id"]),
            request_lineage_id=str(value["request_lineage_id"]),
            task_id=None if value["task_id"] is None else str(value["task_id"]),
            lane_id=None if value["lane_id"] is None else str(value["lane_id"]),
            sections=tuple(RuntimeContextSection.from_dict(item) for item in sections_value),
            max_bytes=int(value["max_bytes"]), created_at=str(value["created_at"]),
        )
        if supplied_size is not None and supplied_size != context.byte_size:
            raise ValueError("runtime turn context byte size mismatch")
        if supplied_digest is not None and supplied_digest != context.context_digest:
            raise ValueError("runtime turn context digest mismatch")
        return context


__all__ = [
    "RUNTIME_CONTEXT_SECTION_SCHEMA_VERSION",
    "RUNTIME_TURN_CONTEXT_SCHEMA_VERSION",
    "RuntimeContextSection",
    "RuntimeContextSectionKind",
    "RuntimeTurnContext",
]
