from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import ComponentKind
from openzyme_extension_spi import EXTENSION_MANIFEST_ENTRY_POINT_GROUP
from openzyme_extension_spi import ExtensionManifestLocator
from openzyme_extension_spi import discover_extension_manifest_locators


def _digest(value: str) -> str:
    return canonical_sha256_digest({"value": value})


def _locator(component_id: str) -> ExtensionManifestLocator:
    return ExtensionManifestLocator(
        component_id=component_id,
        component_kind=ComponentKind.PLUGIN,
        distribution_name=component_id.replace(".", "-"),
        distribution_version="1.0.0",
        resource_package=component_id.replace(".", "_"),
        resource_name="manifests/plugin.json",
        manifest_digest=_digest(component_id),
    )


@dataclass(frozen=True)
class FakeEntryPoint:
    name: str
    provider: Any
    group: str = EXTENSION_MANIFEST_ENTRY_POINT_GROUP
    value: str = "test:locator"

    def load(self) -> Any:
        return self.provider


def test_discovery_returns_sorted_pure_locators_without_activation() -> None:
    calls: list[str] = []

    def research() -> ExtensionManifestLocator:
        calls.append("research-locator")
        return _locator("openzyme.research")

    def science() -> ExtensionManifestLocator:
        calls.append("science-locator")
        return _locator("openzyme.science")

    ignored = FakeEntryPoint(
        name="ignored",
        provider=lambda: object(),
        group="another.group",
    )
    locators = discover_extension_manifest_locators(
        (
            FakeEntryPoint("openzyme.science", science),
            ignored,
            FakeEntryPoint("openzyme.research", research),
        )
    )

    assert [item.component_id for item in locators] == [
        "openzyme.research",
        "openzyme.science",
    ]
    assert sorted(calls) == ["research-locator", "science-locator"]
    assert all(not hasattr(item, "activate") for item in locators)


def test_discovery_rejects_name_drift_duplicates_and_runtime_objects() -> None:
    with pytest.raises(ValueError, match="name"):
        discover_extension_manifest_locators(
            (
                FakeEntryPoint(
                    "openzyme.science",
                    lambda: _locator("openzyme.research"),
                ),
            )
        )
    with pytest.raises(ValueError, match="duplicate"):
        discover_extension_manifest_locators(
            (
                FakeEntryPoint("openzyme.research", lambda: _locator("openzyme.research")),
                FakeEntryPoint(
                    "openzyme.research",
                    lambda: _locator("openzyme.research"),
                    value="other:locator",
                ),
            )
        )
    with pytest.raises(ValueError, match="non-locator"):
        discover_extension_manifest_locators(
            (FakeEntryPoint("openzyme.research", lambda: object()),)
        )


@pytest.mark.parametrize(
    "resource_name",
    ("/absolute.json", "../escape.json", "folder\\manifest.json"),
)
def test_locator_resource_is_package_relative(resource_name: str) -> None:
    with pytest.raises(ValueError, match="package-relative"):
        ExtensionManifestLocator(
            component_id="openzyme.research",
            component_kind=ComponentKind.PLUGIN,
            distribution_name="openzyme-research",
            distribution_version="1.0.0",
            resource_package="openzyme_research",
            resource_name=resource_name,
            manifest_digest=_digest("manifest"),
        )
