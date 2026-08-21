from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from .identity import JsonValue
from .identity import canonical_sha256_digest
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_digest
from .identity import require_identifier


TOOL_INVOCATION_SCHEMA_VERSION = "openzyme_tool_invocation@1"
TOOL_RESULT_SCHEMA_VERSION = "openzyme_tool_result@1"


@dataclass(frozen=True, slots=True)
class ToolInvocation:
    """Provider-independent identity and arguments for one exact tool call."""

    call_id: str
    tool_name: str
    arguments: Mapping[str, JsonValue]
    session_id: str
    agent_member_id: str
    task_id: str | None = None
    lane_id: str | None = None
    route_id: str | None = None
    affordance_snapshot_digest: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("call_id", "tool_name", "session_id", "agent_member_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("task_id", "lane_id", "route_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if self.affordance_snapshot_digest is not None:
            require_digest(
                self.affordance_snapshot_digest,
                field_name="affordance_snapshot_digest",
            )
        arguments = freeze_json(self.arguments, field_name="arguments")
        if not isinstance(arguments, Mapping):
            raise ValueError("arguments must be a JSON object")
        object.__setattr__(self, "arguments", arguments)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TOOL_INVOCATION_SCHEMA_VERSION,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "arguments": json_compatible(self.arguments),
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "route_id": self.route_id,
            "affordance_snapshot_digest": self.affordance_snapshot_digest,
        }


@dataclass(frozen=True, slots=True)
class ToolResult:
    """Public-safe result envelope; private diagnostics are deliberately excluded."""

    call_id: str
    tool_name: str
    ok: bool
    status: str
    summary: str
    payload: JsonValue
    error_code: str | None = None
    hint: str | None = None
    failure_observation: Mapping[str, JsonValue] | None = None
    terminal_action: str | None = None
    terminates_turn: bool = False

    def __post_init__(self) -> None:
        for field_name in ("call_id", "tool_name", "status"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("error_code", "terminal_action"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if not isinstance(self.summary, str) or len(self.summary) > 16_384:
            raise ValueError("summary must be a bounded string")
        if self.hint is not None and (
            not isinstance(self.hint, str) or len(self.hint) > 8_192
        ):
            raise ValueError("hint must be a bounded string")
        object.__setattr__(
            self,
            "payload",
            freeze_json(self.payload, field_name="payload"),
        )
        if self.failure_observation is not None:
            observation = freeze_json(
                self.failure_observation,
                field_name="failure_observation",
            )
            if not isinstance(observation, Mapping):
                raise ValueError("failure_observation must be a JSON object")
            object.__setattr__(self, "failure_observation", observation)
        if self.ok and self.error_code is not None:
            raise ValueError("successful ToolResult must not carry error_code")
        if not self.ok and self.error_code is None:
            raise ValueError("failed ToolResult requires error_code")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TOOL_RESULT_SCHEMA_VERSION,
            "call_id": self.call_id,
            "tool_name": self.tool_name,
            "ok": self.ok,
            "status": self.status,
            "summary": self.summary,
            "payload": json_compatible(self.payload),
            "error_code": self.error_code,
            "hint": self.hint,
            "failure_observation": (
                None
                if self.failure_observation is None
                else json_compatible(self.failure_observation)
            ),
            "terminal_action": self.terminal_action,
            "terminates_turn": self.terminates_turn,
        }

    @property
    def result_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


__all__ = [
    "TOOL_INVOCATION_SCHEMA_VERSION",
    "TOOL_RESULT_SCHEMA_VERSION",
    "ToolInvocation",
    "ToolResult",
]
