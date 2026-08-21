from importlib.metadata import EntryPoint

from openzyme_extension_spi import discover_extension_manifest_locators
from openzyme_extension_spi import read_located_component_manifest

from openzyme_research.manifest_locator import locate_component_manifest
from openzyme_research import RESEARCH_PROJECTION_CONTRACT_DIGEST


def test_research_manifest_is_exact_and_declares_owned_runtime_surfaces() -> None:
    locator = locate_component_manifest()
    manifest = read_located_component_manifest(locator)

    assert manifest.identity.component_id == "openzyme.research"
    assert [tool.contract.tool_name for tool in manifest.tools] == [
        "deep_research.start"
    ]
    assert manifest.workers[0].contribution_id == "openzyme.research.worker@1"
    assert manifest.projections[0].contribution_id == "openzyme.research@1"
    assert (
        manifest.projections[0].contract_digest
        == RESEARCH_PROJECTION_CONTRACT_DIGEST
    )
    assert manifest.projections[0].contract_digest != (
        manifest.tools[0].contract.contract_digest
    )
    assert manifest.state_namespace == "openzyme_research"


def test_research_entry_point_only_locates_manifest() -> None:
    entry = EntryPoint(
        name="openzyme.research",
        value="openzyme_research.manifest_locator:locate_component_manifest",
        group="openzyme.extensions",
    )
    located = discover_extension_manifest_locators((entry,))
    assert located == (locate_component_manifest(),)
