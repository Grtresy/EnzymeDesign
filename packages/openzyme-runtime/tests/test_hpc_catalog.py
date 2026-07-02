from pathlib import Path

import openzyme_runtime
from openzyme_runtime import HpcCatalogQuery
from openzyme_runtime import RepoBackedHpcCatalogProvider as RuntimeRepoBackedHpcCatalogProvider
from openzyme_tools import RepoBackedHpcCatalogProvider


def test_repo_backed_hpc_catalog_provider_filters_and_reads_skills() -> None:
    provider = RepoBackedHpcCatalogProvider()

    results = provider.search_catalog(HpcCatalogQuery(query="pocket", execution_support="runnable"))

    assert [entry.tool_id for entry in results] == ["fpocket"]
    assert results[0].execution_support == "runnable"
    assert "pocket_detection" in results[0].capability_tags

    skill = provider.read_skill("fpocket")
    assert skill.tool_id == "fpocket"
    assert "structure_path" in skill.required_inputs
    assert skill.example_invocation_shape["structure_path"] == "artifact_001.pdb"


def test_runtime_catalog_provider_delegates_to_tools_catalog() -> None:
    provider = RuntimeRepoBackedHpcCatalogProvider()

    results = provider.search_catalog(HpcCatalogQuery(query="dock", execution_support="runnable"))

    assert [entry.tool_id for entry in results] == ["vina"]


def test_runtime_package_does_not_ship_duplicate_hpc_catalog_data() -> None:
    runtime_package_dir = Path(openzyme_runtime.__file__).parent

    assert not (runtime_package_dir / "data" / "hpc_catalog").exists()
