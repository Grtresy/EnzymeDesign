from importlib.metadata import EntryPoint

from openzyme_extension_spi import discover_extension_manifest_locators
from openzyme_extension_spi import read_located_component_manifest

from openzyme_hpc.manifest_locator import locate_component_manifest
from openzyme_hpc import build_hpc_plugin_runtime_surfaces
from openzyme_hpc import HPC_PROJECTION_CONTRACT_DIGEST
from openzyme_hpc import HPC_RENDERER_CONTRACT_DIGEST
from openzyme_hpc import HPC_WORKER_CONTRACT_DIGEST


class _Application:
    def invoke_route(self, *, invocation):
        return {}

    def __getattr__(self, _name):
        return lambda _context, arguments: {
            "workspace_id": str(arguments.get("workspace_id") or "hpcws-1")
        }


def test_hpc_manifest_contributes_inventory_workspace_and_compute_routes() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())

    assert manifest.identity.component_id == "openzyme.hpc"
    assert [item.capability_id for item in manifest.provides] == [
        "openzyme.hpc.compute-route",
        "openzyme.hpc.target-inventory",
        "openzyme.hpc.workspace",
    ]
    assert [route.route_id for route in manifest.routes] == [
        "hpc-primary.revision-job",
        "hpc-primary.workspace-runtime",
    ]
    assert {route.target_id for route in manifest.routes} == {"hpc-primary"}
    assert [item.capability_id for item in manifest.qualification_specs] == [
        "software.openzyme-workspace-runtime"
    ]
    workspace_route = next(
        route for route in manifest.routes if route.route_kind == "remote_workspace"
    )
    assert "software.openzyme-workspace-runtime" in workspace_route.capability_ids
    assert [item.contract.tool_name for item in manifest.tools] == [
        "hpc.workspace.exec",
        "hpc.workspace.fs.list",
        "hpc.workspace.fs.mutate",
        "hpc.workspace.fs.read",
        "hpc.workspace.inspect",
        "hpc.workspace.request",
        "hpc.workspace.sync_source",
        "hpc.workspace.verify",
    ]
    assert all(item.owner_plugin_id == "openzyme.hpc" for item in manifest.tools)
    assert all(item.requires_explicit_route for item in manifest.tools)
    assert all(
        "software.openzyme-workspace-runtime"
        in {requirement.capability_id for requirement in item.requirements}
        for item in manifest.tools
    )
    assert manifest.state_namespace == "openzyme_hpc"
    assert manifest.projections[0].contract_digest == HPC_PROJECTION_CONTRACT_DIGEST
    assert manifest.ui_renderers[0].contract_digest == HPC_RENDERER_CONTRACT_DIGEST
    assert manifest.workers[0].contract_digest == HPC_WORKER_CONTRACT_DIGEST


def test_hpc_entry_point_only_locates_manifest() -> None:
    entry = EntryPoint(
        name="openzyme.hpc",
        value="openzyme_hpc.manifest_locator:locate_component_manifest",
        group="openzyme.extensions",
    )

    assert discover_extension_manifest_locators((entry,)) == (
        locate_component_manifest(),
    )


def test_hpc_runtime_surfaces_exactly_implement_manifest_tools_and_routes() -> None:
    manifest = read_located_component_manifest(locate_component_manifest())
    application = _Application()
    surfaces = build_hpc_plugin_runtime_surfaces(
        workspace_application=application,
        route_application=application,
        projection_application=application,
        worker_application=application,
    )

    declared_tools = {
        item.contract.tool_name: item for item in manifest.tools
    }
    assert {item.tool_name for item in surfaces.tools} == set(declared_tools)
    assert all(
        item.runtime_id == declared_tools[item.tool_name].runtime_id
        and item.contract.contract_digest
        == declared_tools[item.tool_name].contract.contract_digest
        for item in surfaces.tools
    )
    assert {item.route_id for item in surfaces.capability_routes} == {
        item.route_id for item in manifest.routes
    }
    assert {item.section_id for item in surfaces.projections} == {
        item.contribution_id for item in manifest.projections
    }
    assert {item.worker_id for item in surfaces.workers} == {
        item.contribution_id for item in manifest.workers
    }
