from __future__ import annotations

from dataclasses import dataclass
from importlib.resources import files
import importlib.metadata

import pytest

from enzymedesign_hmmer import HMMER_COMPONENT_MANIFEST_DIGEST
from enzymedesign_hmmer import HMMER_DRIVER_REQUEST_CONTRACT_DIGEST
from enzymedesign_hmmer import HMMER_HPC_DRIVER_MANIFEST_DIGEST
from enzymedesign_hmmer import HMMER_LOCAL_DRIVER_MANIFEST_DIGEST
from enzymedesign_hmmer import HMMER_RESULT_SCHEMA_DIGEST
from enzymedesign_hmmer import HMMER_TOOL_SPECS
from enzymedesign_hmmer import HmmerDriver
from enzymedesign_hmmer import build_hmmer_plugin_runtime_surfaces
from enzymedesign_hmmer import locate_component_manifest
from enzymedesign_hmmer import locate_hpc_driver_manifest
from enzymedesign_hmmer import locate_local_driver_manifest
from openzyme_contracts import ToolInvocation
from openzyme_contracts import ToolResult
from openzyme_extension_spi import CapabilityRequirementKind
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


def test_hmmer_plugin_and_both_driver_manifests_are_exact() -> None:
    plugin = _manifest(locate_component_manifest())
    local = _manifest(locate_local_driver_manifest())
    hpc = _manifest(locate_hpc_driver_manifest())

    assert isinstance(plugin, PluginManifest)
    assert isinstance(local, DriverManifest)
    assert isinstance(hpc, DriverManifest)
    assert plugin.manifest_digest == HMMER_COMPONENT_MANIFEST_DIGEST
    assert local.manifest_digest == HMMER_LOCAL_DRIVER_MANIFEST_DIGEST
    assert hpc.manifest_digest == HMMER_HPC_DRIVER_MANIFEST_DIGEST
    assert local.owning_plugin_id == hpc.owning_plugin_id == "enzymedesign.hmmer"
    assert {local.route_kind, hpc.route_kind} == {"local", "hpc"}
    assert {requirement.capability_id for requirement in plugin.requires} == {
        "openzyme.execution.revision-job",
        "software.hmmer",
    }
    software = next(
        item for item in plugin.requires if item.capability_id == "software.hmmer"
    )
    assert software.kind is CapabilityRequirementKind.RESOURCE
    assert software.version_spec == ">=3.3,<4"
    assert software.same_target_as == "openzyme.execution.revision-job"
    assert plugin.qualification_specs[0].version_argv == ("hmmsearch", "-h")

    requirements = importlib.metadata.requires("enzymedesign-hmmer") or []
    forbidden = ("openzyme-core", "openzyme-hpc", "openzyme-hpc-ssh", "openzyme-hpc-slurm")
    assert all(not any(name in requirement for name in forbidden) for requirement in requirements)


def _input(path: str, *, revision_id: str) -> dict[str, object]:
    return {
        "revision_id": revision_id,
        "commit": "a" * 40,
        "tree": "b" * 40,
        "path": path,
        "content_digest": DIGEST,
    }


def _driver_request(*, search: bool, payload_extra: dict[str, object] | None = None):
    spec = next(
        item
        for item in HMMER_TOOL_SPECS
        if item.tool_name.endswith(".search" if search else ".build")
    )
    inputs = (
        [_input("inputs/model.hmm", revision_id="revision-model"),
         _input("inputs/proteins.fasta", revision_id="revision-proteins")]
        if search
        else [_input("inputs/alignment.fasta", revision_id="revision-alignment")]
    )
    payload = {
        "operation": "search" if search else "build",
        "workload_id": "workload-search" if search else "workload-build",
        "cwd": "analysis/hmmer",
        "resource_policy_digest": DIGEST,
        "environment_policy_digest": DIGEST,
        "inputs": inputs,
        "result_root": "results/hmmer",
        "output_path": "results/hmmer/hits.tbl" if search else "results/hmmer/model.hmm",
        **({} if payload_extra is None else payload_extra),
    }
    return DriverInvocationRequest(
        driver_id="enzymedesign.hmmer.hpc",
        owning_plugin_id="enzymedesign.hmmer",
        route_id="hpc-primary.revision-job",
        tool_name=spec.tool_name,
        tool_contract_digest=spec.contract_digest,
        request_contract_digest=HMMER_DRIVER_REQUEST_CONTRACT_DIGEST,
        payload=payload,
    )


@pytest.mark.parametrize(
    ("search", "expected_argv"),
    (
        (False, ["hmmbuild", "--noali", "results/hmmer/model.hmm", "inputs/alignment.fasta"]),
        (
            True,
            [
                "hmmsearch",
                "--noali",
                "--tblout",
                "results/hmmer/hits.tbl",
                "inputs/model.hmm",
                "inputs/proteins.fasta",
            ],
        ),
    ),
)
def test_hmmer_hpc_driver_compiles_typed_workload_without_dispatch(
    search: bool, expected_argv: list[str]
) -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    compiled = HmmerDriver(manifest).compile(_driver_request(search=search))

    assert list(compiled.workload["argv"]) == expected_argv
    assert compiled.workload["capability_requirements"][0]["capability_id"] == (
        "software.hmmer"
    )
    assert compiled.workload["capability_requirements"][0]["version_spec"] == (
        ">=3.3,<4"
    )
    assert "target_id" not in compiled.workload
    assert "credential" not in compiled.workload
    assert "scheduler_job_id" not in compiled.workload


@pytest.mark.parametrize(
    "extra",
    (
        {"host_path": "/private/input.fasta"},
        {"argv": ["hmmsearch", "--other"]},
        {"remote_path": "/cluster/work"},
    ),
)
def test_hmmer_driver_rejects_private_or_caller_compiled_fields(extra) -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    with pytest.raises(ValueError, match="fields are closed"):
        HmmerDriver(manifest).compile(_driver_request(search=True, payload_extra=extra))


@dataclass
class _ToolApplication:
    calls: int = 0

    def request(self, *, invocation):
        self.calls += 1
        return {"workload_id": "workload-1", "workload_digest": DIGEST, "state": "admitted"}


def test_hmmer_tool_requires_explicit_route_and_never_falls_back_or_finishes_task() -> None:
    application = _ToolApplication()
    runtime = build_hmmer_plugin_runtime_surfaces(application=application).tools[0]
    rejected = runtime.invoke(
        ToolInvocation(
            call_id="call-1",
            tool_name=runtime.contract.tool_name,
            arguments={},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
        )
    )
    accepted = runtime.invoke(
        ToolInvocation(
            call_id="call-2",
            tool_name=runtime.contract.tool_name,
            arguments={},
            session_id="session-1",
            agent_member_id="agent-1",
            task_id="task-1",
            route_id="hpc-primary.revision-job",
            affordance_snapshot_digest=DIGEST,
        )
    )

    assert rejected.error_code == "hmmer_route_or_tool_identity_invalid"
    assert rejected.payload["mutation_applied"] is False
    assert accepted.payload["formal_compute_requested"] is True
    assert accepted.payload["raw_shell"] is False
    assert accepted.payload["fallback_performed"] is False
    assert accepted.payload["task_finished"] is False
    assert application.calls == 1


def test_hmmer_result_validator_rejects_raw_shell_receipt() -> None:
    manifest = _manifest(locate_hpc_driver_manifest())
    assert isinstance(manifest, DriverManifest)
    driver = HmmerDriver(manifest)
    workload = driver.compile(_driver_request(search=True))
    raw = ToolResult(
        call_id="call-result",
        tool_name="hpc.workspace.exec",
        ok=True,
        status="settled",
        summary="exploratory shell completed",
        payload={
            "result_contract_digest": HMMER_RESULT_SCHEMA_DIGEST,
            "raw_shell": True,
        },
    )

    with pytest.raises(ValueError, match="formal result contract drifted"):
        driver.validate_result(workload, raw)
