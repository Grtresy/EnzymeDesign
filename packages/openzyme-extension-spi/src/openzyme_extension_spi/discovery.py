from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import importlib.metadata
from typing import Any
from typing import Protocol

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier

from .manifests import ComponentKind


EXTENSION_MANIFEST_ENTRY_POINT_GROUP = "openzyme.extensions"
EXTENSION_MANIFEST_LOCATOR_SCHEMA_VERSION = "openzyme_extension_manifest_locator@1"


@dataclass(frozen=True, slots=True)
class ExtensionManifestLocator:
    """Pure package-resource locator; it is not an activation or runtime factory."""

    component_id: str
    component_kind: ComponentKind
    distribution_name: str
    distribution_version: str
    resource_package: str
    resource_name: str
    manifest_digest: str

    def __post_init__(self) -> None:
        for field_name in (
            "component_id",
            "distribution_name",
            "distribution_version",
            "resource_package",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if (
            not isinstance(self.resource_name, str)
            or not self.resource_name
            or self.resource_name.startswith("/")
            or "\\" in self.resource_name
            or ".." in self.resource_name.split("/")
        ):
            raise ValueError("resource_name must be one package-relative resource")
        require_digest(self.manifest_digest, field_name="manifest_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "schema_version": EXTENSION_MANIFEST_LOCATOR_SCHEMA_VERSION,
            "component_id": self.component_id,
            "component_kind": self.component_kind.value,
            "distribution_name": self.distribution_name,
            "distribution_version": self.distribution_version,
            "resource_package": self.resource_package,
            "resource_name": self.resource_name,
            "manifest_digest": self.manifest_digest,
        }

    @property
    def locator_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


class _EntryPointLike(Protocol):
    name: str
    group: str
    value: str

    def load(self) -> Any: ...


def discover_extension_manifest_locators(
    entry_points: Iterable[_EntryPointLike] | None = None,
) -> tuple[ExtensionManifestLocator, ...]:
    """Discover pure locators only; discovery never activates a component."""

    candidates = (
        importlib.metadata.entry_points(group=EXTENSION_MANIFEST_ENTRY_POINT_GROUP)
        if entry_points is None
        else tuple(entry_points)
    )
    located: dict[str, ExtensionManifestLocator] = {}
    for entry_point in sorted(
        (
            item
            for item in candidates
            if item.group == EXTENSION_MANIFEST_ENTRY_POINT_GROUP
        ),
        key=lambda item: (item.name, item.value),
    ):
        provider = entry_point.load()
        if not callable(provider):
            raise ValueError("extension entry point must resolve to a locator factory")
        locator = provider()
        if not isinstance(locator, ExtensionManifestLocator):
            raise ValueError("extension entry point returned a non-locator object")
        if entry_point.name != locator.component_id:
            raise ValueError("extension entry point name must equal the component ID")
        if locator.component_id in located:
            raise ValueError(f"duplicate extension locator: {locator.component_id}")
        located[locator.component_id] = locator
    return tuple(located[component_id] for component_id in sorted(located))


__all__ = [
    "EXTENSION_MANIFEST_ENTRY_POINT_GROUP",
    "EXTENSION_MANIFEST_LOCATOR_SCHEMA_VERSION",
    "ExtensionManifestLocator",
    "discover_extension_manifest_locators",
]
