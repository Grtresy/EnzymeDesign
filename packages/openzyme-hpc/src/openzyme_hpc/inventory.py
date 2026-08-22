from __future__ import annotations

from dataclasses import dataclass
from dataclasses import replace
from datetime import datetime
from enum import StrEnum
from typing import Any

from openzyme_contracts import ResourceCapabilityFact
from openzyme_contracts import ResourceCapabilityKind
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier


TARGET_CAPABILITY_FACT_SCHEMA = "target_capability_fact@1"
SOFTWARE_QUALIFICATION_RECEIPT_SCHEMA = "software_qualification_receipt@1"
TARGET_TOOLCHAIN_INVENTORY_SCHEMA = "target_toolchain_inventory@1"
INVENTORY_GENERATION_SCHEMA = "inventory_generation@1"
TARGET_HEALTH_OBSERVATION_SCHEMA = "target_health_observation@1"


def _timestamp(value: str, *, field_name: str) -> None:
    if not isinstance(value, str) or not value or value != value.strip():
        raise ValueError(f"{field_name} must be a non-empty timestamp")
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError(f"{field_name} must be an ISO-8601 timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field_name} must include an explicit timezone")


def _canonical_string_tuple(
    values: tuple[str, ...],
    *,
    field_name: str,
) -> tuple[str, ...]:
    if any(not isinstance(value, str) or not value or "\x00" in value for value in values):
        raise ValueError(f"{field_name} must contain bounded non-empty strings")
    if len(values) != len(set(values)):
        raise ValueError(f"{field_name} must not contain duplicates")
    return tuple(sorted(values))


class QualificationReceiptStatus(StrEnum):
    PASSED = "passed"
    FAILED = "failed"
    REVOKED = "revoked"


class TargetHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class SoftwareQualificationReceipt:
    receipt_id: str
    qualification_spec_id: str
    qualification_spec_digest: str
    target_id: str
    environment_digest: str
    capability_id: str
    observed_version: str | None
    version_query_receipt_digest: str
    smoke_input_digest: str
    smoke_result_digest: str
    expected_result_schema_digest: str
    operations: tuple[str, ...]
    status: QualificationReceiptStatus
    observed_at: str
    valid_until: str
    receipt_digest: str

    @classmethod
    def create(cls, **values: Any) -> "SoftwareQualificationReceipt":
        receipt = cls(**values, receipt_digest="sha256:" + "0" * 64)
        return replace(
            receipt,
            receipt_digest=canonical_sha256_digest(receipt.identity_payload),
        )

    def __post_init__(self) -> None:
        for field_name in (
            "receipt_id",
            "qualification_spec_id",
            "target_id",
            "capability_id",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "qualification_spec_digest",
            "environment_digest",
            "version_query_receipt_digest",
            "smoke_input_digest",
            "smoke_result_digest",
            "expected_result_schema_digest",
            "receipt_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.observed_version is not None:
            require_identifier(self.observed_version, field_name="observed_version")
        object.__setattr__(
            self,
            "operations",
            _canonical_string_tuple(self.operations, field_name="operations"),
        )
        if not self.operations:
            raise ValueError("qualification receipt operations must not be empty")
        _timestamp(self.observed_at, field_name="observed_at")
        _timestamp(self.valid_until, field_name="valid_until")
        if datetime.fromisoformat(self.valid_until.replace("Z", "+00:00")) <= datetime.fromisoformat(
            self.observed_at.replace("Z", "+00:00")
        ):
            raise ValueError("valid_until must be later than observed_at")
        if self.receipt_digest != "sha256:" + "0" * 64 and (
            self.receipt_digest != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("qualification receipt digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": SOFTWARE_QUALIFICATION_RECEIPT_SCHEMA,
            "receipt_id": self.receipt_id,
            "qualification_spec_id": self.qualification_spec_id,
            "qualification_spec_digest": self.qualification_spec_digest,
            "target_id": self.target_id,
            "environment_digest": self.environment_digest,
            "capability_id": self.capability_id,
            "observed_version": self.observed_version,
            "version_query_receipt_digest": self.version_query_receipt_digest,
            "smoke_input_digest": self.smoke_input_digest,
            "smoke_result_digest": self.smoke_result_digest,
            "expected_result_schema_digest": self.expected_result_schema_digest,
            "operations": list(self.operations),
            "status": self.status.value,
            "observed_at": self.observed_at,
            "valid_until": self.valid_until,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "receipt_digest": self.receipt_digest}


@dataclass(frozen=True, slots=True)
class TargetCapabilityFact:
    capability_id: str
    kind: ResourceCapabilityKind
    contract_version: str
    version: str | None
    operations: tuple[str, ...]
    environment_digest: str
    qualification_digest: str
    implementation_digest: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, field_name="capability_id")
        require_identifier(self.contract_version, field_name="contract_version")
        if self.version is not None:
            require_identifier(self.version, field_name="version")
        object.__setattr__(
            self,
            "operations",
            _canonical_string_tuple(self.operations, field_name="operations"),
        )
        require_digest(self.environment_digest, field_name="environment_digest")
        require_digest(self.qualification_digest, field_name="qualification_digest")
        if self.implementation_digest is not None:
            require_digest(
                self.implementation_digest,
                field_name="implementation_digest",
            )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": TARGET_CAPABILITY_FACT_SCHEMA,
            "capability_id": self.capability_id,
            "kind": self.kind.value,
            "contract_version": self.contract_version,
            "version": self.version,
            "operations": list(self.operations),
            "environment_digest": self.environment_digest,
            "qualification_digest": self.qualification_digest,
            "implementation_digest": self.implementation_digest,
        }

    @property
    def fact_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class InventoryGeneration:
    target_id: str
    generation: int
    previous_inventory_digest: str | None
    inventory_digest: str
    published_by_actor_id: str
    published_at: str
    generation_digest: str

    @classmethod
    def create(cls, **values: Any) -> "InventoryGeneration":
        record = cls(**values, generation_digest="sha256:" + "0" * 64)
        return replace(
            record,
            generation_digest=canonical_sha256_digest(record.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.target_id, field_name="target_id")
        require_identifier(
            self.published_by_actor_id,
            field_name="published_by_actor_id",
        )
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be positive")
        if self.previous_inventory_digest is not None:
            require_digest(
                self.previous_inventory_digest,
                field_name="previous_inventory_digest",
            )
        require_digest(self.inventory_digest, field_name="inventory_digest")
        require_digest(self.generation_digest, field_name="generation_digest")
        _timestamp(self.published_at, field_name="published_at")
        if self.generation_digest != "sha256:" + "0" * 64 and (
            self.generation_digest != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("inventory generation digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": INVENTORY_GENERATION_SCHEMA,
            "target_id": self.target_id,
            "generation": self.generation,
            "previous_inventory_digest": self.previous_inventory_digest,
            "inventory_digest": self.inventory_digest,
            "published_by_actor_id": self.published_by_actor_id,
            "published_at": self.published_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "generation_digest": self.generation_digest}


@dataclass(frozen=True, slots=True)
class TargetToolchainInventory:
    target_id: str
    generation: int
    target_profile_digest: str
    facts: tuple[TargetCapabilityFact, ...]
    qualification_receipt_digests: tuple[str, ...]
    valid_until: str
    created_at: str
    inventory_digest: str

    @classmethod
    def create(cls, **values: Any) -> "TargetToolchainInventory":
        inventory = cls(**values, inventory_digest="sha256:" + "0" * 64)
        return replace(
            inventory,
            inventory_digest=canonical_sha256_digest(inventory.identity_payload),
        )

    def __post_init__(self) -> None:
        require_identifier(self.target_id, field_name="target_id")
        if not isinstance(self.generation, int) or self.generation < 1:
            raise ValueError("generation must be positive")
        require_digest(self.target_profile_digest, field_name="target_profile_digest")
        capability_ids = [fact.capability_id for fact in self.facts]
        if len(capability_ids) != len(set(capability_ids)):
            raise ValueError("inventory facts must have unique capability IDs")
        object.__setattr__(
            self,
            "facts",
            tuple(sorted(self.facts, key=lambda fact: fact.capability_id)),
        )
        for digest in self.qualification_receipt_digests:
            require_digest(digest, field_name="qualification_receipt_digest")
        if len(set(self.qualification_receipt_digests)) != len(
            self.qualification_receipt_digests
        ):
            raise ValueError("qualification receipt digests must be unique")
        object.__setattr__(
            self,
            "qualification_receipt_digests",
            tuple(sorted(self.qualification_receipt_digests)),
        )
        _timestamp(self.valid_until, field_name="valid_until")
        _timestamp(self.created_at, field_name="created_at")
        require_digest(self.inventory_digest, field_name="inventory_digest")
        if self.inventory_digest != "sha256:" + "0" * 64 and (
            self.inventory_digest != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("target toolchain inventory digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": TARGET_TOOLCHAIN_INVENTORY_SCHEMA,
            "target_id": self.target_id,
            "generation": self.generation,
            "target_profile_digest": self.target_profile_digest,
            "facts": [fact.to_dict() for fact in self.facts],
            "qualification_receipt_digests": list(
                self.qualification_receipt_digests
            ),
            "valid_until": self.valid_until,
            "created_at": self.created_at,
        }

    def to_dict(self) -> dict[str, object]:
        return {**self.identity_payload, "inventory_digest": self.inventory_digest}

    def to_resource_facts(self) -> tuple[ResourceCapabilityFact, ...]:
        return tuple(
            ResourceCapabilityFact(
                capability_id=fact.capability_id,
                kind=fact.kind,
                target_id=self.target_id,
                inventory_generation=self.generation,
                qualification_digest=fact.qualification_digest,
                environment_digest=fact.environment_digest,
                inventory_digest=self.inventory_digest,
                contract_version=fact.contract_version,
                operations=fact.operations,
                version=fact.version,
            )
            for fact in self.facts
        )


@dataclass(frozen=True, slots=True)
class TargetHealthObservation:
    target_id: str
    state: TargetHealthState
    observed_at: str
    observation_digest: str

    @classmethod
    def create(cls, **values: Any) -> "TargetHealthObservation":
        observation = cls(**values, observation_digest="sha256:" + "0" * 64)
        return replace(
            observation,
            observation_digest=canonical_sha256_digest(
                observation.identity_payload
            ),
        )

    def __post_init__(self) -> None:
        require_identifier(self.target_id, field_name="target_id")
        _timestamp(self.observed_at, field_name="observed_at")
        require_digest(self.observation_digest, field_name="observation_digest")
        if self.observation_digest != "sha256:" + "0" * 64 and (
            self.observation_digest
            != canonical_sha256_digest(self.identity_payload)
        ):
            raise ValueError("target health observation digest mismatch")

    @property
    def identity_payload(self) -> dict[str, object]:
        return {
            "schema_version": TARGET_HEALTH_OBSERVATION_SCHEMA,
            "target_id": self.target_id,
            "state": self.state.value,
            "observed_at": self.observed_at,
        }


__all__ = [
    "INVENTORY_GENERATION_SCHEMA",
    "SOFTWARE_QUALIFICATION_RECEIPT_SCHEMA",
    "TARGET_CAPABILITY_FACT_SCHEMA",
    "TARGET_HEALTH_OBSERVATION_SCHEMA",
    "TARGET_TOOLCHAIN_INVENTORY_SCHEMA",
    "InventoryGeneration",
    "QualificationReceiptStatus",
    "SoftwareQualificationReceipt",
    "TargetCapabilityFact",
    "TargetHealthObservation",
    "TargetHealthState",
    "TargetToolchainInventory",
]
