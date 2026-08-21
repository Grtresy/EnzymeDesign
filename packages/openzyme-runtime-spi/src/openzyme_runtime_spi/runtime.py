from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from typing import Protocol

from openzyme_contracts import FailureObservation
from openzyme_contracts import ToolSpec
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


RUNTIME_TURN_COMMAND_SCHEMA_VERSION = "runtime_turn_command@1"
RUNTIME_TURN_OUTCOME_SCHEMA_VERSION = "runtime_turn_outcome@1"
RUNTIME_MESSAGE_SCHEMA_VERSION = "runtime_message@1"
RUNTIME_TOOL_REQUEST_SCHEMA_VERSION = "runtime_tool_request@1"
RUNTIME_USAGE_SCHEMA_VERSION = "runtime_usage@1"


def _require_bounded_text(
    value: str,
    *,
    field_name: str,
    maximum: int,
    allow_empty: bool = False,
) -> str:
    if not isinstance(value, str):
        raise TypeError(f"{field_name} must be a string")
    if (not allow_empty and not value) or len(value) > maximum:
        qualifier = "bounded" if allow_empty else "non-empty and bounded"
        raise ValueError(f"{field_name} must be {qualifier}")
    return value


def _require_positive_int(value: int, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


class RuntimeMessageRole(StrEnum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class RuntimeTurnDisposition(StrEnum):
    READY_FOR_NEXT_STEP = "ready_for_next_step"
    WAITING_APPROVAL = "waiting_approval"
    WAITING_CONTINUATION = "waiting_continuation"
    IDLE = "idle"
    STEP_LIMIT_REACHED = "step_limit_reached"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class RuntimeMessage:
    message_id: str
    role: RuntimeMessageRole
    content: str
    correlation_id: str | None = None
    tool_call_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.message_id, field_name="message_id")
        _require_bounded_text(self.content, field_name="content", maximum=131_072)
        if self.correlation_id is not None:
            require_identifier(self.correlation_id, field_name="correlation_id")
        if self.tool_call_id is not None:
            require_identifier(self.tool_call_id, field_name="tool_call_id")
        if self.role is RuntimeMessageRole.TOOL and self.tool_call_id is None:
            raise ValueError("tool messages require tool_call_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_MESSAGE_SCHEMA_VERSION,
            "message_id": self.message_id,
            "role": self.role.value,
            "content": self.content,
            "correlation_id": self.correlation_id,
            "tool_call_id": self.tool_call_id,
        }


@dataclass(frozen=True, slots=True)
class RuntimeToolRequest:
    request_id: str
    invocation: ToolInvocation
    affordance_snapshot_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.request_id, field_name="request_id")
        require_digest(
            self.affordance_snapshot_digest,
            field_name="affordance_snapshot_digest",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_TOOL_REQUEST_SCHEMA_VERSION,
            "request_id": self.request_id,
            "invocation": self.invocation.to_dict(),
            "affordance_snapshot_digest": self.affordance_snapshot_digest,
        }


@dataclass(frozen=True, slots=True)
class RuntimeUsage:
    input_units: int
    output_units: int
    total_units: int
    provider_reported: bool

    def __post_init__(self) -> None:
        for field_name, value in (
            ("input_units", self.input_units),
            ("output_units", self.output_units),
            ("total_units", self.total_units),
        ):
            if not isinstance(value, int) or isinstance(value, bool) or value < 0:
                raise ValueError(f"{field_name} must be a non-negative integer")
        if self.total_units < self.input_units + self.output_units:
            raise ValueError("total_units cannot be smaller than its bounded components")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_USAGE_SCHEMA_VERSION,
            "input_units": self.input_units,
            "output_units": self.output_units,
            "total_units": self.total_units,
            "provider_reported": self.provider_reported,
        }


@dataclass(frozen=True, slots=True)
class RuntimeTurnCommand:
    command_id: str
    turn_id: str
    session_id: str
    agent_id: str
    agent_member_id: str
    signal_id: str
    signal_attempt: int
    signal_claim_token: str
    runtime_lease_token: str
    runtime_lease_generation: int
    runtime_fence: int
    process_epoch: int
    distribution_id: str
    distribution_manifest_digest: str
    release_digest: str
    adapter_bundle_digest: str
    extension_bundle_digest: str
    declared_tool_catalog_digest: str
    capability_binding_id: str
    capability_binding_revision: int
    capability_binding_digest: str
    affordance_snapshot_id: str
    affordance_snapshot_digest: str
    runtime_adapter_id: str
    runtime_adapter_contract_digest: str
    max_steps: int
    max_duration_seconds: int
    max_input_units: int
    max_output_units: int
    messages: tuple[RuntimeMessage, ...]
    task_id: str | None = None
    lane_id: str | None = None
    continuation_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "command_id",
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "signal_claim_token",
            "runtime_lease_token",
            "distribution_id",
            "capability_binding_id",
            "affordance_snapshot_id",
            "runtime_adapter_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("task_id", "lane_id", "continuation_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        for field_name in (
            "signal_attempt",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
            "capability_binding_revision",
            "max_steps",
            "max_duration_seconds",
            "max_input_units",
            "max_output_units",
        ):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "distribution_manifest_digest",
            "release_digest",
            "adapter_bundle_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_digest",
            "affordance_snapshot_digest",
            "runtime_adapter_contract_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if not self.messages:
            raise ValueError("runtime turn command requires bounded input messages")
        if len(self.messages) > 512:
            raise ValueError("runtime turn command message count exceeds the bound")
        message_ids = tuple(message.message_id for message in self.messages)
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("runtime turn command message IDs must be unique")

    @property
    def command_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        data = {
            "schema_version": RUNTIME_TURN_COMMAND_SCHEMA_VERSION,
            "command_id": self.command_id,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_member_id": self.agent_member_id,
            "signal_id": self.signal_id,
            "signal_attempt": self.signal_attempt,
            "signal_claim_token": self.signal_claim_token,
            "runtime_lease_token": self.runtime_lease_token,
            "runtime_lease_generation": self.runtime_lease_generation,
            "runtime_fence": self.runtime_fence,
            "process_epoch": self.process_epoch,
            "distribution_id": self.distribution_id,
            "distribution_manifest_digest": self.distribution_manifest_digest,
            "release_digest": self.release_digest,
            "adapter_bundle_digest": self.adapter_bundle_digest,
            "extension_bundle_digest": self.extension_bundle_digest,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "capability_binding_id": self.capability_binding_id,
            "capability_binding_revision": self.capability_binding_revision,
            "capability_binding_digest": self.capability_binding_digest,
            "affordance_snapshot_id": self.affordance_snapshot_id,
            "affordance_snapshot_digest": self.affordance_snapshot_digest,
            "runtime_adapter_id": self.runtime_adapter_id,
            "runtime_adapter_contract_digest": self.runtime_adapter_contract_digest,
            "max_steps": self.max_steps,
            "max_duration_seconds": self.max_duration_seconds,
            "max_input_units": self.max_input_units,
            "max_output_units": self.max_output_units,
            "messages": [message.to_dict() for message in self.messages],
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "continuation_id": self.continuation_id,
        }
        if include_digest:
            data["command_digest"] = self.command_digest
        return data


@dataclass(frozen=True, slots=True)
class RuntimeTurnOutcome:
    outcome_id: str
    command_id: str
    command_digest: str
    turn_id: str
    session_id: str
    agent_id: str
    agent_member_id: str
    signal_id: str
    signal_attempt: int
    runtime_lease_generation: int
    runtime_fence: int
    process_epoch: int
    disposition: RuntimeTurnDisposition
    summary: str
    messages: tuple[RuntimeMessage, ...] = ()
    tool_requests: tuple[RuntimeToolRequest, ...] = ()
    usage: RuntimeUsage | None = None
    continuation_id: str | None = None
    waiting_approval_id: str | None = None
    failure: FailureObservation | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "outcome_id",
            "command_id",
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.command_digest, field_name="command_digest")
        for field_name in (
            "signal_attempt",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
        ):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        _require_bounded_text(self.summary, field_name="summary", maximum=16_384)
        for field_name in ("continuation_id", "waiting_approval_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if len(self.messages) > 512 or len(self.tool_requests) > 64:
            raise ValueError("runtime outcome exceeds its bounded collection limits")
        request_ids = tuple(request.request_id for request in self.tool_requests)
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("runtime tool request IDs must be unique")
        if self.disposition is RuntimeTurnDisposition.FAILED and self.failure is None:
            raise ValueError("failed runtime outcome requires structured failure")
        if self.disposition is not RuntimeTurnDisposition.FAILED and self.failure is not None:
            raise ValueError("structured failure is permitted only for failed outcome")
        if (
            self.disposition is RuntimeTurnDisposition.WAITING_APPROVAL
        ) != (self.waiting_approval_id is not None):
            raise ValueError("approval wait disposition and approval ID must agree")
        if (
            self.disposition is RuntimeTurnDisposition.WAITING_CONTINUATION
        ) != (self.continuation_id is not None):
            raise ValueError("continuation disposition and continuation ID must agree")

    @property
    def outcome_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        data = {
            "schema_version": RUNTIME_TURN_OUTCOME_SCHEMA_VERSION,
            "outcome_id": self.outcome_id,
            "command_id": self.command_id,
            "command_digest": self.command_digest,
            "turn_id": self.turn_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_member_id": self.agent_member_id,
            "signal_id": self.signal_id,
            "signal_attempt": self.signal_attempt,
            "runtime_lease_generation": self.runtime_lease_generation,
            "runtime_fence": self.runtime_fence,
            "process_epoch": self.process_epoch,
            "disposition": self.disposition.value,
            "summary": self.summary,
            "messages": [message.to_dict() for message in self.messages],
            "tool_requests": [request.to_dict() for request in self.tool_requests],
            "usage": None if self.usage is None else self.usage.to_dict(),
            "continuation_id": self.continuation_id,
            "waiting_approval_id": self.waiting_approval_id,
            "failure": None if self.failure is None else self.failure.to_dict(),
        }
        if include_digest:
            data["outcome_digest"] = self.outcome_digest
        return data


class RuntimeCapabilityGateway(Protocol):
    """Kernel-owned capability access already scoped to one turn command."""

    def list_tools(
        self,
        *,
        command_id: str,
        affordance_snapshot_digest: str,
    ) -> tuple[ToolSpec, ...]: ...

    def invoke(
        self,
        *,
        command_id: str,
        request: RuntimeToolRequest,
    ) -> ToolResult: ...


class AgentRuntimeAdapter(Protocol):
    adapter_id: str
    adapter_contract_digest: str

    def run_turn(
        self,
        command: RuntimeTurnCommand,
        capability_gateway: RuntimeCapabilityGateway,
    ) -> RuntimeTurnOutcome: ...


__all__ = [
    "AgentRuntimeAdapter",
    "RUNTIME_MESSAGE_SCHEMA_VERSION",
    "RUNTIME_TOOL_REQUEST_SCHEMA_VERSION",
    "RUNTIME_TURN_COMMAND_SCHEMA_VERSION",
    "RUNTIME_TURN_OUTCOME_SCHEMA_VERSION",
    "RUNTIME_USAGE_SCHEMA_VERSION",
    "RuntimeCapabilityGateway",
    "RuntimeMessage",
    "RuntimeMessageRole",
    "RuntimeToolRequest",
    "RuntimeTurnCommand",
    "RuntimeTurnDisposition",
    "RuntimeTurnOutcome",
    "RuntimeUsage",
]
