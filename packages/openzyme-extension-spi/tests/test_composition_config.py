from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_extension_spi import CompositionManifestState
from openzyme_extension_spi import AdapterRequirementMode
from openzyme_extension_spi import PluginRequirementMode
from openzyme_extension_spi import parse_distribution_composition_toml


ROOT = Path(__file__).resolve().parents[3]


def _source(name: str) -> str:
    return (ROOT / "distributions" / name / "openzyme-composition.toml").read_text(
        encoding="utf-8"
    )


def test_standard_composition_is_closed_exact_and_plugin_free() -> None:
    document = parse_distribution_composition_toml(_source("openzyme-standard"))

    assert document.manifest_state is CompositionManifestState.ACTIVE
    assert document.manifest.identity.component_id == "openzyme.standard"
    assert document.manifest.required_plugin_ids == ()
    assert document.manifest.optional_plugin_ids == ()
    assert [item.selection_key for item in document.selected_packages] == [
        "adapter:agent.turn:-",
        "adapter:kernel.store:-",
        "adapter:process.isolation:-",
        "adapter:workspace.backend:-",
        "kernel",
    ]
    assert document.document_digest.startswith("sha256:")


def test_enzymedesign_composition_retains_package_version_and_digest() -> None:
    document = parse_distribution_composition_toml(_source("enzymedesign"))

    hmmer = next(
        item
        for item in document.selected_packages
        if item.component_id == "enzymedesign.hmmer"
    )
    assert hmmer.distribution_name == "enzymedesign-hmmer"
    assert hmmer.distribution_version == "0.1.0"
    assert hmmer.manifest_digest.startswith("sha256:")
    requirement_modes = {
        item.plugin_id: item.requirement_mode for item in document.manifest.plugins
    }
    assert requirement_modes["enzymedesign.hmmer"] is (
        PluginRequirementMode.REQUIRED
    )
    assert requirement_modes["enzymedesign.vina"] is (
        PluginRequirementMode.OPTIONAL
    )
    adapter_modes = {
        item.adapter_component_id: item.requirement_mode
        for item in document.manifest.adapters
    }
    assert adapter_modes["openzyme.research.tavily"] is (
        AdapterRequirementMode.OPTIONAL
    )
    delivery = {
        item.component_id: item for item in document.manifest.delivery_surfaces
    }
    assert delivery["openzyme.host.api"].distribution_name == "openzyme-host-api"
    assert delivery["openzyme.host.api"].distribution_version == "0.1.0"
    assert delivery["openzyme.host.api"].build_digest.startswith("sha256:")


def test_delivery_surface_requires_exact_package_and_build_identity() -> None:
    source = _source("openzyme-standard")

    with pytest.raises(ValueError, match="fields are closed"):
        parse_distribution_composition_toml(
            source.replace(
                'build_digest = "sha256:dd96218a3d0ea0645d11d99f628a1b071c2873bc917d2ef7847dc7fee974370b"',
                'build_digest = "sha256:dd96218a3d0ea0645d11d99f628a1b071c2873bc917d2ef7847dc7fee974370b", ambient = true',
                1,
            )
        )

    with pytest.raises(ValueError, match="fields are closed.*distribution_version"):
        parse_distribution_composition_toml(
            source.replace('distribution_version = "0.1.0", ', "", 1)
        )


def test_composition_rejects_unknown_fields_and_ambient_activation() -> None:
    source = _source("openzyme-standard")
    with pytest.raises(ValueError, match="fields are closed"):
        parse_distribution_composition_toml(source + "\nambient_plugin = true\n")
    with pytest.raises(ValueError, match="must remain false"):
        parse_distribution_composition_toml(
            source.replace(
                "ambient_discovery_enables_components = false",
                "ambient_discovery_enables_components = true",
            )
        )


def test_composition_rejects_duplicate_plugin_across_required_and_optional() -> None:
    source = _source("enzymedesign")
    duplicate = (
        '{ component_id = "enzymedesign.hmmer", distribution_name = '
        '"enzymedesign-hmmer", distribution_version = "0.1.0", manifest_digest = '
        '"sha256:8c5201a668786d1f64cbf56351caeb3596736e780fe75b9333a0f296c8bb4b10" },'
    )
    modified = source.replace("optional = [", f"optional = [\n  {duplicate}", 1)

    with pytest.raises(ValueError, match="unique plugin_id"):
        parse_distribution_composition_toml(modified)
