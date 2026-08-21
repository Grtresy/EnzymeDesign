from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any
from typing import Protocol

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible

from .application import KernelCommandContext


EXTENSION_MUTATION_PLAN_SCHEMA_VERSION = "openzyme_extension_mutation_plan@1"
EXTENSION_MUTATION_RESULT_SCHEMA_VERSION = "openzyme_extension_mutation_result@1"


def _freeze_object(
    value: Mapping[str, JsonValue],
    *,
    field_name: str,
) -> Mapping[str, JsonValue]:
    frozen = freeze_json(value, field_name=field_name)
    if not isinstance(frozen, Mapping):
        raise ValueError(f"{field_name} must be a JSON object")
    return frozen


class ExtensionStateMutationKind(StrEnum):
    UPSERT = "upsert"
    DELETE = "delete"


@dataclass(frozen=True, slots=True)
class ExtensionStateRecord:
    namespace: str
    entity_kind: str
    entity_id: str
    state_version: int
    payload: Mapping[str, JsonValue]
    record_digest: str

    def __post_init__(self) -> None:
        for field_name in ("namespace", "entity_kind", "entity_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.state_version < 1:
            raise ValueError("state_version must be positive")
        object.__setattr__(
            self,
            "payload",
            _freeze_object(self.payload, field_name="payload"),
        )
        require_digest(self.record_digest, field_name="record_digest")


@dataclass(frozen=True, slots=True)
class ExtensionStateCommand:
    context: KernelCommandContext
    participant_id: str
    namespace: str
    operation: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        for field_name in ("participant_id", "namespace", "operation"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "payload",
            _freeze_object(self.payload, field_name="payload"),
        )


@dataclass(frozen=True, slots=True)
class ExtensionStateMutation:
    mutation_kind: ExtensionStateMutationKind
    namespace: str
    entity_kind: str
    entity_id: str
    expected_state_version: int | None
    payload: Mapping[str, JsonValue] | None

    def __post_init__(self) -> None:
        for field_name in ("namespace", "entity_kind", "entity_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if self.expected_state_version is not None and self.expected_state_version < 1:
            raise ValueError("expected_state_version must be positive")
        if self.mutation_kind is ExtensionStateMutationKind.UPSERT:
            if self.payload is None:
                raise ValueError("upsert mutation requires payload")
            object.__setattr__(
                self,
                "payload",
                _freeze_object(self.payload, field_name="payload"),
            )
        elif self.payload is not None:
            raise ValueError("delete mutation must not carry payload")

    def to_dict(self) -> dict[str, Any]:
        return {
            "mutation_kind": self.mutation_kind.value,
            "namespace": self.namespace,
            "entity_kind": self.entity_kind,
            "entity_id": self.entity_id,
            "expected_state_version": self.expected_state_version,
            "payload": None if self.payload is None else json_compatible(self.payload),
        }


@dataclass(frozen=True, slots=True)
class ExtensionTransactionBudget:
    max_reads: int
    max_mutations: int
    max_payload_bytes: int
    max_duration_ms: int

    def __post_init__(self) -> None:
        for field_name in (
            "max_reads",
            "max_mutations",
            "max_payload_bytes",
            "max_duration_ms",
        ):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value < 1:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.max_reads > 1_000 or self.max_mutations > 1_000:
            raise ValueError("extension transaction item budget is too large")
        if self.max_payload_bytes > 4_194_304:
            raise ValueError("extension transaction payload budget is too large")
        if self.max_duration_ms > 5_000:
            raise ValueError("extension transaction duration budget is too large")


@dataclass(frozen=True, slots=True)
class ExtensionMutationPlan:
    plan_id: str
    participant_id: str
    namespace: str
    command_id: str
    mutations: tuple[ExtensionStateMutation, ...]
    budget: ExtensionTransactionBudget
    plan_digest: str

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        participant_id: str,
        namespace: str,
        command_id: str,
        mutations: tuple[ExtensionStateMutation, ...],
        budget: ExtensionTransactionBudget,
    ) -> ExtensionMutationPlan:
        provisional = cls(
            plan_id=plan_id,
            participant_id=participant_id,
            namespace=namespace,
            command_id=command_id,
            mutations=mutations,
            budget=budget,
            plan_digest="sha256:" + "0" * 64,
        )
        return replace(
            provisional,
            plan_digest=canonical_sha256_digest(provisional.digest_payload()),
        )

    def __post_init__(self) -> None:
        for field_name in ("plan_id", "participant_id", "namespace", "command_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if not self.mutations:
            raise ValueError("extension mutation plan must not be empty")
        if len(self.mutations) > self.budget.max_mutations:
            raise ValueError("extension mutation plan exceeds its mutation budget")
        if any(mutation.namespace != self.namespace for mutation in self.mutations):
            raise ValueError("extension mutation plan crossed its namespace")
        keys = [
            (mutation.entity_kind, mutation.entity_id)
            for mutation in self.mutations
        ]
        if len(set(keys)) != len(keys):
            raise ValueError("extension mutation plan repeats an entity")
        object.__setattr__(
            self,
            "mutations",
            tuple(
                sorted(
                    self.mutations,
                    key=lambda item: (item.entity_kind, item.entity_id),
                )
            ),
        )
        require_digest(self.plan_digest, field_name="plan_digest")
        placeholder = "sha256:" + "0" * 64
        if (
            self.plan_digest != placeholder
            and self.plan_digest != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("extension mutation plan digest mismatch")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_MUTATION_PLAN_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "participant_id": self.participant_id,
            "namespace": self.namespace,
            "command_id": self.command_id,
            "mutations": [mutation.to_dict() for mutation in self.mutations],
            "budget": {
                "max_reads": self.budget.max_reads,
                "max_mutations": self.budget.max_mutations,
                "max_payload_bytes": self.budget.max_payload_bytes,
                "max_duration_ms": self.budget.max_duration_ms,
            },
        }


@dataclass(frozen=True, slots=True)
class ExtensionMutationResult:
    plan_id: str
    participant_id: str
    namespace: str
    mutation_applied: bool
    changed_records: tuple[ExtensionStateRecord, ...]
    result: Mapping[str, JsonValue]
    result_digest: str

    @classmethod
    def create(
        cls,
        *,
        plan_id: str,
        participant_id: str,
        namespace: str,
        mutation_applied: bool,
        changed_records: tuple[ExtensionStateRecord, ...],
        result: Mapping[str, JsonValue],
    ) -> ExtensionMutationResult:
        provisional = cls(
            plan_id=plan_id,
            participant_id=participant_id,
            namespace=namespace,
            mutation_applied=mutation_applied,
            changed_records=changed_records,
            result=result,
            result_digest="sha256:" + "0" * 64,
        )
        return replace(
            provisional,
            result_digest=canonical_sha256_digest(provisional.digest_payload()),
        )

    def __post_init__(self) -> None:
        for field_name in ("plan_id", "participant_id", "namespace"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if any(record.namespace != self.namespace for record in self.changed_records):
            raise ValueError("extension result crossed its namespace")
        if not self.mutation_applied and self.changed_records:
            raise ValueError("non-mutating result cannot report changed records")
        object.__setattr__(
            self,
            "result",
            _freeze_object(self.result, field_name="result"),
        )
        require_digest(self.result_digest, field_name="result_digest")
        placeholder = "sha256:" + "0" * 64
        if (
            self.result_digest != placeholder
            and self.result_digest != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("extension mutation result digest mismatch")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_MUTATION_RESULT_SCHEMA_VERSION,
            "plan_id": self.plan_id,
            "participant_id": self.participant_id,
            "namespace": self.namespace,
            "mutation_applied": self.mutation_applied,
            "changed_records": [
                {
                    "namespace": record.namespace,
                    "entity_kind": record.entity_kind,
                    "entity_id": record.entity_id,
                    "state_version": record.state_version,
                    "payload": json_compatible(record.payload),
                    "record_digest": record.record_digest,
                }
                for record in self.changed_records
            ],
            "result": json_compatible(self.result),
        }


class ExtensionStateReader(Protocol):
    """Namespace-confined reads; this is not a repository or raw connection."""

    def get(
        self,
        *,
        namespace: str,
        entity_kind: str,
        entity_id: str,
    ) -> ExtensionStateRecord | None: ...

    def list(
        self,
        *,
        namespace: str,
        entity_kind: str,
        after_entity_id: str | None,
        limit: int,
    ) -> tuple[ExtensionStateRecord, ...]: ...


class ExtensionStateWriter(Protocol):
    """Closed mutation surface enlisted in the Kernel-owned short transaction."""

    def upsert(self, mutation: ExtensionStateMutation) -> ExtensionStateRecord: ...

    def delete(self, mutation: ExtensionStateMutation) -> None: ...


class ExtensionTransactionParticipant(Protocol):
    """Typed participant; implementations must not perform external I/O here."""

    @property
    def participant_id(self) -> str: ...

    @property
    def state_namespace(self) -> str: ...

    def prepare(
        self,
        command: ExtensionStateCommand,
        state: ExtensionStateReader,
    ) -> ExtensionMutationPlan: ...

    def apply(
        self,
        plan: ExtensionMutationPlan,
        state: ExtensionStateWriter,
    ) -> ExtensionMutationResult: ...


class ExtensionTransactionCoordinatorPort(Protocol):
    """Adapter-owned execution of one Kernel-admitted extension transaction."""

    def execute(
        self,
        *,
        command: ExtensionStateCommand,
        participant: ExtensionTransactionParticipant,
        timestamp: str,
    ) -> ExtensionMutationResult: ...


class ExtensionStateApplicationService(Protocol):
    """Kernel-owned admission surface exposed to activated Plugins."""

    def execute(self, command: ExtensionStateCommand) -> ExtensionMutationResult: ...


__all__ = [
    "EXTENSION_MUTATION_PLAN_SCHEMA_VERSION",
    "EXTENSION_MUTATION_RESULT_SCHEMA_VERSION",
    "ExtensionMutationPlan",
    "ExtensionMutationResult",
    "ExtensionStateCommand",
    "ExtensionStateMutation",
    "ExtensionStateMutationKind",
    "ExtensionStateReader",
    "ExtensionStateRecord",
    "ExtensionStateWriter",
    "ExtensionStateApplicationService",
    "ExtensionTransactionBudget",
    "ExtensionTransactionCoordinatorPort",
    "ExtensionTransactionParticipant",
]
