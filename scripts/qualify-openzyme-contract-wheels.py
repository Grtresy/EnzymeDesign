#!/usr/bin/env python3
"""Build and qualify exact OpenZyme wheel installation profiles offline."""

from __future__ import annotations

from dataclasses import dataclass
from email.parser import BytesParser
from email.policy import default
import json
import re
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from typing import Iterable
import zipfile


ROOT = Path(__file__).resolve().parents[1]
NORMALIZE_NAME = re.compile(r"[-_.]+")
REQUIREMENT_NAME = re.compile(r"^[A-Za-z0-9_.-]+")
ALLOWED_PROFILE_EXTERNAL_DISTRIBUTIONS = frozenset(
    {
        # Infrastructure dependencies selected by Standard Adapters.  They are
        # not OpenZyme components and therefore do not participate in the
        # manifest activation graph.
        "fastapi",
        "pydantic",
        # Product-only scientific dependencies.  Profile-specific forbidden
        # distribution checks below prove that Standard never acquires them.
        "biopython",
        "numpy",
    }
)


class WheelQualificationError(RuntimeError):
    """Raised when a wheel or an isolated installation closure drifts."""


@dataclass(frozen=True)
class WorkspaceProject:
    distribution: str
    root: Path
    runtime_dependencies: tuple[str, ...]
    component_kind: str | None


@dataclass(frozen=True)
class InstallationProfile:
    profile_id: str
    roots: tuple[str, ...]
    import_modules: tuple[str, ...]
    forbidden_distributions: tuple[str, ...]


INSTALLATION_PROFILES = (
    InstallationProfile(
        profile_id="contracts_spi_only",
        roots=("openzyme-extension-spi",),
        import_modules=("openzyme_contracts", "openzyme_extension_spi"),
        forbidden_distributions=(
            "openzyme-kernel",
            "openzyme-research",
            "openzyme-science",
        ),
    ),
    InstallationProfile(
        profile_id="kernel_only",
        roots=("openzyme-kernel",),
        import_modules=(
            "openzyme_contracts",
            "openzyme_extension_spi",
            "openzyme_kernel",
            "openzyme_runtime_spi",
        ),
        forbidden_distributions=(
            "openzyme-process-podman",
            "openzyme-research",
            "openzyme-store-sqlite",
        ),
    ),
    InstallationProfile(
        profile_id="standard_only",
        roots=("openzyme-standard",),
        import_modules=(
            "openzyme_contracts",
            "openzyme_extension_spi",
            "openzyme_host_api",
            "openzyme_kernel",
            "openzyme_process_podman",
            "openzyme_runtime_llm",
            "openzyme_runtime_spi",
            "openzyme_standard",
            "openzyme_store_sqlite",
            "openzyme_workspace_git_lfs",
        ),
        forbidden_distributions=(
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
            "openzyme-research",
            "openzyme-research-tavily",
            "openzyme-reporting",
            "openzyme-science",
            "rdkit",
            "tavily-python",
        ),
    ),
    InstallationProfile(
        profile_id="runner_only",
        roots=("mcp-hpc-runner",),
        import_modules=(
            "mcp_hpc_runner",
            "openzyme_contracts",
            "openzyme_execution_contracts",
        ),
        forbidden_distributions=(
            "openzyme-core",
            "openzyme-domain",
            "openzyme-kernel",
        ),
    ),
    InstallationProfile(
        profile_id="enzymedesign_component_set",
        roots=(
            "enzymedesign",
            "enzymedesign-alphafold",
            "enzymedesign-aox",
            "enzymedesign-aox-executor",
            "enzymedesign-bio-provider-adapters",
            "enzymedesign-bio-providers",
            "enzymedesign-docking-preprocess",
            "enzymedesign-hmmer",
            "enzymedesign-sequence-toolpack",
            "enzymedesign-structure",
            "enzymedesign-vina",
            "openzyme-compute",
            "openzyme-hpc",
            "openzyme-hpc-slurm",
            "openzyme-hpc-ssh",
            "openzyme-kernel",
            "openzyme-process-podman",
            "openzyme-reporting",
            "openzyme-research-tavily",
            "openzyme-runtime-llm",
            "openzyme-science-research",
            "openzyme-store-sqlite",
            "openzyme-workspace-git-lfs",
        ),
        import_modules=(
            "enzymedesign_distribution",
            "enzymedesign_alphafold",
            "enzymedesign_aox",
            "enzymedesign_aox_executor",
            "enzymedesign_bio_provider_adapters",
            "enzymedesign_bio_providers",
            "enzymedesign_core",
            "enzymedesign_docking_preprocess",
            "enzymedesign_hmmer",
            "enzymedesign_sequence_toolpack",
            "enzymedesign_structure",
            "enzymedesign_vina",
            "openzyme_compute",
            "openzyme_contracts",
            "openzyme_execution_contracts",
            "openzyme_extension_spi",
            "openzyme_hpc",
            "openzyme_hpc_slurm",
            "openzyme_hpc_ssh",
            "openzyme_kernel",
            "openzyme_process_podman",
            "openzyme_reporting",
            "openzyme_research",
            "openzyme_research_tavily",
            "openzyme_runtime_llm",
            "openzyme_runtime_spi",
            "openzyme_science",
            "openzyme_science_research",
            "openzyme_store_sqlite",
            "openzyme_workspace_git_lfs",
        ),
        forbidden_distributions=(
            "openzyme-core",
            "openzyme-domain",
            "openzyme-runtime",
            "openzyme-tools",
        ),
    ),
)


FORBIDDEN_PRODUCT_PLUGIN_DISTRIBUTIONS = frozenset(
    {
        "openzyme-core",
        "openzyme-domain",
        "openzyme-host-api",
        "openzyme-hpc",
        "openzyme-hpc-slurm",
        "openzyme-hpc-ssh",
        "openzyme-kernel",
        "openzyme-process-podman",
        "openzyme-runtime",
        "openzyme-runtime-llm",
        "openzyme-store-sqlite",
        "openzyme-workspace-git-lfs",
    }
)


def normalize_distribution(value: str) -> str:
    return NORMALIZE_NAME.sub("-", value).lower()


def requirement_distribution(value: str) -> str:
    match = REQUIREMENT_NAME.match(value.strip())
    if match is None:
        raise WheelQualificationError(f"invalid requirement: {value!r}")
    return normalize_distribution(match.group(0))


def workspace_projects(root: Path = ROOT) -> dict[str, WorkspaceProject]:
    projects: dict[str, WorkspaceProject] = {}
    for pyproject in sorted([*(root / "apps").glob("*/pyproject.toml"), *(root / "packages").glob("*/pyproject.toml")]):
        document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        project = document.get("project")
        if not isinstance(project, dict) or not isinstance(project.get("name"), str):
            continue
        distribution = normalize_distribution(project["name"])
        dependencies = project.get("dependencies", [])
        if not isinstance(dependencies, list) or any(
            not isinstance(item, str) for item in dependencies
        ):
            raise WheelQualificationError(
                f"{pyproject.relative_to(root)} has invalid runtime dependencies"
            )
        if distribution in projects:
            raise WheelQualificationError(f"duplicate workspace distribution: {distribution}")
        component = document.get("tool", {}).get("openzyme", {}).get("component", {})
        component_kind = component.get("component_kind")
        if component_kind is not None and not isinstance(component_kind, str):
            raise WheelQualificationError(
                f"{pyproject.relative_to(root)} has invalid component kind"
            )
        projects[distribution] = WorkspaceProject(
            distribution=distribution,
            root=pyproject.parent,
            runtime_dependencies=tuple(
                sorted(requirement_distribution(item) for item in dependencies)
            ),
            component_kind=component_kind,
        )
    return projects


def validate_product_plugin_wheel_dependencies(
    project: WorkspaceProject,
    runtime_dependencies: tuple[str, ...],
) -> None:
    if project.component_kind != "product_plugin":
        return
    matches = sorted(
        set(runtime_dependencies).intersection(
            FORBIDDEN_PRODUCT_PLUGIN_DISTRIBUTIONS
        )
    )
    if matches:
        raise WheelQualificationError(
            f"{project.distribution} product Plugin wheel has forbidden "
            f"implementation dependency: {matches!r}"
        )


def dependency_closure(
    roots: Iterable[str],
    projects: dict[str, WorkspaceProject],
) -> tuple[str, ...]:
    pending = [normalize_distribution(item) for item in roots]
    closure: set[str] = set()
    while pending:
        distribution = pending.pop()
        if distribution in closure:
            continue
        project = projects.get(distribution)
        if project is None:
            raise WheelQualificationError(
                f"profile references non-workspace distribution: {distribution}"
            )
        closure.add(distribution)
        for dependency in project.runtime_dependencies:
            if dependency in ALLOWED_PROFILE_EXTERNAL_DISTRIBUTIONS:
                continue
            if dependency not in projects:
                raise WheelQualificationError(
                    f"{distribution} has non-wheelhouse runtime dependency: {dependency}"
                )
            pending.append(dependency)
    return tuple(sorted(closure))


def external_dependency_closure(
    roots: Iterable[str],
    projects: dict[str, WorkspaceProject],
) -> tuple[str, ...]:
    pending = [normalize_distribution(item) for item in roots]
    visited: set[str] = set()
    external: set[str] = set()
    while pending:
        distribution = pending.pop()
        if distribution in visited:
            continue
        project = projects.get(distribution)
        if project is None:
            raise WheelQualificationError(
                f"profile references non-workspace distribution: {distribution}"
            )
        visited.add(distribution)
        for dependency in project.runtime_dependencies:
            if dependency in ALLOWED_PROFILE_EXTERNAL_DISTRIBUTIONS:
                external.add(dependency)
                continue
            if dependency not in projects:
                raise WheelQualificationError(
                    f"{distribution} has non-wheelhouse runtime dependency: {dependency}"
                )
            pending.append(dependency)
    return tuple(sorted(external))


def _run(*argv: str, cwd: Path = ROOT) -> None:
    subprocess.run(
        argv,
        cwd=cwd,
        check=True,
        text=True,
        timeout=240,
    )


def _wheel_metadata(wheel: Path) -> tuple[str, tuple[str, ...]]:
    with zipfile.ZipFile(wheel) as archive:
        metadata_members = [
            name for name in archive.namelist() if name.endswith(".dist-info/METADATA")
        ]
        if len(metadata_members) != 1:
            raise WheelQualificationError(
                f"{wheel.name} has {len(metadata_members)} METADATA members"
            )
        metadata = BytesParser(policy=default).parsebytes(
            archive.read(metadata_members[0])
        )
    name = metadata.get("Name")
    if not isinstance(name, str):
        raise WheelQualificationError(f"{wheel.name} has no distribution name")
    runtime_dependencies = tuple(
        sorted(
            requirement_distribution(requirement)
            for requirement in metadata.get_all("Requires-Dist", [])
            if "extra ==" not in requirement
        )
    )
    return normalize_distribution(name), runtime_dependencies


def _build_wheelhouse(
    *,
    dist_root: Path,
    projects: dict[str, WorkspaceProject],
    distributions: tuple[str, ...],
) -> dict[str, Path]:
    for distribution in distributions:
        _run(
            "uv",
            "build",
            "--offline",
            "--package",
            distribution,
            "--out-dir",
            str(dist_root),
        )
    wheels: dict[str, Path] = {}
    for wheel in sorted(dist_root.glob("*.whl")):
        distribution, requirements = _wheel_metadata(wheel)
        if distribution in wheels:
            raise WheelQualificationError(
                f"duplicate wheel for distribution: {distribution}"
            )
        if distribution not in projects:
            raise WheelQualificationError(f"unexpected wheel: {distribution}")
        if requirements != projects[distribution].runtime_dependencies:
            raise WheelQualificationError(
                f"{distribution} METADATA runtime requirements drifted: "
                f"expected={projects[distribution].runtime_dependencies!r}, "
                f"observed={requirements!r}"
            )
        validate_product_plugin_wheel_dependencies(
            projects[distribution], requirements
        )
        wheels[distribution] = wheel
    missing = set(distributions) - set(wheels)
    if missing:
        raise WheelQualificationError(f"wheel build omitted: {sorted(missing)!r}")
    return wheels


def _profile_probe_script(
    profile: InstallationProfile,
    expected_workspace_distributions: tuple[str, ...],
    workspace_distributions: tuple[str, ...],
) -> str:
    return f"""
import importlib
import importlib.metadata
import os
import socket
import sqlite3
import subprocess

def forbidden(*_args, **_kwargs):
    raise AssertionError("isolated profile import attempted external I/O")

socket.create_connection = forbidden
socket.socket.connect = forbidden
sqlite3.connect = forbidden
subprocess.Popen = forbidden
os.system = forbidden

expected_workspace = {json.dumps(list(expected_workspace_distributions))}
workspace_distributions = set({json.dumps(list(workspace_distributions))})
observed_workspace = sorted(
    name.lower().replace("_", "-").replace(".", "-")
    for name in (
        distribution.metadata.get("Name", "")
        for distribution in importlib.metadata.distributions()
    )
    if name.lower().replace("_", "-").replace(".", "-")
    in workspace_distributions
)
assert observed_workspace == expected_workspace, (
    observed_workspace,
    expected_workspace,
)
for distribution in {json.dumps(list(profile.forbidden_distributions))}:
    try:
        importlib.metadata.distribution(distribution)
    except importlib.metadata.PackageNotFoundError:
        continue
    raise AssertionError(f"forbidden distribution installed: {{distribution}}")
for entry_point in importlib.metadata.entry_points(group="openzyme.extensions"):
    owner = entry_point.dist.metadata.get("Name", "")
    owner = owner.lower().replace("_", "-").replace(".", "-")
    assert owner in set(expected_workspace), (
        "ambient extension entry point",
        entry_point.name,
        owner,
    )
for module_name in {json.dumps(list(profile.import_modules))}:
    importlib.import_module(module_name)
"""


def _qualify_profile(
    *,
    temp_root: Path,
    dist_root: Path,
    profile: InstallationProfile,
    projects: dict[str, WorkspaceProject],
) -> None:
    expected_workspace = dependency_closure(profile.roots, projects)
    profile_root = temp_root / profile.profile_id
    _run(sys.executable, "-m", "venv", str(profile_root))
    python = profile_root / "bin" / "python"
    _run(
        "uv",
        "--offline",
        "pip",
        "install",
        "--python",
        str(python),
        "--find-links",
        str(dist_root),
        *profile.roots,
        cwd=temp_root,
    )
    _run(
        str(python),
        "-c",
        _profile_probe_script(
            profile,
            expected_workspace,
            tuple(sorted(projects)),
        ),
        cwd=temp_root,
    )


def main() -> int:
    projects = workspace_projects()
    profile_closures = {
        profile.profile_id: dependency_closure(profile.roots, projects)
        for profile in INSTALLATION_PROFILES
    }
    profile_external_closures = {
        profile.profile_id: external_dependency_closure(profile.roots, projects)
        for profile in INSTALLATION_PROFILES
    }
    distributions = tuple(
        sorted(
            {
                distribution
                for closure in profile_closures.values()
                for distribution in closure
            }
        )
    )
    with tempfile.TemporaryDirectory(prefix="openzyme-wheel-profiles-") as raw:
        temp_root = Path(raw)
        dist_root = temp_root / "dist"
        dist_root.mkdir()
        _build_wheelhouse(
            dist_root=dist_root,
            projects=projects,
            distributions=distributions,
        )
        for profile in INSTALLATION_PROFILES:
            _qualify_profile(
                temp_root=temp_root,
                dist_root=dist_root,
                profile=profile,
                projects=projects,
            )

    print(
        json.dumps(
            {
                "schema_id": "openzyme_wheel_installation_qualification@1",
                "profiles": profile_closures,
                "external_profiles": profile_external_closures,
                "network_used": False,
                "external_effects_real": False,
                "terminal_status": "pass",
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
