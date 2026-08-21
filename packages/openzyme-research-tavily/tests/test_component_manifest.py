from openzyme_extension_spi import read_located_component_manifest

from openzyme_research_tavily import locate_component_manifest


def test_tavily_manifest_explicitly_implements_research_provider_port() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.research.tavily"
    assert "openzyme.research@1" in manifest.required_contracts
    assert "openzyme.research.provider@1" in manifest.required_contracts
    assert [item.contribution_id for item in manifest.port_contracts] == [
        "openzyme.research.provider@1"
    ]
