from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import replace
from enum import StrEnum
from typing import Any

from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import require_digest
from .identity import require_identifier


EXTENSION_CAPABILITY_FACT_SCHEMA_VERSION = "extension_capability_fact@1"
RESOURCE_CAPABILITY_FACT_SCHEMA_VERSION = "resource_capability_fact@1"
SESSION_CAPABILITY_BINDING_REVISION_SCHEMA_VERSION = (
    "session_capability_binding_revision@1"
)
TOOL_AFFORDANCE_SNAPSHOT_SCHEMA_VERSION = "tool_affordance_snapshot@1"


class ResourceCapabilityKind(StrEnum):
    SOFTWARE = "software"
    HARDWARE = "hardware"
    ACCELERATOR = "accelerator"
    DATASET = "dataset"
    ASSET = "asset"
    LICENSE = "license"
    SERVICE = "service"


class ToolAffordanceState(StrEnum):
    AVAILABLE = "available"
    AVAILABLE_WITH_APPROVAL = "available_with_approval"
    BLOCKED_DEPENDENCY = "blocked_dependency"
    BLOCKED_CONFIGURATION = "blocked_configuration"
    BLOCKED_QUALIFICATION = "blocked_qualification"
    BLOCKED_AUTHORITY = "blocked_authority"
    BLOCKED_PROVISIONING = "blocked_provisioning"
    TEMPORARILY_UNAVAILABLE = "temporarily_unavailable"
    HIDDEN = "hidden"

    @property
    def model_visible(self) -> bool:
        return self in {
            ToolAffordanceState.AVAILABLE,
            ToolAffordanceState.AVAILABLE_WITH_APPROVAL,
        }


@dataclass(frozen=True, slots=True)
class ExtensionCapabilityFact:
    capability_id: str
    contract_id: str
    provider_component_id: str
    provider_version: str
    contract_digest: str
    activation_epoch: int
    contract_version: str = "1"
    operations: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, field_name="capability_id")
        require_identifier(self.contract_id, field_name="contract_id")
        require_identifier(
            self.provider_component_id,
            field_name="provider_component_id",
        )
        require_identifier(self.provider_version, field_name="provider_version")
        require_digest(self.contract_digest, field_name="contract_digest")
        if self.activation_epoch < 1:
            raise ValueError("activation_epoch must be positive")
        require_identifier(self.contract_version, field_name="contract_version")
        object.__setattr__(
            self,
            "operations",
            canonical_string_tuple(self.operations, field_name="operations"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": EXTENSION_CAPABILITY_FACT_SCHEMA_VERSION,
            "capability_id": self.capability_id,
            "contract_id": self.contract_id,
            "provider_component_id": self.provider_component_id,
            "provider_version": self.provider_version,
            "contract_digest": self.contract_digest,
            "activation_epoch": self.activation_epoch,
            "contract_version": self.contract_version,
            "operations": list(self.operations),
        }

    @property
    def fact_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class ResourceCapabilityFact:
    capability_id: str
    kind: ResourceCapabilityKind
    target_id: str
    inventory_generation: int
    qualification_digest: str
    environment_digest: str
    inventory_digest: str
    contract_version: str = "1"
    operations: tuple[str, ...] = ()
    version: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, field_name="capability_id")
        require_identifier(self.target_id, field_name="target_id")
        if self.inventory_generation < 1:
            raise ValueError("inventory_generation must be positive")
        require_digest(
            self.qualification_digest,
            field_name="qualification_digest",
        )
        require_digest(self.environment_digest, field_name="environment_digest")
        require_digest(self.inventory_digest, field_name="inventory_digest")
        require_identifier(self.contract_version, field_name="contract_version")
        object.__setattr__(
            self,
            "operations",
            canonical_string_tuple(self.operations, field_name="operations"),
        )
        if self.version is not None:
            require_identifier(self.version, field_name="version")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": RESOURCE_CAPABILITY_FACT_SCHEMA_VERSION,
            "capability_id": self.capability_id,
            "kind": self.kind.value,
            "target_id": self.target_id,
            "inventory_generation": self.inventory_generation,
            "qualification_digest": self.qualification_digest,
            "environment_digest": self.environment_digest,
            "inventory_digest": self.inventory_digest,
            "contract_version": self.contract_version,
            "operations": list(self.operations),
            "version": self.version,
        }

    @property
    def fact_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class RouteRef:
    route_id: str
    provider_component_id: str
    capability_ids: tuple[str, ...]
    route_digest: str
    capability_proof_digest: str
    target_id: str | None = None
    inventory_generation: int | None = None
    inventory_digest: str | None = None
    driver_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.route_id, field_name="route_id")
        require_identifier(
            self.provider_component_id,
            field_name="provider_component_id",
        )
        object.__setattr__(
            self,
            "capability_ids",
            canonical_string_tuple(
                self.capability_ids,
                field_name="capability_ids",
                allow_empty=False,
            ),
        )
        require_digest(self.route_digest, field_name="route_digest")
        require_digest(
            self.capability_proof_digest,
            field_name="capability_proof_digest",
        )
        target_values = (
            self.target_id,
            self.inventory_generation,
            self.inventory_digest,
        )
        if not (all(value is None for value in target_values) or all(
            value is not None for value in target_values
        )):
            raise ValueError(
                "target_id, inventory_generation and inventory_digest must be supplied together"
            )
        if self.target_id is not None:
            require_identifier(self.target_id, field_name="target_id")
            if self.inventory_generation is None or self.inventory_generation < 1:
                raise ValueError("inventory_generation must be positive")
            require_digest(self.inventory_digest or "", field_name="inventory_digest")
        if self.driver_id is not None:
            require_identifier(self.driver_id, field_name="driver_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "provider_component_id": self.provider_component_id,
            "capability_ids": list(self.capability_ids),
            "route_digest": self.route_digest,
            "capability_proof_digest": self.capability_proof_digest,
            "target_id": self.target_id,
            "inventory_generation": self.inventory_generation,
            "inventory_digest": self.inventory_digest,
            "driver_id": self.driver_id,
        }


@dataclass(frozen=True, slots=True)
class TargetInventoryBinding:
    target_id: str
    inventory_generation: int
    inventory_digest: str
    qualification_valid_until: str

    def __post_init__(self) -> None:
        require_identifier(self.target_id, field_name="target_id")
        if self.inventory_generation < 1:
            raise ValueError("inventory_generation must be positive")
        require_digest(self.inventory_digest, field_name="inventory_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "target_id": self.target_id,
            "inventory_generation": self.inventory_generation,
            "inventory_digest": self.inventory_digest,
            "qualification_valid_until": self.qualification_valid_until,
        }


@dataclass(frozen=True, slots=True)
class SessionCapabilityBindingRevision:
    binding_id: str
    session_id: str
    revision: int
    extension_bundle_digest: str
    route_catalog_digest: str
    inventory_bindings: tuple[TargetInventoryBinding, ...]
    created_by_actor_id: str
    created_at: str
    binding_digest: str

    @classmethod
    def create(
        cls,
        *,
        binding_id: str,
        session_id: str,
        revision: int,
        extension_bundle_digest: str,
        route_catalog_digest: str,
        inventory_bindings: tuple[TargetInventoryBinding, ...],
        created_by_actor_id: str,
        created_at: str,
    ) -> SessionCapabilityBindingRevision:
        binding = cls(
            binding_id=binding_id,
            session_id=session_id,
            revision=revision,
            extension_bundle_digest=extension_bundle_digest,
            route_catalog_digest=route_catalog_digest,
            inventory_bindings=inventory_bindings,
            created_by_actor_id=created_by_actor_id,
            created_at=created_at,
            binding_digest="sha256:" + "0" * 64,
        )
        return replace(
            binding,
            binding_digest=canonical_sha256_digest(binding.digest_payload()),
        )

    def __post_init__(self) -> None:
        require_identifier(self.binding_id, field_name="binding_id")
        require_identifier(self.session_id, field_name="session_id")
        require_identifier(
            self.created_by_actor_id,
            field_name="created_by_actor_id",
        )
        if self.revision < 1:
            raise ValueError("revision must be positive")
        require_digest(
            self.extension_bundle_digest,
            field_name="extension_bundle_digest",
        )
        require_digest(self.route_catalog_digest, field_name="route_catalog_digest")
        target_ids = [binding.target_id for binding in self.inventory_bindings]
        if len(set(target_ids)) != len(target_ids):
            raise ValueError("inventory_bindings must have unique target_id values")
        object.__setattr__(
            self,
            "inventory_bindings",
            tuple(
                sorted(self.inventory_bindings, key=lambda binding: binding.target_id)
            ),
        )
        require_digest(self.binding_digest, field_name="binding_digest")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": SESSION_CAPABILITY_BINDING_REVISION_SCHEMA_VERSION,
            "binding_id": self.binding_id,
            "session_id": self.session_id,
            "revision": self.revision,
            "extension_bundle_digest": self.extension_bundle_digest,
            "route_catalog_digest": self.route_catalog_digest,
            "inventory_bindings": [
                binding.to_dict() for binding in self.inventory_bindings
            ],
            "created_by_actor_id": self.created_by_actor_id,
            "created_at": self.created_at,
        }

    def has_valid_digest(self) -> bool:
        return canonical_sha256_digest(self.digest_payload()) == self.binding_digest

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "binding_digest": self.binding_digest}

    @classmethod
    def from_dict(cls, value: object) -> SessionCapabilityBindingRevision:
        expected = {
            "schema_version",
            "binding_id",
            "session_id",
            "revision",
            "extension_bundle_digest",
            "route_catalog_digest",
            "inventory_bindings",
            "created_by_actor_id",
            "created_at",
            "binding_digest",
        }
        if not isinstance(value, Mapping) or set(value) != expected:
            raise ValueError("Session capability binding fields are closed")
        if value["schema_version"] != SESSION_CAPABILITY_BINDING_REVISION_SCHEMA_VERSION:
            raise ValueError("unsupported Session capability binding schema")
        raw_bindings = value["inventory_bindings"]
        if not isinstance(raw_bindings, tuple | list) or any(
            not isinstance(item, Mapping)
            or set(item)
            != {
                "target_id",
                "inventory_generation",
                "inventory_digest",
                "qualification_valid_until",
            }
            for item in raw_bindings
        ):
            raise ValueError("Session capability inventory bindings are closed")
        binding = cls(
            binding_id=str(value["binding_id"]),
            session_id=str(value["session_id"]),
            revision=int(value["revision"]),
            extension_bundle_digest=str(value["extension_bundle_digest"]),
            route_catalog_digest=str(value["route_catalog_digest"]),
            inventory_bindings=tuple(
                TargetInventoryBinding(
                    target_id=str(item["target_id"]),
                    inventory_generation=int(item["inventory_generation"]),
                    inventory_digest=str(item["inventory_digest"]),
                    qualification_valid_until=str(
                        item["qualification_valid_until"]
                    ),
                )
                for item in raw_bindings
            ),
            created_by_actor_id=str(value["created_by_actor_id"]),
            created_at=str(value["created_at"]),
            binding_digest=str(value["binding_digest"]),
        )
        if not binding.has_valid_digest():
            raise ValueError("Session capability binding digest mismatch")
        return binding


@dataclass(frozen=True, slots=True)
class ToolAffordanceBlocker:
    code: str
    requirement: str | None = None
    target_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.code, field_name="code")
        if self.target_id is not None:
            require_identifier(self.target_id, field_name="target_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "code": self.code,
            "requirement": self.requirement,
            "target_id": self.target_id,
        }


@dataclass(frozen=True, slots=True)
class ToolAffordance:
    tool_name: str
    tool_contract_digest: str
    state: ToolAffordanceState
    required_authorities: tuple[str, ...]
    route_ids: tuple[str, ...] = ()
    route_refs: tuple[RouteRef, ...] = ()
    blockers: tuple[ToolAffordanceBlocker, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.tool_name, field_name="tool_name")
        require_digest(
            self.tool_contract_digest,
            field_name="tool_contract_digest",
        )
        object.__setattr__(
            self,
            "required_authorities",
            canonical_string_tuple(
                self.required_authorities,
                field_name="required_authorities",
            ),
        )
        object.__setattr__(
            self,
            "route_ids",
            canonical_string_tuple(self.route_ids, field_name="route_ids"),
        )
        route_ref_ids = [route.route_id for route in self.route_refs]
        if len(set(route_ref_ids)) != len(route_ref_ids):
            raise ValueError("route_refs must have unique route IDs")
        object.__setattr__(
            self,
            "route_refs",
            tuple(sorted(self.route_refs, key=lambda route: route.route_id)),
        )
        if self.route_refs and tuple(sorted(route_ref_ids)) != self.route_ids:
            raise ValueError("route_ids must exactly match route_refs")
        blocker_keys = [
            (blocker.code, blocker.requirement or "", blocker.target_id or "")
            for blocker in self.blockers
        ]
        if len(set(blocker_keys)) != len(blocker_keys):
            raise ValueError("blockers must be unique")
        object.__setattr__(
            self,
            "blockers",
            tuple(
                blocker
                for _, blocker in sorted(
                    zip(blocker_keys, self.blockers, strict=True),
                    key=lambda item: item[0],
                )
            ),
        )
        if self.state.model_visible and self.blockers:
            raise ValueError("available affordances must not contain blockers")
        if self.state is ToolAffordanceState.HIDDEN and (
            self.route_ids or self.route_refs or self.blockers
        ):
            raise ValueError("hidden affordances must not disclose routes or blockers")

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool_name": self.tool_name,
            "tool_contract_digest": self.tool_contract_digest,
            "state": self.state.value,
            "required_authorities": list(self.required_authorities),
            "route_ids": list(self.route_ids),
            "route_refs": [route.to_dict() for route in self.route_refs],
            "blockers": [blocker.to_dict() for blocker in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class ToolAffordanceSnapshot:
    snapshot_id: str
    session_id: str
    agent_member_id: str
    turn_id: str
    declared_tool_catalog_digest: str
    capability_binding_digest: str
    authority_lease_digest: str
    workspace_generation: int
    health_observation_digest: str
    subject_policy_digest: str
    affordances: tuple[ToolAffordance, ...]
    created_at: str
    snapshot_digest: str

    def __post_init__(self) -> None:
        for field_name in ("snapshot_id", "session_id", "agent_member_id", "turn_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        for field_name in (
            "declared_tool_catalog_digest",
            "capability_binding_digest",
            "authority_lease_digest",
            "health_observation_digest",
            "subject_policy_digest",
            "snapshot_digest",
        ):
            require_digest(getattr(self, field_name), field_name=field_name)
        if self.workspace_generation < 0:
            raise ValueError("workspace_generation must be non-negative")
        tool_names = [affordance.tool_name for affordance in self.affordances]
        if len(set(tool_names)) != len(tool_names):
            raise ValueError("affordances must have unique tool names")
        object.__setattr__(
            self,
            "affordances",
            tuple(
                sorted(self.affordances, key=lambda affordance: affordance.tool_name)
            ),
        )

    @property
    def model_visible_tool_names(self) -> tuple[str, ...]:
        return tuple(
            affordance.tool_name
            for affordance in self.affordances
            if affordance.state.model_visible
        )

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": TOOL_AFFORDANCE_SNAPSHOT_SCHEMA_VERSION,
            "snapshot_id": self.snapshot_id,
            "session_id": self.session_id,
            "agent_member_id": self.agent_member_id,
            "turn_id": self.turn_id,
            "declared_tool_catalog_digest": self.declared_tool_catalog_digest,
            "capability_binding_digest": self.capability_binding_digest,
            "authority_lease_digest": self.authority_lease_digest,
            "workspace_generation": self.workspace_generation,
            "health_observation_digest": self.health_observation_digest,
            "subject_policy_digest": self.subject_policy_digest,
            "affordances": [affordance.to_dict() for affordance in self.affordances],
            "created_at": self.created_at,
        }

    def has_valid_digest(self) -> bool:
        return canonical_sha256_digest(self.digest_payload()) == self.snapshot_digest

    def to_dict(self) -> dict[str, Any]:
        return {**self.digest_payload(), "snapshot_digest": self.snapshot_digest}


__all__ = [
    "EXTENSION_CAPABILITY_FACT_SCHEMA_VERSION",
    "RESOURCE_CAPABILITY_FACT_SCHEMA_VERSION",
    "SESSION_CAPABILITY_BINDING_REVISION_SCHEMA_VERSION",
    "TOOL_AFFORDANCE_SNAPSHOT_SCHEMA_VERSION",
    "ExtensionCapabilityFact",
    "ResourceCapabilityFact",
    "ResourceCapabilityKind",
    "RouteRef",
    "SessionCapabilityBindingRevision",
    "TargetInventoryBinding",
    "ToolAffordance",
    "ToolAffordanceBlocker",
    "ToolAffordanceSnapshot",
    "ToolAffordanceState",
]
