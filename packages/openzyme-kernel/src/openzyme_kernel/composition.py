from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CapabilityCardinality
from openzyme_extension_spi import CapabilityProvision
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import DistributionManifest
from openzyme_extension_spi import PluginActivationState
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import PluginSelection

from .errors import KernelContractError


@dataclass(frozen=True, slots=True)
class ActivationBlocker:
    code: str
    capability_id: str | None = None
    requirement: str | None = None

    def to_dict(self) -> dict[str, str | None]:
        return {
            "code": self.code,
            "capability_id": self.capability_id,
            "requirement": self.requirement,
        }


@dataclass(frozen=True, slots=True)
class PluginActivation:
    selection: PluginSelection
    state: PluginActivationState
    manifest: PluginManifest | None
    blockers: tuple[ActivationBlocker, ...] = ()

    @property
    def plugin_id(self) -> str:
        return self.selection.plugin_id

    @property
    def contributes_contracts(self) -> bool:
        return self.manifest is not None and self.state in {
            PluginActivationState.ACTIVE,
            PluginActivationState.DEGRADED,
        }

    def safe_dict(self) -> dict[str, Any]:
        return {
            "plugin_id": self.plugin_id,
            "requirement_mode": self.selection.requirement_mode.value,
            "state": self.state.value,
            "manifest_digest": (
                self.manifest.manifest_digest if self.manifest is not None else None
            ),
            "blockers": [blocker.to_dict() for blocker in self.blockers],
        }


@dataclass(frozen=True, slots=True)
class ActivatedPluginComposition:
    distribution_id: str
    distribution_manifest_digest: str
    activations: tuple[PluginActivation, ...]
    extension_bundle_digest: str
    ignored_component_ids: tuple[str, ...]

    @property
    def contributing_manifests(self) -> tuple[PluginManifest, ...]:
        return tuple(
            activation.manifest
            for activation in self.activations
            if activation.contributes_contracts and activation.manifest is not None
        )

    def activation_for(self, plugin_id: str) -> PluginActivation | None:
        return next(
            (
                activation
                for activation in self.activations
                if activation.plugin_id == plugin_id
            ),
            None,
        )


def _contract_matches(contract_version: str, contract_spec: str) -> bool:
    normalized_version = contract_version.removeprefix("@")
    normalized_spec = contract_spec.removeprefix("@")
    if normalized_spec in {"*", normalized_version}:
        return True
    if normalized_spec.endswith(".*"):
        return normalized_version.startswith(normalized_spec[:-1])
    return normalized_version.split(".", maxsplit=1)[0] == normalized_spec


def _compatible_providers(
    *,
    requirement: Any,
    providers: dict[str, list[tuple[str, CapabilityProvision]]],
) -> list[tuple[str, CapabilityProvision]]:
    return [
        (plugin_id, provision)
        for plugin_id, provision in providers.get(requirement.capability_id, [])
        if _contract_matches(provision.contract_version, requirement.contract_spec)
        and set(requirement.operations).issubset(provision.operations)
    ]


def _reject_cycles(edges: dict[str, set[str]]) -> None:
    visiting: list[str] = []
    visited: set[str] = set()

    def visit(plugin_id: str) -> None:
        if plugin_id in visiting:
            cycle_start = visiting.index(plugin_id)
            cycle = [*visiting[cycle_start:], plugin_id]
            raise KernelContractError(
                "capability_dependency_cycle",
                "Plugin capability dependencies contain a cycle",
                details={"cycle": cycle},
            )
        if plugin_id in visited:
            return
        visiting.append(plugin_id)
        for provider_id in sorted(edges.get(plugin_id, set())):
            visit(provider_id)
        visiting.pop()
        visited.add(plugin_id)

    for plugin_id in sorted(edges):
        visit(plugin_id)


def activate_plugin_composition(
    distribution: DistributionManifest,
    *,
    located_plugin_manifests: dict[str, PluginManifest],
) -> ActivatedPluginComposition:
    selected_ids = {selection.plugin_id for selection in distribution.plugins}
    ignored_component_ids = tuple(
        sorted(set(located_plugin_manifests).difference(selected_ids))
    )
    present: dict[str, PluginManifest] = {}
    activations_by_id: dict[str, PluginActivation] = {}

    for selection in distribution.plugins:
        manifest = located_plugin_manifests.get(selection.plugin_id)
        if manifest is None:
            if selection.requirement_mode is PluginRequirementMode.REQUIRED:
                raise KernelContractError(
                    "required_plugin_missing",
                    f"required Plugin is missing: {selection.plugin_id}",
                    details={"plugin_id": selection.plugin_id},
                )
            activations_by_id[selection.plugin_id] = PluginActivation(
                selection=selection,
                state=PluginActivationState.INACTIVE,
                manifest=None,
                blockers=(ActivationBlocker(code="optional_plugin_absent"),),
            )
            continue
        if manifest.identity.component_id != selection.plugin_id:
            raise KernelContractError(
                "plugin_identity_mismatch",
                "located Plugin identity does not match the selected ID",
                details={
                    "selected_plugin_id": selection.plugin_id,
                    "observed_plugin_id": manifest.identity.component_id,
                },
            )
        if manifest.manifest_digest != selection.manifest_digest:
            raise KernelContractError(
                "plugin_manifest_digest_mismatch",
                "located Plugin manifest differs from the Distribution selection",
                details={
                    "plugin_id": selection.plugin_id,
                    "expected_manifest_digest": selection.manifest_digest,
                    "observed_manifest_digest": manifest.manifest_digest,
                },
            )
        present[selection.plugin_id] = manifest

    for driver in distribution.drivers:
        if driver.owning_plugin_id not in present:
            owner_selection = next(
                selection
                for selection in distribution.plugins
                if selection.plugin_id == driver.owning_plugin_id
            )
            if owner_selection.requirement_mode is PluginRequirementMode.OPTIONAL:
                continue
            raise KernelContractError(
                "driver_owner_inactive",
                "a selected Driver cannot activate without its owning Plugin",
                details={
                    "driver_id": driver.driver_id,
                    "owning_plugin_id": driver.owning_plugin_id,
                },
            )

    providers: dict[str, list[tuple[str, CapabilityProvision]]] = {}
    for plugin_id, manifest in present.items():
        for provision in manifest.provides:
            providers.setdefault(provision.capability_id, []).append(
                (plugin_id, provision)
            )

    for capability_id, capability_providers in sorted(providers.items()):
        if len(capability_providers) <= 1:
            continue
        if any(
            provision.cardinality is CapabilityCardinality.SINGLE
            for _, provision in capability_providers
        ):
            raise KernelContractError(
                "capability_provider_collision",
                "a single-valued capability has multiple providers",
                details={
                    "capability_id": capability_id,
                    "provider_plugin_ids": sorted(
                        plugin_id for plugin_id, _ in capability_providers
                    ),
                },
            )

    edges: dict[str, set[str]] = {plugin_id: set() for plugin_id in present}
    for plugin_id, manifest in present.items():
        resource_blockers: list[ActivationBlocker] = []
        declared_requirement_ids = {
            requirement.capability_id for requirement in manifest.requires
        }
        for requirement in manifest.requires:
            if (
                requirement.same_target_as is not None
                and requirement.same_target_as not in declared_requirement_ids
            ):
                raise KernelContractError(
                    "same_target_requirement_missing",
                    "same-target constraint references an undeclared capability requirement",
                    details={
                        "plugin_id": plugin_id,
                        "capability_id": requirement.capability_id,
                        "same_target_as": requirement.same_target_as,
                    },
                )
            if requirement.kind is CapabilityRequirementKind.RESOURCE:
                resource_blockers.append(
                    ActivationBlocker(
                        code="resource_capability_unbound",
                        capability_id=requirement.capability_id,
                        requirement=requirement.version_spec,
                    )
                )
                continue
            compatible = _compatible_providers(
                requirement=requirement,
                providers=providers,
            )
            if not compatible:
                raise KernelContractError(
                    "plugin_dependency_unsatisfied",
                    "a selected Plugin has no compatible semantic capability provider",
                    details={
                        "plugin_id": plugin_id,
                        "capability_id": requirement.capability_id,
                        "contract_spec": requirement.contract_spec,
                        "operations": list(requirement.operations),
                    },
                )
            edges[plugin_id].update(provider_id for provider_id, _ in compatible)
        selection = next(
            item for item in distribution.plugins if item.plugin_id == plugin_id
        )
        activations_by_id[plugin_id] = PluginActivation(
            selection=selection,
            state=(
                PluginActivationState.DEGRADED
                if resource_blockers
                else PluginActivationState.ACTIVE
            ),
            manifest=manifest,
            blockers=tuple(resource_blockers),
        )

    _reject_cycles(edges)
    activations = tuple(
        activations_by_id[selection.plugin_id] for selection in distribution.plugins
    )
    extension_bundle_payload = {
        "distribution_id": distribution.identity.component_id,
        "distribution_manifest_digest": distribution.manifest_digest,
        "plugins": [
            {
                "plugin_id": activation.plugin_id,
                "requirement_mode": activation.selection.requirement_mode.value,
                "presence": (
                    "present" if activation.manifest is not None else "inactive"
                ),
                "manifest_digest": (
                    activation.manifest.manifest_digest
                    if activation.manifest is not None
                    else activation.selection.manifest_digest
                ),
            }
            for activation in activations
        ],
    }
    return ActivatedPluginComposition(
        distribution_id=distribution.identity.component_id,
        distribution_manifest_digest=distribution.manifest_digest,
        activations=activations,
        extension_bundle_digest=canonical_sha256_digest(extension_bundle_payload),
        ignored_component_ids=ignored_component_ids,
    )


__all__ = [
    "ActivatedPluginComposition",
    "ActivationBlocker",
    "PluginActivation",
    "activate_plugin_composition",
]
