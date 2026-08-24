from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from typing import Any
from typing import ClassVar
from typing import Mapping
from typing import Protocol

from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureObservation
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import ToolSpec
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import parse_failure_observation
from openzyme_contracts import validate_failure_diagnostic_pair


RUNTIME_TURN_COMMAND_SCHEMA_VERSION = "runtime_turn_command@2"
RUNTIME_TURN_OUTCOME_SCHEMA_VERSION = "runtime_turn_outcome@1"
RUNTIME_TURN_OUTCOME_RECEIPT_SCHEMA_VERSION = "runtime_turn_outcome_receipt@1"
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


class RuntimeToolInvocationError(RuntimeError):
    """Typed, secret-safe effect truth emitted by a mounted tool runtime."""

    def __init__(
        self,
        *,
        code: str,
        summary: str,
        effect_certainty: ExternalEffectCertainty,
        mutation_applied: bool | None,
        diagnostic_id: str,
        reconcile_required: bool,
        status: str = "runtime_contract_failure",
        hint: str | None = None,
    ) -> None:
        require_identifier(code, field_name="code")
        require_identifier(diagnostic_id, field_name="diagnostic_id")
        _require_bounded_text(summary, field_name="summary", maximum=16_384)
        _require_bounded_text(status, field_name="status", maximum=128)
        if hint is not None:
            _require_bounded_text(hint, field_name="hint", maximum=4_096)
        if effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if mutation_applied is not False or reconcile_required:
                raise ValueError(
                    "no_effect runtime error requires mutation_applied=false "
                    "and reconcile_required=false"
                )
        elif effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if mutation_applied is not None or not reconcile_required:
                raise ValueError(
                    "dispatch_in_doubt runtime error requires unknown mutation "
                    "and reconciliation"
                )
        elif mutation_applied is None:
            raise ValueError("settled runtime error requires a mutation fact")
        self.code = code
        self.summary = summary
        self.effect_certainty = effect_certainty
        self.mutation_applied = mutation_applied
        self.diagnostic_id = diagnostic_id
        self.reconcile_required = reconcile_required
        self.status = status
        self.hint = hint
        super().__init__(summary)


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeMessage":
        expected = {
            "schema_version",
            "message_id",
            "role",
            "content",
            "correlation_id",
            "tool_call_id",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != RUNTIME_MESSAGE_SCHEMA_VERSION
        ):
            raise ValueError("runtime message has an invalid closed schema")
        return cls(
            message_id=str(payload["message_id"]),
            role=RuntimeMessageRole(str(payload["role"])),
            content=str(payload["content"]),
            correlation_id=None
            if payload["correlation_id"] is None
            else str(payload["correlation_id"]),
            tool_call_id=None
            if payload["tool_call_id"] is None
            else str(payload["tool_call_id"]),
        )


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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeToolRequest":
        expected = {
            "schema_version",
            "request_id",
            "invocation",
            "affordance_snapshot_digest",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != RUNTIME_TOOL_REQUEST_SCHEMA_VERSION
        ):
            raise ValueError("runtime tool request has an invalid closed schema")
        invocation_value = payload["invocation"]
        if not isinstance(invocation_value, Mapping) or set(invocation_value) != {
            "schema_version",
            "call_id",
            "tool_name",
            "arguments",
            "session_id",
            "agent_member_id",
            "task_id",
            "lane_id",
            "route_id",
            "affordance_snapshot_digest",
        }:
            raise ValueError("runtime tool invocation has an invalid closed schema")
        arguments = invocation_value["arguments"]
        if not isinstance(arguments, Mapping):
            raise ValueError("runtime tool invocation arguments must be an object")
        invocation = ToolInvocation(
            call_id=str(invocation_value["call_id"]),
            tool_name=str(invocation_value["tool_name"]),
            arguments=dict(arguments),
            session_id=str(invocation_value["session_id"]),
            agent_member_id=str(invocation_value["agent_member_id"]),
            task_id=None
            if invocation_value["task_id"] is None
            else str(invocation_value["task_id"]),
            lane_id=None
            if invocation_value["lane_id"] is None
            else str(invocation_value["lane_id"]),
            route_id=None
            if invocation_value["route_id"] is None
            else str(invocation_value["route_id"]),
            affordance_snapshot_digest=None
            if invocation_value["affordance_snapshot_digest"] is None
            else str(invocation_value["affordance_snapshot_digest"]),
        )
        return cls(
            request_id=str(payload["request_id"]),
            invocation=invocation,
            affordance_snapshot_digest=str(payload["affordance_snapshot_digest"]),
        )


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
            raise ValueError(
                "total_units cannot be smaller than its bounded components"
            )
        if not isinstance(self.provider_reported, bool):
            raise ValueError("provider_reported must be boolean")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_USAGE_SCHEMA_VERSION,
            "input_units": self.input_units,
            "output_units": self.output_units,
            "total_units": self.total_units,
            "provider_reported": self.provider_reported,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeUsage":
        expected = {
            "schema_version",
            "input_units",
            "output_units",
            "total_units",
            "provider_reported",
        }
        if (
            set(payload) != expected
            or payload.get("schema_version") != RUNTIME_USAGE_SCHEMA_VERSION
        ):
            raise ValueError("runtime usage has an invalid closed schema")
        return cls(
            input_units=int(payload["input_units"]),
            output_units=int(payload["output_units"]),
            total_units=int(payload["total_units"]),
            provider_reported=payload["provider_reported"],
        )


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
    workflow_authority_id: str
    workflow_authority_epoch: int
    workflow_authority_digest: str
    signal_authority_link_digest: str
    tool_exposure_snapshot_id: str
    tool_exposure_snapshot_digest: str
    context: RuntimeTurnContext
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
            "workflow_authority_id",
            "tool_exposure_snapshot_id",
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
            "workflow_authority_epoch",
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
            "workflow_authority_digest",
            "signal_authority_link_digest",
            "tool_exposure_snapshot_digest",
            "runtime_adapter_contract_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if (
            self.context.session_id != self.session_id
            or self.context.agent_id != self.agent_id
            or self.context.agent_member_id != self.agent_member_id
            or self.context.turn_id != self.turn_id
            or self.context.signal_id != self.signal_id
            or self.context.task_id != self.task_id
            or self.context.lane_id != self.lane_id
        ):
            raise ValueError("runtime turn context identity differs from command")
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
            "workflow_authority_id": self.workflow_authority_id,
            "workflow_authority_epoch": self.workflow_authority_epoch,
            "workflow_authority_digest": self.workflow_authority_digest,
            "signal_authority_link_digest": self.signal_authority_link_digest,
            "tool_exposure_snapshot_id": self.tool_exposure_snapshot_id,
            "tool_exposure_snapshot_digest": self.tool_exposure_snapshot_digest,
            "context": self.context.to_dict(),
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

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeTurnCommand":
        value = dict(payload)
        supplied_digest = value.pop("command_digest", None)
        expected = {
            "schema_version",
            "command_id",
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "signal_attempt",
            "signal_claim_token",
            "runtime_lease_token",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
            "distribution_id",
            "distribution_manifest_digest",
            "release_digest",
            "adapter_bundle_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_id",
            "capability_binding_revision",
            "capability_binding_digest",
            "affordance_snapshot_id",
            "affordance_snapshot_digest",
            "workflow_authority_id",
            "workflow_authority_epoch",
            "workflow_authority_digest",
            "signal_authority_link_digest",
            "tool_exposure_snapshot_id",
            "tool_exposure_snapshot_digest",
            "context",
            "runtime_adapter_id",
            "runtime_adapter_contract_digest",
            "max_steps",
            "max_duration_seconds",
            "max_input_units",
            "max_output_units",
            "messages",
            "task_id",
            "lane_id",
            "continuation_id",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != RUNTIME_TURN_COMMAND_SCHEMA_VERSION
        ):
            raise ValueError("runtime turn command has an invalid closed schema")
        context_value = value["context"]
        messages_value = value["messages"]
        if not isinstance(context_value, Mapping):
            raise ValueError("runtime turn command context must be an object")
        if not isinstance(messages_value, list) or any(
            not isinstance(item, Mapping) for item in messages_value
        ):
            raise ValueError(
                "runtime turn command messages must be an array of objects"
            )
        command = cls(
            command_id=str(value["command_id"]),
            turn_id=str(value["turn_id"]),
            session_id=str(value["session_id"]),
            agent_id=str(value["agent_id"]),
            agent_member_id=str(value["agent_member_id"]),
            signal_id=str(value["signal_id"]),
            signal_attempt=int(value["signal_attempt"]),
            signal_claim_token=str(value["signal_claim_token"]),
            runtime_lease_token=str(value["runtime_lease_token"]),
            runtime_lease_generation=int(value["runtime_lease_generation"]),
            runtime_fence=int(value["runtime_fence"]),
            process_epoch=int(value["process_epoch"]),
            distribution_id=str(value["distribution_id"]),
            distribution_manifest_digest=str(value["distribution_manifest_digest"]),
            release_digest=str(value["release_digest"]),
            adapter_bundle_digest=str(value["adapter_bundle_digest"]),
            extension_bundle_digest=str(value["extension_bundle_digest"]),
            declared_tool_catalog_digest=str(value["declared_tool_catalog_digest"]),
            capability_binding_id=str(value["capability_binding_id"]),
            capability_binding_revision=int(value["capability_binding_revision"]),
            capability_binding_digest=str(value["capability_binding_digest"]),
            affordance_snapshot_id=str(value["affordance_snapshot_id"]),
            affordance_snapshot_digest=str(value["affordance_snapshot_digest"]),
            workflow_authority_id=str(value["workflow_authority_id"]),
            workflow_authority_epoch=int(value["workflow_authority_epoch"]),
            workflow_authority_digest=str(value["workflow_authority_digest"]),
            signal_authority_link_digest=str(value["signal_authority_link_digest"]),
            tool_exposure_snapshot_id=str(value["tool_exposure_snapshot_id"]),
            tool_exposure_snapshot_digest=str(value["tool_exposure_snapshot_digest"]),
            context=RuntimeTurnContext.from_dict(context_value),
            runtime_adapter_id=str(value["runtime_adapter_id"]),
            runtime_adapter_contract_digest=str(
                value["runtime_adapter_contract_digest"]
            ),
            max_steps=int(value["max_steps"]),
            max_duration_seconds=int(value["max_duration_seconds"]),
            max_input_units=int(value["max_input_units"]),
            max_output_units=int(value["max_output_units"]),
            messages=tuple(RuntimeMessage.from_dict(item) for item in messages_value),
            task_id=None if value["task_id"] is None else str(value["task_id"]),
            lane_id=None if value["lane_id"] is None else str(value["lane_id"]),
            continuation_id=(
                None
                if value["continuation_id"] is None
                else str(value["continuation_id"])
            ),
        )
        if supplied_digest is not None and supplied_digest != command.command_digest:
            raise ValueError("runtime turn command digest mismatch")
        return command


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
    workflow_authority_id: str
    workflow_authority_epoch: int
    workflow_authority_digest: str
    tool_exposure_snapshot_id: str
    tool_exposure_snapshot_digest: str
    disposition: RuntimeTurnDisposition
    summary: str
    messages: tuple[RuntimeMessage, ...] = ()
    tool_requests: tuple[RuntimeToolRequest, ...] = ()
    usage: RuntimeUsage | None = None
    continuation_id: str | None = None
    waiting_approval_id: str | None = None
    failure: FailureObservation | None = None
    task_id: str | None = None
    lane_id: str | None = None
    correlation_id: str | None = None
    private_diagnostic: PrivateDiagnosticRecord | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        for field_name in (
            "outcome_id",
            "command_id",
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "workflow_authority_id",
            "tool_exposure_snapshot_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.command_digest, field_name="command_digest")
        for field_name in (
            "signal_attempt",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
            "workflow_authority_epoch",
        ):
            _require_positive_int(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "workflow_authority_digest",
            "tool_exposure_snapshot_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        _require_bounded_text(self.summary, field_name="summary", maximum=16_384)
        for field_name in (
            "continuation_id",
            "waiting_approval_id",
            "task_id",
            "lane_id",
            "correlation_id",
        ):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if len(self.messages) > 512 or len(self.tool_requests) > 64:
            raise ValueError("runtime outcome exceeds its bounded collection limits")
        message_ids = tuple(message.message_id for message in self.messages)
        if len(set(message_ids)) != len(message_ids):
            raise ValueError("runtime outcome message IDs must be unique")
        request_ids = tuple(request.request_id for request in self.tool_requests)
        if len(set(request_ids)) != len(request_ids):
            raise ValueError("runtime tool request IDs must be unique")
        if self.disposition is RuntimeTurnDisposition.FAILED and self.failure is None:
            raise ValueError("failed runtime outcome requires structured failure")
        if (
            self.disposition is not RuntimeTurnDisposition.FAILED
            and self.failure is not None
        ):
            raise ValueError("structured failure is permitted only for failed outcome")
        if self.private_diagnostic is not None:
            if (
                self.failure is None
                or self.disposition is not RuntimeTurnDisposition.FAILED
            ):
                raise ValueError(
                    "private diagnostic is permitted only for failed outcome"
                )
            validate_failure_diagnostic_pair(self.failure, self.private_diagnostic)
        elif (
            self.failure is not None
            and self.failure.private_diagnostic_digest is not None
        ):
            raise ValueError("failure private diagnostic sidecar is missing")
        if (self.disposition is RuntimeTurnDisposition.WAITING_APPROVAL) != (
            self.waiting_approval_id is not None
        ):
            raise ValueError("approval wait disposition and approval ID must agree")
        if (self.disposition is RuntimeTurnDisposition.WAITING_CONTINUATION) != (
            self.continuation_id is not None
        ):
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
            "workflow_authority_id": self.workflow_authority_id,
            "workflow_authority_epoch": self.workflow_authority_epoch,
            "workflow_authority_digest": self.workflow_authority_digest,
            "tool_exposure_snapshot_id": self.tool_exposure_snapshot_id,
            "tool_exposure_snapshot_digest": self.tool_exposure_snapshot_digest,
            "disposition": self.disposition.value,
            "summary": self.summary,
            "messages": [message.to_dict() for message in self.messages],
            "tool_requests": [request.to_dict() for request in self.tool_requests],
            "usage": None if self.usage is None else self.usage.to_dict(),
            "continuation_id": self.continuation_id,
            "waiting_approval_id": self.waiting_approval_id,
            "failure": None if self.failure is None else self.failure.to_dict(),
            "task_id": self.task_id,
            "lane_id": self.lane_id,
            "correlation_id": self.correlation_id,
        }
        if include_digest:
            data["outcome_digest"] = self.outcome_digest
        return data

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeTurnOutcome":
        value = dict(payload)
        supplied_digest = value.pop("outcome_digest", None)
        expected = {
            "schema_version",
            "outcome_id",
            "command_id",
            "command_digest",
            "turn_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "signal_attempt",
            "runtime_lease_generation",
            "runtime_fence",
            "process_epoch",
            "workflow_authority_id",
            "workflow_authority_epoch",
            "workflow_authority_digest",
            "tool_exposure_snapshot_id",
            "tool_exposure_snapshot_digest",
            "disposition",
            "summary",
            "messages",
            "tool_requests",
            "usage",
            "continuation_id",
            "waiting_approval_id",
            "failure",
            "task_id",
            "lane_id",
            "correlation_id",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != RUNTIME_TURN_OUTCOME_SCHEMA_VERSION
        ):
            raise ValueError("runtime turn outcome has an invalid closed schema")
        messages_value = value["messages"]
        tool_requests_value = value["tool_requests"]
        if not isinstance(messages_value, list) or any(
            not isinstance(item, Mapping) for item in messages_value
        ):
            raise ValueError("runtime outcome messages must be an array of objects")
        if not isinstance(tool_requests_value, list) or any(
            not isinstance(item, Mapping) for item in tool_requests_value
        ):
            raise ValueError(
                "runtime outcome tool requests must be an array of objects"
            )
        usage_value = value["usage"]
        if usage_value is not None and not isinstance(usage_value, Mapping):
            raise ValueError("runtime outcome usage must be an object or null")
        failure_value = value["failure"]
        failure = None
        if failure_value is not None:
            if not isinstance(failure_value, Mapping):
                raise ValueError("runtime outcome failure must be an object")
            parsed = parse_failure_observation(failure_value)
            if not isinstance(parsed, FailureObservation):
                raise ValueError(
                    "legacy failure cannot settle a current runtime outcome"
                )
            failure = parsed
        outcome = cls(
            outcome_id=str(value["outcome_id"]),
            command_id=str(value["command_id"]),
            command_digest=str(value["command_digest"]),
            turn_id=str(value["turn_id"]),
            session_id=str(value["session_id"]),
            agent_id=str(value["agent_id"]),
            agent_member_id=str(value["agent_member_id"]),
            signal_id=str(value["signal_id"]),
            signal_attempt=int(value["signal_attempt"]),
            runtime_lease_generation=int(value["runtime_lease_generation"]),
            runtime_fence=int(value["runtime_fence"]),
            process_epoch=int(value["process_epoch"]),
            workflow_authority_id=str(value["workflow_authority_id"]),
            workflow_authority_epoch=int(value["workflow_authority_epoch"]),
            workflow_authority_digest=str(value["workflow_authority_digest"]),
            tool_exposure_snapshot_id=str(value["tool_exposure_snapshot_id"]),
            tool_exposure_snapshot_digest=str(value["tool_exposure_snapshot_digest"]),
            disposition=RuntimeTurnDisposition(str(value["disposition"])),
            summary=str(value["summary"]),
            messages=tuple(RuntimeMessage.from_dict(item) for item in messages_value),
            tool_requests=tuple(
                RuntimeToolRequest.from_dict(item) for item in tool_requests_value
            ),
            usage=None if usage_value is None else RuntimeUsage.from_dict(usage_value),
            continuation_id=None
            if value["continuation_id"] is None
            else str(value["continuation_id"]),
            waiting_approval_id=None
            if value["waiting_approval_id"] is None
            else str(value["waiting_approval_id"]),
            failure=failure,
            task_id=None if value["task_id"] is None else str(value["task_id"]),
            lane_id=None if value["lane_id"] is None else str(value["lane_id"]),
            correlation_id=None
            if value["correlation_id"] is None
            else str(value["correlation_id"]),
        )
        if supplied_digest is not None and supplied_digest != outcome.outcome_digest:
            raise ValueError("runtime turn outcome digest mismatch")
        return outcome


@dataclass(frozen=True, slots=True)
class RuntimeTurnOutcomeReceipt:
    SCHEMA_VERSION: ClassVar[str] = RUNTIME_TURN_OUTCOME_RECEIPT_SCHEMA_VERSION

    receipt_id: str
    outcome: RuntimeTurnOutcome
    accepted_at: str

    def __post_init__(self) -> None:
        require_identifier(self.receipt_id, field_name="receipt_id")
        require_identifier(self.accepted_at, field_name="accepted_at")

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "outcome": self.outcome.to_dict(),
            "accepted_at": self.accepted_at,
        }
        if include_digest:
            payload["receipt_digest"] = self.receipt_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeTurnOutcomeReceipt":
        value = dict(payload)
        supplied_digest = value.pop("receipt_digest", None)
        expected = {"schema_version", "receipt_id", "outcome", "accepted_at"}
        if set(value) != expected or value.get("schema_version") != cls.SCHEMA_VERSION:
            raise ValueError(
                "runtime turn outcome receipt has an invalid closed schema"
            )
        outcome_value = value["outcome"]
        if not isinstance(outcome_value, Mapping):
            raise ValueError("runtime turn outcome receipt requires an outcome object")
        receipt = cls(
            receipt_id=str(value["receipt_id"]),
            outcome=RuntimeTurnOutcome.from_dict(outcome_value),
            accepted_at=str(value["accepted_at"]),
        )
        if supplied_digest is not None and supplied_digest != receipt.receipt_digest:
            raise ValueError("runtime turn outcome receipt digest mismatch")
        return receipt


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
    "RUNTIME_TURN_OUTCOME_RECEIPT_SCHEMA_VERSION",
    "RUNTIME_USAGE_SCHEMA_VERSION",
    "RuntimeCapabilityGateway",
    "RuntimeMessage",
    "RuntimeMessageRole",
    "RuntimeToolRequest",
    "RuntimeToolInvocationError",
    "RuntimeTurnCommand",
    "RuntimeTurnDisposition",
    "RuntimeTurnOutcome",
    "RuntimeTurnOutcomeReceipt",
    "RuntimeUsage",
]
