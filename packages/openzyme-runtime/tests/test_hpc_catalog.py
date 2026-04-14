from openzyme_runtime import HpcCatalogQuery
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
    assert skill.example_invocation_shape["structure_path"] == "candidate_001.pdb"
