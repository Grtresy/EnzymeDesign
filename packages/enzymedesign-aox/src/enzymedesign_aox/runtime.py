from __future__ import annotations

from dataclasses import dataclass

from enzymedesign_core import ExactProductCapabilityRouteRuntime
from enzymedesign_core import ProductCapabilityRouteApplication


AOX_PLUGIN_ID = "enzymedesign.aox"
AOX_ROUTE_ID = "enzymedesign.aox.sandbox@1"
AOX_DRIVER_ID = "enzymedesign.aox.executor"


@dataclass(frozen=True, slots=True)
class AoxPluginRuntimeSurfaces:
    capability_routes: tuple[ExactProductCapabilityRouteRuntime, ...]


def build_aox_plugin_runtime_surfaces(
    *, route_application: ProductCapabilityRouteApplication
) -> AoxPluginRuntimeSurfaces:
    return AoxPluginRuntimeSurfaces(
        capability_routes=(
            ExactProductCapabilityRouteRuntime(
                route_id=AOX_ROUTE_ID,
                owner_plugin_id=AOX_PLUGIN_ID,
                driver_id=AOX_DRIVER_ID,
                capability_ids=("enzymedesign.aox.workflow",),
                application=route_application,
            ),
        )
    )


__all__ = [
    "AOX_DRIVER_ID",
    "AOX_PLUGIN_ID",
    "AOX_ROUTE_ID",
    "AoxPluginRuntimeSurfaces",
    "build_aox_plugin_runtime_surfaces",
]
