from pathlib import Path

from openzyme_core import SkillRegistry


class CountingSkillRegistry(SkillRegistry):
    def __init__(self, *, catalog_root: Path) -> None:
        self.load_calls = 0
        super().__init__(catalog_root=catalog_root)

    def _read_skill_markdown(self, descriptor):  # type: ignore[override]
        self.load_calls += 1
        return super()._read_skill_markdown(descriptor)


def _catalog_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "openzyme-tools"
        / "src"
        / "openzyme_tools"
        / "data"
        / "hpc_catalog"
    )


def test_skill_registry_lists_catalog_without_loading_documents() -> None:
    registry = CountingSkillRegistry(catalog_root=_catalog_root())

    descriptors = registry.list_skills()

    assert [descriptor.skill_key for descriptor in descriptors] == ["fpocket", "vina", "alphafold3"]
    assert registry.load_calls == 0


def test_skill_registry_loads_on_demand_and_caches_documents() -> None:
    registry = CountingSkillRegistry(catalog_root=_catalog_root())

    first = registry.load_skill("vina")
    second = registry.load_skill("vina")

    assert "receptor_path" in first.required_inputs
    assert "best affinity estimate" in first.outputs
    assert first.example_invocation_shape["ligand_path"] == "ligand.pdbqt"
    assert second is first
    assert registry.load_calls == 1
