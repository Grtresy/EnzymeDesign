from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files

import pytest

from enzymedesign_structure import FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_structure import FPOCKET_HPC_DRIVER_MANIFEST_DIGEST
from enzymedesign_structure import FPOCKET_LOCAL_DRIVER_MANIFEST_DIGEST
from enzymedesign_structure import FPOCKET_RESULT_SCHEMA_DIGEST
from enzymedesign_structure import FPOCKET_TOOL_SPEC
from enzymedesign_structure import STRUCTURE_COMPONENT_MANIFEST_DIGEST
from enzymedesign_structure import FpocketDriver
from enzymedesign_structure import FpocketToolRuntime
from enzymedesign_structure import locate_component_manifest
from enzymedesign_structure import locate_hpc_driver_manifest
from enzymedesign_structure import locate_local_driver_manifest
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_extension_spi import DriverInvocationRequest
from openzyme_extension_spi import DriverManifest
from openzyme_extension_spi import PluginManifest
from openzyme_extension_spi import parse_component_manifest_json


DIGEST = "sha256:" + "1" * 64


def _manifest(locator):
    return parse_component_manifest_json(
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )


def test_structure_plugin_and_fpocket_drivers_have_exact_manifests() -> None:
    plugin = _manifest(locate_component_manifest())
    local = _manifest(locate_local_driver_manifest())
    hpc = _manifest(locate_hpc_driver_manifest())

    assert isinstance(plugin, PluginManifest)
    assert isinstance(local, DriverManifest)
    assert isinstance(hpc, DriverManifest)
    assert plugin.manifest_digest == STRUCTURE_COMPONENT_MANIFEST_DIGEST
    assert local.manifest_digest == FPOCKET_LOCAL_DRIVER_MANIFEST_DIGEST
    assert hpc.manifest_digest == FPOCKET_HPC_DRIVER_MANIFEST_DIGEST
    assert {item.capability_id for item in plugin.requires} == {
        "openzyme.execution.revision-job",
        "software.fpocket",
    }
    assert {local.route_kind, hpc.route_kind} == {"local", "hpc"}


def _driver_request(**extra):
    payload = {
        "workload_id": "workload-pocket",
        "cwd": "analysis/fpocket",
        "resource_policy_digest": DIGEST,
        "environment_policy_digest": DIGEST,
        "inputs": (
            {
                "revision_id": "revision-1",
                "commit": "a" * 40,
                "tree": "b" * 40,
                "path": "inputs/structure.pdb",
                "content_digest": DIGEST,
            },
        ),
        "result_root": "results/fpocket",
        **extra,
    }
    return DriverInvocationRequest(
        driver_id="enzymedesign.fpocket.hpc",
        owning_plugin_id="enzymedesign.structure",
        route_id="hpc-primary.revision-job",
        tool_name=FPOCKET_TOOL_SPEC.tool_name,
        tool_contract_digest=FPOCKET_TOOL_SPEC.contract_digest,
        request_contract_digest=FPOCKET_DRIVER_REQUEST_CONTRACT_DIGEST,
        payload=payload,
    )


def test_fpocket_driver_compiles_typed_workload_without_provider_or_target() -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    workload = FpocketDriver(manifest).compile(_driver_request())

    assert list(workload.workload["argv"]) == [
        "fpocket",
        "-f",
        "inputs/structure.pdb",
    ]
    assert [dict(item) for item in workload.workload["capability_requirements"]] == [
        {
            "capability_id": "software.fpocket",
            "version_spec": ">=4,<5",
            "operations": ("detect",),
        }
    ]
    assert "target_id" not in workload.workload
    assert "credential" not in workload.workload


@pytest.mark.parametrize(
    "extra", ({"argv": ["fpocket"]}, {"host_path": "/tmp/structure.pdb"})
)
def test_fpocket_driver_rejects_caller_compiled_or_private_fields(extra) -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    with pytest.raises(ValueError, match="fields are closed"):
        FpocketDriver(manifest).compile(_driver_request(**extra))


@dataclass
class _Application:
    calls: int = 0

    def request(self, *, invocation):
        self.calls += 1
        return {
            "workload_id": "workload-pocket",
            "workload_digest": DIGEST,
            "state": "admitted",
        }


def test_fpocket_tool_requires_route_and_raw_shell_is_not_formal() -> None:
    application = _Application()
    runtime = FpocketToolRuntime(application)
    rejected = runtime.invoke(
        ToolInvocation(
            call_id="call-1",
            tool_name=FPOCKET_TOOL_SPEC.tool_name,
            arguments={},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
        )
    )
    accepted = runtime.invoke(
        ToolInvocation(
            call_id="call-2",
            tool_name=FPOCKET_TOOL_SPEC.tool_name,
            arguments={},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
            route_id="hpc-primary.revision-job",
            affordance_snapshot_digest=DIGEST,
        )
    )
    assert rejected.error_code == "fpocket_route_or_tool_identity_invalid"
    assert accepted.payload["raw_shell"] is False
    assert accepted.payload["task_finished"] is False

    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    driver = FpocketDriver(manifest)
    workload = driver.compile(_driver_request())
    with pytest.raises(ValueError, match="formal result contract drifted"):
        driver.validate_result(
            workload,
            ToolResult(
                call_id="call-shell",
                tool_name="hpc.workspace.exec",
                ok=True,
                status="settled",
                summary="exploratory",
                payload={
                    "result_contract_digest": FPOCKET_RESULT_SCHEMA_DIGEST,
                    "raw_shell": True,
                },
            ),
        )
