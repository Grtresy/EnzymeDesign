from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any
from typing import Protocol

from openzyme_contracts import EvidenceRef
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureObservation
from openzyme_contracts import RouteRef
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible


KERNEL_COMMAND_CONTEXT_SCHEMA_VERSION = "openzyme_kernel_command_context@1"
KERNEL_QUERY_CONTEXT_SCHEMA_VERSION = "openzyme_kernel_query_context@1"
KERNEL_MUTATION_RECEIPT_SCHEMA_VERSION = "openzyme_kernel_mutation_receipt@1"


def _require_positive(value: int, *, field_name: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value < 1:
        raise ValueError(f"{field_name} must be a positive integer")
    return value


def _freeze_payload(
    payload: Mapping[str, JsonValue],
    *,
    field_name: str = "payload",
) -> Mapping[str, JsonValue]:
    frozen = freeze_json(payload, field_name=field_name)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return frozen


@dataclass(frozen=True, slots=True)
class KernelQueryContext:
    session_id: str
    actor_id: str
    owner_plugin_id: str
    authority_lease_id: str
    extension_bundle_digest: str
    capability_binding_digest: str
    correlation_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "session_id",
            "actor_id",
            "owner_plugin_id",
            "authority_lease_id",
            "correlation_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.extension_bundle_digest,
            field_name="extension_bundle_digest",
        )
        require_digest(
            self.capability_binding_digest,
            field_name="capability_binding_digest",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": KERNEL_QUERY_CONTEXT_SCHEMA_VERSION,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "owner_plugin_id": self.owner_plugin_id,
            "authority_lease_id": self.authority_lease_id,
            "extension_bundle_digest": self.extension_bundle_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "correlation_id": self.correlation_id,
        }


@dataclass(frozen=True, slots=True)
class KernelCommandContext:
    command_id: str
    session_id: str
    actor_id: str
    owner_plugin_id: str
    authority_lease_id: str
    authority_generation: int
    authority_fence: int
    expected_session_version: int
    extension_bundle_digest: str
    capability_binding_digest: str
    idempotency_key: str
    correlation_id: str
    workspace_generation: int | None = None
    route_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "command_id",
            "session_id",
            "actor_id",
            "owner_plugin_id",
            "authority_lease_id",
            "idempotency_key",
            "correlation_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "authority_generation",
            "authority_fence",
            "expected_session_version",
        ):
            _require_positive(getattr(self, field_name), field_name=field_name)
        if self.workspace_generation is not None:
            _require_positive(
                self.workspace_generation,
                field_name="workspace_generation",
            )
        if self.route_id is not None:
            require_identifier(self.route_id, field_name="route_id")
        require_digest(
            self.extension_bundle_digest,
            field_name="extension_bundle_digest",
        )
        require_digest(
            self.capability_binding_digest,
            field_name="capability_binding_digest",
        )

    def to_query_context(self) -> KernelQueryContext:
        return KernelQueryContext(
            session_id=self.session_id,
            actor_id=self.actor_id,
            owner_plugin_id=self.owner_plugin_id,
            authority_lease_id=self.authority_lease_id,
            extension_bundle_digest=self.extension_bundle_digest,
            capability_binding_digest=self.capability_binding_digest,
            correlation_id=self.correlation_id,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": KERNEL_COMMAND_CONTEXT_SCHEMA_VERSION,
            "command_id": self.command_id,
            "session_id": self.session_id,
            "actor_id": self.actor_id,
            "owner_plugin_id": self.owner_plugin_id,
            "authority_lease_id": self.authority_lease_id,
            "authority_generation": self.authority_generation,
            "authority_fence": self.authority_fence,
            "expected_session_version": self.expected_session_version,
            "extension_bundle_digest": self.extension_bundle_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "idempotency_key": self.idempotency_key,
            "correlation_id": self.correlation_id,
            "workspace_generation": self.workspace_generation,
            "route_id": self.route_id,
        }


@dataclass(frozen=True, slots=True)
class KernelEntityRef:
    entity_kind: str
    entity_id: str
    state_version: int
    entity_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.entity_kind, field_name="entity_kind")
        require_identifier(self.entity_id, field_name="entity_id")
        _require_positive(self.state_version, field_name="state_version")
        require_digest(self.entity_digest, field_name="entity_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "state_version": self.state_version,
            "entity_digest": self.entity_digest,
        }


@dataclass(frozen=True, slots=True)
class KernelEntitySnapshot:
    entity: KernelEntityRef
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        object.__setattr__(self, "payload", _freeze_payload(self.payload))

    def to_dict(self) -> dict[str, Any]:
        return {
            "entity": self.entity.to_dict(),
            "payload": json_compatible(self.payload),
        }


@dataclass(frozen=True, slots=True)
class KernelMutationReceipt:
    command_id: str
    service_id: str
    operation: str
    mutation_applied: bool
    effect_certainty: ExternalEffectCertainty
    fallback_performed: bool
    entity_refs: tuple[KernelEntityRef, ...]
    event_refs: tuple[str, ...]
    result: Mapping[str, JsonValue]
    receipt_digest: str

    @classmethod
    def create(
        cls,
        *,
        command_id: str,
        service_id: str,
        operation: str,
        mutation_applied: bool,
        effect_certainty: ExternalEffectCertainty,
        entity_refs: tuple[KernelEntityRef, ...] = (),
        event_refs: tuple[str, ...] = (),
        result: Mapping[str, JsonValue] | None = None,
    ) -> KernelMutationReceipt:
        provisional = cls(
            command_id=command_id,
            service_id=service_id,
            operation=operation,
            mutation_applied=mutation_applied,
            effect_certainty=effect_certainty,
            fallback_performed=False,
            entity_refs=entity_refs,
            event_refs=event_refs,
            result=result or {},
            receipt_digest="sha256:" + "0" * 64,
        )
        return replace(
            provisional,
            receipt_digest=canonical_sha256_digest(provisional.digest_payload()),
        )

    def __post_init__(self) -> None:
        for field_name in ("command_id", "service_id", "operation"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.fallback_performed:
            raise ValueError("Kernel application receipt must not hide fallback")
        entity_keys = [
            (item.entity_kind, item.entity_id, item.state_version)
            for item in self.entity_refs
        ]
        if len(set(entity_keys)) != len(entity_keys):
            raise ValueError("entity_refs must be unique")
        object.__setattr__(
            self,
            "entity_refs",
            tuple(
                sorted(
                    self.entity_refs,
                    key=lambda item: (
                        item.entity_kind,
                        item.entity_id,
                        item.state_version,
                    ),
                )
            ),
        )
        for event_ref in self.event_refs:
            require_identifier(event_ref, field_name="event_refs")
        if len(set(self.event_refs)) != len(self.event_refs):
            raise ValueError("event_refs must be unique")
        object.__setattr__(self, "event_refs", tuple(sorted(self.event_refs)))
        object.__setattr__(self, "result", _freeze_payload(self.result, field_name="result"))
        require_digest(self.receipt_digest, field_name="receipt_digest")
        placeholder = "sha256:" + "0" * 64
        if (
            self.receipt_digest != placeholder
            and self.receipt_digest
            != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("Kernel mutation receipt digest mismatch")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": KERNEL_MUTATION_RECEIPT_SCHEMA_VERSION,
            "command_id": self.command_id,
            "service_id": self.service_id,
            "operation": self.operation,
            "mutation_applied": self.mutation_applied,
            "effect_certainty": self.effect_certainty.value,
            "fallback_performed": self.fallback_performed,
            "entity_refs": [item.to_dict() for item in self.entity_refs],
            "event_refs": list(self.event_refs),
            "result": json_compatible(self.result),
        }

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "receipt_digest": self.receipt_digest}


class TaskCommandKind(StrEnum):
    UPDATE_NON_TERMINAL = "update_non_terminal"
    ATTACH_EVIDENCE = "attach_evidence"
    FINISH = "finish"


class ProtocolCommandKind(StrEnum):
    DELEGATE = "delegate"
    SEND = "send"
    HANDOFF = "handoff"


class ApprovalCommandKind(StrEnum):
    REQUEST = "request"
    CONSUME = "consume"


class PublicationCommandKind(StrEnum):
    VERIFY_CHECKPOINT = "verify_checkpoint"
    PUBLISH = "publish"
    VERIFY_REVISION_PATH = "verify_revision_path"


class ControlledOperationCommandKind(StrEnum):
    ADMIT = "admit"
    OBSERVE = "observe"
    RECONCILE = "reconcile"
    CANCEL = "cancel"


class ContinuationCommandKind(StrEnum):
    REGISTER = "register"
    DELIVER = "deliver"
    FAIL = "fail"


class ExtensionInvocationCommandKind(StrEnum):
    START = "start"
    SETTLE = "settle"


class TaskEvidenceCommandKind(StrEnum):
    REGISTER = "register"
    VALIDATE = "validate"


@dataclass(frozen=True, slots=True)
class TaskApplicationCommand:
    context: KernelCommandContext
    operation: TaskCommandKind
    task_id: str
    expected_task_version: int
    payload: Mapping[str, JsonValue]
    evidence_refs: tuple[EvidenceRef, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.task_id, field_name="task_id")
        _require_positive(
            self.expected_task_version,
            field_name="expected_task_version",
        )
        object.__setattr__(self, "payload", _freeze_payload(self.payload))
        if self.operation is not TaskCommandKind.FINISH and self.evidence_refs:
            raise ValueError("only task.finish may carry finish evidence refs")


@dataclass(frozen=True, slots=True)
class ProtocolApplicationCommand:
    context: KernelCommandContext
    operation: ProtocolCommandKind
    protocol_ref: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.protocol_ref, field_name="protocol_ref")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class ApprovalApplicationCommand:
    context: KernelCommandContext
    operation: ApprovalCommandKind
    approval_id: str
    intent_digest: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.approval_id, field_name="approval_id")
        require_digest(self.intent_digest, field_name="intent_digest")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class PublicationApplicationCommand:
    context: KernelCommandContext
    operation: PublicationCommandKind
    resource_id: str
    workspace_id: str
    expected_workspace_generation: int
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.resource_id, field_name="resource_id")
        require_identifier(self.workspace_id, field_name="workspace_id")
        _require_positive(
            self.expected_workspace_generation,
            field_name="expected_workspace_generation",
        )
        if (
            self.context.workspace_generation is not None
            and self.context.workspace_generation != self.expected_workspace_generation
        ):
            raise ValueError("workspace generation differs from command context")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class ControlledOperationApplicationCommand:
    context: KernelCommandContext
    operation: ControlledOperationCommandKind
    operation_id: str
    intent_digest: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.operation_id, field_name="operation_id")
        require_digest(self.intent_digest, field_name="intent_digest")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))
        if self.operation is ControlledOperationCommandKind.ADMIT:
            if self.context.route_id is None:
                raise ValueError("controlled-operation admission requires explicit route_id")


@dataclass(frozen=True, slots=True)
class ContinuationApplicationCommand:
    context: KernelCommandContext
    operation: ContinuationCommandKind
    continuation_id: str
    source_version: int
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.continuation_id, field_name="continuation_id")
        _require_positive(self.source_version, field_name="source_version")
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class FailureRecordCommand:
    context: KernelCommandContext
    observation: FailureObservation


@dataclass(frozen=True, slots=True)
class ExtensionInvocationApplicationCommand:
    context: KernelCommandContext
    operation: ExtensionInvocationCommandKind
    invocation_id: str
    tool_name: str
    tool_contract_digest: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        require_identifier(self.invocation_id, field_name="invocation_id")
        require_identifier(self.tool_name, field_name="tool_name")
        require_digest(
            self.tool_contract_digest,
            field_name="tool_contract_digest",
        )
        object.__setattr__(self, "payload", _freeze_payload(self.payload))


@dataclass(frozen=True, slots=True)
class TaskEvidenceApplicationCommand:
    context: KernelCommandContext
    operation: TaskEvidenceCommandKind
    task_id: str
    evidence_ref: EvidenceRef
    expected_task_version: int

    def __post_init__(self) -> None:
        require_identifier(self.task_id, field_name="task_id")
        _require_positive(
            self.expected_task_version,
            field_name="expected_task_version",
        )
        if self.evidence_ref.task_id != self.task_id:
            raise ValueError("evidence_ref belongs to a different task")


@dataclass(frozen=True, slots=True)
class AuthorityCheckRequest:
    context: KernelQueryContext
    operation: str
    scope_id: str
    expected_generation: int
    expected_fence: int

    def __post_init__(self) -> None:
        require_identifier(self.operation, field_name="operation")
        require_identifier(self.scope_id, field_name="scope_id")
        _require_positive(self.expected_generation, field_name="expected_generation")
        _require_positive(self.expected_fence, field_name="expected_fence")


@dataclass(frozen=True, slots=True)
class AuthorityDecision:
    allowed: bool
    operation: str
    scope_id: str
    authority_lease_id: str
    generation: int
    fence: int
    denial_code: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("operation", "scope_id", "authority_lease_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        _require_positive(self.generation, field_name="generation")
        _require_positive(self.fence, field_name="fence")
        if self.allowed and self.denial_code is not None:
            raise ValueError("allowed authority decision cannot carry denial_code")
        if not self.allowed:
            if self.denial_code is None:
                raise ValueError("denied authority decision requires denial_code")
            require_identifier(self.denial_code, field_name="denial_code")


@dataclass(frozen=True, slots=True)
class TaskEvidenceValidation:
    accepted: bool
    validator_ids: tuple[str, ...]
    rejection_codes: tuple[str, ...]
    validation_digest: str

    def __post_init__(self) -> None:
        for values, field_name in (
            (self.validator_ids, "validator_ids"),
            (self.rejection_codes, "rejection_codes"),
        ):
            for value in values:
                require_identifier(value, field_name=field_name)
            if len(set(values)) != len(values):
                raise ValueError(f"{field_name} must not contain duplicates")
            object.__setattr__(self, field_name, tuple(sorted(values)))
        if self.accepted and self.rejection_codes:
            raise ValueError("accepted validation cannot carry rejection codes")
        require_digest(self.validation_digest, field_name="validation_digest")


class TaskApplicationService(Protocol):
    def inspect(
        self,
        context: KernelQueryContext,
        task_id: str,
    ) -> KernelEntitySnapshot: ...

    def execute(self, command: TaskApplicationCommand) -> KernelMutationReceipt: ...


class ProtocolApplicationService(Protocol):
    def execute(self, command: ProtocolApplicationCommand) -> KernelMutationReceipt: ...


class ApprovalApplicationService(Protocol):
    def execute(self, command: ApprovalApplicationCommand) -> KernelMutationReceipt: ...


class AuthorityApplicationService(Protocol):
    def authorize(self, request: AuthorityCheckRequest) -> AuthorityDecision: ...


class PublicationApplicationService(Protocol):
    def execute(
        self,
        command: PublicationApplicationCommand,
    ) -> KernelMutationReceipt: ...


class ControlledOperationApplicationService(Protocol):
    def execute(
        self,
        command: ControlledOperationApplicationCommand,
    ) -> KernelMutationReceipt: ...


class ContinuationApplicationService(Protocol):
    def execute(
        self,
        command: ContinuationApplicationCommand,
    ) -> KernelMutationReceipt: ...


class FailureApplicationService(Protocol):
    def record(self, command: FailureRecordCommand) -> KernelMutationReceipt: ...


class CapabilityQueryApplicationService(Protocol):
    def inspect_tools(
        self,
        context: KernelQueryContext,
    ) -> ToolAffordanceSnapshot: ...

    def resolve_routes(
        self,
        context: KernelQueryContext,
        capability_ids: tuple[str, ...],
    ) -> tuple[RouteRef, ...]: ...


class ExtensionInvocationApplicationService(Protocol):
    def execute(
        self,
        command: ExtensionInvocationApplicationCommand,
    ) -> KernelMutationReceipt: ...


class TaskEvidenceApplicationService(Protocol):
    def execute(
        self,
        command: TaskEvidenceApplicationCommand,
    ) -> KernelMutationReceipt: ...

    def validate(
        self,
        context: KernelQueryContext,
        task_id: str,
        evidence_refs: tuple[EvidenceRef, ...],
    ) -> TaskEvidenceValidation: ...


__all__ = [
    "KERNEL_COMMAND_CONTEXT_SCHEMA_VERSION",
    "KERNEL_MUTATION_RECEIPT_SCHEMA_VERSION",
    "KERNEL_QUERY_CONTEXT_SCHEMA_VERSION",
    "ApprovalApplicationCommand",
    "ApprovalApplicationService",
    "ApprovalCommandKind",
    "AuthorityApplicationService",
    "AuthorityCheckRequest",
    "AuthorityDecision",
    "CapabilityQueryApplicationService",
    "ContinuationApplicationCommand",
    "ContinuationApplicationService",
    "ContinuationCommandKind",
    "ControlledOperationApplicationCommand",
    "ControlledOperationApplicationService",
    "ControlledOperationCommandKind",
    "ExtensionInvocationApplicationCommand",
    "ExtensionInvocationApplicationService",
    "ExtensionInvocationCommandKind",
    "FailureApplicationService",
    "FailureRecordCommand",
    "KernelCommandContext",
    "KernelEntityRef",
    "KernelEntitySnapshot",
    "KernelMutationReceipt",
    "KernelQueryContext",
    "ProtocolApplicationCommand",
    "ProtocolApplicationService",
    "ProtocolCommandKind",
    "PublicationApplicationCommand",
    "PublicationApplicationService",
    "PublicationCommandKind",
    "TaskApplicationCommand",
    "TaskApplicationService",
    "TaskCommandKind",
    "TaskEvidenceApplicationCommand",
    "TaskEvidenceApplicationService",
    "TaskEvidenceCommandKind",
    "TaskEvidenceValidation",
]
