from pathlib import Path

from openzyme_extension_spi import AdapterRequirementMode
from openzyme_extension_spi import parse_distribution_composition_toml
from openzyme_extension_spi import read_located_component_manifest

from openzyme_research.manifest_locator import locate_component_manifest
from openzyme_research import RESEARCH_PROVIDER_CONTRACT_DIGEST
from openzyme_research import RESEARCH_START_TOOL_SPEC
from openzyme_research import ResearchProviderDescriptor
from openzyme_research import ResearchProviderKind


ROOT = Path(__file__).resolve().parents[3]


def test_research_is_absent_from_standard_and_core_has_no_task_kind_planner() -> None:
    standard = (
        ROOT / "distributions/openzyme-standard/openzyme-composition.toml"
    ).read_text(encoding="utf-8")
    retired_core_project = ROOT / "packages/openzyme-core/pyproject.toml"
    kernel_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(
            (ROOT / "packages/openzyme-kernel/src/openzyme_kernel").glob("*.py")
        )
    )

    assert "openzyme.research" not in standard
    assert not retired_core_project.exists()
    assert "DeepResearchTaskPlanner" not in kernel_sources
    assert 'task.kind == "research"' not in kernel_sources


def test_provider_is_a_tool_requirement_not_a_kernel_or_package_import() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())
    requirement = manifest.tools[0].requirements[0]

    assert requirement.capability_id == "openzyme.research.provider"
    assert requirement.operations == ("dispatch", "reconcile")
    source = (
        ROOT / "packages/openzyme-research/src/openzyme_research/services.py"
    ).read_text(encoding="utf-8")
    assert "openzyme_research_tavily" not in source
    assert "tavily" not in source.casefold()


def test_tavily_is_optional_and_absence_has_no_browser_fallback() -> None:
    composition = parse_distribution_composition_toml(
        (
            ROOT / "distributions/enzymedesign/openzyme-composition.toml"
        ).read_bytes()
    )
    research_adapters = [
        adapter
        for adapter in composition.manifest.adapters
        if adapter.slot_id == "research.provider"
    ]

    assert len(research_adapters) == 1
    assert (
        research_adapters[0].adapter_component_id == "openzyme.research.tavily"
    )
    assert (
        research_adapters[0].requirement_mode is AdapterRequirementMode.OPTIONAL
    )
    assert all(
        "browser" not in adapter.adapter_component_id
        for adapter in composition.manifest.adapters
    )


def test_research_plugin_removal_does_not_add_a_kernel_import_or_base_projection() -> None:
    kernel_sources = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(
            (ROOT / "packages/openzyme-kernel/src/openzyme_kernel").glob("*.py")
        )
    )
    standard = (
        ROOT / "distributions/openzyme-standard/openzyme-composition.toml"
    ).read_text(encoding="utf-8")

    assert "openzyme_research" not in kernel_sources
    assert "deep_research" not in kernel_sources
    assert "openzyme.research" not in standard


def test_provider_adapter_replacement_preserves_research_tool_contract() -> None:
    web = ResearchProviderDescriptor(
        adapter_component_id="example.research.web",
        provider_id="example.research.web",
        provider_kind=ResearchProviderKind.WEB,
        contract_digest=RESEARCH_PROVIDER_CONTRACT_DIGEST,
    )
    browser = ResearchProviderDescriptor(
        adapter_component_id="example.research.browser",
        provider_id="example.research.browser",
        provider_kind=ResearchProviderKind.BROWSER,
        contract_digest=RESEARCH_PROVIDER_CONTRACT_DIGEST,
    )
    manifest = read_located_component_manifest(locate_component_manifest())

    assert web.contract_digest == browser.contract_digest
    assert manifest.tools[0].contract == RESEARCH_START_TOOL_SPEC
    assert manifest.tools[0].requirements[0].capability_id == (
        "openzyme.research.provider"
    )
