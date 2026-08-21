from __future__ import annotations

from enzymedesign_aox import AOX_DRIVER_ID
from enzymedesign_aox import AOX_ROUTE_ID
from enzymedesign_aox import build_aox_plugin_runtime_surfaces


class _Application:
    def invoke_route(self, *, invocation, driver_id):
        return {"state": "accepted", "driver_id": driver_id}


def test_aox_runtime_surfaces_bind_the_exact_sandbox_driver() -> None:
    surfaces = build_aox_plugin_runtime_surfaces(route_application=_Application())

    assert len(surfaces.capability_routes) == 1
    route = surfaces.capability_routes[0]
    assert route.route_id == AOX_ROUTE_ID
    assert route.driver_id == AOX_DRIVER_ID
    assert route.capability_ids == ("enzymedesign.aox.workflow",)
