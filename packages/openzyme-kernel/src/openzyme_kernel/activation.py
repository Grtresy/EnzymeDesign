from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import AdapterManifest
from openzyme_extension_spi import AdapterSelection
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import DistributionCompositionDocument
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import DriverSelection
from openzyme_extension_spi import ExtensionManifestLocator
from openzyme_extension_spi import NamedContribution
from openzyme_extension_spi import PluginActivationState
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import QualificationSpec
from openzyme_extension_spi import SelectedComponentPackage

from .catalog import DeclaredToolCatalog
from .catalog import DeclaredToolEntry
from .catalog import HttpRouteCatalog
from .catalog import RouteCatalog
from .catalog import build_declared_tool_catalog
from .catalog import build_http_route_catalog
from .catalog import build_route_catalog
from .composition import ActivatedPluginComposition
from .composition import activate_plugin_composition
from .errors import KernelContractError


CONTRIBUTION_CATALOG_SCHEMA_VERSION = "openzyme_contribution_catalog@1"
ACTIVATED_DISTRIBUTION_SCHEMA_VERSION = "openzyme_activated_distribution@1"


@dataclass(frozen=True, slots=True)
class KernelActivationIdentity:
    component_id: str
    distribution_name: str
    distribution_version: str
    contract_digest: str
    manifest_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "component_id",
            "distribution_name",
            "distribution_version",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.contract_digest, field_name="contract_digest")
        require_digest(self.manifest_digest, field_name="manifest_digest")


@dataclass(frozen=True, slots=True)
class ContributionCatalogEntry:
    contribution_id: str
    owner_plugin_id: str
    contract_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.contribution_id, field_name="contribution_id")
        require_identifier(self.owner_plugin_id, field_name="owner_plugin_id")
        require_digest(self.contract_digest, field_name="contract_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "contribution_id": self.contribution_id,
            "owner_plugin_id": self.owner_plugin_id,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class ContributionCatalog:
    catalog_kind: str
    entries: tuple[ContributionCatalogEntry, ...]
    catalog_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.catalog_kind, field_name="catalog_kind")
        require_digest(self.catalog_digest, field_name="catalog_digest")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": CONTRIBUTION_CATALOG_SCHEMA_VERSION,
            "catalog_kind": self.catalog_kind,
            "entries": [entry.to_dict() for entry in self.entries],
            "catalog_digest": self.catalog_digest,
        }


@dataclass(frozen=True, slots=True)
class ExtensionContributionCatalogs:
    projection: ContributionCatalog
    ui_renderer: ContributionCatalog
    worker: ContributionCatalog
    finish_validator: ContributionCatalog
    schema: ContributionCatalog
    migration: ContributionCatalog
    transaction_participant: ContributionCatalog
    qualification: ContributionCatalog

    @property
    def catalogs_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "projection": self.projection.catalog_digest,
                "ui_renderer": self.ui_renderer.catalog_digest,
                "worker": self.worker.catalog_digest,
                "finish_validator": self.finish_validator.catalog_digest,
                "schema": self.schema.catalog_digest,
                "migration": self.migration.catalog_digest,
                "transaction_participant": (
                    self.transaction_participant.catalog_digest
                ),
                "qualification": self.qualification.catalog_digest,
            }
        )


@dataclass(frozen=True, slots=True)
class ActivatedAdapterBinding:
    selection: AdapterSelection
    manifest: AdapterManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection.to_dict(),
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class ActivatedDriverBinding:
    selection: DriverSelection
    manifest: DriverManifest

    def to_dict(self) -> dict[str, Any]:
        return {
            "selection": self.selection.to_dict(),
            "manifest": self.manifest.to_dict(),
        }


@dataclass(frozen=True, slots=True)
class SelectedManifestLocators:
    selected: tuple[ExtensionManifestLocator, ...]
    ignored_component_ids: tuple[str, ...]

    @property
    def selection_digest(self) -> str:
        return canonical_sha256_digest(
            {
                "selected": [item.to_dict() for item in self.selected],
                "ignored_component_ids": list(self.ignored_component_ids),
            }
        )


@dataclass(frozen=True, slots=True)
class ActivatedDistributionComposition:
    distribution_id: str
    distribution_manifest_digest: str
    composition_document_digest: str
    kernel_identity: KernelActivationIdentity
    adapters: tuple[ActivatedAdapterBinding, ...]
    plugins: ActivatedPluginComposition
    drivers: tuple[ActivatedDriverBinding, ...]
    adapter_bundle_digest: str
    driver_bundle_digest: str
    declared_tool_catalog: DeclaredToolCatalog
    route_catalog: RouteCatalog
    http_route_catalog: HttpRouteCatalog
    contribution_catalogs: ExtensionContributionCatalogs
    ignored_component_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ACTIVATED_DISTRIBUTION_SCHEMA_VERSION,
            "distribution_id": self.distribution_id,
            "distribution_manifest_digest": self.distribution_manifest_digest,
            "composition_document_digest": self.composition_document_digest,
            "kernel_manifest_digest": self.kernel_identity.manifest_digest,
            "adapter_bundle_digest": self.adapter_bundle_digest,
            "extension_bundle_digest": self.plugins.extension_bundle_digest,
            "driver_bundle_digest": self.driver_bundle_digest,
            "declared_tool_catalog_digest": (
                self.declared_tool_catalog.catalog_digest
            ),
            "route_catalog_digest": self.route_catalog.catalog_digest,
            "http_route_catalog_digest": self.http_route_catalog.catalog_digest,
            "contribution_catalogs_digest": (
                self.contribution_catalogs.catalogs_digest
            ),
            "ignored_component_ids": list(self.ignored_component_ids),
        }

    @property
    def activation_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


def _catalog(
    kind: str,
    entries: tuple[ContributionCatalogEntry, ...],
) -> ContributionCatalog:
    by_id: dict[str, ContributionCatalogEntry] = {}
    for entry in entries:
        previous = by_id.get(entry.contribution_id)
        if previous is not None:
            raise KernelContractError(
                f"{kind}_catalog_collision",
                f"two Plugins declare the same {kind} identity",
                details={
                    "contribution_id": entry.contribution_id,
                    "first_owner_plugin_id": previous.owner_plugin_id,
                    "second_owner_plugin_id": entry.owner_plugin_id,
                },
            )
        by_id[entry.contribution_id] = entry
    canonical = tuple(by_id[key] for key in sorted(by_id))
    digest = canonical_sha256_digest(
        {
            "schema_version": CONTRIBUTION_CATALOG_SCHEMA_VERSION,
            "catalog_kind": kind,
            "entries": [entry.to_dict() for entry in canonical],
        }
    )
    return ContributionCatalog(kind, canonical, digest)


def _named_entries(
    manifests: tuple[PluginManifest, ...],
    attribute: str,
) -> tuple[ContributionCatalogEntry, ...]:
    entries: list[ContributionCatalogEntry] = []
    for manifest in manifests:
        for contribution in getattr(manifest, attribute):
            assert isinstance(contribution, NamedContribution)
            entries.append(
                ContributionCatalogEntry(
                    contribution_id=contribution.contribution_id,
                    owner_plugin_id=manifest.identity.component_id,
                    contract_digest=contribution.contract_digest,
                )
            )
    return tuple(entries)


def build_extension_contribution_catalogs(
    composition: ActivatedPluginComposition,
) -> ExtensionContributionCatalogs:
    manifests = composition.contributing_manifests
    namespaces: dict[str, str] = {}
    for manifest in manifests:
        if manifest.state_namespace is None:
            continue
        previous = namespaces.get(manifest.state_namespace)
        if previous is not None:
            raise KernelContractError(
                "migration_namespace_collision",
                "two Plugins declare the same state/migration namespace",
                details={
                    "state_namespace": manifest.state_namespace,
                    "first_owner_plugin_id": previous,
                    "second_owner_plugin_id": manifest.identity.component_id,
                },
            )
        namespaces[manifest.state_namespace] = manifest.identity.component_id

    qualification_entries: list[ContributionCatalogEntry] = []
    for manifest in manifests:
        for qualification in manifest.qualification_specs:
            assert isinstance(qualification, QualificationSpec)
            qualification_entries.append(
                ContributionCatalogEntry(
                    contribution_id=qualification.qualification_spec_id,
                    owner_plugin_id=manifest.identity.component_id,
                    contract_digest=qualification.qualification_spec_digest,
                )
            )
    return ExtensionContributionCatalogs(
        projection=_catalog("projection", _named_entries(manifests, "projections")),
        ui_renderer=_catalog(
            "ui_renderer",
            _named_entries(manifests, "ui_renderers"),
        ),
        worker=_catalog("worker", _named_entries(manifests, "workers")),
        finish_validator=_catalog(
            "finish_validator",
            _named_entries(manifests, "finish_validators"),
        ),
        schema=_catalog("schema", _named_entries(manifests, "schemas")),
        migration=_catalog("migration", _named_entries(manifests, "migrations")),
        transaction_participant=_catalog(
            "transaction_participant",
            _named_entries(manifests, "transaction_participants"),
        ),
        qualification=_catalog("qualification", tuple(qualification_entries)),
    )


def _verify_selected_package(
    selected: SelectedComponentPackage,
    *,
    component_id: str,
    component_kind: ComponentKind,
    distribution_name: str,
    distribution_version: str,
    manifest_digest: str,
) -> None:
    mismatches = {
        "component_id": selected.component_id != component_id,
        "component_kind": selected.component_kind is not component_kind,
        "distribution_name": selected.distribution_name != distribution_name,
        "distribution_version": (
            selected.distribution_version != distribution_version
        ),
        "manifest_digest": selected.manifest_digest != manifest_digest,
    }
    drifted = sorted(key for key, value in mismatches.items() if value)
    if drifted:
        raise KernelContractError(
            "selected_component_identity_drift",
            "located component differs from the exact Distribution selection",
            details={"component_id": selected.component_id, "drifted_fields": drifted},
        )


def select_distribution_manifest_locators(
    document: DistributionCompositionDocument,
    discovered: tuple[ExtensionManifestLocator, ...],
) -> SelectedManifestLocators:
    """Select exact locators without reading resources or enabling ambient wheels."""

    discovered_by_id: dict[str, ExtensionManifestLocator] = {}
    for locator in discovered:
        if locator.component_id in discovered_by_id:
            raise KernelContractError(
                "extension_locator_collision",
                "more than one locator declares the same component ID",
                details={"component_id": locator.component_id},
            )
        discovered_by_id[locator.component_id] = locator

    refs_by_component: dict[str, list[SelectedComponentPackage]] = {}
    for selected in document.selected_packages:
        if selected.component_kind is ComponentKind.KERNEL:
            continue
        refs_by_component.setdefault(selected.component_id, []).append(selected)
    for component_id, references in refs_by_component.items():
        identities = {
            (
                item.component_kind,
                item.distribution_name,
                item.distribution_version,
                item.manifest_digest,
            )
            for item in references
        }
        if len(identities) != 1:
            raise KernelContractError(
                "selected_component_package_ambiguous",
                "one component ID is selected with conflicting package identities",
                details={"component_id": component_id},
            )

    optional_plugin_ids = set(document.manifest.optional_plugin_ids)
    optional_adapter_ids = {
        selection.adapter_component_id
        for selection in document.manifest.adapters
        if selection.requirement_mode.value == "optional"
    }
    optional_driver_ids = {
        selection.driver_id
        for selection in document.manifest.drivers
        if selection.owning_plugin_id in optional_plugin_ids
    }
    selected_locators: list[ExtensionManifestLocator] = []
    for component_id in sorted(refs_by_component):
        reference = refs_by_component[component_id][0]
        locator = discovered_by_id.get(component_id)
        if locator is None:
            if (
                component_id in optional_plugin_ids
                or component_id in optional_driver_ids
                or component_id in optional_adapter_ids
            ):
                continue
            raise KernelContractError(
                "required_component_locator_missing",
                "Distribution-selected component has no installed locator",
                details={"component_id": component_id},
            )
        mismatches = {
            "component_kind": locator.component_kind is not reference.component_kind,
            "distribution_name": (
                locator.distribution_name != reference.distribution_name
            ),
            "distribution_version": (
                locator.distribution_version != reference.distribution_version
            ),
            "manifest_digest": locator.manifest_digest != reference.manifest_digest,
        }
        drifted = sorted(field for field, mismatch in mismatches.items() if mismatch)
        if drifted:
            raise KernelContractError(
                "extension_locator_identity_drift",
                "installed locator differs from the exact Distribution selection",
                details={"component_id": component_id, "drifted_fields": drifted},
            )
        selected_locators.append(locator)
    ignored = tuple(
        sorted(set(discovered_by_id).difference(refs_by_component))
    )
    return SelectedManifestLocators(tuple(selected_locators), ignored)


def activate_distribution_composition(
    document: DistributionCompositionDocument,
    *,
    kernel_identity: KernelActivationIdentity,
    located_manifests: dict[str, AdapterManifest | PluginManifest | DriverManifest],
    kernel_tools: tuple[DeclaredToolEntry, ...] = (),
) -> ActivatedDistributionComposition:
    if document.manifest_state.value != "active":
        raise KernelContractError(
            "distribution_not_activatable",
            "composition document is an explicit scaffold and cannot activate",
            details={"distribution_id": document.manifest.identity.component_id},
        )
    refs_by_key = {item.selection_key: item for item in document.selected_packages}
    kernel_ref = refs_by_key.get("kernel")
    if kernel_ref is None:
        raise KernelContractError(
            "selected_component_reference_missing",
            "Distribution has no exact selected-package reference for Kernel",
            details={"selection_key": "kernel"},
        )
    _verify_selected_package(
        kernel_ref,
        component_id=kernel_identity.component_id,
        component_kind=ComponentKind.KERNEL,
        distribution_name=kernel_identity.distribution_name,
        distribution_version=kernel_identity.distribution_version,
        manifest_digest=kernel_identity.manifest_digest,
    )
    selection = document.manifest.kernel
    if (
        selection.implementation_component_id != kernel_identity.component_id
        or selection.implementation_manifest_digest != kernel_identity.manifest_digest
        or selection.contract_digest != kernel_identity.contract_digest
    ):
        raise KernelContractError(
            "kernel_selection_identity_drift",
            "located Kernel differs from the exact Distribution selection",
            details={"component_id": kernel_identity.component_id},
        )

    adapters: list[ActivatedAdapterBinding] = []
    for adapter_selection in document.manifest.adapters:
        observed = located_manifests.get(adapter_selection.adapter_component_id)
        if observed is None and adapter_selection.requirement_mode.value == "optional":
            continue
        if not isinstance(observed, AdapterManifest):
            raise KernelContractError(
                "required_adapter_missing",
                "selected Adapter is missing or has the wrong component kind",
                details={"component_id": adapter_selection.adapter_component_id},
            )
        selection_key = f"adapter:{adapter_selection.selection_key}"
        ref = refs_by_key.get(selection_key)
        if ref is None:
            raise KernelContractError(
                "selected_component_reference_missing",
                "Distribution has no exact selected-package reference for Adapter",
                details={"selection_key": selection_key},
            )
        _verify_selected_package(
            ref,
            component_id=observed.identity.component_id,
            component_kind=ComponentKind.ADAPTER,
            distribution_name=observed.identity.distribution_name,
            distribution_version=observed.identity.distribution_version,
            manifest_digest=observed.manifest_digest,
        )
        if observed.manifest_digest != adapter_selection.manifest_digest:
            raise KernelContractError(
                "adapter_manifest_digest_mismatch",
                "selected Adapter manifest digest drifted",
                details={"component_id": observed.identity.component_id},
            )
        if observed.target_scoped != (adapter_selection.target_id is not None):
            raise KernelContractError(
                "adapter_target_scope_mismatch",
                "Adapter target scope differs from its exact slot selection",
                details={
                    "component_id": observed.identity.component_id,
                    "selection_key": selection_key,
                },
            )
        adapters.append(ActivatedAdapterBinding(adapter_selection, observed))

    selected_plugin_ids = {item.plugin_id for item in document.manifest.plugins}
    plugin_manifests: dict[str, PluginManifest] = {}
    for plugin_id in selected_plugin_ids:
        observed = located_manifests.get(plugin_id)
        if observed is None:
            continue
        if not isinstance(observed, PluginManifest):
            raise KernelContractError(
                "plugin_component_kind_mismatch",
                "selected Plugin locator resolved to another component kind",
                details={"component_id": plugin_id},
            )
        ref = refs_by_key.get(f"plugin:{plugin_id}")
        if ref is None:
            raise KernelContractError(
                "selected_component_reference_missing",
                "Distribution has no exact selected-package reference for Plugin",
                details={"selection_key": f"plugin:{plugin_id}"},
            )
        _verify_selected_package(
            ref,
            component_id=observed.identity.component_id,
            component_kind=ComponentKind.PLUGIN,
            distribution_name=observed.identity.distribution_name,
            distribution_version=observed.identity.distribution_version,
            manifest_digest=observed.manifest_digest,
        )
        if (
            observed.required_kernel_contract != selection.contract_id
            or observed.required_extension_spi_contract
            != "openzyme.extension-spi@1"
        ):
            raise KernelContractError(
                "plugin_core_contract_mismatch",
                "Plugin requires a different Kernel or Extension SPI contract",
                details={"component_id": plugin_id},
            )
        plugin_manifests[plugin_id] = observed
    plugin_composition = activate_plugin_composition(
        document.manifest,
        located_plugin_manifests=plugin_manifests,
    )

    drivers: list[ActivatedDriverBinding] = []
    for driver_selection in document.manifest.drivers:
        owner_activation = plugin_composition.activation_for(
            driver_selection.owning_plugin_id
        )
        if (
            owner_activation is None
            or owner_activation.state is PluginActivationState.INACTIVE
        ):
            continue
        observed = located_manifests.get(driver_selection.driver_id)
        if not isinstance(observed, DriverManifest):
            raise KernelContractError(
                "required_driver_missing",
                "selected Driver is missing or has the wrong component kind",
                details={"component_id": driver_selection.driver_id},
            )
        selection_key = f"driver:{driver_selection.selection_key}"
        ref = refs_by_key.get(selection_key)
        if ref is None:
            raise KernelContractError(
                "selected_component_reference_missing",
                "Distribution has no exact selected-package reference for Driver",
                details={"selection_key": selection_key},
            )
        _verify_selected_package(
            ref,
            component_id=observed.identity.component_id,
            component_kind=ComponentKind.DRIVER,
            distribution_name=observed.identity.distribution_name,
            distribution_version=observed.identity.distribution_version,
            manifest_digest=observed.manifest_digest,
        )
        if (
            observed.manifest_digest != driver_selection.manifest_digest
            or observed.owning_plugin_id != driver_selection.owning_plugin_id
        ):
            raise KernelContractError(
                "driver_selection_identity_drift",
                "Driver differs from its exact owning Plugin selection",
                details={"component_id": driver_selection.driver_id},
            )
        owner_manifest = owner_activation.manifest
        assert owner_manifest is not None
        owner_contracts = {
            f"{provision.capability_id}@{provision.contract_version.removeprefix('@')}"
            for provision in owner_manifest.provides
        }
        if observed.owning_plugin_contract not in owner_contracts:
            raise KernelContractError(
                "driver_owner_contract_mismatch",
                "Driver does not bind a capability contract provided by its owning Plugin",
                details={
                    "component_id": driver_selection.driver_id,
                    "owning_plugin_id": driver_selection.owning_plugin_id,
                },
            )
        available_port_contracts = {
            contribution.contribution_id
            for adapter in adapters
            for contribution in adapter.manifest.port_contracts
        }
        missing_ports = sorted(
            set(observed.required_port_contracts).difference(
                available_port_contracts
            )
        )
        if missing_ports:
            raise KernelContractError(
                "driver_port_contract_unsatisfied",
                "Driver requires an Adapter Port contract not selected by the Distribution",
                details={
                    "component_id": driver_selection.driver_id,
                    "missing_port_contracts": missing_ports,
                },
            )
        matching_routes = tuple(
            route
            for route in owner_manifest.routes
            if route.driver_id == observed.identity.component_id
            and route.route_kind == observed.route_kind
        )
        if not matching_routes:
            raise KernelContractError(
                "driver_route_missing",
                "Driver is not mounted by an exact route from its owning Plugin",
                details={
                    "component_id": driver_selection.driver_id,
                    "owning_plugin_id": driver_selection.owning_plugin_id,
                },
            )
        drivers.append(ActivatedDriverBinding(driver_selection, observed))

    activated_driver_ids = {
        binding.manifest.identity.component_id for binding in drivers
    }
    for manifest in plugin_composition.contributing_manifests:
        for route in manifest.routes:
            if (
                route.driver_id is not None
                and route.driver_id not in activated_driver_ids
            ):
                raise KernelContractError(
                    "route_driver_missing",
                    "Plugin route references a Driver not activated by the Distribution",
                    details={
                        "route_id": route.route_id,
                        "driver_id": route.driver_id,
                        "owner_plugin_id": manifest.identity.component_id,
                    },
                )

    contribution_catalogs = build_extension_contribution_catalogs(
        plugin_composition
    )
    declared_tools = build_declared_tool_catalog(
        kernel_tools=kernel_tools,
        composition=plugin_composition,
    )
    routes = build_route_catalog(plugin_composition)
    http_routes = build_http_route_catalog(plugin_composition)
    capability_route_ids = {route.route_id for route in routes.routes}
    http_route_ids = {route.route_id for route in http_routes.routes}
    duplicate_route_ids = sorted(capability_route_ids & http_route_ids)
    if duplicate_route_ids:
        raise KernelContractError(
            "route_id_collision",
            "capability and HTTP catalogs contain the same route ID",
            details={"route_ids": duplicate_route_ids},
        )
    canonical_adapters = tuple(
        sorted(adapters, key=lambda item: item.selection.selection_key)
    )
    canonical_drivers = tuple(
        sorted(drivers, key=lambda item: item.selection.selection_key)
    )
    adapter_bundle_digest = canonical_sha256_digest(
        [item.to_dict() for item in canonical_adapters]
    )
    driver_bundle_digest = canonical_sha256_digest(
        [item.to_dict() for item in canonical_drivers]
    )
    selected_component_ids = {
        item.component_id for item in document.selected_packages
    }
    ignored = tuple(sorted(set(located_manifests).difference(selected_component_ids)))
    return ActivatedDistributionComposition(
        distribution_id=document.manifest.identity.component_id,
        distribution_manifest_digest=document.manifest.manifest_digest,
        composition_document_digest=document.document_digest,
        kernel_identity=kernel_identity,
        adapters=canonical_adapters,
        plugins=plugin_composition,
        drivers=canonical_drivers,
        adapter_bundle_digest=adapter_bundle_digest,
        driver_bundle_digest=driver_bundle_digest,
        declared_tool_catalog=declared_tools,
        route_catalog=routes,
        http_route_catalog=http_routes,
        contribution_catalogs=contribution_catalogs,
        ignored_component_ids=ignored,
    )


__all__ = [
    "ACTIVATED_DISTRIBUTION_SCHEMA_VERSION",
    "CONTRIBUTION_CATALOG_SCHEMA_VERSION",
    "ActivatedAdapterBinding",
    "ActivatedDistributionComposition",
    "ActivatedDriverBinding",
    "ContributionCatalog",
    "ContributionCatalogEntry",
    "ExtensionContributionCatalogs",
    "KernelActivationIdentity",
    "SelectedManifestLocators",
    "activate_distribution_composition",
    "build_extension_contribution_catalogs",
    "select_distribution_manifest_locators",
]
