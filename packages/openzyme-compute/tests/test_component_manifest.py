from __future__ import annotations

from importlib.resources import files

from openzyme_compute import COMPUTE_COMPONENT_MANIFEST_DIGEST
from openzyme_compute import COMPUTE_PROJECTION_CONTRACT_DIGEST
from openzyme_compute import COMPUTE_RENDERER_CONTRACT_DIGEST
from openzyme_compute import COMPUTE_TOOL_SPECS
from openzyme_compute import build_compute_plugin_runtime_surfaces
from openzyme_compute import locate_component_manifest
from openzyme_extension_spi import parse_component_manifest_json


def test_compute_plugin_manifest_is_exact_and_purely_locatable() -> None:
    locator = locate_component_manifest()
    source = (
        files(locator.resource_package)
        .joinpath(locator.resource_name)
        .read_text(encoding="utf-8")
    )
    manifest = parse_component_manifest_json(source)

    assert locator.manifest_digest == COMPUTE_COMPONENT_MANIFEST_DIGEST
    assert manifest.manifest_digest == COMPUTE_COMPONENT_MANIFEST_DIGEST
    assert manifest.identity.component_id == "openzyme.compute"
    assert manifest.state_namespace == "openzyme_compute"
    assert manifest.requires == ()
    assert [item.capability_id for item in manifest.provides] == [
        "openzyme.execution.revision-job"
    ]
    assert {item.contract.tool_name: item.contract.to_dict() for item in manifest.tools} == {
        item.tool_name: item.to_dict() for item in COMPUTE_TOOL_SPECS
    }
    assert manifest.projections[0].contract_digest == COMPUTE_PROJECTION_CONTRACT_DIGEST
    assert manifest.ui_renderers[0].contract_digest == COMPUTE_RENDERER_CONTRACT_DIGEST
    assert [item.contribution_id for item in manifest.workers] == [
        "openzyme.compute.worker@1"
    ]
    assert [item.contribution_id for item in manifest.transaction_participants] == [
        "openzyme.compute.transaction@1"
    ]


def test_compute_manifest_has_no_provider_or_private_locator_vocabulary() -> None:
    source = (
        files("openzyme_compute")
        .joinpath("manifests/plugin.json")
        .read_text(encoding="utf-8")
        .lower()
    )

    assert "slurm" not in source
    assert "ssh" not in source
    assert "host_path" not in source
    assert "remote_root" not in source
    assert "login_alias" not in source
    assert "scheduler_job_id" not in source
    assert "expected_outputs" not in source


def test_compute_runtime_surface_exactly_implements_manifest() -> None:
    class Application:
        pass

    runtime = build_compute_plugin_runtime_surfaces(
        tool_application=Application(),
        projection_application=Application(),
        worker_application=Application(),
    )
    manifest = parse_component_manifest_json(
        files("openzyme_compute")
        .joinpath("manifests/plugin.json")
        .read_text(encoding="utf-8")
    )

    assert {item.contract.tool_name for item in runtime.tools} == {
        item.contract.tool_name for item in manifest.tools
    }
    assert {item.runtime_id for item in runtime.tools} == {
        item.runtime_id for item in manifest.tools
    }
    assert {item.section_id for item in runtime.projections} == {
        item.contribution_id for item in manifest.projections
    }
    assert {item.worker_id for item in runtime.workers} == {
        item.contribution_id for item in manifest.workers
    }
    assert {item.participant_id for item in runtime.transaction_participants} == {
        item.contribution_id for item in manifest.transaction_participants
    }
