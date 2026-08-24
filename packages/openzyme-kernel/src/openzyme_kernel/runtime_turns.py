from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from datetime import datetime
from enum import StrEnum
from typing import Any
from typing import Mapping
from typing import Protocol

from openzyme_contracts import AgentRuntimeSignal
from openzyme_contracts import AgentRuntimeSignalStatus
from openzyme_contracts import ClockPort
from openzyme_contracts import ControlStorePort
from openzyme_contracts import DurableEventRecord
from openzyme_contracts import ExternalEffectCertainty
from openzyme_contracts import FailureActorKind
from openzyme_contracts import FailureClass
from openzyme_contracts import FailureRecoverability
from openzyme_contracts import IdGeneratorPort
from openzyme_contracts import KernelMutationKind
from openzyme_contracts import KernelRecordReaderPort
from openzyme_contracts import KernelStateMutation
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import OutboxRecord
from openzyme_contracts import PrivateDiagnosticRecord
from openzyme_contracts import RetryEligibility
from openzyme_contracts import RuntimeSignalAuthorityLink
from openzyme_contracts import RuntimeTurnContext
from openzyme_contracts import SessionCapabilityBindingRevision
from openzyme_contracts import SessionRuntimeLease
from openzyme_contracts import StructuredFailureContext
from openzyme_contracts import ToolAffordanceSnapshot
from openzyme_contracts import ToolExposureSnapshot
from openzyme_contracts import UnitOfWorkRequest
from openzyme_contracts import WorkflowAuthorityBinding
from openzyme_contracts import WorkflowAuthorityStatus
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import observe_structured_failure
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts import validate_failure_diagnostic_pair
from openzyme_contracts.identity import json_compatible
from openzyme_runtime_spi import AgentRuntimeAdapter
from openzyme_runtime_spi import RuntimeCapabilityGateway
from openzyme_runtime_spi import RuntimeMessage
from openzyme_runtime_spi import RuntimeMessageRole
from openzyme_runtime_spi import RuntimeTurnCommand
from openzyme_runtime_spi import RuntimeTurnDisposition
from openzyme_runtime_spi import RuntimeTurnOutcome
from openzyme_runtime_spi import RuntimeTurnOutcomeReceipt

from .errors import KernelContractError


RUNTIME_OUTCOME_CONSUMPTION_SCHEMA_VERSION = "runtime_outcome_consumption@2"
RUNTIME_CONTINUATION_INTENT_SCHEMA_VERSION = "runtime_continuation_intent@1"
RUNTIME_SETTLEMENT_INTENT_SCHEMA_VERSION = "runtime_settlement_intent@1"
RUNTIME_CONTINUATION_RESUME_VALIDATION_SCHEMA_VERSION = (
    "runtime_continuation_resume_validation@1"
)
_DURABLE_SETTLEMENT_DIAGNOSTIC_CODES = frozenset(
    {
        "runtime_command_outcome_collision",
        "runtime_settlement_identity_missing",
        "runtime_settlement_fence_stale",
        "runtime_settlement_lease_expired",
        "runtime_outcome_receipt_collision",
        "runtime_outcome_failure_collision",
        "runtime_outcome_private_diagnostic_collision",
        "runtime_outcome_message_collision",
        "runtime_canonical_state_stale",
        "runtime_outcome_commit_failed",
    }
)


def _parse_instant(value: str, *, field_name: str) -> datetime:
    try:
        instant = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (AttributeError, ValueError) as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 instant") from exc
    if instant.tzinfo is None:
        raise ValueError(f"{field_name} must include a timezone")
    return instant


def _command_correlation_id(command: RuntimeTurnCommand) -> str | None:
    return next(
        (
            message.correlation_id
            for message in reversed(command.messages)
            if message.correlation_id is not None
        ),
        None,
    )


@dataclass(frozen=True, slots=True)
class RuntimeTurnBudget:
    max_steps: int
    max_duration_seconds: int
    max_input_units: int
    max_output_units: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_steps",
            "max_duration_seconds",
            "max_input_units",
            "max_output_units",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")


@dataclass(frozen=True, slots=True)
class RuntimeTurnAdmission:
    command_id: str
    turn_id: str
    agent_member_id: str
    signal_claim_token: str
    signal: AgentRuntimeSignal
    session_lease: SessionRuntimeLease
    runtime_lease_generation: int
    process_epoch: int
    distribution_id: str
    distribution_manifest_digest: str
    release_identity: LayeredReleaseIdentity
    capability_binding: SessionCapabilityBindingRevision
    affordance_snapshot: ToolAffordanceSnapshot
    workflow_authority: WorkflowAuthorityBinding
    signal_authority_link: RuntimeSignalAuthorityLink
    tool_exposure_snapshot: ToolExposureSnapshot
    context: RuntimeTurnContext
    runtime_adapter_id: str
    runtime_adapter_contract_digest: str
    budget: RuntimeTurnBudget
    messages: tuple[RuntimeMessage, ...]
    observed_at: str
    continuation_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "command_id",
            "turn_id",
            "agent_member_id",
            "signal_claim_token",
            "distribution_id",
            "runtime_adapter_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "distribution_manifest_digest",
            "runtime_adapter_contract_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        for field_name in ("runtime_lease_generation", "process_epoch"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.continuation_id is not None:
            require_identifier(self.continuation_id, field_name="continuation_id")
        if not self.messages or len(self.messages) > 512:
            raise ValueError(
                "runtime admission requires a bounded non-empty message set"
            )
        _parse_instant(self.observed_at, field_name="observed_at")


class RuntimeOutcomeConsumeDisposition(StrEnum):
    ACCEPTED = "accepted"
    DUPLICATE = "duplicate"


class RuntimeContinuationDeliveryStatus(StrEnum):
    PENDING = "pending"
    DELIVERED = "delivered"


@dataclass(frozen=True, slots=True)
class RuntimeContinuationIntent:
    continuation_id: str
    session_id: str
    agent_id: str
    agent_member_id: str
    source_command_id: str
    source_command_digest: str
    source_outcome_id: str
    source_outcome_digest: str
    source_signal_id: str
    source_signal_authority_link_digest: str
    source_workflow_authority_id: str
    source_workflow_authority_epoch: int
    source_workflow_authority_binding_digest: str
    process_epoch: int
    release_digest: str
    extension_bundle_digest: str
    declared_tool_catalog_digest: str
    capability_binding_id: str
    capability_binding_revision: int
    capability_binding_digest: str
    affordance_snapshot_id: str
    affordance_snapshot_digest: str
    delivery_status: RuntimeContinuationDeliveryStatus
    delivery_attempt: int
    created_at: str
    delivery_signal_id: str | None = None
    delivery_signal_authority_link_digest: str | None = None
    delivery_identity_digest: str | None = None
    delivered_at: str | None = None
    recipient_runtime_executed: bool = False
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "continuation_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "source_command_id",
            "source_outcome_id",
            "source_signal_id",
            "source_workflow_authority_id",
            "capability_binding_id",
            "affordance_snapshot_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "source_command_digest",
            "source_outcome_digest",
            "source_signal_authority_link_digest",
            "source_workflow_authority_binding_digest",
            "release_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_digest",
            "affordance_snapshot_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "process_epoch",
            "capability_binding_revision",
            "source_workflow_authority_epoch",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be positive")
        if (
            not isinstance(self.delivery_attempt, int)
            or isinstance(self.delivery_attempt, bool)
            or self.delivery_attempt < 0
        ):
            raise ValueError("delivery_attempt must be non-negative")
        if not isinstance(self.delivery_status, RuntimeContinuationDeliveryStatus):
            raise ValueError("delivery_status must be a closed continuation status")
        if not isinstance(self.recipient_runtime_executed, bool) or not isinstance(
            self.fallback_performed,
            bool,
        ):
            raise ValueError("continuation delivery facts must be booleans")
        _parse_instant(self.created_at, field_name="created_at")
        delivery_fields = (
            self.delivery_signal_id,
            self.delivery_signal_authority_link_digest,
            self.delivery_identity_digest,
            self.delivered_at,
        )
        if self.delivery_status is RuntimeContinuationDeliveryStatus.PENDING:
            if self.delivery_attempt != 0 or any(
                value is not None for value in delivery_fields
            ):
                raise ValueError("pending continuation must not carry delivery facts")
        elif self.delivery_attempt != 1 or any(
            value is None for value in delivery_fields
        ):
            raise ValueError("delivered continuation requires one exact delivery")
        else:
            assert self.delivery_signal_id is not None
            assert self.delivery_signal_authority_link_digest is not None
            assert self.delivery_identity_digest is not None
            assert self.delivered_at is not None
            require_identifier(
                self.delivery_signal_id,
                field_name="delivery_signal_id",
            )
            require_digest(
                self.delivery_signal_authority_link_digest,
                field_name="delivery_signal_authority_link_digest",
            )
            require_digest(
                self.delivery_identity_digest,
                field_name="delivery_identity_digest",
            )
            _parse_instant(self.delivered_at, field_name="delivered_at")
        if self.recipient_runtime_executed or self.fallback_performed:
            raise ValueError("continuation delivery only queues work without fallback")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_CONTINUATION_INTENT_SCHEMA_VERSION,
            "continuation_id": self.continuation_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_member_id": self.agent_member_id,
            "source_command_id": self.source_command_id,
            "source_command_digest": self.source_command_digest,
            "source_outcome_id": self.source_outcome_id,
            "source_outcome_digest": self.source_outcome_digest,
            "source_signal_id": self.source_signal_id,
            "source_signal_authority_link_digest": (
                self.source_signal_authority_link_digest
            ),
            "source_workflow_authority_id": self.source_workflow_authority_id,
            "source_workflow_authority_epoch": (self.source_workflow_authority_epoch),
            "source_workflow_authority_binding_digest": (
                self.source_workflow_authority_binding_digest
            ),
            "process_epoch": self.process_epoch,
            "release_digest": self.release_digest,
            "extension_bundle_digest": self.extension_bundle_digest,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "capability_binding_id": self.capability_binding_id,
            "capability_binding_revision": self.capability_binding_revision,
            "capability_binding_digest": self.capability_binding_digest,
            "affordance_snapshot_id": self.affordance_snapshot_id,
            "affordance_snapshot_digest": self.affordance_snapshot_digest,
            "delivery_status": self.delivery_status.value,
            "delivery_attempt": self.delivery_attempt,
            "delivery_signal_id": self.delivery_signal_id,
            "delivery_signal_authority_link_digest": (
                self.delivery_signal_authority_link_digest
            ),
            "delivery_identity_digest": self.delivery_identity_digest,
            "created_at": self.created_at,
            "delivered_at": self.delivered_at,
            "recipient_runtime_executed": False,
            "fallback_performed": False,
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "RuntimeContinuationIntent":
        value = dict(payload)
        expected = {
            "schema_version",
            "continuation_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "source_command_id",
            "source_command_digest",
            "source_outcome_id",
            "source_outcome_digest",
            "source_signal_id",
            "source_signal_authority_link_digest",
            "source_workflow_authority_id",
            "source_workflow_authority_epoch",
            "source_workflow_authority_binding_digest",
            "process_epoch",
            "release_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_id",
            "capability_binding_revision",
            "capability_binding_digest",
            "affordance_snapshot_id",
            "affordance_snapshot_digest",
            "delivery_status",
            "delivery_attempt",
            "delivery_signal_id",
            "delivery_signal_authority_link_digest",
            "delivery_identity_digest",
            "created_at",
            "delivered_at",
            "recipient_runtime_executed",
            "fallback_performed",
        }
        if (
            set(value) != expected
            or value.get("schema_version") != RUNTIME_CONTINUATION_INTENT_SCHEMA_VERSION
        ):
            raise ValueError("runtime continuation intent has an invalid closed schema")
        for field_name in ("recipient_runtime_executed", "fallback_performed"):
            if not isinstance(value[field_name], bool):
                raise ValueError(
                    f"runtime continuation intent {field_name} must be boolean"
                )
        for field_name in (
            "continuation_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "source_command_id",
            "source_command_digest",
            "source_outcome_id",
            "source_outcome_digest",
            "source_signal_id",
            "source_signal_authority_link_digest",
            "source_workflow_authority_id",
            "source_workflow_authority_binding_digest",
            "release_digest",
            "extension_bundle_digest",
            "declared_tool_catalog_digest",
            "capability_binding_id",
            "capability_binding_digest",
            "affordance_snapshot_id",
            "affordance_snapshot_digest",
            "delivery_status",
            "created_at",
        ):
            if not isinstance(value[field_name], str):
                raise ValueError(
                    f"runtime continuation intent {field_name} must be a string"
                )
        for field_name in (
            "source_workflow_authority_epoch",
            "process_epoch",
            "capability_binding_revision",
            "delivery_attempt",
        ):
            if not isinstance(value[field_name], int) or isinstance(
                value[field_name],
                bool,
            ):
                raise ValueError(
                    f"runtime continuation intent {field_name} must be an integer"
                )
        for field_name in (
            "delivery_signal_id",
            "delivery_signal_authority_link_digest",
            "delivery_identity_digest",
            "delivered_at",
        ):
            if value[field_name] is not None and not isinstance(
                value[field_name],
                str,
            ):
                raise ValueError(
                    f"runtime continuation intent {field_name} must be a string or null"
                )
        return cls(
            continuation_id=str(value["continuation_id"]),
            session_id=str(value["session_id"]),
            agent_id=str(value["agent_id"]),
            agent_member_id=str(value["agent_member_id"]),
            source_command_id=str(value["source_command_id"]),
            source_command_digest=str(value["source_command_digest"]),
            source_outcome_id=str(value["source_outcome_id"]),
            source_outcome_digest=str(value["source_outcome_digest"]),
            source_signal_id=str(value["source_signal_id"]),
            source_signal_authority_link_digest=str(
                value["source_signal_authority_link_digest"]
            ),
            source_workflow_authority_id=str(value["source_workflow_authority_id"]),
            source_workflow_authority_epoch=int(
                value["source_workflow_authority_epoch"]
            ),
            source_workflow_authority_binding_digest=str(
                value["source_workflow_authority_binding_digest"]
            ),
            process_epoch=int(value["process_epoch"]),
            release_digest=str(value["release_digest"]),
            extension_bundle_digest=str(value["extension_bundle_digest"]),
            declared_tool_catalog_digest=str(value["declared_tool_catalog_digest"]),
            capability_binding_id=str(value["capability_binding_id"]),
            capability_binding_revision=int(value["capability_binding_revision"]),
            capability_binding_digest=str(value["capability_binding_digest"]),
            affordance_snapshot_id=str(value["affordance_snapshot_id"]),
            affordance_snapshot_digest=str(value["affordance_snapshot_digest"]),
            delivery_status=RuntimeContinuationDeliveryStatus(
                str(value["delivery_status"])
            ),
            delivery_attempt=int(value["delivery_attempt"]),
            delivery_signal_id=(
                None
                if value["delivery_signal_id"] is None
                else str(value["delivery_signal_id"])
            ),
            delivery_signal_authority_link_digest=(
                None
                if value["delivery_signal_authority_link_digest"] is None
                else str(value["delivery_signal_authority_link_digest"])
            ),
            delivery_identity_digest=(
                None
                if value["delivery_identity_digest"] is None
                else str(value["delivery_identity_digest"])
            ),
            created_at=str(value["created_at"]),
            delivered_at=(
                None if value["delivered_at"] is None else str(value["delivered_at"])
            ),
            recipient_runtime_executed=value["recipient_runtime_executed"],
            fallback_performed=value["fallback_performed"],
        )


@dataclass(frozen=True, slots=True)
class RuntimeContinuationResumeValidation:
    continuation_id: str
    conversation_resume_allowed: bool
    dispatch_allowed: bool
    blocker_code: str | None
    mutation_applied: bool = False
    fallback_performed: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.continuation_id, field_name="continuation_id")
        if not self.conversation_resume_allowed:
            raise ValueError("hard continuation rejection must raise a Kernel error")
        if self.dispatch_allowed != (self.blocker_code is None):
            raise ValueError(
                "dispatch permission and blocker identity are inconsistent"
            )
        if self.blocker_code is not None:
            require_identifier(self.blocker_code, field_name="blocker_code")
        if self.mutation_applied or self.fallback_performed:
            raise ValueError(
                "continuation validation is read-only and never falls back"
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": (RUNTIME_CONTINUATION_RESUME_VALIDATION_SCHEMA_VERSION),
            "continuation_id": self.continuation_id,
            "conversation_resume_allowed": self.conversation_resume_allowed,
            "dispatch_allowed": self.dispatch_allowed,
            "blocker_code": self.blocker_code,
            "mutation_applied": False,
            "fallback_performed": False,
        }


def validate_runtime_continuation_resume(
    intent: RuntimeContinuationIntent,
    command: RuntimeTurnCommand,
) -> RuntimeContinuationResumeValidation:
    """Validate one saved continuation without replay, conversion, or mutation."""

    hard_identity = {
        "continuation_id": (intent.continuation_id, command.continuation_id),
        "session_id": (intent.session_id, command.session_id),
        "agent_id": (intent.agent_id, command.agent_id),
        "agent_member_id": (intent.agent_member_id, command.agent_member_id),
        "process_epoch": (intent.process_epoch, command.process_epoch),
        "release_digest": (intent.release_digest, command.release_digest),
        "extension_bundle_digest": (
            intent.extension_bundle_digest,
            command.extension_bundle_digest,
        ),
        "declared_tool_catalog_digest": (
            intent.declared_tool_catalog_digest,
            command.declared_tool_catalog_digest,
        ),
        "workflow_authority_id": (
            intent.source_workflow_authority_id,
            command.workflow_authority_id,
        ),
        "workflow_authority_epoch": (
            intent.source_workflow_authority_epoch,
            command.workflow_authority_epoch,
        ),
        "workflow_authority_digest": (
            intent.source_workflow_authority_binding_digest,
            command.workflow_authority_digest,
        ),
        "delivery_signal_id": (intent.delivery_signal_id, command.signal_id),
        "delivery_signal_authority_link_digest": (
            intent.delivery_signal_authority_link_digest,
            command.signal_authority_link_digest,
        ),
    }
    drifted = sorted(
        field_name
        for field_name, (expected, observed) in hard_identity.items()
        if expected != observed
    )
    if drifted:
        raise KernelContractError(
            "runtime_continuation_contract_stale",
            "saved continuation differs from the exact runtime contract identity",
            details={
                "continuation_id": intent.continuation_id,
                "drifted_fields": drifted,
                "mutation_applied": False,
                "fallback_performed": False,
            },
        )
    binding_matches = (
        intent.capability_binding_id == command.capability_binding_id
        and intent.capability_binding_revision == command.capability_binding_revision
        and intent.capability_binding_digest == command.capability_binding_digest
    )
    snapshot_matches = (
        intent.affordance_snapshot_id == command.affordance_snapshot_id
        and intent.affordance_snapshot_digest == command.affordance_snapshot_digest
    )
    blocker = None
    if not binding_matches:
        blocker = "runtime_continuation_binding_stale"
    elif not snapshot_matches:
        blocker = "runtime_continuation_affordance_stale"
    return RuntimeContinuationResumeValidation(
        continuation_id=intent.continuation_id,
        conversation_resume_allowed=True,
        dispatch_allowed=blocker is None,
        blocker_code=blocker,
    )


@dataclass(frozen=True, slots=True)
class RuntimeSettlementIntent:
    settlement_id: str
    session_id: str
    agent_id: str
    agent_member_id: str
    signal_id: str
    signal_attempt: int
    source_command_id: str
    source_command_digest: str
    source_outcome_id: str
    source_outcome_digest: str
    disposition: RuntimeTurnDisposition
    waiting_approval_id: str | None
    failure_id: str | None
    task_transition_performed: bool = False

    def __post_init__(self) -> None:
        for field_name in (
            "settlement_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
            "source_command_id",
            "source_outcome_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.source_command_digest, field_name="source_command_digest")
        require_digest(self.source_outcome_digest, field_name="source_outcome_digest")
        if self.signal_attempt < 1:
            raise ValueError("signal_attempt must be positive")
        for field_name in ("waiting_approval_id", "failure_id"):
            value = getattr(self, field_name)
            if value is not None:
                require_identifier(value, field_name=field_name)
        if self.task_transition_performed:
            raise ValueError("runtime settlement must not perform a Task transition")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_SETTLEMENT_INTENT_SCHEMA_VERSION,
            "settlement_id": self.settlement_id,
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_member_id": self.agent_member_id,
            "signal_id": self.signal_id,
            "signal_attempt": self.signal_attempt,
            "source_command_id": self.source_command_id,
            "source_command_digest": self.source_command_digest,
            "source_outcome_id": self.source_outcome_id,
            "source_outcome_digest": self.source_outcome_digest,
            "disposition": self.disposition.value,
            "waiting_approval_id": self.waiting_approval_id,
            "failure_id": self.failure_id,
            "task_transition_performed": False,
        }


@dataclass(frozen=True, slots=True)
class RuntimeOutcomeConsumption:
    consumption_id: str
    command_id: str
    command_digest: str
    outcome_id: str
    outcome_digest: str
    outcome_receipt: RuntimeTurnOutcomeReceipt
    session_id: str
    agent_id: str
    agent_member_id: str
    signal_id: str
    signal_attempt: int
    continuation_intent: RuntimeContinuationIntent | None
    settlement_intent: RuntimeSettlementIntent
    consumed_at: str
    private_diagnostic: PrivateDiagnosticRecord | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        for field_name in (
            "consumption_id",
            "command_id",
            "outcome_id",
            "session_id",
            "agent_id",
            "agent_member_id",
            "signal_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.command_digest, field_name="command_digest")
        require_digest(self.outcome_digest, field_name="outcome_digest")
        if (
            self.outcome_receipt.outcome.command_id != self.command_id
            or self.outcome_receipt.outcome.command_digest != self.command_digest
            or self.outcome_receipt.outcome.outcome_id != self.outcome_id
            or self.outcome_receipt.outcome.outcome_digest != self.outcome_digest
            or self.outcome_receipt.outcome.session_id != self.session_id
            or self.outcome_receipt.outcome.agent_id != self.agent_id
            or self.outcome_receipt.outcome.agent_member_id != self.agent_member_id
            or self.outcome_receipt.outcome.signal_id != self.signal_id
            or self.outcome_receipt.outcome.signal_attempt != self.signal_attempt
        ):
            raise ValueError(
                "runtime outcome receipt identity differs from consumption"
            )
        if self.signal_attempt < 1:
            raise ValueError("signal_attempt must be positive")
        outcome = self.outcome_receipt.outcome
        if self.private_diagnostic is not outcome.private_diagnostic:
            if (
                self.private_diagnostic is None
                or outcome.private_diagnostic is None
                or self.private_diagnostic.record_digest
                != outcome.private_diagnostic.record_digest
            ):
                raise ValueError(
                    "runtime consumption private diagnostic differs from outcome"
                )
        if self.private_diagnostic is not None:
            if outcome.failure is None:
                raise ValueError("runtime private diagnostic lacks a failure")
            validate_failure_diagnostic_pair(
                outcome.failure,
                self.private_diagnostic,
            )
        _parse_instant(self.consumed_at, field_name="consumed_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RUNTIME_OUTCOME_CONSUMPTION_SCHEMA_VERSION,
            "consumption_id": self.consumption_id,
            "command_id": self.command_id,
            "command_digest": self.command_digest,
            "outcome_id": self.outcome_id,
            "outcome_digest": self.outcome_digest,
            "outcome_receipt": self.outcome_receipt.to_dict(),
            "session_id": self.session_id,
            "agent_id": self.agent_id,
            "agent_member_id": self.agent_member_id,
            "signal_id": self.signal_id,
            "signal_attempt": self.signal_attempt,
            "continuation_intent": (
                None
                if self.continuation_intent is None
                else self.continuation_intent.to_dict()
            ),
            "settlement_intent": self.settlement_intent.to_dict(),
            "consumed_at": self.consumed_at,
        }

    @property
    def consumption_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class RuntimeOutcomeConsumeResult:
    disposition: RuntimeOutcomeConsumeDisposition
    command_digest: str
    outcome_digest: str
    consumption_digest: str

    def __post_init__(self) -> None:
        require_digest(self.command_digest, field_name="command_digest")
        require_digest(self.outcome_digest, field_name="outcome_digest")
        require_digest(self.consumption_digest, field_name="consumption_digest")


class RuntimeOutcomeRepository(Protocol):
    """Atomically persist one consumption and its continuation/settlement outbox."""

    def consume(
        self,
        consumption: RuntimeOutcomeConsumption,
    ) -> RuntimeOutcomeConsumeResult: ...


class ControlStoreRuntimeOutcomeRepository:
    """Once-only command/outcome owner over the generic ControlStore Port.

    Runtime Adapters never receive a writer.  The Host first registers the exact
    command, then the coordinator validates an Adapter outcome and asks this owner to
    atomically settle the signal plus continuation/settlement intents.  No Task record
    is read or mutated here.
    """

    def __init__(
        self,
        *,
        store: ControlStorePort,
        reader: KernelRecordReaderPort,
        clock: ClockPort,
        ids: IdGeneratorPort,
    ) -> None:
        self._store = store
        self._reader = reader
        self._clock = clock
        self._ids = ids

    def register_command(
        self,
        command: RuntimeTurnCommand,
        *,
        tool_exposure_snapshot: ToolExposureSnapshot | None = None,
    ) -> str:
        if tool_exposure_snapshot is not None and (
            tool_exposure_snapshot.exposure_snapshot_id
            != command.tool_exposure_snapshot_id
            or tool_exposure_snapshot.exposure_snapshot_digest
            != command.tool_exposure_snapshot_digest
        ):
            raise KernelContractError(
                "runtime_tool_exposure_snapshot_identity_conflict",
                "Runtime command and supplied tool exposure snapshot differ",
            )
        existing = self._reader.read(
            entity_type="runtime_turn_command", entity_id=command.command_id
        )
        if existing is not None:
            if existing.payload.get("command_digest") != command.command_digest:
                raise KernelContractError(
                    "runtime_command_identity_conflict",
                    "Runtime command identity already names another command",
                )
            existing_exposure = self._reader.read(
                entity_type="tool_exposure_snapshot",
                entity_id=command.tool_exposure_snapshot_id,
            )
            if (
                existing_exposure is None
                or existing_exposure.payload.get("exposure_snapshot_digest")
                != command.tool_exposure_snapshot_digest
            ):
                raise KernelContractError(
                    "runtime_command_identity_missing",
                    "Admitted runtime command lacks its exact tool exposure snapshot",
                )
            return command.command_digest
        (
            session,
            signal,
            lease,
            member,
            workflow,
            signal_link,
            exposure,
        ) = self._require_live_command_identity(
            command,
            tool_exposure_snapshot=tool_exposure_snapshot,
        )
        context_record = self._reader.read(
            entity_type="runtime_turn_context",
            entity_id=command.context.context_id,
        )
        if context_record is not None and (
            context_record.payload.get("context_digest")
            != command.context.context_digest
        ):
            raise KernelContractError(
                "runtime_turn_context_identity_conflict",
                "Runtime context identity already names different canonical facts",
            )
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=command.command_id,
            session_id=command.session_id,
            actor_id=command.agent_member_id,
            authority_lease_id=str(signal.payload["capability_lease_id"]),
            authority_generation=command.runtime_lease_generation,
            authority_fence=command.runtime_fence,
            expected_session_version=session.state_version,
            idempotency_key=f"runtime-command:{command.command_id}",
            command_digest=command.command_digest,
        )
        unit = self._store.begin(request)
        try:
            for record in (
                session,
                signal,
                lease,
                member,
                workflow,
                signal_link,
            ):
                self._require_same_record(unit, record)
            if exposure is None:
                assert tool_exposure_snapshot is not None
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="tool_exposure_snapshot",
                        entity_id=tool_exposure_snapshot.exposure_snapshot_id,
                        expected_state_version=None,
                        payload=tool_exposure_snapshot.to_dict(),
                    )
                )
            else:
                self._require_same_record(unit, exposure)
            if context_record is None:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="runtime_turn_context",
                        entity_id=command.context.context_id,
                        expected_state_version=None,
                        payload=command.context.to_dict(),
                    )
                )
            else:
                self._require_same_record(unit, context_record)
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="runtime_turn_command",
                    entity_id=command.command_id,
                    expected_state_version=None,
                    payload=command.to_dict(),
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=command.session_id,
                event_type="runtime.command.admitted",
                source_entity_type="runtime_turn_command",
                source_entity_id=command.command_id,
                source_state_version=1,
                command_id=command.command_id,
                payload={
                    "command_id": command.command_id,
                    "command_digest": command.command_digest,
                    "signal_id": command.signal_id,
                    "workflow_authority_id": command.workflow_authority_id,
                    "workflow_authority_epoch": command.workflow_authority_epoch,
                    "tool_exposure_snapshot_id": command.tool_exposure_snapshot_id,
                    "context_id": command.context.context_id,
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=command.session_id,
                    topic="openzyme.kernel.runtime-command-events",
                    occurrence_id=event.event_id,
                    payload={
                        "event_id": event.event_id,
                        "command_id": command.command_id,
                        "command_digest": command.command_digest,
                    },
                    payload_digest=canonical_sha256_digest(
                        {
                            "event_id": event.event_id,
                            "command_id": command.command_id,
                            "command_digest": command.command_digest,
                        }
                    ),
                    created_at=self._clock.now_iso(),
                )
            )
            receipt = unit.commit()
        except Exception:
            unit.rollback()
            raise
        if not receipt.committed:
            raise KernelContractError(
                "runtime_command_commit_failed", "Runtime command was not committed"
            )
        return command.command_digest

    def consume(
        self,
        consumption: RuntimeOutcomeConsumption,
    ) -> RuntimeOutcomeConsumeResult:
        """Settle once, recording stale/collision rejection as a new occurrence."""

        try:
            return self._consume_once(consumption)
        except KernelContractError as exc:
            if exc.code not in _DURABLE_SETTLEMENT_DIAGNOSTIC_CODES:
                raise
            try:
                self._record_settlement_diagnostic(consumption, exc)
            except Exception as diagnostic_error:
                rejected = KernelContractError(
                    "runtime_settlement_diagnostic_record_failed",
                    "Runtime settlement was rejected and its diagnostic could not be recorded",
                    details={
                        "source_error_code": exc.code,
                        "diagnostic_recorded": False,
                        "mutation_applied": False,
                        "fallback_performed": False,
                    },
                )
                rejected.add_note(
                    f"diagnostic writer failed with {type(diagnostic_error).__name__}"
                )
                raise rejected from diagnostic_error
            raise

    def _consume_once(
        self,
        consumption: RuntimeOutcomeConsumption,
    ) -> RuntimeOutcomeConsumeResult:
        existing = self._reader.read(
            entity_type="runtime_outcome_consumption",
            entity_id=consumption.command_id,
        )
        if existing is not None:
            if (
                existing.payload.get("command_digest") != consumption.command_digest
                or existing.payload.get("outcome_digest") != consumption.outcome_digest
            ):
                raise KernelContractError(
                    "runtime_command_outcome_collision",
                    "One RuntimeCommand cannot consume another outcome",
                )
            self._require_existing_failure_pair(consumption)
            return RuntimeOutcomeConsumeResult(
                disposition=RuntimeOutcomeConsumeDisposition.DUPLICATE,
                command_digest=consumption.command_digest,
                outcome_digest=consumption.outcome_digest,
                consumption_digest=str(existing.payload["consumption_digest"]),
            )
        command_record = self._reader.read(
            entity_type="runtime_turn_command", entity_id=consumption.command_id
        )
        if (
            command_record is None
            or command_record.payload.get("command_digest")
            != consumption.command_digest
        ):
            raise KernelContractError(
                "runtime_command_not_admitted",
                "Runtime outcome has no exact canonical command",
            )
        signal = self._reader.read(
            entity_type="agent_runtime_signal", entity_id=consumption.signal_id
        )
        lease = self._reader.read(
            entity_type="session_runtime_lease", entity_id=consumption.session_id
        )
        member = self._reader.read(
            entity_type="agent_member", entity_id=consumption.agent_member_id
        )
        workflow = self._reader.read(
            entity_type="workflow_authority_binding",
            entity_id=str(command_record.payload.get("workflow_authority_id")),
        )
        signal_link = self._reader.read(
            entity_type="runtime_signal_authority_link",
            entity_id=consumption.signal_id,
        )
        exposure = self._reader.read(
            entity_type="tool_exposure_snapshot",
            entity_id=str(command_record.payload.get("tool_exposure_snapshot_id")),
        )
        if any(
            record is None
            for record in (signal, lease, member, workflow, signal_link, exposure)
        ):
            raise KernelContractError(
                "runtime_settlement_identity_missing",
                "Runtime settlement canonical identity is incomplete",
            )
        assert signal is not None
        assert lease is not None
        assert member is not None
        assert workflow is not None
        assert signal_link is not None
        assert exposure is not None
        command_payload = command_record.payload
        outcome = consumption.outcome_receipt.outcome
        if (
            signal.payload.get("status") != "claimed"
            or signal.payload.get("attempt_count") != consumption.signal_attempt
            or signal.payload.get("session_lease_token")
            != command_payload.get("runtime_lease_token")
            or signal.payload.get("session_fencing_token")
            != command_payload.get("runtime_fence")
            or lease.payload.get("lease_token")
            != command_payload.get("runtime_lease_token")
            or lease.payload.get("fencing_token")
            != command_payload.get("runtime_fence")
            or lease.payload.get("generation")
            != command_payload.get("runtime_lease_generation")
            or lease.payload.get("released_at") is not None
            or member.payload.get("process_epoch")
            != command_payload.get("process_epoch")
            or member.payload.get("status")
            in {
                "completed",
                "failed",
                "stopped",
                "shutdown",
            }
            or workflow.payload.get("status") != "active"
            or workflow.payload.get("epoch")
            != command_payload.get("workflow_authority_epoch")
            or workflow.payload.get("binding_digest")
            != command_payload.get("workflow_authority_digest")
            or signal_link.payload.get("link_digest")
            != command_payload.get("signal_authority_link_digest")
            or signal_link.payload.get("authority_id")
            != command_payload.get("workflow_authority_id")
            or exposure.payload.get("exposure_snapshot_digest")
            != command_payload.get("tool_exposure_snapshot_digest")
            or outcome.task_id != signal.payload.get("task_id")
            or outcome.lane_id != signal.payload.get("lane_id")
            or outcome.correlation_id != signal.payload.get("correlation_id")
        ):
            raise KernelContractError(
                "runtime_settlement_fence_stale",
                "Runtime outcome differs from current signal/lease/process epoch",
            )
        if _parse_instant(
            str(lease.payload["expires_at"]), field_name="lease.expires_at"
        ) <= _parse_instant(self._clock.now_iso(), field_name="now"):
            raise KernelContractError(
                "runtime_settlement_lease_expired",
                "Runtime outcome arrived after Session lease expiry",
            )
        conversation_payloads = self._preflight_outcome_records(consumption)
        session = self._reader.read(
            entity_type="session", entity_id=consumption.session_id
        )
        if session is None:
            raise KernelContractError("session_not_found", "Runtime Session is absent")
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=consumption.command_id,
            session_id=consumption.session_id,
            actor_id=consumption.agent_member_id,
            authority_lease_id=str(signal.payload["capability_lease_id"]),
            authority_generation=int(lease.payload["generation"]),
            authority_fence=int(lease.payload["fencing_token"]),
            expected_session_version=session.state_version,
            idempotency_key=f"runtime-outcome:{consumption.command_id}",
            command_digest=consumption.command_digest,
        )
        unit = self._store.begin(request)
        try:
            for record in (
                session,
                command_record,
                signal,
                lease,
                member,
                workflow,
                signal_link,
                exposure,
            ):
                self._require_same_record(unit, record)
            failure = consumption.outcome_receipt.outcome.failure
            if failure is not None:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="failure_observation",
                        entity_id=failure.failure_id,
                        expected_state_version=None,
                        payload=failure.to_internal_dict(),
                    )
                )
            private_diagnostic = consumption.private_diagnostic
            if private_diagnostic is not None:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="private_diagnostic",
                        entity_id=private_diagnostic.diagnostic_id,
                        expected_state_version=None,
                        payload=private_diagnostic.to_dict(),
                    )
                )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="runtime_turn_outcome",
                    entity_id=consumption.outcome_receipt.receipt_id,
                    expected_state_version=None,
                    payload=consumption.outcome_receipt.to_dict(),
                )
            )
            for message_id, payload in conversation_payloads:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="conversation_message",
                        entity_id=message_id,
                        expected_state_version=None,
                        payload=payload,
                    )
                )
            terminal_signal = dict(signal.payload)
            terminal_signal.update(
                {
                    "status": (
                        "failed"
                        if consumption.settlement_intent.disposition
                        is RuntimeTurnDisposition.FAILED
                        else "completed"
                    ),
                    "completed_at": consumption.consumed_at,
                    "claim_expires_at": None,
                    "error_message": (
                        consumption.settlement_intent.failure_id
                        if consumption.settlement_intent.disposition
                        is RuntimeTurnDisposition.FAILED
                        else None
                    ),
                }
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.REPLACE,
                    entity_type="agent_runtime_signal",
                    entity_id=consumption.signal_id,
                    expected_state_version=signal.state_version,
                    payload=terminal_signal,
                )
            )
            consumption_payload = {
                **consumption.to_dict(),
                "consumption_digest": consumption.consumption_digest,
            }
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="runtime_outcome_consumption",
                    entity_id=consumption.command_id,
                    expected_state_version=None,
                    payload=consumption_payload,
                )
            )
            if consumption.continuation_intent is not None:
                unit.stage(
                    KernelStateMutation.create(
                        mutation_id=self._ids.new_id(namespace="mutation"),
                        kind=KernelMutationKind.CREATE,
                        entity_type="runtime_continuation_intent",
                        entity_id=consumption.continuation_intent.continuation_id,
                        expected_state_version=None,
                        payload=consumption.continuation_intent.to_dict(),
                    )
                )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="runtime_settlement_intent",
                    entity_id=consumption.settlement_intent.settlement_id,
                    expected_state_version=None,
                    payload=consumption.settlement_intent.to_dict(),
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=consumption.session_id,
                event_type="runtime.outcome.consumed",
                source_entity_type="runtime_outcome_consumption",
                source_entity_id=consumption.command_id,
                source_state_version=1,
                command_id=consumption.command_id,
                payload={
                    "command_id": consumption.command_id,
                    "outcome_id": consumption.outcome_id,
                    "outcome_digest": consumption.outcome_digest,
                    "outcome_receipt_id": consumption.outcome_receipt.receipt_id,
                    "outcome_receipt_digest": (
                        consumption.outcome_receipt.receipt_digest
                    ),
                    "disposition": consumption.settlement_intent.disposition.value,
                    "message_ids": [
                        message.message_id
                        for message in consumption.outcome_receipt.outcome.messages
                    ],
                    "failure_id": (
                        None
                        if consumption.outcome_receipt.outcome.failure is None
                        else consumption.outcome_receipt.outcome.failure.failure_id
                    ),
                    "task_transition_performed": False,
                },
            )
            unit.append_event(event)
            topics = ["openzyme.kernel.runtime-settlement"]
            if consumption.continuation_intent is not None:
                topics.append("openzyme.kernel.runtime-continuation")
            for topic in topics:
                payload = {
                    "event_id": event.event_id,
                    "command_id": consumption.command_id,
                    "consumption_digest": consumption.consumption_digest,
                    "topic": topic,
                }
                unit.append_outbox(
                    OutboxRecord(
                        outbox_id=self._ids.new_id(namespace="outbox"),
                        session_id=consumption.session_id,
                        topic=topic,
                        occurrence_id=event.event_id,
                        payload=payload,
                        payload_digest=canonical_sha256_digest(payload),
                        created_at=self._clock.now_iso(),
                    )
                )
            receipt = unit.commit()
        except Exception:
            unit.rollback()
            raise
        if not receipt.committed:
            raise KernelContractError(
                "runtime_outcome_commit_failed", "Runtime outcome was not committed"
            )
        return RuntimeOutcomeConsumeResult(
            disposition=RuntimeOutcomeConsumeDisposition.ACCEPTED,
            command_digest=consumption.command_digest,
            outcome_digest=consumption.outcome_digest,
            consumption_digest=consumption.consumption_digest,
        )

    def _preflight_outcome_records(
        self,
        consumption: RuntimeOutcomeConsumption,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        receipt = consumption.outcome_receipt
        existing_receipt = self._reader.read(
            entity_type="runtime_turn_outcome",
            entity_id=receipt.receipt_id,
        )
        if existing_receipt is not None:
            raise KernelContractError(
                "runtime_outcome_receipt_collision",
                "Outcome receipt exists without the exact consumption marker",
                details={
                    "receipt_id": receipt.receipt_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        failure = receipt.outcome.failure
        if (
            failure is not None
            and self._reader.read(
                entity_type="failure_observation",
                entity_id=failure.failure_id,
            )
            is not None
        ):
            raise KernelContractError(
                "runtime_outcome_failure_collision",
                "Runtime outcome failure identity already exists",
                details={
                    "failure_id": failure.failure_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        private_diagnostic = consumption.private_diagnostic
        if (
            private_diagnostic is not None
            and self._reader.read(
                entity_type="private_diagnostic",
                entity_id=private_diagnostic.diagnostic_id,
            )
            is not None
        ):
            raise KernelContractError(
                "runtime_outcome_private_diagnostic_collision",
                "Runtime outcome private diagnostic identity already exists",
                details={
                    "diagnostic_id": private_diagnostic.diagnostic_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        payloads = self._conversation_payloads(receipt)
        collisions = tuple(
            message_id
            for message_id, _ in payloads
            if self._reader.read(
                entity_type="conversation_message",
                entity_id=message_id,
            )
            is not None
        )
        if collisions:
            raise KernelContractError(
                "runtime_outcome_message_collision",
                "Runtime output message identity already exists",
                details={
                    "message_ids": collisions,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        return payloads

    def _require_existing_failure_pair(
        self,
        consumption: RuntimeOutcomeConsumption,
    ) -> None:
        failure = consumption.outcome_receipt.outcome.failure
        if failure is None:
            return
        existing_failure = self._reader.read(
            entity_type="failure_observation",
            entity_id=failure.failure_id,
        )
        if (
            existing_failure is None
            or json_compatible(existing_failure.payload) != failure.to_internal_dict()
        ):
            raise KernelContractError(
                "runtime_outcome_failure_collision",
                "Duplicate Runtime outcome differs from its durable failure pair",
                details={
                    "failure_id": failure.failure_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        private_diagnostic = consumption.private_diagnostic
        if private_diagnostic is None:
            return
        existing_private = self._reader.read(
            entity_type="private_diagnostic",
            entity_id=private_diagnostic.diagnostic_id,
        )
        if (
            existing_private is None
            or json_compatible(existing_private.payload) != private_diagnostic.to_dict()
        ):
            raise KernelContractError(
                "runtime_outcome_private_diagnostic_collision",
                "Duplicate Runtime outcome differs from its private diagnostic",
                details={
                    "diagnostic_id": private_diagnostic.diagnostic_id,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )

    def _record_settlement_diagnostic(
        self,
        consumption: RuntimeOutcomeConsumption,
        error: KernelContractError,
    ) -> None:
        suffix = canonical_sha256_digest(
            {
                "command_id": consumption.command_id,
                "outcome_digest": consumption.outcome_digest,
                "error_code": error.code,
            }
        ).removeprefix("sha256:")[:24]
        failure_id = f"failure_settlement_{suffix}"
        diagnostic_id = f"diagnostic_settlement_{suffix}"
        outcome = consumption.outcome_receipt.outcome
        records = observe_structured_failure(
            error,
            context=StructuredFailureContext(
                failure_id=failure_id,
                diagnostic_id=diagnostic_id,
                session_id=consumption.session_id,
                component="openzyme.kernel.runtime-outcome-repository",
                operation="consume_outcome",
                phase="outcome_settlement",
                source_kind="runtime_outcome_settlement",
                source_ref=consumption.command_id,
                source_version=consumption.outcome_digest,
                # The diagnostic occurrence is derived from this exact settlement
                # attempt.  Reuse its canonical timestamp so an advancing wall
                # clock cannot turn an exact retry (including after restart) into
                # a different public/private pair.
                created_at=consumption.consumed_at,
                task_id=outcome.task_id,
                lane_id=outcome.lane_id,
                agent_id=consumption.agent_id,
                correlation_id=outcome.correlation_id,
            ),
            failure_class=FailureClass.RUNTIME,
            recoverability=FailureRecoverability.TERMINAL,
            effect_certainty=ExternalEffectCertainty.NO_EFFECT,
            retry_eligibility=RetryEligibility.TERMINAL,
            actor_kind=FailureActorKind.HARNESS,
            error_code=error.code,
            safe_summary=(
                "Runtime outcome settlement was rejected before any partial mutation."
            ),
            safe_hint=(
                "Refresh the exact command, signal, lease, workflow, transcript, and "
                "failure identities before a new occurrence."
            ),
            next_action="inspect_settlement_diagnostic",
            mutation_applied=False,
            fallback_performed=False,
            reconcile_required=False,
            public_facts={
                "prior_output_message_count": len(outcome.messages),
                "prior_tool_request_count": len(outcome.tool_requests),
            },
            identities={
                "command_id": consumption.command_id,
                "signal_id": consumption.signal_id,
            },
            likely_causes=(
                "A current settlement fence or immutable outcome identity changed.",
            ),
            private_context={
                "error_details": error.details,
                "consumption": consumption.to_dict(),
            },
        )
        existing_failure = self._reader.read(
            entity_type="failure_observation",
            entity_id=failure_id,
        )
        existing_private = self._reader.read(
            entity_type="private_diagnostic",
            entity_id=diagnostic_id,
        )
        if existing_failure is not None or existing_private is not None:
            if (
                existing_failure is not None
                and existing_private is not None
                and json_compatible(existing_failure.payload)
                == records.public.to_internal_dict()
                and json_compatible(existing_private.payload)
                == records.private.to_dict()
            ):
                return
            raise KernelContractError(
                "runtime_settlement_diagnostic_collision",
                "Settlement diagnostic identity already names another occurrence",
                details={
                    "diagnostic_id": diagnostic_id,
                    "diagnostic_recorded": False,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        session = self._reader.read(
            entity_type="session",
            entity_id=consumption.session_id,
        )
        signal = self._reader.read(
            entity_type="agent_runtime_signal",
            entity_id=consumption.signal_id,
        )
        lease = self._reader.read(
            entity_type="session_runtime_lease",
            entity_id=consumption.session_id,
        )
        member = self._reader.read(
            entity_type="agent_member",
            entity_id=consumption.agent_member_id,
        )
        if any(record is None for record in (session, signal, lease, member)):
            raise KernelContractError(
                "runtime_settlement_diagnostic_authority_missing",
                "Current canonical authority cannot record settlement diagnostics",
                details={
                    "diagnostic_id": diagnostic_id,
                    "diagnostic_recorded": False,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
        assert session is not None
        assert signal is not None
        assert lease is not None
        assert member is not None
        diagnostic_command_id = f"settlement-diagnostic-{suffix}"
        request = UnitOfWorkRequest(
            unit_of_work_id=self._ids.new_id(namespace="uow"),
            command_id=diagnostic_command_id,
            session_id=consumption.session_id,
            actor_id=consumption.agent_member_id,
            authority_lease_id=str(signal.payload["capability_lease_id"]),
            authority_generation=int(lease.payload["generation"]),
            authority_fence=int(lease.payload["fencing_token"]),
            expected_session_version=session.state_version,
            idempotency_key=f"runtime-settlement-diagnostic:{suffix}",
            command_digest=canonical_sha256_digest(
                {
                    "public": records.public.to_internal_dict(),
                    "private_digest": records.private.record_digest,
                }
            ),
        )
        unit = self._store.begin(request)
        try:
            for current in (session, signal, lease, member):
                self._require_same_record(unit, current)
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="failure_observation",
                    entity_id=failure_id,
                    expected_state_version=None,
                    payload=records.public.to_internal_dict(),
                )
            )
            unit.stage(
                KernelStateMutation.create(
                    mutation_id=self._ids.new_id(namespace="mutation"),
                    kind=KernelMutationKind.CREATE,
                    entity_type="private_diagnostic",
                    entity_id=diagnostic_id,
                    expected_state_version=None,
                    payload=records.private.to_dict(),
                )
            )
            event = DurableEventRecord.create(
                event_id=self._ids.new_id(namespace="event"),
                session_id=consumption.session_id,
                event_type="runtime.outcome.settlement_rejected",
                source_entity_type="failure_observation",
                source_entity_id=failure_id,
                source_state_version=1,
                command_id=diagnostic_command_id,
                payload={
                    "failure_id": failure_id,
                    "diagnostic_id": diagnostic_id,
                    "source_command_id": consumption.command_id,
                    "source_outcome_id": consumption.outcome_id,
                    "error_code": error.code,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )
            unit.append_event(event)
            outbox_payload = {
                "event_id": event.event_id,
                "failure_id": failure_id,
                "diagnostic_id": diagnostic_id,
                "source_command_id": consumption.command_id,
            }
            unit.append_outbox(
                OutboxRecord(
                    outbox_id=self._ids.new_id(namespace="outbox"),
                    session_id=consumption.session_id,
                    topic="openzyme.kernel.runtime-settlement-diagnostics",
                    occurrence_id=event.event_id,
                    payload=outbox_payload,
                    payload_digest=canonical_sha256_digest(outbox_payload),
                    created_at=self._clock.now_iso(),
                )
            )
            receipt = unit.commit()
        except Exception:
            unit.rollback()
            raise
        if not receipt.committed:
            raise KernelContractError(
                "runtime_settlement_diagnostic_commit_failed",
                "Settlement diagnostic Unit of Work did not commit",
                details={
                    "diagnostic_id": diagnostic_id,
                    "diagnostic_recorded": False,
                    "mutation_applied": False,
                    "fallback_performed": False,
                },
            )

    @staticmethod
    def _conversation_payloads(
        receipt: RuntimeTurnOutcomeReceipt,
    ) -> tuple[tuple[str, dict[str, Any]], ...]:
        outcome = receipt.outcome
        rows: list[tuple[str, dict[str, Any]]] = []
        for message in outcome.messages:
            message_type = (
                "assistant_message"
                if message.role is RuntimeMessageRole.ASSISTANT
                else "tool_message"
            )
            rows.append(
                (
                    message.message_id,
                    {
                        "message_id": message.message_id,
                        "session_id": outcome.session_id,
                        "sender_actor_id": outcome.agent_member_id,
                        "admitted_by_actor_id": outcome.agent_member_id,
                        "sender_kind": message.role.value,
                        "content": message.content,
                        "message_type": message_type,
                        "correlation_id": (
                            message.correlation_id or outcome.correlation_id
                        ),
                        "task_id": outcome.task_id,
                        "lane_id": outcome.lane_id,
                        "request_lineage_id": None,
                        "workflow_refs": [],
                        "skill_keys": [],
                        "created_at": receipt.accepted_at,
                    },
                )
            )
        return tuple(rows)

    @staticmethod
    def _require_same_record(unit, expected) -> None:  # noqa: ANN001
        current = unit.read(
            entity_type=expected.entity_type, entity_id=expected.entity_id
        )
        if current is None or current.record_digest != expected.record_digest:
            raise KernelContractError(
                "runtime_canonical_state_stale",
                "Runtime canonical identity changed before atomic commit",
            )

    def _require_live_command_identity(
        self,
        command: RuntimeTurnCommand,
        *,
        tool_exposure_snapshot: ToolExposureSnapshot | None,
    ):
        session = self._reader.read(entity_type="session", entity_id=command.session_id)
        signal = self._reader.read(
            entity_type="agent_runtime_signal", entity_id=command.signal_id
        )
        lease = self._reader.read(
            entity_type="session_runtime_lease", entity_id=command.session_id
        )
        member = self._reader.read(
            entity_type="agent_member", entity_id=command.agent_member_id
        )
        workflow = self._reader.read(
            entity_type="workflow_authority_binding",
            entity_id=command.workflow_authority_id,
        )
        signal_link = self._reader.read(
            entity_type="runtime_signal_authority_link",
            entity_id=command.signal_id,
        )
        exposure = self._reader.read(
            entity_type="tool_exposure_snapshot",
            entity_id=command.tool_exposure_snapshot_id,
        )
        if any(
            record is None
            for record in (session, signal, lease, member, workflow, signal_link)
        ) or (exposure is None and tool_exposure_snapshot is None):
            raise KernelContractError(
                "runtime_command_identity_missing",
                "Runtime command canonical identity is incomplete",
            )
        assert session is not None
        assert signal is not None
        assert lease is not None
        assert member is not None
        assert workflow is not None
        assert signal_link is not None
        exposure_payload = (
            exposure.payload
            if exposure is not None
            else tool_exposure_snapshot.to_dict()
            if tool_exposure_snapshot is not None
            else {}
        )
        if (
            exposure is not None
            and tool_exposure_snapshot is not None
            and exposure.payload.get("exposure_snapshot_digest")
            != tool_exposure_snapshot.exposure_snapshot_digest
        ):
            raise KernelContractError(
                "runtime_tool_exposure_snapshot_identity_conflict",
                "Stored and supplied tool exposure snapshots differ",
            )
        now = _parse_instant(self._clock.now_iso(), field_name="now")
        if (
            signal.payload.get("session_id") != command.session_id
            or signal.payload.get("agent_id") != command.agent_id
            or signal.payload.get("agent_member_id") != command.agent_member_id
            or signal.payload.get("status") != "claimed"
            or signal.payload.get("attempt_count") != command.signal_attempt
            or signal.payload.get("claim_token") != command.signal_claim_token
            or signal.payload.get("session_lease_token") != command.runtime_lease_token
            or signal.payload.get("session_fencing_token") != command.runtime_fence
            or lease.payload.get("lease_token") != command.runtime_lease_token
            or lease.payload.get("generation") != command.runtime_lease_generation
            or lease.payload.get("fencing_token") != command.runtime_fence
            or lease.payload.get("released_at") is not None
            or member.payload.get("session_id") != command.session_id
            or member.payload.get("agent_id") != command.agent_id
            or member.payload.get("process_epoch") != command.process_epoch
            or member.payload.get("status")
            in {
                "completed",
                "failed",
                "stopped",
                "shutdown",
            }
            or workflow.payload.get("session_id") != command.session_id
            or workflow.payload.get("authorized_actor_id") != command.agent_member_id
            or workflow.payload.get("status") != "active"
            or workflow.payload.get("epoch") != command.workflow_authority_epoch
            or workflow.payload.get("binding_digest")
            != command.workflow_authority_digest
            or signal_link.payload.get("session_id") != command.session_id
            or signal_link.payload.get("signal_id") != command.signal_id
            or signal_link.payload.get("authority_id") != command.workflow_authority_id
            or signal_link.payload.get("authority_epoch")
            != command.workflow_authority_epoch
            or signal_link.payload.get("authority_binding_digest")
            != command.workflow_authority_digest
            or signal_link.payload.get("link_digest")
            != command.signal_authority_link_digest
            or exposure_payload.get("exposure_snapshot_id")
            != command.tool_exposure_snapshot_id
            or exposure_payload.get("session_id") != command.session_id
            or exposure_payload.get("agent_member_id") != command.agent_member_id
            or exposure_payload.get("turn_id") != command.turn_id
            or exposure_payload.get("declared_tool_catalog_digest")
            != command.declared_tool_catalog_digest
            or exposure_payload.get("capability_binding_digest")
            != command.capability_binding_digest
            or exposure_payload.get("affordance_snapshot_id")
            != command.affordance_snapshot_id
            or exposure_payload.get("affordance_snapshot_digest")
            != command.affordance_snapshot_digest
            or exposure_payload.get("workflow_authority_id")
            != command.workflow_authority_id
            or exposure_payload.get("workflow_authority_epoch")
            != command.workflow_authority_epoch
            or exposure_payload.get("workflow_authority_digest")
            != command.workflow_authority_digest
            or exposure_payload.get("exposure_snapshot_digest")
            != command.tool_exposure_snapshot_digest
            or _parse_instant(
                str(signal.payload["claim_expires_at"]), field_name="claim_expires_at"
            )
            <= now
            or _parse_instant(
                str(lease.payload["expires_at"]), field_name="lease.expires_at"
            )
            <= now
        ):
            raise KernelContractError(
                "runtime_command_fence_stale",
                "Runtime command differs from current signal/lease/process epoch",
            )
        return session, signal, lease, member, workflow, signal_link, exposure


@dataclass(frozen=True, slots=True)
class RuntimeTurnCoordinator:
    adapter: AgentRuntimeAdapter
    outcomes: RuntimeOutcomeRepository

    def build_command(self, admission: RuntimeTurnAdmission) -> RuntimeTurnCommand:
        self._validate_admission(admission)
        return RuntimeTurnCommand(
            command_id=admission.command_id,
            turn_id=admission.turn_id,
            session_id=admission.signal.session_id,
            agent_id=admission.signal.agent_id,
            agent_member_id=admission.agent_member_id,
            signal_id=admission.signal.signal_id,
            signal_attempt=admission.signal.attempt_count,
            signal_claim_token=admission.signal_claim_token,
            runtime_lease_token=admission.session_lease.lease_token,
            runtime_lease_generation=admission.runtime_lease_generation,
            runtime_fence=admission.session_lease.fencing_token,
            process_epoch=admission.process_epoch,
            distribution_id=admission.distribution_id,
            distribution_manifest_digest=admission.distribution_manifest_digest,
            release_digest=admission.release_identity.release_digest,
            adapter_bundle_digest=admission.release_identity.adapter_bundle_digest,
            extension_bundle_digest=admission.release_identity.extension_bundle_digest,
            declared_tool_catalog_digest=(
                admission.release_identity.declared_tool_catalog_digest
            ),
            capability_binding_id=admission.capability_binding.binding_id,
            capability_binding_revision=admission.capability_binding.revision,
            capability_binding_digest=admission.capability_binding.binding_digest,
            affordance_snapshot_id=admission.affordance_snapshot.snapshot_id,
            affordance_snapshot_digest=admission.affordance_snapshot.snapshot_digest,
            workflow_authority_id=admission.workflow_authority.authority_id,
            workflow_authority_epoch=admission.workflow_authority.epoch,
            workflow_authority_digest=(admission.workflow_authority.binding_digest),
            signal_authority_link_digest=(admission.signal_authority_link.link_digest),
            tool_exposure_snapshot_id=(
                admission.tool_exposure_snapshot.exposure_snapshot_id
            ),
            tool_exposure_snapshot_digest=(
                admission.tool_exposure_snapshot.exposure_snapshot_digest
            ),
            context=admission.context,
            runtime_adapter_id=admission.runtime_adapter_id,
            runtime_adapter_contract_digest=(admission.runtime_adapter_contract_digest),
            max_steps=admission.budget.max_steps,
            max_duration_seconds=admission.budget.max_duration_seconds,
            max_input_units=admission.budget.max_input_units,
            max_output_units=admission.budget.max_output_units,
            messages=admission.messages,
            task_id=admission.signal.task_id,
            lane_id=admission.signal.lane_id,
            continuation_id=admission.continuation_id,
        )

    def run_turn(
        self,
        admission: RuntimeTurnAdmission,
        capability_gateway: RuntimeCapabilityGateway,
        *,
        consumed_at: str,
    ) -> tuple[RuntimeTurnOutcome, RuntimeOutcomeConsumeResult]:
        command = self.build_command(admission)
        outcome = self.adapter.run_turn(command, capability_gateway)
        return outcome, self.consume_outcome(
            command,
            outcome,
            consumed_at=consumed_at,
        )

    def consume_outcome(
        self,
        command: RuntimeTurnCommand,
        outcome: RuntimeTurnOutcome,
        *,
        consumed_at: str,
    ) -> RuntimeOutcomeConsumeResult:
        """Validate and atomically consume one outcome without rerunning the Adapter."""

        consumption = self._build_consumption(
            command=command,
            outcome=outcome,
            consumed_at=consumed_at,
        )
        result = self.outcomes.consume(consumption)
        if (
            result.command_digest != consumption.command_digest
            or result.outcome_digest != consumption.outcome_digest
            or (
                result.disposition is RuntimeOutcomeConsumeDisposition.ACCEPTED
                and result.consumption_digest != consumption.consumption_digest
            )
        ):
            raise KernelContractError(
                "runtime_outcome_repository_digest_mismatch",
                "runtime outcome repository returned another consumption identity",
                details={"command_id": command.command_id},
            )
        return result

    def _validate_admission(self, admission: RuntimeTurnAdmission) -> None:
        signal = admission.signal
        lease = admission.session_lease
        binding = admission.capability_binding
        snapshot = admission.affordance_snapshot
        workflow = admission.workflow_authority
        signal_link = admission.signal_authority_link
        exposure = admission.tool_exposure_snapshot
        context = admission.context
        observed_at = _parse_instant(admission.observed_at, field_name="observed_at")
        if (
            signal.status is not AgentRuntimeSignalStatus.CLAIMED
            or signal.attempt_count < 1
            or signal.claimed_by != lease.owner_id
            or signal.session_id != lease.session_id
            or signal.session_lease_token != lease.lease_token
            or signal.session_fencing_token != lease.fencing_token
        ):
            raise KernelContractError(
                "runtime_signal_claim_stale",
                "runtime command does not bind the current claimed signal and Session lease",
                details={"signal_id": signal.signal_id},
            )
        if lease.released_at is not None or observed_at >= _parse_instant(
            lease.expires_at,
            field_name="session_lease.expires_at",
        ):
            raise KernelContractError(
                "runtime_lease_stale",
                "runtime command uses a released or expired Session runtime lease",
                details={"session_id": signal.session_id},
            )
        if signal.claim_expires_at is None or observed_at >= _parse_instant(
            signal.claim_expires_at,
            field_name="signal.claim_expires_at",
        ):
            raise KernelContractError(
                "runtime_signal_claim_expired",
                "runtime signal claim expired before command construction",
                details={"signal_id": signal.signal_id},
            )
        if not binding.has_valid_digest() or not snapshot.has_valid_digest():
            raise KernelContractError(
                "runtime_turn_identity_invalid",
                "runtime binding or affordance snapshot digest is invalid",
                details={"session_id": signal.session_id},
            )
        mismatches = {
            "binding_session": binding.session_id != signal.session_id,
            "snapshot_session": snapshot.session_id != signal.session_id,
            "snapshot_member": snapshot.agent_member_id != admission.agent_member_id,
            "snapshot_turn": snapshot.turn_id != admission.turn_id,
            "snapshot_binding": (
                snapshot.capability_binding_digest != binding.binding_digest
            ),
            "binding_extension_bundle": (
                binding.extension_bundle_digest
                != admission.release_identity.extension_bundle_digest
            ),
            "snapshot_catalog": (
                snapshot.declared_tool_catalog_digest
                != admission.release_identity.declared_tool_catalog_digest
            ),
            "signal_workspace_generation": (
                signal.workspace_generation is not None
                and signal.workspace_generation != snapshot.workspace_generation
            ),
            "workflow_status": workflow.status is not WorkflowAuthorityStatus.ACTIVE,
            "workflow_session": workflow.session_id != signal.session_id,
            "workflow_actor": (
                workflow.authorized_actor_id != admission.agent_member_id
            ),
            "workflow_task": (
                workflow.task_id is not None and workflow.task_id != signal.task_id
            ),
            "workflow_lane": (
                workflow.lane_id is not None and workflow.lane_id != signal.lane_id
            ),
            "signal_link_signal": signal_link.signal_id != signal.signal_id,
            "signal_link_session": signal_link.session_id != signal.session_id,
            "signal_link_authority": (
                signal_link.authority_id != workflow.authority_id
                or signal_link.authority_epoch != workflow.epoch
                or signal_link.authority_binding_digest != workflow.binding_digest
            ),
            "exposure_session": exposure.session_id != signal.session_id,
            "exposure_member": (exposure.agent_member_id != admission.agent_member_id),
            "exposure_turn": exposure.turn_id != admission.turn_id,
            "exposure_affordance": (
                exposure.affordance_snapshot_id != snapshot.snapshot_id
                or exposure.affordance_snapshot_digest != snapshot.snapshot_digest
            ),
            "exposure_capability": (
                exposure.capability_binding_digest != binding.binding_digest
            ),
            "exposure_workflow": (
                exposure.workflow_authority_id != workflow.authority_id
                or exposure.workflow_authority_epoch != workflow.epoch
                or exposure.workflow_authority_digest != workflow.binding_digest
            ),
            "context_session": context.session_id != signal.session_id,
            "context_agent": context.agent_id != signal.agent_id,
            "context_member": context.agent_member_id != admission.agent_member_id,
            "context_turn": context.turn_id != admission.turn_id,
            "context_signal": context.signal_id != signal.signal_id,
            "context_task": context.task_id != signal.task_id,
            "context_lane": context.lane_id != signal.lane_id,
            "context_lineage": (
                context.request_lineage_id != workflow.request_lineage_id
            ),
        }
        drifted = sorted(key for key, mismatch in mismatches.items() if mismatch)
        if drifted:
            raise KernelContractError(
                "runtime_turn_identity_drift",
                "runtime command identities do not belong to one pinned turn",
                details={"drifted_fields": drifted, "signal_id": signal.signal_id},
            )
        if (
            admission.runtime_adapter_id != self.adapter.adapter_id
            or admission.runtime_adapter_contract_digest
            != self.adapter.adapter_contract_digest
        ):
            raise KernelContractError(
                "runtime_adapter_identity_drift",
                "selected runtime Adapter differs from the pinned command identity",
                details={"runtime_adapter_id": admission.runtime_adapter_id},
            )

    def _build_consumption(
        self,
        *,
        command: RuntimeTurnCommand,
        outcome: RuntimeTurnOutcome,
        consumed_at: str,
    ) -> RuntimeOutcomeConsumption:
        expected = {
            "command_id": command.command_id,
            "command_digest": command.command_digest,
            "turn_id": command.turn_id,
            "session_id": command.session_id,
            "agent_id": command.agent_id,
            "agent_member_id": command.agent_member_id,
            "signal_id": command.signal_id,
            "signal_attempt": command.signal_attempt,
            "runtime_lease_generation": command.runtime_lease_generation,
            "runtime_fence": command.runtime_fence,
            "process_epoch": command.process_epoch,
            "workflow_authority_id": command.workflow_authority_id,
            "workflow_authority_epoch": command.workflow_authority_epoch,
            "workflow_authority_digest": command.workflow_authority_digest,
            "tool_exposure_snapshot_id": command.tool_exposure_snapshot_id,
            "tool_exposure_snapshot_digest": (command.tool_exposure_snapshot_digest),
            "task_id": command.task_id,
            "lane_id": command.lane_id,
            "correlation_id": _command_correlation_id(command),
        }
        observed = {field_name: getattr(outcome, field_name) for field_name in expected}
        drifted = sorted(
            field_name
            for field_name, expected_value in expected.items()
            if observed[field_name] != expected_value
        )
        if drifted:
            raise KernelContractError(
                "runtime_outcome_identity_drift",
                "runtime Adapter returned an outcome for another command occurrence",
                details={"command_id": command.command_id, "drifted_fields": drifted},
            )
        if outcome.usage is not None and (
            outcome.usage.input_units > command.max_input_units
            or outcome.usage.output_units > command.max_output_units
        ):
            raise KernelContractError(
                "runtime_outcome_budget_exceeded",
                "runtime Adapter reported usage outside the immutable command budget",
                details={"command_id": command.command_id},
            )
        unexpected_roles = sorted(
            {
                message.role.value
                for message in outcome.messages
                if message.role
                not in {RuntimeMessageRole.ASSISTANT, RuntimeMessageRole.TOOL}
            }
        )
        if unexpected_roles:
            raise KernelContractError(
                "runtime_outcome_message_role_invalid",
                "Runtime outcome may persist only assistant and tool output rows",
                details={
                    "command_id": command.command_id,
                    "message_roles": unexpected_roles,
                },
            )
        failure = outcome.failure
        if failure is not None and (
            failure.session_id != command.session_id
            or failure.agent_id != command.agent_id
            or failure.task_id != command.task_id
            or failure.lane_id != command.lane_id
        ):
            raise KernelContractError(
                "runtime_outcome_failure_identity_drift",
                "Runtime failure differs from the exact turn task/lane/agent scope",
                details={"command_id": command.command_id},
            )
        for request in outcome.tool_requests:
            invocation = request.invocation
            if (
                request.affordance_snapshot_digest != command.affordance_snapshot_digest
                or invocation.affordance_snapshot_digest
                != command.affordance_snapshot_digest
                or invocation.session_id != command.session_id
                or invocation.agent_member_id != command.agent_member_id
                or invocation.task_id != command.task_id
                or invocation.lane_id != command.lane_id
            ):
                raise KernelContractError(
                    "runtime_tool_request_identity_drift",
                    "runtime tool request escaped the command capability gateway scope",
                    details={
                        "command_id": command.command_id,
                        "request_id": request.request_id,
                    },
                )
        continuation = None
        if outcome.disposition is RuntimeTurnDisposition.WAITING_CONTINUATION:
            assert outcome.continuation_id is not None
            continuation = RuntimeContinuationIntent(
                continuation_id=outcome.continuation_id,
                session_id=command.session_id,
                agent_id=command.agent_id,
                agent_member_id=command.agent_member_id,
                source_command_id=command.command_id,
                source_command_digest=command.command_digest,
                source_outcome_id=outcome.outcome_id,
                source_outcome_digest=outcome.outcome_digest,
                source_signal_id=command.signal_id,
                source_signal_authority_link_digest=(
                    command.signal_authority_link_digest
                ),
                source_workflow_authority_id=command.workflow_authority_id,
                source_workflow_authority_epoch=command.workflow_authority_epoch,
                source_workflow_authority_binding_digest=(
                    command.workflow_authority_digest
                ),
                process_epoch=command.process_epoch,
                release_digest=command.release_digest,
                extension_bundle_digest=command.extension_bundle_digest,
                declared_tool_catalog_digest=command.declared_tool_catalog_digest,
                capability_binding_id=command.capability_binding_id,
                capability_binding_revision=command.capability_binding_revision,
                capability_binding_digest=command.capability_binding_digest,
                affordance_snapshot_id=command.affordance_snapshot_id,
                affordance_snapshot_digest=command.affordance_snapshot_digest,
                delivery_status=RuntimeContinuationDeliveryStatus.PENDING,
                delivery_attempt=0,
                created_at=consumed_at,
            )
        settlement = RuntimeSettlementIntent(
            settlement_id=f"settlement-{outcome.outcome_id}",
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=command.signal_attempt,
            source_command_id=command.command_id,
            source_command_digest=command.command_digest,
            source_outcome_id=outcome.outcome_id,
            source_outcome_digest=outcome.outcome_digest,
            disposition=outcome.disposition,
            waiting_approval_id=outcome.waiting_approval_id,
            failure_id=None if outcome.failure is None else outcome.failure.failure_id,
        )
        outcome_receipt = RuntimeTurnOutcomeReceipt(
            receipt_id=f"outcome-receipt-{outcome.outcome_id}",
            outcome=outcome,
            accepted_at=consumed_at,
        )
        return RuntimeOutcomeConsumption(
            consumption_id=f"consumption-{command.command_id}",
            command_id=command.command_id,
            command_digest=command.command_digest,
            outcome_id=outcome.outcome_id,
            outcome_digest=outcome.outcome_digest,
            outcome_receipt=outcome_receipt,
            session_id=command.session_id,
            agent_id=command.agent_id,
            agent_member_id=command.agent_member_id,
            signal_id=command.signal_id,
            signal_attempt=command.signal_attempt,
            continuation_intent=continuation,
            settlement_intent=settlement,
            consumed_at=consumed_at,
            private_diagnostic=outcome.private_diagnostic,
        )


__all__ = [
    "ControlStoreRuntimeOutcomeRepository",
    "RUNTIME_CONTINUATION_INTENT_SCHEMA_VERSION",
    "RUNTIME_CONTINUATION_RESUME_VALIDATION_SCHEMA_VERSION",
    "RUNTIME_OUTCOME_CONSUMPTION_SCHEMA_VERSION",
    "RUNTIME_SETTLEMENT_INTENT_SCHEMA_VERSION",
    "RuntimeContinuationIntent",
    "RuntimeContinuationDeliveryStatus",
    "RuntimeContinuationResumeValidation",
    "RuntimeOutcomeConsumeDisposition",
    "RuntimeOutcomeConsumeResult",
    "RuntimeOutcomeConsumption",
    "RuntimeOutcomeRepository",
    "RuntimeSettlementIntent",
    "RuntimeTurnAdmission",
    "RuntimeTurnBudget",
    "RuntimeTurnCoordinator",
    "validate_runtime_continuation_resume",
]
