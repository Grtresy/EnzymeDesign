from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from openzyme_contracts import DeploymentActivationEpoch
from openzyme_contracts import LayeredReleaseIdentity
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_extension_spi import CapabilityRouteRuntimeContribution
from openzyme_extension_spi import ExtensionTransactionParticipant
from openzyme_extension_spi import HttpRouteRuntimeContribution
from openzyme_extension_spi import ProjectionContributor
from openzyme_extension_spi import TaskEvidenceValidator
from openzyme_extension_spi import ToolRuntimeContribution
from openzyme_extension_spi import WorkerContributor

from .activation import ActivatedDistributionComposition
from .deployment_activation import DeploymentActivationGate
from .deployment_activation import DeploymentSurface
from .errors import KernelContractError


MOUNTED_EXTENSION_SURFACES_SCHEMA_VERSION = "openzyme_mounted_extension_surfaces@1"


@dataclass(frozen=True, slots=True)
class PluginRuntimeContributions:
    owner_plugin_id: str
    manifest_digest: str
    tools: tuple[ToolRuntimeContribution, ...] = ()
    capability_routes: tuple[CapabilityRouteRuntimeContribution, ...] = ()
    http_routes: tuple[HttpRouteRuntimeContribution, ...] = ()
    projections: tuple[ProjectionContributor, ...] = ()
    workers: tuple[WorkerContributor, ...] = ()
    finish_validators: tuple[TaskEvidenceValidator, ...] = ()
    transaction_participants: tuple[ExtensionTransactionParticipant, ...] = ()

    def __post_init__(self) -> None:
        require_identifier(self.owner_plugin_id, field_name="owner_plugin_id")
        require_digest(self.manifest_digest, field_name="manifest_digest")


@dataclass(frozen=True, slots=True)
class MountedExtensionSurfaces:
    epoch_id: str
    activation_digest: str
    tools: tuple[tuple[str, ToolRuntimeContribution], ...]
    capability_routes: tuple[tuple[str, CapabilityRouteRuntimeContribution], ...]
    http_routes: tuple[tuple[str, HttpRouteRuntimeContribution], ...]
    projections: tuple[tuple[str, ProjectionContributor], ...]
    workers: tuple[tuple[str, WorkerContributor], ...]
    finish_validators: tuple[tuple[str, TaskEvidenceValidator], ...]
    transaction_participants: tuple[
        tuple[str, ExtensionTransactionParticipant], ...
    ]
    mount_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.epoch_id, field_name="epoch_id")
        require_digest(self.activation_digest, field_name="activation_digest")
        require_digest(self.mount_digest, field_name="mount_digest")
        placeholder = "sha256:" + "0" * 64
        if (
            self.mount_digest != placeholder
            and self.mount_digest != canonical_sha256_digest(self.digest_payload())
        ):
            raise ValueError("mount_digest does not match mounted identities")

    def digest_payload(self) -> dict[str, Any]:
        return {
            "schema_version": MOUNTED_EXTENSION_SURFACES_SCHEMA_VERSION,
            "epoch_id": self.epoch_id,
            "activation_digest": self.activation_digest,
            "tools": [item[0] for item in self.tools],
            "capability_routes": [item[0] for item in self.capability_routes],
            "http_routes": [item[0] for item in self.http_routes],
            "projections": [item[0] for item in self.projections],
            "workers": [item[0] for item in self.workers],
            "finish_validators": [item[0] for item in self.finish_validators],
            "transaction_participants": [
                item[0] for item in self.transaction_participants
            ],
        }


def mount_extension_surfaces(
    *,
    gate: DeploymentActivationGate,
    composition: ActivatedDistributionComposition,
    runtime_bundles: tuple[PluginRuntimeContributions, ...],
) -> MountedExtensionSurfaces:
    """Validate every runtime object before returning one immutable mount set."""

    authorizations = {
        surface: gate.require_active(surface)
        for surface in (
            DeploymentSurface.REPOSITORY_WRITER,
            DeploymentSurface.HTTP_ROUTE,
            DeploymentSurface.WORKER,
            DeploymentSurface.RUNTIME,
        )
    }
    epochs = {
        gate.validate_authorization(authorization, surface=surface)
        for surface, authorization in authorizations.items()
    }
    if len({epoch.activation_digest for epoch in epochs}) != 1:
        raise KernelContractError(
            "deployment_activation_changed_during_mount",
            "deployment activation changed while validating extension surfaces",
        )
    epoch = next(iter(epochs))
    if epoch.composition_bundle_digest != _composition_bundle_digest(
        composition,
        epoch.release_identity,
    ):
        raise KernelContractError(
            "extension_mount_composition_drift",
            "runtime mount composition differs from the active deployment epoch",
            details={"epoch_id": epoch.epoch_id},
        )

    bundles_by_owner = _unique_bundles(runtime_bundles)
    contributing = {
        manifest.identity.component_id: manifest
        for manifest in composition.plugins.contributing_manifests
    }
    unexpected = sorted(set(bundles_by_owner).difference(contributing))
    if unexpected:
        raise KernelContractError(
            "runtime_bundle_unselected",
            "runtime contributions were supplied for an inactive or unselected Plugin",
            details={"plugin_ids": unexpected},
        )

    all_tools: list[tuple[str, ToolRuntimeContribution]] = []
    all_routes: list[tuple[str, CapabilityRouteRuntimeContribution]] = []
    all_http: list[tuple[str, HttpRouteRuntimeContribution]] = []
    all_projections: list[tuple[str, ProjectionContributor]] = []
    all_workers: list[tuple[str, WorkerContributor]] = []
    all_validators: list[tuple[str, TaskEvidenceValidator]] = []
    all_participants: list[tuple[str, ExtensionTransactionParticipant]] = []

    active_driver_owners = {
        binding.manifest.identity.component_id: binding.manifest.owning_plugin_id
        for binding in composition.drivers
    }
    for plugin_id, manifest in sorted(contributing.items()):
        expected_surface_count = sum(
            len(items)
            for items in (
                manifest.tools,
                manifest.routes,
                manifest.http_routes,
                manifest.projections,
                manifest.workers,
                manifest.finish_validators,
                manifest.transaction_participants,
            )
        )
        bundle = bundles_by_owner.get(plugin_id)
        if bundle is None:
            if expected_surface_count:
                raise KernelContractError(
                    "plugin_runtime_bundle_missing",
                    "Plugin declares runtime surfaces but supplied no runtime bundle",
                    details={"plugin_id": plugin_id},
                )
            continue
        if bundle.manifest_digest != manifest.manifest_digest:
            raise KernelContractError(
                "plugin_runtime_manifest_drift",
                "Plugin runtime bundle belongs to another manifest",
                details={"plugin_id": plugin_id},
            )
        _reject_forbidden_implementation_modules(bundle)

        expected_tools = {
            item.contract.tool_name: item for item in manifest.tools
        }
        mounted_tools = _unique_runtime_objects(
            bundle.tools,
            key=lambda item: item.contract.tool_name,
            collision_code="tool_runtime_collision",
        )
        _require_exact_keys(
            plugin_id,
            "tool",
            expected_tools,
            mounted_tools,
        )
        for tool_name, runtime in mounted_tools.items():
            declaration = expected_tools[tool_name]
            if (
                runtime.owner_plugin_id != plugin_id
                or runtime.runtime_id != declaration.runtime_id
                or runtime.contract.contract_digest
                != declaration.contract.contract_digest
            ):
                raise KernelContractError(
                    "tool_runtime_contract_drift",
                    "tool runtime differs from its exact Plugin declaration",
                    details={"plugin_id": plugin_id, "tool_name": tool_name},
                )
            all_tools.append((tool_name, runtime))

        expected_routes = {item.route_id: item for item in manifest.routes}
        mounted_routes = _unique_runtime_objects(
            bundle.capability_routes,
            key=lambda item: item.route_id,
            collision_code="capability_route_runtime_collision",
        )
        _require_exact_keys(plugin_id, "capability_route", expected_routes, mounted_routes)
        for route_id, runtime in mounted_routes.items():
            declaration = expected_routes[route_id]
            if (
                runtime.owner_plugin_id != plugin_id
                or runtime.driver_id != declaration.driver_id
            ):
                raise KernelContractError(
                    "capability_route_runtime_drift",
                    "capability route runtime differs from its declaration",
                    details={"plugin_id": plugin_id, "route_id": route_id},
                )
            if declaration.driver_id is not None and (
                active_driver_owners.get(declaration.driver_id) != plugin_id
            ):
                raise KernelContractError(
                    "driver_route_owner_mismatch",
                    "Driver runtime may only mount on a route owned by its Plugin",
                    details={
                        "plugin_id": plugin_id,
                        "route_id": route_id,
                        "driver_id": declaration.driver_id,
                    },
                )
            all_routes.append((route_id, runtime))

        expected_http = {item.route_id: item for item in manifest.http_routes}
        mounted_http = _unique_runtime_objects(
            bundle.http_routes,
            key=lambda item: item.route_id,
            collision_code="http_route_runtime_collision",
        )
        _require_exact_keys(plugin_id, "http_route", expected_http, mounted_http)
        for route_id, runtime in mounted_http.items():
            declaration = expected_http[route_id]
            if (
                runtime.owner_plugin_id != plugin_id
                or runtime.method != declaration.method.value
                or runtime.path != declaration.path
                or runtime.contract_digest != declaration.contract_digest
            ):
                raise KernelContractError(
                    "http_route_runtime_contract_drift",
                    "HTTP route runtime differs from its exact Plugin declaration",
                    details={"plugin_id": plugin_id, "route_id": route_id},
                )
            all_http.append((route_id, runtime))

        expected_projections = {
            item.contribution_id: item for item in manifest.projections
        }
        mounted_projections = _unique_runtime_objects(
            bundle.projections,
            key=lambda item: item.section_id,
            collision_code="projection_runtime_collision",
        )
        _require_exact_keys(
            plugin_id,
            "projection",
            expected_projections,
            mounted_projections,
        )
        for section_id, runtime in mounted_projections.items():
            if (
                runtime.section_contract_digest
                != expected_projections[section_id].contract_digest
            ):
                raise KernelContractError(
                    "projection_runtime_contract_drift",
                    "projection runtime differs from its manifest contract",
                    details={"plugin_id": plugin_id, "section_id": section_id},
                )
            all_projections.append((section_id, runtime))

        expected_workers = {item.contribution_id for item in manifest.workers}
        mounted_workers = _unique_runtime_objects(
            bundle.workers,
            key=lambda item: item.worker_id,
            collision_code="worker_runtime_collision",
        )
        _require_exact_keys(plugin_id, "worker", expected_workers, mounted_workers)
        all_workers.extend(mounted_workers.items())

        expected_validators = {
            item.contribution_id for item in manifest.finish_validators
        }
        mounted_validators = _unique_runtime_objects(
            bundle.finish_validators,
            key=lambda item: item.validator_id,
            collision_code="finish_validator_runtime_collision",
        )
        _require_exact_keys(
            plugin_id,
            "finish_validator",
            expected_validators,
            mounted_validators,
        )
        all_validators.extend(mounted_validators.items())

        expected_participants = {
            item.contribution_id for item in manifest.transaction_participants
        }
        mounted_participants = _unique_runtime_objects(
            bundle.transaction_participants,
            key=lambda item: item.participant_id,
            collision_code="transaction_participant_runtime_collision",
        )
        _require_exact_keys(
            plugin_id,
            "transaction_participant",
            expected_participants,
            mounted_participants,
        )
        for participant_id, participant in mounted_participants.items():
            if participant.state_namespace != manifest.state_namespace:
                raise KernelContractError(
                    "transaction_participant_namespace_drift",
                    "transaction participant crossed its Plugin namespace",
                    details={
                        "plugin_id": plugin_id,
                        "participant_id": participant_id,
                    },
                )
            all_participants.append((participant_id, participant))

    mounted = MountedExtensionSurfaces(
        epoch_id=epoch.epoch_id,
        activation_digest=epoch.activation_digest,
        tools=tuple(sorted(all_tools, key=lambda item: item[0])),
        capability_routes=tuple(sorted(all_routes, key=lambda item: item[0])),
        http_routes=tuple(sorted(all_http, key=lambda item: item[0])),
        projections=tuple(sorted(all_projections, key=lambda item: item[0])),
        workers=tuple(sorted(all_workers, key=lambda item: item[0])),
        finish_validators=tuple(sorted(all_validators, key=lambda item: item[0])),
        transaction_participants=tuple(
            sorted(all_participants, key=lambda item: item[0])
        ),
        mount_digest="sha256:" + "0" * 64,
    )
    return MountedExtensionSurfaces(
        epoch_id=mounted.epoch_id,
        activation_digest=mounted.activation_digest,
        tools=mounted.tools,
        capability_routes=mounted.capability_routes,
        http_routes=mounted.http_routes,
        projections=mounted.projections,
        workers=mounted.workers,
        finish_validators=mounted.finish_validators,
        transaction_participants=mounted.transaction_participants,
        mount_digest=canonical_sha256_digest(mounted.digest_payload()),
    )


def _composition_bundle_digest(
    composition: ActivatedDistributionComposition,
    release_identity: LayeredReleaseIdentity,
) -> str:
    provisional = DeploymentActivationEpoch.create(
        epoch_id="comparison-epoch",
        sequence=1,
        distribution_id=composition.distribution_id,
        kernel_manifest_digest=composition.kernel_identity.manifest_digest,
        distribution_manifest_digest=composition.distribution_manifest_digest,
        composition_document_digest=composition.composition_document_digest,
        composition_activation_digest=composition.activation_digest,
        driver_bundle_digest=composition.driver_bundle_digest,
        http_route_catalog_digest=composition.http_route_catalog.catalog_digest,
        contribution_catalogs_digest=composition.contribution_catalogs.catalogs_digest,
        release_identity=release_identity,
        schema_verification_digest="sha256:" + "1" * 64,
        wheel_verification_digest="sha256:" + "2" * 64,
        activated_by_actor_id="comparison",
        activated_at="comparison",
    )
    return provisional.composition_bundle_digest


def _unique_bundles(
    bundles: tuple[PluginRuntimeContributions, ...],
) -> dict[str, PluginRuntimeContributions]:
    result: dict[str, PluginRuntimeContributions] = {}
    for bundle in bundles:
        if bundle.owner_plugin_id in result:
            raise KernelContractError(
                "plugin_runtime_bundle_collision",
                "more than one runtime bundle was supplied for one Plugin",
                details={"plugin_id": bundle.owner_plugin_id},
            )
        result[bundle.owner_plugin_id] = bundle
    return result


def _unique_runtime_objects(
    values: tuple[Any, ...],
    *,
    key: Callable[[Any], str],
    collision_code: str,
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for value in values:
        identity = key(value)
        require_identifier(identity, field_name="runtime_contribution_id")
        if identity in result:
            raise KernelContractError(
                collision_code,
                "runtime bundle repeats a contribution identity",
                details={"contribution_id": identity},
            )
        result[identity] = value
    return result


def _require_exact_keys(
    plugin_id: str,
    kind: str,
    expected: Any,
    observed: dict[str, Any],
) -> None:
    expected_keys = set(expected)
    observed_keys = set(observed)
    if expected_keys != observed_keys:
        raise KernelContractError(
            "plugin_runtime_surface_incomplete",
            "Plugin runtime bundle does not exactly implement its manifest surface",
            details={
                "plugin_id": plugin_id,
                "surface_kind": kind,
                "missing_ids": sorted(expected_keys - observed_keys),
                "unexpected_ids": sorted(observed_keys - expected_keys),
            },
        )


def _reject_forbidden_implementation_modules(
    bundle: PluginRuntimeContributions,
) -> None:
    values = (
        *bundle.tools,
        *bundle.capability_routes,
        *bundle.http_routes,
        *bundle.projections,
        *bundle.workers,
        *bundle.finish_validators,
        *bundle.transaction_participants,
    )
    forbidden_roots = ("openzyme_host_api", "openzyme_core.repositories")
    for value in values:
        module = type(value).__module__
        if module.startswith(forbidden_roots):
            raise KernelContractError(
                "plugin_runtime_forbidden_dependency",
                "Plugin runtime surface is implemented by a Host or legacy repository module",
                details={
                    "plugin_id": bundle.owner_plugin_id,
                    "module": module,
                },
            )


__all__ = [
    "MOUNTED_EXTENSION_SURFACES_SCHEMA_VERSION",
    "MountedExtensionSurfaces",
    "PluginRuntimeContributions",
    "mount_extension_surfaces",
]
