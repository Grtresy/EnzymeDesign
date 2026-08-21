from openzyme_extension_spi import read_located_component_manifest

from openzyme_science_research import locate_component_manifest


def test_science_research_manifest_requires_research_and_science() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())
    assert [item.capability_id for item in manifest.requires] == [
        "openzyme.research",
        "openzyme.science",
    ]
    assert manifest.provides[0].capability_id == "openzyme.science-research"
