from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from typing import Any
from typing import ClassVar
from typing import Mapping

from .failures import FailureObservation
from .failures import PrivateDiagnosticRecord
from .failures import parse_failure_observation
from .failures import validate_failure_diagnostic_pair
from .identity import canonical_sha256_digest
from .identity import require_digest
from .identity import require_identifier
from .reliability import ExternalEffectCertainty
from .reliability import RetryEligibility


WORKSPACE_PROVISIONING_INTENT_SCHEMA_VERSION = "workspace_provisioning_intent@1"
WORKSPACE_PROVISIONING_CLAIM_SCHEMA_VERSION = "workspace_provisioning_claim@1"
WORKSPACE_PROVISIONING_REQUEST_SCHEMA_VERSION = "workspace_provisioning_request@1"
WORKSPACE_PROVISIONING_RECONCILIATION_REQUEST_SCHEMA_VERSION = (
    "workspace_provisioning_reconciliation_request@1"
)
WORKSPACE_PROVISIONING_RECONCILIATION_SCHEMA_VERSION = (
    "workspace_provisioning_reconciliation@1"
)
WORKSPACE_PROVISIONING_RECEIPT_SCHEMA_VERSION = "workspace_provisioning_receipt@1"
WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS = frozenset(
    {
        "adapter_invoked",
        "attempt",
        "blocked_intent_digest",
        "blocked_intent_state_version",
        "dispatch_receipt_digest",
        "external_effect_performed",
        "fallback_performed",
        "historical_intent_preserved",
        "intent_id",
        "parent_reconciliation_id",
        "readiness",
        "reconciliation_digest",
        "reconciliation_enqueued",
        "reconciliation_id",
        "requested_claim_seconds",
        "runtime_executed",
        "source_receipt_digest",
        "source_receipt_id",
        "status",
        "task_transition_performed",
        "workspace_provisioning_reconciliation_enqueued",
    }
)
WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS = frozenset(
    {
        "adapter_invoked",
        "external_effect_performed",
        "failed_intent_id",
        "fallback_performed",
        "generation",
        "readiness",
        "resolved_reconciliation_id",
        "runtime_executed",
        "successor_intent_created",
        "successor_intent_id",
        "task_transition_performed",
        "workspace_generation_reserved",
        "workspace_id",
        "workspace_provisioning_enqueued",
    }
)


class WorkspaceProvisioningStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    READY = "ready"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"

    @property
    def is_terminal(self) -> bool:
        return self in {self.READY, self.BLOCKED, self.CANCELLED}


class WorkspaceProvisioningReceiptDisposition(StrEnum):
    READY = "ready"
    BLOCKED = "blocked"


class WorkspaceProvisioningReconciliationStatus(StrEnum):
    PENDING = "pending"
    CLAIMED = "claimed"
    READY = "ready"
    BLOCKED = "blocked"

    @property
    def is_terminal(self) -> bool:
        return self in {self.READY, self.BLOCKED}


def _positive(value: int, *, field_name: str, allow_zero: bool = False) -> int:
    minimum = 0 if allow_zero else 1
    if not isinstance(value, int) or isinstance(value, bool) or value < minimum:
        qualifier = "non-negative" if allow_zero else "positive"
        raise ValueError(f"{field_name} must be a {qualifier} integer")
    return value


def _closed(payload: Mapping[str, Any], fields: frozenset[str], schema: str) -> None:
    if set(payload) != fields or payload.get("schema_version") != schema:
        raise ValueError(f"{schema} payload has an invalid closed schema")


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningClaim:
    SCHEMA_VERSION: ClassVar[str] = WORKSPACE_PROVISIONING_CLAIM_SCHEMA_VERSION

    intent_id: str
    intent_digest: str
    claim_owner_id: str
    claim_token: str
    claim_epoch: int
    claim_expires_at: str
    claimed_at: str

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id",
            "claim_owner_id",
            "claim_token",
            "claim_expires_at",
            "claimed_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.intent_digest, field_name="intent_digest")
        _positive(self.claim_epoch, field_name="claim_epoch")

    @property
    def claim_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "intent_id": self.intent_id,
            "intent_digest": self.intent_digest,
            "claim_owner_id": self.claim_owner_id,
            "claim_token": self.claim_token,
            "claim_epoch": self.claim_epoch,
            "claim_expires_at": self.claim_expires_at,
            "claimed_at": self.claimed_at,
        }
        if include_digest:
            payload["claim_digest"] = self.claim_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkspaceProvisioningClaim":
        value = dict(payload)
        supplied_digest = value.pop("claim_digest", None)
        _closed(
            value,
            frozenset(
                {
                    "schema_version",
                    "intent_id",
                    "intent_digest",
                    "claim_owner_id",
                    "claim_token",
                    "claim_epoch",
                    "claim_expires_at",
                    "claimed_at",
                }
            ),
            cls.SCHEMA_VERSION,
        )
        claim = cls(
            intent_id=str(value["intent_id"]),
            intent_digest=str(value["intent_digest"]),
            claim_owner_id=str(value["claim_owner_id"]),
            claim_token=str(value["claim_token"]),
            claim_epoch=int(value["claim_epoch"]),
            claim_expires_at=str(value["claim_expires_at"]),
            claimed_at=str(value["claimed_at"]),
        )
        if supplied_digest is not None and supplied_digest != claim.claim_digest:
            raise ValueError("workspace provisioning claim digest mismatch")
        return claim


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningIntent:
    SCHEMA_VERSION: ClassVar[str] = WORKSPACE_PROVISIONING_INTENT_SCHEMA_VERSION

    intent_id: str
    session_id: str
    agent_member_id: str
    workspace_id: str
    generation: int
    repository_pin_digest: str
    provider_id: str
    target_id: str
    adapter_binding_digest: str
    controlled_operation_id: str
    status: WorkspaceProvisioningStatus
    state_version: int
    claim_epoch: int
    created_at: str
    updated_at: str
    claim_owner_id: str | None = None
    claim_token: str | None = None
    claim_expires_at: str | None = None
    terminal_receipt_digest: str | None = None
    effect_certainty: ExternalEffectCertainty | None = None
    mutation_applied: bool | None = None
    fallback_performed: bool = False
    retry_eligibility: RetryEligibility | None = None
    reconcile_required: bool = False
    failure_id: str | None = None
    diagnostic_id: str | None = None
    settled_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "intent_id",
            "session_id",
            "agent_member_id",
            "workspace_id",
            "provider_id",
            "target_id",
            "controlled_operation_id",
            "created_at",
            "updated_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in ("repository_pin_digest", "adapter_binding_digest"):
            require_digest(getattr(self, field_name), field_name=field_name)
        _positive(self.generation, field_name="generation")
        _positive(self.state_version, field_name="state_version")
        _positive(self.claim_epoch, field_name="claim_epoch", allow_zero=True)
        if self.fallback_performed:
            raise ValueError("workspace provisioning never permits fallback")

        claim_values = (
            self.claim_owner_id,
            self.claim_token,
            self.claim_expires_at,
        )
        if self.status is WorkspaceProvisioningStatus.PENDING:
            if self.claim_epoch != 0 or any(
                value is not None for value in claim_values
            ):
                raise ValueError("pending provisioning intent cannot carry a claim")
        else:
            if self.claim_epoch < 1 or any(value is None for value in claim_values):
                raise ValueError(
                    "claimed or terminal provisioning intent requires a full claim"
                )
            for field_name in ("claim_owner_id", "claim_token", "claim_expires_at"):
                require_identifier(getattr(self, field_name), field_name=field_name)

        terminal_values = (
            self.terminal_receipt_digest,
            self.effect_certainty,
            self.retry_eligibility,
            self.settled_at,
        )
        if not self.status.is_terminal:
            if any(value is not None for value in terminal_values):
                raise ValueError(
                    "non-terminal provisioning intent cannot carry settlement"
                )
            if (
                self.mutation_applied is not None
                or self.reconcile_required
                or self.failure_id is not None
                or self.diagnostic_id is not None
            ):
                raise ValueError(
                    "non-terminal provisioning intent cannot carry failure facts"
                )
            return

        if any(value is None for value in terminal_values):
            raise ValueError(
                "terminal provisioning intent requires complete settlement facts"
            )
        require_digest(
            self.terminal_receipt_digest or "", field_name="terminal_receipt_digest"
        )
        require_identifier(self.settled_at or "", field_name="settled_at")
        if self.status is WorkspaceProvisioningStatus.READY:
            if self.failure_id is not None or self.diagnostic_id is not None:
                raise ValueError("ready provisioning intent cannot carry a failure")
            if self.mutation_applied is not True or self.reconcile_required:
                raise ValueError("ready provisioning requires known applied mutation")
            if self.effect_certainty not in {
                ExternalEffectCertainty.EFFECT_KNOWN,
                ExternalEffectCertainty.TERMINAL_KNOWN,
            }:
                raise ValueError("ready provisioning requires known effect certainty")
            if self.retry_eligibility is not RetryEligibility.TERMINAL:
                raise ValueError("ready provisioning occurrence is terminal")
        elif self.status is WorkspaceProvisioningStatus.BLOCKED:
            for field_name in ("failure_id", "diagnostic_id"):
                require_identifier(getattr(self, field_name), field_name=field_name)
            if self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
                if self.mutation_applied is not False or self.reconcile_required:
                    raise ValueError(
                        "no_effect blocker requires mutation=false and no reconciliation"
                    )
            elif self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
                if self.mutation_applied is not None or not self.reconcile_required:
                    raise ValueError(
                        "dispatch_in_doubt blocker requires reconciliation"
                    )
                if self.retry_eligibility is not RetryEligibility.RECONCILE_REQUIRED:
                    raise ValueError("dispatch_in_doubt blocker must forbid redispatch")
            elif self.mutation_applied is None:
                raise ValueError("known provisioning failure requires a mutation fact")
        elif self.status is WorkspaceProvisioningStatus.CANCELLED:
            if self.effect_certainty is not ExternalEffectCertainty.NO_EFFECT:
                raise ValueError("cancelled provisioning must prove no effect")
            if self.mutation_applied is not False or self.reconcile_required:
                raise ValueError(
                    "cancelled provisioning cannot report mutation or reconciliation"
                )
            if self.failure_id is not None or self.diagnostic_id is not None:
                raise ValueError("cancelled provisioning is not a failure observation")

    @property
    def identity_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "workspace_provisioning_identity@1",
                "intent_id": self.intent_id,
                "session_id": self.session_id,
                "agent_member_id": self.agent_member_id,
                "workspace_id": self.workspace_id,
                "generation": self.generation,
                "repository_pin_digest": self.repository_pin_digest,
                "provider_id": self.provider_id,
                "target_id": self.target_id,
                "adapter_binding_digest": self.adapter_binding_digest,
                "controlled_operation_id": self.controlled_operation_id,
            }
        )

    @property
    def intent_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digests=False))

    @property
    def claim(self) -> WorkspaceProvisioningClaim | None:
        if self.claim_owner_id is None:
            return None
        return WorkspaceProvisioningClaim(
            intent_id=self.intent_id,
            intent_digest=self.intent_digest,
            claim_owner_id=self.claim_owner_id,
            claim_token=self.claim_token or "",
            claim_epoch=self.claim_epoch,
            claim_expires_at=self.claim_expires_at or "",
            claimed_at=self.updated_at,
        )

    def to_dict(self, *, include_digests: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "intent_id": self.intent_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "workspace_id": self.workspace_id,
            "generation": self.generation,
            "repository_pin_digest": self.repository_pin_digest,
            "provider_id": self.provider_id,
            "target_id": self.target_id,
            "adapter_binding_digest": self.adapter_binding_digest,
            "controlled_operation_id": self.controlled_operation_id,
            "status": self.status.value,
            "state_version": self.state_version,
            "claim_epoch": self.claim_epoch,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "claim_owner_id": self.claim_owner_id,
            "claim_token": self.claim_token,
            "claim_expires_at": self.claim_expires_at,
            "terminal_receipt_digest": self.terminal_receipt_digest,
            "effect_certainty": None
            if self.effect_certainty is None
            else self.effect_certainty.value,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "retry_eligibility": None
            if self.retry_eligibility is None
            else self.retry_eligibility.value,
            "reconcile_required": self.reconcile_required,
            "failure_id": self.failure_id,
            "diagnostic_id": self.diagnostic_id,
            "settled_at": self.settled_at,
        }
        if include_digests:
            payload["identity_digest"] = self.identity_digest
            payload["intent_digest"] = self.intent_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkspaceProvisioningIntent":
        value = dict(payload)
        identity_digest = value.pop("identity_digest", None)
        intent_digest = value.pop("intent_digest", None)
        _closed(
            value,
            frozenset(
                {
                    "schema_version",
                    "intent_id",
                    "session_id",
                    "agent_member_id",
                    "workspace_id",
                    "generation",
                    "repository_pin_digest",
                    "provider_id",
                    "target_id",
                    "adapter_binding_digest",
                    "controlled_operation_id",
                    "status",
                    "state_version",
                    "claim_epoch",
                    "created_at",
                    "updated_at",
                    "claim_owner_id",
                    "claim_token",
                    "claim_expires_at",
                    "terminal_receipt_digest",
                    "effect_certainty",
                    "mutation_applied",
                    "fallback_performed",
                    "retry_eligibility",
                    "reconcile_required",
                    "failure_id",
                    "diagnostic_id",
                    "settled_at",
                }
            ),
            cls.SCHEMA_VERSION,
        )
        intent = cls(
            intent_id=str(value["intent_id"]),
            session_id=str(value["session_id"]),
            agent_member_id=str(value["agent_member_id"]),
            workspace_id=str(value["workspace_id"]),
            generation=int(value["generation"]),
            repository_pin_digest=str(value["repository_pin_digest"]),
            provider_id=str(value["provider_id"]),
            target_id=str(value["target_id"]),
            adapter_binding_digest=str(value["adapter_binding_digest"]),
            controlled_operation_id=str(value["controlled_operation_id"]),
            status=WorkspaceProvisioningStatus(str(value["status"])),
            state_version=int(value["state_version"]),
            claim_epoch=int(value["claim_epoch"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            claim_owner_id=None
            if value["claim_owner_id"] is None
            else str(value["claim_owner_id"]),
            claim_token=None
            if value["claim_token"] is None
            else str(value["claim_token"]),
            claim_expires_at=None
            if value["claim_expires_at"] is None
            else str(value["claim_expires_at"]),
            terminal_receipt_digest=None
            if value["terminal_receipt_digest"] is None
            else str(value["terminal_receipt_digest"]),
            effect_certainty=None
            if value["effect_certainty"] is None
            else ExternalEffectCertainty(str(value["effect_certainty"])),
            mutation_applied=value["mutation_applied"],
            fallback_performed=value["fallback_performed"],
            retry_eligibility=None
            if value["retry_eligibility"] is None
            else RetryEligibility(str(value["retry_eligibility"])),
            reconcile_required=value["reconcile_required"],
            failure_id=None
            if value["failure_id"] is None
            else str(value["failure_id"]),
            diagnostic_id=None
            if value["diagnostic_id"] is None
            else str(value["diagnostic_id"]),
            settled_at=None
            if value["settled_at"] is None
            else str(value["settled_at"]),
        )
        if identity_digest is not None and identity_digest != intent.identity_digest:
            raise ValueError("workspace provisioning identity digest mismatch")
        if intent_digest is not None and intent_digest != intent.intent_digest:
            raise ValueError("workspace provisioning intent digest mismatch")
        return intent


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningRequest:
    SCHEMA_VERSION: ClassVar[str] = WORKSPACE_PROVISIONING_REQUEST_SCHEMA_VERSION

    request_id: str
    intent_id: str
    intent_digest: str
    claim_token: str
    claim_epoch: int
    session_id: str
    agent_member_id: str
    workspace_id: str
    generation: int
    repository_pin_digest: str
    provider_id: str
    target_id: str
    adapter_binding_digest: str
    controlled_operation_id: str

    def __post_init__(self) -> None:
        for field_name in (
            "request_id",
            "intent_id",
            "claim_token",
            "session_id",
            "agent_member_id",
            "workspace_id",
            "provider_id",
            "target_id",
            "controlled_operation_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "intent_digest",
            "repository_pin_digest",
            "adapter_binding_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        _positive(self.claim_epoch, field_name="claim_epoch")
        _positive(self.generation, field_name="generation")

    @property
    def request_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            **{
                field_name: getattr(self, field_name)
                for field_name in (
                    "request_id",
                    "intent_id",
                    "intent_digest",
                    "claim_token",
                    "claim_epoch",
                    "session_id",
                    "agent_member_id",
                    "workspace_id",
                    "generation",
                    "repository_pin_digest",
                    "provider_id",
                    "target_id",
                    "adapter_binding_digest",
                    "controlled_operation_id",
                )
            },
        }
        if include_digest:
            payload["request_digest"] = self.request_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkspaceProvisioningRequest":
        value = dict(payload)
        supplied_digest = value.pop("request_digest", None)
        _closed(
            value,
            frozenset(
                {
                    "schema_version",
                    "request_id",
                    "intent_id",
                    "intent_digest",
                    "claim_token",
                    "claim_epoch",
                    "session_id",
                    "agent_member_id",
                    "workspace_id",
                    "generation",
                    "repository_pin_digest",
                    "provider_id",
                    "target_id",
                    "adapter_binding_digest",
                    "controlled_operation_id",
                }
            ),
            cls.SCHEMA_VERSION,
        )
        request = cls(
            request_id=str(value["request_id"]),
            intent_id=str(value["intent_id"]),
            intent_digest=str(value["intent_digest"]),
            claim_token=str(value["claim_token"]),
            claim_epoch=int(value["claim_epoch"]),
            session_id=str(value["session_id"]),
            agent_member_id=str(value["agent_member_id"]),
            workspace_id=str(value["workspace_id"]),
            generation=int(value["generation"]),
            repository_pin_digest=str(value["repository_pin_digest"]),
            provider_id=str(value["provider_id"]),
            target_id=str(value["target_id"]),
            adapter_binding_digest=str(value["adapter_binding_digest"]),
            controlled_operation_id=str(value["controlled_operation_id"]),
        )
        if supplied_digest is not None and supplied_digest != request.request_digest:
            raise ValueError("workspace provisioning request digest mismatch")
        return request


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReconciliationRequest:
    """Observation-only request for one dispatch-in-doubt provisioning occurrence."""

    SCHEMA_VERSION: ClassVar[str] = (
        WORKSPACE_PROVISIONING_RECONCILIATION_REQUEST_SCHEMA_VERSION
    )

    reconciliation_id: str
    provision_request: WorkspaceProvisioningRequest
    dispatch_receipt_digest: str
    reason_code: str
    requested_at: str

    def __post_init__(self) -> None:
        for field_name in ("reconciliation_id", "reason_code", "requested_at"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.dispatch_receipt_digest,
            field_name="dispatch_receipt_digest",
        )

    @property
    def reconciliation_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "reconciliation_id": self.reconciliation_id,
            "provision_request": self.provision_request.to_dict(),
            "dispatch_receipt_digest": self.dispatch_receipt_digest,
            "reason_code": self.reason_code,
            "requested_at": self.requested_at,
        }
        if include_digest:
            payload["reconciliation_digest"] = self.reconciliation_digest
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "WorkspaceProvisioningReconciliationRequest":
        value = dict(payload)
        supplied_digest = value.pop("reconciliation_digest", None)
        _closed(
            value,
            frozenset(
                {
                    "schema_version",
                    "reconciliation_id",
                    "provision_request",
                    "dispatch_receipt_digest",
                    "reason_code",
                    "requested_at",
                }
            ),
            cls.SCHEMA_VERSION,
        )
        request_value = value["provision_request"]
        if not isinstance(request_value, Mapping):
            raise ValueError("provision_request must be an object")
        request = cls(
            reconciliation_id=str(value["reconciliation_id"]),
            provision_request=WorkspaceProvisioningRequest.from_dict(request_value),
            dispatch_receipt_digest=str(value["dispatch_receipt_digest"]),
            reason_code=str(value["reason_code"]),
            requested_at=str(value["requested_at"]),
        )
        if (
            supplied_digest is not None
            and supplied_digest != request.reconciliation_digest
        ):
            raise ValueError(
                "workspace provisioning reconciliation request digest mismatch"
            )
        return request


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReconciliation:
    """Durable, claim-fenced observation of one failed provision dispatch.

    The original blocked provisioning intent and its receipt stay immutable.
    Successive reconciliation attempts form an explicit parent-linked lineage
    and always carry the exact original provision request.
    """

    SCHEMA_VERSION: ClassVar[str] = WORKSPACE_PROVISIONING_RECONCILIATION_SCHEMA_VERSION

    reconciliation_id: str
    session_id: str
    intent_id: str
    blocked_intent_state_version: int
    blocked_intent_digest: str
    source_receipt_id: str
    source_receipt_digest: str
    dispatch_receipt_digest: str
    provision_request: WorkspaceProvisioningRequest
    attempt: int
    parent_reconciliation_id: str | None
    reason_code: str
    requested_at: str
    requested_claim_seconds: int
    status: WorkspaceProvisioningReconciliationStatus
    state_version: int
    claim_epoch: int
    created_at: str
    updated_at: str
    claim_owner_id: str | None = None
    claim_token: str | None = None
    claim_expires_at: str | None = None
    result_receipt_id: str | None = None
    result_receipt_digest: str | None = None
    result_terminal_receipt_digest: str | None = None
    effect_certainty: ExternalEffectCertainty | None = None
    mutation_applied: bool | None = None
    fallback_performed: bool = False
    retry_eligibility: RetryEligibility | None = None
    reconcile_required: bool = False
    failure_id: str | None = None
    diagnostic_id: str | None = None
    settled_at: str | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "reconciliation_id",
            "session_id",
            "intent_id",
            "source_receipt_id",
            "reason_code",
            "requested_at",
            "created_at",
            "updated_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "blocked_intent_digest",
            "source_receipt_digest",
            "dispatch_receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        _positive(
            self.blocked_intent_state_version,
            field_name="blocked_intent_state_version",
        )
        _positive(self.attempt, field_name="attempt")
        if (
            not isinstance(self.requested_claim_seconds, int)
            or isinstance(self.requested_claim_seconds, bool)
            or not 1 <= self.requested_claim_seconds <= 86_400
        ):
            raise ValueError("requested_claim_seconds must be between 1 and 86400")
        _positive(self.state_version, field_name="state_version")
        _positive(self.claim_epoch, field_name="claim_epoch", allow_zero=True)
        if self.attempt == 1:
            if self.parent_reconciliation_id is not None:
                raise ValueError("first reconciliation attempt cannot have a parent")
        else:
            require_identifier(
                self.parent_reconciliation_id,
                field_name="parent_reconciliation_id",
            )
        if (
            self.provision_request.session_id != self.session_id
            or self.provision_request.intent_id != self.intent_id
        ):
            raise ValueError(
                "reconciliation must carry the exact source provision request"
            )
        if self.fallback_performed:
            raise ValueError(
                "workspace provisioning reconciliation never permits fallback"
            )

        claim_values = (
            self.claim_owner_id,
            self.claim_token,
            self.claim_expires_at,
        )
        if self.status is WorkspaceProvisioningReconciliationStatus.PENDING:
            if self.claim_epoch != 0 or any(
                value is not None for value in claim_values
            ):
                raise ValueError("pending reconciliation cannot carry a claim")
        else:
            if self.claim_epoch < 1 or any(value is None for value in claim_values):
                raise ValueError(
                    "claimed or terminal reconciliation requires a full claim"
                )
            for field_name in (
                "claim_owner_id",
                "claim_token",
                "claim_expires_at",
            ):
                require_identifier(getattr(self, field_name), field_name=field_name)

        terminal_values = (
            self.result_receipt_id,
            self.result_receipt_digest,
            self.result_terminal_receipt_digest,
            self.effect_certainty,
            self.retry_eligibility,
            self.settled_at,
        )
        if not self.status.is_terminal:
            if any(value is not None for value in terminal_values):
                raise ValueError("non-terminal reconciliation cannot carry settlement")
            if (
                self.mutation_applied is not None
                or self.reconcile_required
                or self.failure_id is not None
                or self.diagnostic_id is not None
            ):
                raise ValueError(
                    "non-terminal reconciliation cannot carry result facts"
                )
            return

        if any(value is None for value in terminal_values):
            raise ValueError(
                "terminal reconciliation requires complete settlement facts"
            )
        require_identifier(self.result_receipt_id or "", field_name="result_receipt_id")
        require_digest(
            self.result_receipt_digest or "",
            field_name="result_receipt_digest",
        )
        require_digest(
            self.result_terminal_receipt_digest or "",
            field_name="result_terminal_receipt_digest",
        )
        require_identifier(self.settled_at or "", field_name="settled_at")
        if self.status is WorkspaceProvisioningReconciliationStatus.READY:
            if self.effect_certainty is not ExternalEffectCertainty.TERMINAL_KNOWN:
                raise ValueError("ready reconciliation requires terminal-known effect")
            if self.mutation_applied is not True:
                raise ValueError("ready reconciliation requires known applied mutation")
            if self.retry_eligibility is not RetryEligibility.TERMINAL:
                raise ValueError("ready reconciliation is terminal")
            if (
                self.reconcile_required
                or self.failure_id is not None
                or self.diagnostic_id is not None
            ):
                raise ValueError("ready reconciliation cannot carry failure facts")
            return

        for field_name in ("failure_id", "diagnostic_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
            if self.mutation_applied is not False or self.reconcile_required:
                raise ValueError(
                    "no-effect reconciliation requires mutation=false and no successor observation"
                )
        elif self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
            if self.mutation_applied is not None or not self.reconcile_required:
                raise ValueError(
                    "dispatch-in-doubt reconciliation requires another explicit observation"
                )
            if self.retry_eligibility is not RetryEligibility.RECONCILE_REQUIRED:
                raise ValueError("dispatch-in-doubt reconciliation forbids redispatch")
        elif self.mutation_applied is None:
            raise ValueError("known reconciliation result requires a mutation fact")

    @property
    def identity_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "schema_version": "workspace_provisioning_reconciliation_identity@1",
                "reconciliation_id": self.reconciliation_id,
                "session_id": self.session_id,
                "intent_id": self.intent_id,
                "blocked_intent_state_version": self.blocked_intent_state_version,
                "blocked_intent_digest": self.blocked_intent_digest,
                "source_receipt_id": self.source_receipt_id,
                "source_receipt_digest": self.source_receipt_digest,
                "dispatch_receipt_digest": self.dispatch_receipt_digest,
                "provision_request_digest": self.provision_request.request_digest,
                "attempt": self.attempt,
                "parent_reconciliation_id": self.parent_reconciliation_id,
                "requested_claim_seconds": self.requested_claim_seconds,
            }
        )

    @property
    def reconciliation_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digests=False))

    def to_dict(self, *, include_digests: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "reconciliation_id": self.reconciliation_id,
            "session_id": self.session_id,
            "intent_id": self.intent_id,
            "blocked_intent_state_version": self.blocked_intent_state_version,
            "blocked_intent_digest": self.blocked_intent_digest,
            "source_receipt_id": self.source_receipt_id,
            "source_receipt_digest": self.source_receipt_digest,
            "dispatch_receipt_digest": self.dispatch_receipt_digest,
            "provision_request": self.provision_request.to_dict(),
            "attempt": self.attempt,
            "parent_reconciliation_id": self.parent_reconciliation_id,
            "reason_code": self.reason_code,
            "requested_at": self.requested_at,
            "requested_claim_seconds": self.requested_claim_seconds,
            "status": self.status.value,
            "state_version": self.state_version,
            "claim_epoch": self.claim_epoch,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
            "claim_owner_id": self.claim_owner_id,
            "claim_token": self.claim_token,
            "claim_expires_at": self.claim_expires_at,
            "result_receipt_id": self.result_receipt_id,
            "result_receipt_digest": self.result_receipt_digest,
            "result_terminal_receipt_digest": self.result_terminal_receipt_digest,
            "effect_certainty": (
                None if self.effect_certainty is None else self.effect_certainty.value
            ),
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "retry_eligibility": (
                None if self.retry_eligibility is None else self.retry_eligibility.value
            ),
            "reconcile_required": self.reconcile_required,
            "failure_id": self.failure_id,
            "diagnostic_id": self.diagnostic_id,
            "settled_at": self.settled_at,
        }
        if include_digests:
            payload["identity_digest"] = self.identity_digest
            payload["reconciliation_digest"] = self.reconciliation_digest
        return payload

    @classmethod
    def from_dict(
        cls,
        payload: Mapping[str, Any],
    ) -> "WorkspaceProvisioningReconciliation":
        value = dict(payload)
        identity_digest = value.pop("identity_digest", None)
        reconciliation_digest = value.pop("reconciliation_digest", None)
        _closed(
            value,
            frozenset(
                {
                    "schema_version",
                    "reconciliation_id",
                    "session_id",
                    "intent_id",
                    "blocked_intent_state_version",
                    "blocked_intent_digest",
                    "source_receipt_id",
                    "source_receipt_digest",
                    "dispatch_receipt_digest",
                    "provision_request",
                    "attempt",
                    "parent_reconciliation_id",
                    "reason_code",
                    "requested_at",
                    "requested_claim_seconds",
                    "status",
                    "state_version",
                    "claim_epoch",
                    "created_at",
                    "updated_at",
                    "claim_owner_id",
                    "claim_token",
                    "claim_expires_at",
                    "result_receipt_id",
                    "result_receipt_digest",
                    "result_terminal_receipt_digest",
                    "effect_certainty",
                    "mutation_applied",
                    "fallback_performed",
                    "retry_eligibility",
                    "reconcile_required",
                    "failure_id",
                    "diagnostic_id",
                    "settled_at",
                }
            ),
            cls.SCHEMA_VERSION,
        )
        request_value = value["provision_request"]
        if not isinstance(request_value, Mapping):
            raise ValueError("provision_request must be an object")
        reconciliation = cls(
            reconciliation_id=str(value["reconciliation_id"]),
            session_id=str(value["session_id"]),
            intent_id=str(value["intent_id"]),
            blocked_intent_state_version=int(value["blocked_intent_state_version"]),
            blocked_intent_digest=str(value["blocked_intent_digest"]),
            source_receipt_id=str(value["source_receipt_id"]),
            source_receipt_digest=str(value["source_receipt_digest"]),
            dispatch_receipt_digest=str(value["dispatch_receipt_digest"]),
            provision_request=WorkspaceProvisioningRequest.from_dict(request_value),
            attempt=int(value["attempt"]),
            parent_reconciliation_id=(
                None
                if value["parent_reconciliation_id"] is None
                else str(value["parent_reconciliation_id"])
            ),
            reason_code=str(value["reason_code"]),
            requested_at=str(value["requested_at"]),
            requested_claim_seconds=int(value["requested_claim_seconds"]),
            status=WorkspaceProvisioningReconciliationStatus(str(value["status"])),
            state_version=int(value["state_version"]),
            claim_epoch=int(value["claim_epoch"]),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
            claim_owner_id=(
                None
                if value["claim_owner_id"] is None
                else str(value["claim_owner_id"])
            ),
            claim_token=None
            if value["claim_token"] is None
            else str(value["claim_token"]),
            claim_expires_at=(
                None
                if value["claim_expires_at"] is None
                else str(value["claim_expires_at"])
            ),
            result_receipt_id=(
                None
                if value["result_receipt_id"] is None
                else str(value["result_receipt_id"])
            ),
            result_receipt_digest=(
                None
                if value["result_receipt_digest"] is None
                else str(value["result_receipt_digest"])
            ),
            result_terminal_receipt_digest=(
                None
                if value["result_terminal_receipt_digest"] is None
                else str(value["result_terminal_receipt_digest"])
            ),
            effect_certainty=(
                None
                if value["effect_certainty"] is None
                else ExternalEffectCertainty(str(value["effect_certainty"]))
            ),
            mutation_applied=value["mutation_applied"],
            fallback_performed=value["fallback_performed"],
            retry_eligibility=(
                None
                if value["retry_eligibility"] is None
                else RetryEligibility(str(value["retry_eligibility"]))
            ),
            reconcile_required=value["reconcile_required"],
            failure_id=None
            if value["failure_id"] is None
            else str(value["failure_id"]),
            diagnostic_id=(
                None if value["diagnostic_id"] is None else str(value["diagnostic_id"])
            ),
            settled_at=None
            if value["settled_at"] is None
            else str(value["settled_at"]),
        )
        if (
            identity_digest is not None
            and identity_digest != reconciliation.identity_digest
        ):
            raise ValueError(
                "workspace provisioning reconciliation identity digest mismatch"
            )
        if (
            reconciliation_digest is not None
            and reconciliation_digest != reconciliation.reconciliation_digest
        ):
            raise ValueError("workspace provisioning reconciliation digest mismatch")
        return reconciliation


@dataclass(frozen=True, slots=True)
class WorkspaceProvisioningReceipt:
    SCHEMA_VERSION: ClassVar[str] = WORKSPACE_PROVISIONING_RECEIPT_SCHEMA_VERSION

    receipt_id: str
    request_id: str
    request_digest: str
    intent_id: str
    intent_digest: str
    claim_token: str
    claim_epoch: int
    controlled_operation_id: str
    disposition: WorkspaceProvisioningReceiptDisposition
    session_id: str
    agent_member_id: str
    workspace_id: str
    generation: int
    repository_pin_digest: str
    provider_id: str
    target_id: str
    adapter_binding_digest: str
    effect_certainty: ExternalEffectCertainty
    mutation_applied: bool | None
    fallback_performed: bool
    retry_eligibility: RetryEligibility
    reconcile_required: bool
    observed_root_identity_digest: str | None
    terminal_receipt_digest: str
    completed_at: str
    failure: FailureObservation | None = None
    private_diagnostic: PrivateDiagnosticRecord | None = field(
        default=None,
        repr=False,
        compare=False,
    )

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "request_id",
            "intent_id",
            "claim_token",
            "controlled_operation_id",
            "session_id",
            "agent_member_id",
            "workspace_id",
            "provider_id",
            "target_id",
            "completed_at",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "request_digest",
            "intent_digest",
            "repository_pin_digest",
            "adapter_binding_digest",
            "terminal_receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.observed_root_identity_digest is not None:
            require_digest(
                self.observed_root_identity_digest,
                field_name="observed_root_identity_digest",
            )
        _positive(self.claim_epoch, field_name="claim_epoch")
        _positive(self.generation, field_name="generation")
        if self.fallback_performed:
            raise ValueError("workspace provisioner receipt cannot report fallback")
        if self.disposition is WorkspaceProvisioningReceiptDisposition.READY:
            if (
                self.failure is not None
                or self.private_diagnostic is not None
                or self.observed_root_identity_digest is None
            ):
                raise ValueError(
                    "ready provisioning receipt requires root identity and no failure pair"
                )
            if self.mutation_applied is not True or self.reconcile_required:
                raise ValueError(
                    "ready provisioning receipt requires known applied mutation"
                )
            if self.retry_eligibility is not RetryEligibility.TERMINAL:
                raise ValueError("ready provisioning receipt must be terminal")
        else:
            if self.failure is None:
                raise ValueError(
                    "blocked provisioning receipt requires a failure observation"
                )
            if (
                self.failure.session_id != self.session_id
                or self.failure.effect_certainty is not self.effect_certainty
                or self.failure.mutation_applied is not self.mutation_applied
                or self.failure.fallback_performed is not self.fallback_performed
                or self.failure.retry_eligibility is not self.retry_eligibility
            ):
                raise ValueError(
                    "blocked provisioning receipt and failure effect facts must agree"
                )
            if self.private_diagnostic is not None:
                validate_failure_diagnostic_pair(
                    self.failure,
                    self.private_diagnostic,
                )
            elif self.failure.private_diagnostic_digest is not None:
                raise ValueError(
                    "blocked provisioning receipt is missing its private diagnostic"
                )
            if self.effect_certainty is ExternalEffectCertainty.NO_EFFECT:
                if self.mutation_applied is not False or self.reconcile_required:
                    raise ValueError(
                        "no_effect receipt has invalid mutation/reconciliation facts"
                    )
            elif self.effect_certainty is ExternalEffectCertainty.DISPATCH_IN_DOUBT:
                if self.mutation_applied is not None or not self.reconcile_required:
                    raise ValueError(
                        "dispatch_in_doubt receipt must require reconciliation"
                    )
            elif self.mutation_applied is None:
                raise ValueError("known blocked receipt requires mutation fact")

    @property
    def receipt_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict(include_digest=False))

    def to_dict(self, *, include_digest: bool = True) -> dict[str, Any]:
        payload = {
            "schema_version": self.SCHEMA_VERSION,
            "receipt_id": self.receipt_id,
            "request_id": self.request_id,
            "request_digest": self.request_digest,
            "intent_id": self.intent_id,
            "intent_digest": self.intent_digest,
            "claim_token": self.claim_token,
            "claim_epoch": self.claim_epoch,
            "controlled_operation_id": self.controlled_operation_id,
            "disposition": self.disposition.value,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "workspace_id": self.workspace_id,
            "generation": self.generation,
            "repository_pin_digest": self.repository_pin_digest,
            "provider_id": self.provider_id,
            "target_id": self.target_id,
            "adapter_binding_digest": self.adapter_binding_digest,
            "effect_certainty": self.effect_certainty.value,
            "mutation_applied": self.mutation_applied,
            "fallback_performed": self.fallback_performed,
            "retry_eligibility": self.retry_eligibility.value,
            "reconcile_required": self.reconcile_required,
            "observed_root_identity_digest": self.observed_root_identity_digest,
            "terminal_receipt_digest": self.terminal_receipt_digest,
            "completed_at": self.completed_at,
            "failure": None if self.failure is None else self.failure.to_dict(),
        }
        if include_digest:
            payload["receipt_digest"] = self.receipt_digest
        return payload

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "WorkspaceProvisioningReceipt":
        value = dict(payload)
        supplied_digest = value.pop("receipt_digest", None)
        _closed(
            value,
            frozenset(
                {
                    "schema_version",
                    "receipt_id",
                    "request_id",
                    "request_digest",
                    "intent_id",
                    "intent_digest",
                    "claim_token",
                    "claim_epoch",
                    "controlled_operation_id",
                    "disposition",
                    "session_id",
                    "agent_member_id",
                    "workspace_id",
                    "generation",
                    "repository_pin_digest",
                    "provider_id",
                    "target_id",
                    "adapter_binding_digest",
                    "effect_certainty",
                    "mutation_applied",
                    "fallback_performed",
                    "retry_eligibility",
                    "reconcile_required",
                    "observed_root_identity_digest",
                    "terminal_receipt_digest",
                    "completed_at",
                    "failure",
                }
            ),
            cls.SCHEMA_VERSION,
        )
        failure_value = value["failure"]
        failure = None
        if failure_value is not None:
            if not isinstance(failure_value, Mapping):
                raise ValueError("workspace provisioning failure must be an object")
            parsed = parse_failure_observation(failure_value)
            if not isinstance(parsed, FailureObservation):
                raise ValueError(
                    "legacy failure observations cannot settle provisioning"
                )
            failure = parsed
        receipt = cls(
            receipt_id=str(value["receipt_id"]),
            request_id=str(value["request_id"]),
            request_digest=str(value["request_digest"]),
            intent_id=str(value["intent_id"]),
            intent_digest=str(value["intent_digest"]),
            claim_token=str(value["claim_token"]),
            claim_epoch=int(value["claim_epoch"]),
            controlled_operation_id=str(value["controlled_operation_id"]),
            disposition=WorkspaceProvisioningReceiptDisposition(
                str(value["disposition"])
            ),
            session_id=str(value["session_id"]),
            agent_member_id=str(value["agent_member_id"]),
            workspace_id=str(value["workspace_id"]),
            generation=int(value["generation"]),
            repository_pin_digest=str(value["repository_pin_digest"]),
            provider_id=str(value["provider_id"]),
            target_id=str(value["target_id"]),
            adapter_binding_digest=str(value["adapter_binding_digest"]),
            effect_certainty=ExternalEffectCertainty(str(value["effect_certainty"])),
            mutation_applied=value["mutation_applied"],
            fallback_performed=value["fallback_performed"],
            retry_eligibility=RetryEligibility(str(value["retry_eligibility"])),
            reconcile_required=value["reconcile_required"],
            observed_root_identity_digest=None
            if value["observed_root_identity_digest"] is None
            else str(value["observed_root_identity_digest"]),
            terminal_receipt_digest=str(value["terminal_receipt_digest"]),
            completed_at=str(value["completed_at"]),
            failure=failure,
        )
        if supplied_digest is not None and supplied_digest != receipt.receipt_digest:
            raise ValueError("workspace provisioning receipt digest mismatch")
        return receipt


__all__ = [
    "WORKSPACE_PROVISIONING_CLAIM_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_INTENT_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_RECEIPT_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_RECONCILIATION_ADMISSION_RESULT_FIELDS",
    "WORKSPACE_PROVISIONING_RECONCILIATION_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_RECONCILIATION_REQUEST_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_REQUEST_SCHEMA_VERSION",
    "WORKSPACE_PROVISIONING_SUCCESSOR_ADMISSION_RESULT_FIELDS",
    "WorkspaceProvisioningClaim",
    "WorkspaceProvisioningIntent",
    "WorkspaceProvisioningReceipt",
    "WorkspaceProvisioningReceiptDisposition",
    "WorkspaceProvisioningReconciliation",
    "WorkspaceProvisioningReconciliationRequest",
    "WorkspaceProvisioningReconciliationStatus",
    "WorkspaceProvisioningRequest",
    "WorkspaceProvisioningStatus",
]
