from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[3]
SCRIPT = ROOT / "scripts" / "qualify-openzyme-contract-wheels.py"


def _load_module():
    spec = importlib.util.spec_from_file_location(
        "openzyme_wheel_qualification",
        SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_wheel_profiles_have_closed_independent_installation_sets() -> None:
    module = _load_module()
    projects = module.workspace_projects()
    closures = {
        profile.profile_id: set(module.dependency_closure(profile.roots, projects))
        for profile in module.INSTALLATION_PROFILES
    }

    assert closures["contracts_spi_only"] == {
        "openzyme-contracts",
        "openzyme-extension-spi",
    }
    assert closures["kernel_only"] == {
        "openzyme-contracts",
        "openzyme-extension-spi",
        "openzyme-kernel",
        "openzyme-runtime-spi",
    }
    assert "openzyme-research" not in closures["standard_only"]
    assert "openzyme-science" not in closures["standard_only"]
    assert closures["runner_only"] == {
        "mcp-hpc-runner",
        "openzyme-contracts",
        "openzyme-execution-contracts",
    }
    assert {
        "enzymedesign-aox",
        "enzymedesign-aox-executor",
        "enzymedesign-hmmer",
        "enzymedesign-vina",
        "openzyme-hpc",
        "openzyme-research",
        "openzyme-science",
    } < closures["enzymedesign_component_set"]
    assert closures["enzymedesign_component_set"].isdisjoint(
        {"openzyme-core", "openzyme-domain", "openzyme-runtime", "openzyme-tools"}
    )
    external_closures = {
        profile.profile_id: set(
            module.external_dependency_closure(profile.roots, projects)
        )
        for profile in module.INSTALLATION_PROFILES
    }
    assert external_closures["enzymedesign_component_set"] == {
        "biopython",
        "fastapi",
        "langchain",
        "langchain-openai",
        "numpy",
        "packaging",
        "pydantic",
        "tavily-python",
    }
    assert external_closures["standard_only"] == {
        "fastapi",
        "langchain",
        "langchain-openai",
        "pydantic",
    }

    standard = next(
        profile
        for profile in module.INSTALLATION_PROFILES
        if profile.profile_id == "standard_only"
    )
    assert {
        "biopython",
        "enzymedesign",
        "meeko",
        "mcp-hpc-runner",
        "numpy",
        "openbabel-wheel",
        "openzyme-compute",
        "openzyme-hpc",
        "openzyme-hpc-slurm",
        "openzyme-hpc-ssh",
        "openzyme-research-tavily",
        "rdkit",
        "tavily-python",
    } <= set(standard.forbidden_distributions)


def test_wheel_profile_dependency_resolution_fails_closed() -> None:
    module = _load_module()
    projects = module.workspace_projects()
    with pytest.raises(
        module.WheelQualificationError,
        match="non-workspace distribution",
    ):
        module.dependency_closure(("missing-distribution",), projects)

    broken = dict(projects)
    original = broken["openzyme-kernel"]
    broken["openzyme-kernel"] = module.WorkspaceProject(
        distribution=original.distribution,
        root=original.root,
        runtime_dependencies=("ambient-provider",),
        component_kind=original.component_kind,
    )
    with pytest.raises(
        module.WheelQualificationError,
        match="non-wheelhouse runtime dependency",
    ):
        module.dependency_closure(("openzyme-kernel",), broken)
    with pytest.raises(
        module.WheelQualificationError,
        match="non-wheelhouse runtime dependency",
    ):
        module.external_dependency_closure(("openzyme-kernel",), broken)


def test_product_plugin_wheel_dependency_gate_rejects_implementations() -> None:
    module = _load_module()
    project = module.workspace_projects()["enzymedesign-hmmer"]

    module.validate_product_plugin_wheel_dependencies(
        project, project.runtime_dependencies
    )
    with pytest.raises(
        module.WheelQualificationError,
        match="product Plugin wheel has forbidden implementation dependency",
    ):
        module.validate_product_plugin_wheel_dependencies(
            project,
            (*project.runtime_dependencies, "openzyme-hpc-slurm"),
        )
