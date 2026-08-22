from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import canonical_string_tuple

from .contributions import CapabilityProvision
from .contributions import CapabilityRequirement
from .contributions import NamedContribution
from .contributions import HttpRouteContribution
from .contributions import QualificationSpec
from .contributions import RouteContribution
from .contributions import ToolContribution


ADAPTER_MANIFEST_SCHEMA_VERSION = "openzyme_adapter_manifest@1"
PLUGIN_MANIFEST_SCHEMA_VERSION = "openzyme_plugin_manifest@1"
DRIVER_MANIFEST_SCHEMA_VERSION = "openzyme_driver_manifest@1"
DISTRIBUTION_MANIFEST_SCHEMA_VERSION = "openzyme_distribution_manifest@1"


class ComponentKind(StrEnum):
    KERNEL = "kernel"
    ADAPTER = "adapter"
    PLUGIN = "plugin"
    DRIVER = "driver"
    DISTRIBUTION = "distribution"


class PluginRequirementMode(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class AdapterRequirementMode(StrEnum):
    REQUIRED = "required"
    OPTIONAL = "optional"


class PluginActivationState(StrEnum):
    ACTIVE = "active"
    INACTIVE = "inactive"
    DEGRADED = "degraded"


@dataclass(frozen=True, slots=True)
class ComponentIdentity:
    component_id: str
    component_kind: ComponentKind
    component_version: str
    distribution_name: str
    distribution_version: str
    build_digest: str
    contract_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "component_id",
            "component_version",
            "distribution_name",
            "distribution_version",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.build_digest, field_name="build_digest")
        require_digest(self.contract_digest, field_name="contract_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "component_id": self.component_id,
            "component_kind": self.component_kind.value,
            "component_version": self.component_version,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "build_digest": self.build_digest,
            "contract_digest": self.contract_digest,
        }


def _sorted_unique_records(
    records: tuple[Any, ...],
    *,
    key: str,
    field_name: str,
) -> tuple[Any, ...]:
    keys = [getattr(record, key) for record in records]
    if len(set(keys)) != len(keys):
        raise ValueError(f"{field_name} must have unique {key} values")
    return tuple(sorted(records, key=lambda record: getattr(record, key)))


@dataclass(frozen=True, slots=True)
class AdapterManifest:
    identity: ComponentIdentity
    required_contracts: tuple[str, ...]
    port_contracts: tuple[NamedContribution, ...]
    configuration_schema_digest: str
    preflight_contract_digest: str
    target_scoped: bool = False

    def __post_init__(self) -> None:
        if self.identity.component_kind is not ComponentKind.ADAPTER:
            raise ValueError("AdapterManifest requires an adapter identity")
        object.__setattr__(
            self,
            "required_contracts",
            canonical_string_tuple(
                self.required_contracts,
                field_name="required_contracts",
            ),
        )
        object.__setattr__(
            self,
            "port_contracts",
            _sorted_unique_records(
                self.port_contracts,
                key="contribution_id",
                field_name="port_contracts",
            ),
        )
        require_digest(
            self.configuration_schema_digest,
            field_name="configuration_schema_digest",
        )
        require_digest(
            self.preflight_contract_digest,
            field_name="preflight_contract_digest",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ADAPTER_MANIFEST_SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "required_contracts": list(self.required_contracts),
            "port_contracts": [item.to_dict() for item in self.port_contracts],
            "configuration_schema_digest": self.configuration_schema_digest,
            "preflight_contract_digest": self.preflight_contract_digest,
            "target_scoped": self.target_scoped,
        }

    @property
    def manifest_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class PluginManifest:
    identity: ComponentIdentity
    required_kernel_contract: str
    required_extension_spi_contract: str
    provides: tuple[CapabilityProvision, ...] = ()
    requires: tuple[CapabilityRequirement, ...] = ()
    tools: tuple[ToolContribution, ...] = ()
    qualification_specs: tuple[QualificationSpec, ...] = ()
    routes: tuple[RouteContribution, ...] = ()
    http_routes: tuple[HttpRouteContribution, ...] = ()
    projections: tuple[NamedContribution, ...] = ()
    ui_renderers: tuple[NamedContribution, ...] = ()
    workers: tuple[NamedContribution, ...] = ()
    finish_validators: tuple[NamedContribution, ...] = ()
    schemas: tuple[NamedContribution, ...] = ()
    migrations: tuple[NamedContribution, ...] = ()
    transaction_participants: tuple[NamedContribution, ...] = ()
    state_namespace: str | None = None
    migration_bundle_digest: str | None = None
    configuration_schema_digest: str | None = None

    def __post_init__(self) -> None:
        if self.identity.component_kind is not ComponentKind.PLUGIN:
            raise ValueError("PluginManifest requires a plugin identity")
        require_identifier(
            self.required_kernel_contract,
            field_name="required_kernel_contract",
        )
        require_identifier(
            self.required_extension_spi_contract,
            field_name="required_extension_spi_contract",
        )
        for field_name, records, key in (
            ("provides", self.provides, "capability_id"),
            ("requires", self.requires, "capability_id"),
            ("tools", self.tools, "contract"),
            (
                "qualification_specs",
                self.qualification_specs,
                "qualification_spec_id",
            ),
            ("routes", self.routes, "route_id"),
            ("http_routes", self.http_routes, "route_id"),
            ("projections", self.projections, "contribution_id"),
            ("ui_renderers", self.ui_renderers, "contribution_id"),
            ("workers", self.workers, "contribution_id"),
            ("finish_validators", self.finish_validators, "contribution_id"),
            ("schemas", self.schemas, "contribution_id"),
            ("migrations", self.migrations, "contribution_id"),
            (
                "transaction_participants",
                self.transaction_participants,
                "contribution_id",
            ),
        ):
            if field_name == "tools":
                tool_names = [record.contract.tool_name for record in records]
                if len(set(tool_names)) != len(tool_names):
                    raise ValueError("tools must have unique canonical names")
                normalized = tuple(
                    sorted(records, key=lambda record: record.contract.tool_name)
                )
            else:
                normalized = _sorted_unique_records(
                    records,
                    key=key,
                    field_name=field_name,
                )
            object.__setattr__(self, field_name, normalized)
        if any(
            tool.owner_plugin_id != self.identity.component_id for tool in self.tools
        ):
            raise ValueError("every tool must be owned by the manifest Plugin")
        if any(
            spec.owner_plugin_id != self.identity.component_id
            for spec in self.qualification_specs
        ):
            raise ValueError("every qualification spec must be owned by the Plugin")
        if any(
            route.owner_component_id != self.identity.component_id
            for route in self.routes
        ):
            raise ValueError("every route must be owned by the manifest Plugin")
        if any(
            route.owner_plugin_id != self.identity.component_id
            for route in self.http_routes
        ):
            raise ValueError("every HTTP route must be owned by the manifest Plugin")
        route_keys = [route.route_key for route in self.http_routes]
        if len(set(route_keys)) != len(route_keys):
            raise ValueError("HTTP routes must have unique normalized method/path keys")
        if (self.state_namespace is None) != (self.migration_bundle_digest is None):
            raise ValueError(
                "state_namespace and migration_bundle_digest must be supplied together"
            )
        state_contributions = (
            self.schemas,
            self.migrations,
            self.transaction_participants,
        )
        if any(state_contributions) and self.state_namespace is None:
            raise ValueError(
                "state contributions require an exact state_namespace and migration bundle"
            )
        if self.state_namespace is not None:
            require_identifier(self.state_namespace, field_name="state_namespace")
            require_digest(
                self.migration_bundle_digest or "",
                field_name="migration_bundle_digest",
            )
        if self.configuration_schema_digest is not None:
            require_digest(
                self.configuration_schema_digest,
                field_name="configuration_schema_digest",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": PLUGIN_MANIFEST_SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "required_kernel_contract": self.required_kernel_contract,
            "required_extension_spi_contract": self.required_extension_spi_contract,
            "provides": [item.to_dict() for item in self.provides],
            "requires": [item.to_dict() for item in self.requires],
            "tools": [item.to_dict() for item in self.tools],
            "qualification_specs": [
                item.to_dict() for item in self.qualification_specs
            ],
            "routes": [item.to_dict() for item in self.routes],
            "http_routes": [item.to_dict() for item in self.http_routes],
            "projections": [item.to_dict() for item in self.projections],
            "ui_renderers": [item.to_dict() for item in self.ui_renderers],
            "workers": [item.to_dict() for item in self.workers],
            "finish_validators": [item.to_dict() for item in self.finish_validators],
            "schemas": [item.to_dict() for item in self.schemas],
            "migrations": [item.to_dict() for item in self.migrations],
            "transaction_participants": [
                item.to_dict() for item in self.transaction_participants
            ],
            "state_namespace": self.state_namespace,
            "migration_bundle_digest": self.migration_bundle_digest,
            "configuration_schema_digest": self.configuration_schema_digest,
        }

    @property
    def manifest_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class DriverManifest:
    identity: ComponentIdentity
    owning_plugin_id: str
    owning_plugin_contract: str
    route_kind: str
    required_port_contracts: tuple[str, ...]
    workload_contract_digest: str
    result_contract_digest: str

    def __post_init__(self) -> None:
        if self.identity.component_kind is not ComponentKind.DRIVER:
            raise ValueError("DriverManifest requires a driver identity")
        for field_name in ("owning_plugin_id", "owning_plugin_contract", "route_kind"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "required_port_contracts",
            canonical_string_tuple(
                self.required_port_contracts,
                field_name="required_port_contracts",
                allow_empty=False,
            ),
        )
        require_digest(
            self.workload_contract_digest,
            field_name="workload_contract_digest",
        )
        require_digest(
            self.result_contract_digest,
            field_name="result_contract_digest",
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DRIVER_MANIFEST_SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "owning_plugin_id": self.owning_plugin_id,
            "owning_plugin_contract": self.owning_plugin_contract,
            "route_kind": self.route_kind,
            "required_port_contracts": list(self.required_port_contracts),
            "workload_contract_digest": self.workload_contract_digest,
            "result_contract_digest": self.result_contract_digest,
        }

    @property
    def manifest_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class KernelSelection:
    contract_id: str
    contract_digest: str
    implementation_component_id: str
    implementation_manifest_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.contract_id, field_name="contract_id")
        require_identifier(
            self.implementation_component_id,
            field_name="implementation_component_id",
        )
        require_digest(self.contract_digest, field_name="contract_digest")
        require_digest(
            self.implementation_manifest_digest,
            field_name="implementation_manifest_digest",
        )

    def to_dict(self) -> dict[str, str]:
        return {
            "contract_id": self.contract_id,
            "contract_digest": self.contract_digest,
            "implementation_component_id": self.implementation_component_id,
            "implementation_manifest_digest": self.implementation_manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class AdapterSelection:
    slot_id: str
    adapter_component_id: str
    manifest_digest: str
    target_id: str | None = None
    requirement_mode: AdapterRequirementMode = AdapterRequirementMode.REQUIRED

    def __post_init__(self) -> None:
        require_identifier(self.slot_id, field_name="slot_id")
        require_identifier(
            self.adapter_component_id,
            field_name="adapter_component_id",
        )
        require_digest(self.manifest_digest, field_name="manifest_digest")
        if self.target_id is not None:
            require_identifier(self.target_id, field_name="target_id")

    @property
    def selection_key(self) -> str:
        return f"{self.slot_id}:{self.target_id or '-'}"

    def to_dict(self) -> dict[str, str | None]:
        return {
            "slot_id": self.slot_id,
            "adapter_component_id": self.adapter_component_id,
            "manifest_digest": self.manifest_digest,
            "target_id": self.target_id,
            "requirement_mode": self.requirement_mode.value,
        }


@dataclass(frozen=True, slots=True)
class PluginSelection:
    plugin_id: str
    manifest_digest: str
    requirement_mode: PluginRequirementMode

    def __post_init__(self) -> None:
        require_identifier(self.plugin_id, field_name="plugin_id")
        require_digest(self.manifest_digest, field_name="manifest_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "plugin_id": self.plugin_id,
            "manifest_digest": self.manifest_digest,
            "requirement_mode": self.requirement_mode.value,
        }


@dataclass(frozen=True, slots=True)
class DriverSelection:
    slot_id: str
    driver_id: str
    owning_plugin_id: str
    manifest_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.slot_id, field_name="slot_id")
        require_identifier(self.driver_id, field_name="driver_id")
        require_identifier(self.owning_plugin_id, field_name="owning_plugin_id")
        require_digest(self.manifest_digest, field_name="manifest_digest")

    @property
    def selection_key(self) -> str:
        return self.slot_id

    def to_dict(self) -> dict[str, str]:
        return {
            "slot_id": self.slot_id,
            "driver_id": self.driver_id,
            "owning_plugin_id": self.owning_plugin_id,
            "manifest_digest": self.manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class DeliverySurfaceSelection:
    component_id: str
    distribution_name: str
    distribution_version: str
    build_digest: str
    contract_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "component_id",
            "distribution_name",
            "distribution_version",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.build_digest, field_name="build_digest")
        require_digest(self.contract_digest, field_name="contract_digest")

    @property
    def selection_key(self) -> str:
        return self.component_id

    def to_dict(self) -> dict[str, str]:
        return {
            "component_id": self.component_id,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "build_digest": self.build_digest,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class DistributionManifest:
    identity: ComponentIdentity
    kernel: KernelSelection
    adapters: tuple[AdapterSelection, ...]
    plugins: tuple[PluginSelection, ...]
    drivers: tuple[DriverSelection, ...]
    delivery_surfaces: tuple[DeliverySurfaceSelection, ...]

    def __post_init__(self) -> None:
        if self.identity.component_kind is not ComponentKind.DISTRIBUTION:
            raise ValueError("DistributionManifest requires a distribution identity")
        adapter_keys = [selection.selection_key for selection in self.adapters]
        if len(set(adapter_keys)) != len(adapter_keys):
            raise ValueError("Adapter slots must have one exact selected provider")
        object.__setattr__(
            self,
            "adapters",
            tuple(sorted(self.adapters, key=lambda selection: selection.selection_key)),
        )
        object.__setattr__(
            self,
            "plugins",
            _sorted_unique_records(
                self.plugins,
                key="plugin_id",
                field_name="plugins",
            ),
        )
        object.__setattr__(
            self,
            "drivers",
            _sorted_unique_records(
                self.drivers,
                key="selection_key",
                field_name="drivers",
            ),
        )
        driver_ids = [selection.driver_id for selection in self.drivers]
        if len(set(driver_ids)) != len(driver_ids):
            raise ValueError("Drivers must have globally unique driver_id values")
        object.__setattr__(
            self,
            "delivery_surfaces",
            _sorted_unique_records(
                self.delivery_surfaces,
                key="selection_key",
                field_name="delivery_surfaces",
            ),
        )
        selected_plugin_ids = {selection.plugin_id for selection in self.plugins}
        orphan_drivers = [
            selection.driver_id
            for selection in self.drivers
            if selection.owning_plugin_id not in selected_plugin_ids
        ]
        if orphan_drivers:
            raise ValueError(
                f"Drivers require their owning Plugin: {sorted(orphan_drivers)!r}"
            )

    @property
    def required_plugin_ids(self) -> tuple[str, ...]:
        return tuple(
            selection.plugin_id
            for selection in self.plugins
            if selection.requirement_mode is PluginRequirementMode.REQUIRED
        )

    @property
    def optional_plugin_ids(self) -> tuple[str, ...]:
        return tuple(
            selection.plugin_id
            for selection in self.plugins
            if selection.requirement_mode is PluginRequirementMode.OPTIONAL
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DISTRIBUTION_MANIFEST_SCHEMA_VERSION,
            "identity": self.identity.to_dict(),
            "kernel": self.kernel.to_dict(),
            "adapters": [selection.to_dict() for selection in self.adapters],
            "plugins": [selection.to_dict() for selection in self.plugins],
            "drivers": [selection.to_dict() for selection in self.drivers],
            "delivery_surfaces": [
                selection.to_dict() for selection in self.delivery_surfaces
            ],
        }

    @property
    def manifest_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


ComponentManifest = AdapterManifest | PluginManifest | DriverManifest


__all__ = [
    "ADAPTER_MANIFEST_SCHEMA_VERSION",
    "DISTRIBUTION_MANIFEST_SCHEMA_VERSION",
    "DRIVER_MANIFEST_SCHEMA_VERSION",
    "PLUGIN_MANIFEST_SCHEMA_VERSION",
    "AdapterManifest",
    "AdapterRequirementMode",
    "AdapterSelection",
    "ComponentIdentity",
    "ComponentKind",
    "ComponentManifest",
    "DistributionManifest",
    "DeliverySurfaceSelection",
    "DriverManifest",
    "DriverSelection",
    "KernelSelection",
    "PluginActivationState",
    "PluginManifest",
    "PluginRequirementMode",
    "PluginSelection",
]
