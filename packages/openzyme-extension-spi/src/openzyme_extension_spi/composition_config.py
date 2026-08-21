from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import tomllib
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .contributions import NamedContribution
from .manifests import AdapterSelection
from .manifests import AdapterRequirementMode
from .manifests import ComponentIdentity
from .manifests import ComponentKind
from .manifests import DistributionManifest
from .manifests import DriverSelection
from .manifests import KernelSelection
from .manifests import PluginRequirementMode
from .manifests import PluginSelection


COMPOSITION_DOCUMENT_SCHEMA_VERSION = "openzyme_composition@1"


class CompositionManifestState(StrEnum):
    SCAFFOLD_NOT_ACTIVATABLE = "scaffold_not_activatable"
    ACTIVE = "active"


@dataclass(frozen=True, slots=True)
class SelectedComponentPackage:
    selection_key: str
    component_id: str
    component_kind: ComponentKind
    distribution_name: str
    distribution_version: str
    manifest_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "selection_key",
            "component_id",
            "distribution_name",
            "distribution_version",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(self.manifest_digest, field_name="manifest_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "selection_key": self.selection_key,
            "component_id": self.component_id,
            "component_kind": self.component_kind.value,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "manifest_digest": self.manifest_digest,
        }


@dataclass(frozen=True, slots=True)
class DistributionCompositionDocument:
    manifest_state: CompositionManifestState
    manifest: DistributionManifest
    selected_packages: tuple[SelectedComponentPackage, ...]
    ambient_discovery_enables_components: bool
    session_hot_swap: bool

    def __post_init__(self) -> None:
        keys = [item.selection_key for item in self.selected_packages]
        if len(set(keys)) != len(keys):
            raise ValueError("selected package keys must be unique")
        expected_keys = {
            "kernel",
            *(
                f"adapter:{selection.selection_key}"
                for selection in self.manifest.adapters
            ),
            *(f"plugin:{selection.plugin_id}" for selection in self.manifest.plugins),
            *(
                f"driver:{selection.selection_key}"
                for selection in self.manifest.drivers
            ),
        }
        observed_keys = set(keys)
        if observed_keys != expected_keys:
            raise ValueError(
                "selected package references must exactly match Distribution "
                f"selections; missing={sorted(expected_keys - observed_keys)}, "
                f"unknown={sorted(observed_keys - expected_keys)}"
            )
        refs_by_key = {item.selection_key: item for item in self.selected_packages}

        def verify_ref(
            selection_key: str,
            *,
            component_id: str,
            component_kind: ComponentKind,
            manifest_digest: str,
        ) -> None:
            selected = refs_by_key[selection_key]
            if (
                selected.component_id != component_id
                or selected.component_kind is not component_kind
                or selected.manifest_digest != manifest_digest
            ):
                raise ValueError(
                    "selected package identity must exactly match its "
                    f"Distribution selection: {selection_key}"
                )

        verify_ref(
            "kernel",
            component_id=self.manifest.kernel.implementation_component_id,
            component_kind=ComponentKind.KERNEL,
            manifest_digest=self.manifest.kernel.implementation_manifest_digest,
        )
        for selection in self.manifest.adapters:
            verify_ref(
                f"adapter:{selection.selection_key}",
                component_id=selection.adapter_component_id,
                component_kind=ComponentKind.ADAPTER,
                manifest_digest=selection.manifest_digest,
            )
        for selection in self.manifest.plugins:
            verify_ref(
                f"plugin:{selection.plugin_id}",
                component_id=selection.plugin_id,
                component_kind=ComponentKind.PLUGIN,
                manifest_digest=selection.manifest_digest,
            )
        for selection in self.manifest.drivers:
            verify_ref(
                f"driver:{selection.selection_key}",
                component_id=selection.driver_id,
                component_kind=ComponentKind.DRIVER,
                manifest_digest=selection.manifest_digest,
            )
        object.__setattr__(
            self,
            "selected_packages",
            tuple(sorted(self.selected_packages, key=lambda item: item.selection_key)),
        )
        if self.ambient_discovery_enables_components or self.session_hot_swap:
            raise ValueError("ambient activation and Session hot swap must remain false")

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": COMPOSITION_DOCUMENT_SCHEMA_VERSION,
            "manifest_state": self.manifest_state.value,
            "distribution_manifest": self.manifest.to_dict(),
            "selected_packages": [item.to_dict() for item in self.selected_packages],
            "policy": {
                "ambient_discovery_enables_components": False,
                "session_hot_swap": False,
            },
        }

    @property
    def document_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


def _object(value: Any, *, field_name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{field_name} must be an object")
    return value


def _array(value: Any, *, field_name: str) -> tuple[Any, ...]:
    if not isinstance(value, list):
        raise ValueError(f"{field_name} must be an array")
    return tuple(value)


def _closed(
    value: Mapping[str, Any],
    *,
    field_name: str,
    required: frozenset[str],
    optional: frozenset[str] = frozenset(),
) -> None:
    observed = set(value)
    if observed != required | (observed & optional):
        missing = sorted(required.difference(observed))
        unknown = sorted(observed.difference(required | optional))
        raise ValueError(
            f"{field_name} fields are closed; missing={missing}, unknown={unknown}"
        )


def _text(value: Any, *, field_name: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{field_name} must be a string")
    require_identifier(value, field_name=field_name)
    return value


def _selection_ref(
    value: Mapping[str, Any],
    *,
    field_name: str,
    component_kind: ComponentKind,
    selection_key: str,
) -> SelectedComponentPackage:
    return SelectedComponentPackage(
        selection_key=selection_key,
        component_id=_text(value["component_id"], field_name=f"{field_name}.component_id"),
        component_kind=component_kind,
        distribution_name=_text(
            value["distribution_name"],
            field_name=f"{field_name}.distribution_name",
        ),
        distribution_version=_text(
            value["distribution_version"],
            field_name=f"{field_name}.distribution_version",
        ),
        manifest_digest=str(value["manifest_digest"]),
    )


def parse_distribution_composition_toml(
    source: str | bytes,
) -> DistributionCompositionDocument:
    """Parse one closed, exact Distribution selection without loading components."""

    if isinstance(source, bytes):
        source = source.decode("utf-8")
    if not isinstance(source, str):
        raise TypeError("composition source must be UTF-8 text or bytes")
    payload = tomllib.loads(source)
    required_top = frozenset(
        {
            "schema_id",
            "manifest_state",
            "distribution",
            "kernel",
            "adapters",
            "plugins",
            "drivers",
            "delivery_surfaces",
            "policy",
        }
    )
    _closed(payload, field_name="composition", required=required_top)
    if payload["schema_id"] != COMPOSITION_DOCUMENT_SCHEMA_VERSION:
        raise ValueError("composition schema_id is unsupported")
    manifest_state = CompositionManifestState(payload["manifest_state"])

    distribution = _object(payload["distribution"], field_name="distribution")
    _closed(
        distribution,
        field_name="distribution",
        required=frozenset(
            {
                "id",
                "version",
                "distribution_name",
                "build_digest",
                "contract_digest",
            }
        ),
    )
    distribution_id = _text(distribution["id"], field_name="distribution.id")
    distribution_version = _text(
        distribution["version"],
        field_name="distribution.version",
    )
    identity = ComponentIdentity(
        component_id=distribution_id,
        component_kind=ComponentKind.DISTRIBUTION,
        component_version=distribution_version,
        distribution_name=_text(
            distribution["distribution_name"],
            field_name="distribution.distribution_name",
        ),
        distribution_version=distribution_version,
        build_digest=str(distribution["build_digest"]),
        contract_digest=str(distribution["contract_digest"]),
    )

    kernel = _object(payload["kernel"], field_name="kernel")
    _closed(
        kernel,
        field_name="kernel",
        required=frozenset(
            {
                "component_id",
                "contract_id",
                "contract_digest",
                "manifest_digest",
                "distribution_name",
                "distribution_version",
            }
        ),
    )
    kernel_ref = _selection_ref(
        kernel,
        field_name="kernel",
        component_kind=ComponentKind.KERNEL,
        selection_key="kernel",
    )
    kernel_selection = KernelSelection(
        contract_id=_text(kernel["contract_id"], field_name="kernel.contract_id"),
        contract_digest=str(kernel["contract_digest"]),
        implementation_component_id=kernel_ref.component_id,
        implementation_manifest_digest=kernel_ref.manifest_digest,
    )

    adapter_selections: list[AdapterSelection] = []
    selected_packages: list[SelectedComponentPackage] = [kernel_ref]
    for index, item in enumerate(_array(payload["adapters"], field_name="adapters")):
        adapter = _object(item, field_name=f"adapters[{index}]")
        _closed(
            adapter,
            field_name=f"adapters[{index}]",
            required=frozenset(
                {
                    "slot",
                    "component_id",
                    "distribution_name",
                    "distribution_version",
                    "manifest_digest",
                }
            ),
            optional=frozenset({"target_id", "required"}),
        )
        slot_id = _text(adapter["slot"], field_name=f"adapters[{index}].slot")
        target_id = adapter.get("target_id")
        if target_id is not None:
            target_id = _text(target_id, field_name=f"adapters[{index}].target_id")
        required = adapter.get("required", True)
        if not isinstance(required, bool):
            raise ValueError(f"adapters[{index}].required must be boolean")
        selection_key = f"adapter:{slot_id}:{target_id or '-'}"
        ref = _selection_ref(
            adapter,
            field_name=f"adapters[{index}]",
            component_kind=ComponentKind.ADAPTER,
            selection_key=selection_key,
        )
        selected_packages.append(ref)
        adapter_selections.append(
            AdapterSelection(
                slot_id=slot_id,
                adapter_component_id=ref.component_id,
                manifest_digest=ref.manifest_digest,
                target_id=target_id,
                requirement_mode=(
                    AdapterRequirementMode.REQUIRED
                    if required
                    else AdapterRequirementMode.OPTIONAL
                ),
            )
        )

    plugins = _object(payload["plugins"], field_name="plugins")
    _closed(
        plugins,
        field_name="plugins",
        required=frozenset({"required", "optional"}),
    )
    plugin_selections: list[PluginSelection] = []
    for mode in (PluginRequirementMode.REQUIRED, PluginRequirementMode.OPTIONAL):
        values = _array(plugins[mode.value], field_name=f"plugins.{mode.value}")
        for index, item in enumerate(values):
            plugin = _object(item, field_name=f"plugins.{mode.value}[{index}]")
            _closed(
                plugin,
                field_name=f"plugins.{mode.value}[{index}]",
                required=frozenset(
                    {
                        "component_id",
                        "distribution_name",
                        "distribution_version",
                        "manifest_digest",
                    }
                ),
            )
            ref = _selection_ref(
                plugin,
                field_name=f"plugins.{mode.value}[{index}]",
                component_kind=ComponentKind.PLUGIN,
                selection_key=f"plugin:{plugin['component_id']}",
            )
            selected_packages.append(ref)
            plugin_selections.append(
                PluginSelection(
                    plugin_id=ref.component_id,
                    manifest_digest=ref.manifest_digest,
                    requirement_mode=mode,
                )
            )

    driver_selections: list[DriverSelection] = []
    for index, item in enumerate(_array(payload["drivers"], field_name="drivers")):
        driver = _object(item, field_name=f"drivers[{index}]")
        _closed(
            driver,
            field_name=f"drivers[{index}]",
            required=frozenset(
                {
                    "slot",
                    "component_id",
                    "owning_plugin_id",
                    "distribution_name",
                    "distribution_version",
                    "manifest_digest",
                }
            ),
        )
        slot_id = _text(driver["slot"], field_name=f"drivers[{index}].slot")
        ref = _selection_ref(
            driver,
            field_name=f"drivers[{index}]",
            component_kind=ComponentKind.DRIVER,
            selection_key=f"driver:{slot_id}",
        )
        selected_packages.append(ref)
        driver_selections.append(
            DriverSelection(
                slot_id=slot_id,
                driver_id=ref.component_id,
                owning_plugin_id=_text(
                    driver["owning_plugin_id"],
                    field_name=f"drivers[{index}].owning_plugin_id",
                ),
                manifest_digest=ref.manifest_digest,
            )
        )

    delivery_surfaces: list[NamedContribution] = []
    for index, item in enumerate(
        _array(payload["delivery_surfaces"], field_name="delivery_surfaces")
    ):
        surface = _object(item, field_name=f"delivery_surfaces[{index}]")
        _closed(
            surface,
            field_name=f"delivery_surfaces[{index}]",
            required=frozenset({"component_id", "contract_digest"}),
        )
        delivery_surfaces.append(
            NamedContribution(
                contribution_id=_text(
                    surface["component_id"],
                    field_name=f"delivery_surfaces[{index}].component_id",
                ),
                contract_digest=str(surface["contract_digest"]),
            )
        )

    policy = _object(payload["policy"], field_name="policy")
    _closed(
        policy,
        field_name="policy",
        required=frozenset(
            {"ambient_discovery_enables_components", "session_hot_swap"}
        ),
    )
    for field_name in ("ambient_discovery_enables_components", "session_hot_swap"):
        if not isinstance(policy[field_name], bool):
            raise ValueError(f"policy.{field_name} must be boolean")

    manifest = DistributionManifest(
        identity=identity,
        kernel=kernel_selection,
        adapters=tuple(adapter_selections),
        plugins=tuple(plugin_selections),
        drivers=tuple(driver_selections),
        delivery_surfaces=tuple(delivery_surfaces),
    )
    return DistributionCompositionDocument(
        manifest_state=manifest_state,
        manifest=manifest,
        selected_packages=tuple(selected_packages),
        ambient_discovery_enables_components=policy[
            "ambient_discovery_enables_components"
        ],
        session_hot_swap=policy["session_hot_swap"],
    )


__all__ = [
    "COMPOSITION_DOCUMENT_SCHEMA_VERSION",
    "CompositionManifestState",
    "DistributionCompositionDocument",
    "SelectedComponentPackage",
    "parse_distribution_composition_toml",
]
