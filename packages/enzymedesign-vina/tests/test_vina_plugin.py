from __future__ import annotations

from importlib.resources import files
import importlib.metadata
import os
from pathlib import Path
import subprocess
import sys

import pytest

from enzymedesign_vina import VINA_COMPONENT_MANIFEST_DIGEST
from enzymedesign_vina import VINA_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_vina import VINA_HPC_DRIVER_MANIFEST_DIGEST
from enzymedesign_vina import VINA_LOCAL_DRIVER_MANIFEST_DIGEST
from enzymedesign_vina import VINA_LEGACY_RESULT_SCHEMA_DIGEST
from enzymedesign_vina import VINA_MODERN_RESULT_SCHEMA_DIGEST
from enzymedesign_vina import VINA_TOOL_SPEC
from enzymedesign_vina import VinaDriver
from enzymedesign_vina import VinaToolRuntime
from enzymedesign_vina import build_vina_plugin_runtime_surfaces
from enzymedesign_vina import locate_component_manifest
from enzymedesign_vina import locate_hpc_driver_manifest
from enzymedesign_vina import locate_local_driver_manifest
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import ToolDispatchBinding
from openzyme_extension_spi import parse_component_manifest_json


DIGEST = "sha256:" + "2" * 64


class _RuntimeApplication:
    def request(self, *, invocation):
        return {"workload_id": "workload-vina", "workload_digest": DIGEST, "state": "admitted"}

    def invoke_route(self, *, invocation, driver_id):
        return {"state": "compiled", "driver_id": driver_id}


def _manifest(locator):
    return parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )


def test_vina_manifest_declares_compute_and_same_target_software_requirement() -> None:
    plugin = _manifest(locate_component_manifest())
    local = _manifest(locate_local_driver_manifest())
    hpc = _manifest(locate_hpc_driver_manifest())

    assert isinstance(plugin, PluginManifest)
    assert isinstance(local, DriverManifest)
    assert isinstance(hpc, DriverManifest)
    assert plugin.manifest_digest == VINA_COMPONENT_MANIFEST_DIGEST
    assert local.manifest_digest == VINA_LOCAL_DRIVER_MANIFEST_DIGEST
    assert hpc.manifest_digest == VINA_HPC_DRIVER_MANIFEST_DIGEST
    software = next(
        item for item in plugin.requires if item.capability_id == "software.autodock-vina"
    )
    assert software.kind is CapabilityRequirementKind.RESOURCE
    assert software.version_spec == ">=1.1.2,<2"
    assert software.same_target_as == "openzyme.execution.revision-job"
    route_versions = {
        route.route_id: route.requirements[0].version_spec for route in plugin.routes
    }
    assert route_versions == {
        "enzymedesign.vina.hpc-primary@1": "==1.1.2",
        "enzymedesign.vina.local@1": ">=1.2,<2",
    }
    requirements = importlib.metadata.requires("enzymedesign-vina") or []
    assert all(
        all(name not in requirement for name in ("openzyme-core", "openzyme-hpc", "slurm", "ssh"))
        for requirement in requirements
    )


def test_vina_runtime_surfaces_match_both_declared_routes() -> None:
    application = _RuntimeApplication()
    surfaces = build_vina_plugin_runtime_surfaces(
        application=application,
        route_application=application,
    )

    assert len(surfaces.tools) == 1
    assert {item.route_id for item in surfaces.capability_routes} == {
        "enzymedesign.vina.hpc-primary@1",
        "enzymedesign.vina.local@1",
    }


def _input(path: str, revision_id: str):
    return {
        "revision_id": revision_id,
        "commit": "a" * 40,
        "tree": "b" * 40,
        "path": path,
        "content_digest": DIGEST,
    }


def _request(
    *,
    driver_id: str = "enzymedesign.vina.hpc",
    route_id: str = "enzymedesign.vina.hpc-primary@1",
    extra=None,
):
    return DriverInvocationRequest(
        driver_id=driver_id,
        owning_plugin_id="enzymedesign.vina",
        route_id=route_id,
        tool_name=VINA_TOOL_SPEC.tool_name,
        tool_contract_digest=VINA_TOOL_SPEC.contract_digest,
        request_contract_digest=VINA_DRIVER_REQUEST_CONTRACT_DIGEST,
        payload={
            "workload_id": "vina-workload-1",
            "cwd": "analysis/vina",
            "resource_policy_digest": DIGEST,
            "environment_policy_digest": DIGEST,
            "inputs": [
                _input("inputs/receptor.pdbqt", "receptor-revision"),
                _input("inputs/ligand.pdbqt", "ligand-revision"),
                _input("inputs/vina.conf", "config-revision"),
            ],
            "result_root": "results/vina",
            "poses_path": "results/vina/poses.pdbqt",
            "score_path": "results/vina/vina.log",
            **({} if extra is None else extra),
        },
    )


def test_vina_hpc_driver_compiles_closed_workload_without_hpc_identity() -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    compiled = VinaDriver(manifest).compile(_request())

    assert list(compiled.workload["argv"]) == [
        "vina",
        "--receptor",
        "inputs/receptor.pdbqt",
        "--ligand",
        "inputs/ligand.pdbqt",
        "--config",
        "inputs/vina.conf",
        "--out",
        "results/vina/poses.pdbqt",
        "--log",
        "results/vina/vina.log",
    ]
    assert compiled.workload["capability_requirements"][0]["capability_id"] == (
        "software.autodock-vina"
    )
    assert "target_id" not in compiled.workload
    assert "credential" not in compiled.workload


def test_vina_local_driver_compiles_modern_poses_remark_profile() -> None:
    manifest = _manifest(locate_local_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    compiled = VinaDriver(manifest).compile(
        _request(
            driver_id="enzymedesign.vina.local",
            route_id="enzymedesign.vina.local@1",
        )
    )

    argv = list(compiled.workload["argv"])
    assert argv[:2] == ["python", "-c"]
    assert "REMARK VINA RESULT:" in argv[2]
    assert "--log" not in argv
    assert argv[-2:] == [
        "results/vina/poses.pdbqt",
        "results/vina/vina.log",
    ]
    assert compiled.workload["capability_requirements"][0]["version_spec"] == (
        ">=1.2,<2"
    )
    assert compiled.workload["result_contract"]["contract_id"] == (
        "enzymedesign.vina.result.modern@1"
    )
    assert compiled.result_contract_digest == VINA_MODERN_RESULT_SCHEMA_DIGEST


@pytest.mark.parametrize(
    ("vina_output", "expected_returncode"),
    (
        ("REMARK VINA RESULT:    -7.5      0.000      0.000\n", 0),
        ("REMARK generated without a score\n", 65),
    ),
)
def test_vina_modern_extractor_requires_poses_score_remark(
    tmp_path: Path,
    vina_output: str,
    expected_returncode: int,
) -> None:
    manifest = _manifest(locate_local_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    compiled = VinaDriver(manifest).compile(
        _request(
            driver_id="enzymedesign.vina.local",
            route_id="enzymedesign.vina.local@1",
        )
    )
    argv = list(compiled.workload["argv"])
    fake_vina = tmp_path / "vina"
    fake_vina.write_text(
        "#!/usr/bin/env python3\n"
        "import pathlib, sys\n"
        "output = pathlib.Path(sys.argv[sys.argv.index('--out') + 1])\n"
        "output.parent.mkdir(parents=True, exist_ok=True)\n"
        f"output.write_text({vina_output!r}, encoding='utf-8')\n",
        encoding="utf-8",
    )
    fake_vina.chmod(0o755)
    (tmp_path / "results/vina").mkdir(parents=True)
    completed = subprocess.run(
        [sys.executable, *argv[1:]],
        cwd=tmp_path,
        env={**os.environ, "PATH": f"{tmp_path}{os.pathsep}{os.environ['PATH']}"},
        check=False,
        capture_output=True,
        text=True,
    )

    assert completed.returncode == expected_returncode
    score_path = tmp_path / "results/vina/vina.log"
    if expected_returncode == 0:
        assert score_path.read_text(encoding="utf-8") == (
            "score_semantics=poses-remark-derived-file-v1\n" + vina_output
        )
    else:
        assert not score_path.exists()


def test_vina_driver_rejects_cross_route_profile() -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    with pytest.raises(ValueError, match="contract drifted"):
        VinaDriver(manifest).compile(
            _request(route_id="enzymedesign.vina.local@1")
        )


@pytest.mark.parametrize(
    ("field", "value"),
    (
        ("vina_result_profile", "legacy-log-v1"),
        ("score_semantics", "legacy-log-file-v1"),
        ("result_contract_digest", VINA_LEGACY_RESULT_SCHEMA_DIGEST),
    ),
)
def test_vina_modern_result_rejects_profile_drift(field: str, value: str) -> None:
    manifest = _manifest(locate_local_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    driver = VinaDriver(manifest)
    workload = driver.compile(
        _request(
            driver_id="enzymedesign.vina.local",
            route_id="enzymedesign.vina.local@1",
        )
    )
    payload = {
        "result_contract_digest": VINA_MODERN_RESULT_SCHEMA_DIGEST,
        "vina_result_profile": "modern-poses-remark-v1",
        "score_semantics": "poses-remark-derived-file-v1",
        "raw_shell": False,
    }
    payload[field] = value
    result = ToolResult(
        call_id="modern-result-drift",
        tool_name=VINA_TOOL_SPEC.tool_name,
        ok=True,
        status="settled",
        summary="modern Vina result",
        payload=payload,
    )

    with pytest.raises(ValueError, match="formal result contract drifted"):
        driver.validate_result(workload, result)


@pytest.mark.parametrize("extra", ({"argv": ["vina"]}, {"host_path": "/tmp/a"}))
def test_vina_driver_rejects_caller_argv_and_private_path(extra) -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    with pytest.raises(ValueError, match="fields are closed"):
        VinaDriver(manifest).compile(_request(extra=extra))


def test_vina_tool_and_result_keep_raw_shell_non_formal() -> None:
    class Application:
        def request(self, *, invocation, dispatch):
            del invocation, dispatch
            return {
                "execution_id": "execution-1",
                "operation_id": "operation-1",
                "workload_id": "vina-workload-1",
                "workload_digest": DIGEST,
                "state": "admitted",
            }

    runtime = VinaToolRuntime(Application())
    invocation = ToolInvocation(
            call_id="call-1",
            tool_name=VINA_TOOL_SPEC.tool_name,
            arguments={},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
            route_id="hpc-primary.revision-job",
            affordance_snapshot_digest=DIGEST,
        )
    accepted = runtime.invoke_admitted(
        invocation,
        ToolDispatchBinding(
            tool_name=VINA_TOOL_SPEC.tool_name,
            tool_contract_digest=VINA_TOOL_SPEC.contract_digest,
            affordance_snapshot_digest=DIGEST,
            capability_binding_digest=DIGEST,
            extension_bundle_digest=DIGEST,
            authority_lease_id="lease-1",
            authority_lease_digest=DIGEST,
            authority_generation=1,
            authority_fence=1,
            workspace_generation=1,
            route_id="hpc-primary.revision-job",
            route_digest=DIGEST,
            provider_component_id="enzymedesign.vina",
            driver_id="enzymedesign.vina.hpc",
            target_id="hpc-primary",
            inventory_generation=1,
            inventory_digest=DIGEST,
            qualification_digest=DIGEST,
            capability_proof_digest=DIGEST,
        ),
    )
    assert accepted.payload["formal_compute_requested"] is True
    assert accepted.payload["raw_shell"] is False
    assert accepted.payload["fallback_performed"] is False
    assert accepted.payload["task_finished"] is False

    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    driver = VinaDriver(manifest)
    workload = driver.compile(_request())
    raw = ToolResult(
        call_id="raw-1",
        tool_name="hpc.workspace.exec",
        ok=True,
        status="settled",
        summary="exploratory Vina shell",
        payload={
            "result_contract_digest": VINA_LEGACY_RESULT_SCHEMA_DIGEST,
            "vina_result_profile": "legacy-log-v1",
            "score_semantics": "legacy-log-file-v1",
            "raw_shell": True,
        },
    )
    with pytest.raises(ValueError, match="formal result contract drifted"):
        driver.validate_result(workload, raw)
