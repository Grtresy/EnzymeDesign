from __future__ import annotations

from importlib.resources import files
import importlib.metadata

import pytest

from enzymedesign_vina import VINA_COMPONENT_MANIFEST_DIGEST
from enzymedesign_vina import VINA_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_vina import VINA_HPC_DRIVER_MANIFEST_DIGEST
from enzymedesign_vina import VINA_LOCAL_DRIVER_MANIFEST_DIGEST
from enzymedesign_vina import VINA_RESULT_SCHEMA_DIGEST
from enzymedesign_vina import VINA_TOOL_SPEC
from enzymedesign_vina import VinaDriver
from enzymedesign_vina import VinaToolRuntime
from enzymedesign_vina import locate_component_manifest
from enzymedesign_vina import locate_hpc_driver_manifest
from enzymedesign_vina import locate_local_driver_manifest
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_extension_spi import CapabilityRequirementKind
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import parse_component_manifest_json


DIGEST = "sha256:" + "2" * 64


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
    assert software.version_spec == ">=1.2,<2"
    assert software.same_target_as == "openzyme.execution.revision-job"
    requirements = importlib.metadata.requires("enzymedesign-vina") or []
    assert all(
        all(name not in requirement for name in ("openzyme-core", "openzyme-hpc", "slurm", "ssh"))
        for requirement in requirements
    )


def _input(path: str, revision_id: str):
    return {
        "revision_id": revision_id,
        "commit": "a" * 40,
        "tree": "b" * 40,
        "path": path,
        "content_digest": DIGEST,
    }


def _request(*, extra=None):
    return DriverInvocationRequest(
        driver_id="enzymedesign.vina.hpc",
        owning_plugin_id="enzymedesign.vina",
        route_id="hpc-primary.revision-job",
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


@pytest.mark.parametrize("extra", ({"argv": ["vina"]}, {"host_path": "/tmp/a"}))
def test_vina_driver_rejects_caller_argv_and_private_path(extra) -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    with pytest.raises(ValueError, match="fields are closed"):
        VinaDriver(manifest).compile(_request(extra=extra))


def test_vina_tool_and_result_keep_raw_shell_non_formal() -> None:
    class Application:
        def request(self, *, invocation):
            return {"workload_id": "vina-workload-1", "workload_digest": DIGEST, "state": "admitted"}

    runtime = VinaToolRuntime(Application())
    accepted = runtime.invoke(
        ToolInvocation(
            call_id="call-1",
            tool_name=VINA_TOOL_SPEC.tool_name,
            arguments={},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
            route_id="hpc-primary.revision-job",
            affordance_snapshot_digest=DIGEST,
        )
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
        payload={"result_contract_digest": VINA_RESULT_SCHEMA_DIGEST, "raw_shell": True},
    )
    with pytest.raises(ValueError, match="formal result contract drifted"):
        driver.validate_result(workload, raw)
