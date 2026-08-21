from __future__ import annotations

from dataclasses import dataclass

from .projection_worker import HpcProjectionApplication
from .projection_worker import HpcProjectionContributor
from .projection_worker import HpcWorkerApplication
from .projection_worker import HpcWorkerContributor
from .routes import HpcCapabilityRouteApplication
from .routes import HpcCapabilityRouteRuntime
from .routes import build_hpc_capability_route_runtimes
from .workspace_tools import HpcWorkspaceToolApplication
from .workspace_tools import HpcWorkspaceToolRuntime
from .workspace_tools import build_hpc_workspace_tool_runtimes


@dataclass(frozen=True, slots=True)
class HpcPluginRuntimeSurfaces:
    """Plugin-owned runtime objects; the Distribution wraps these in its mount bundle."""

    tools: tuple[HpcWorkspaceToolRuntime, ...]
    capability_routes: tuple[HpcCapabilityRouteRuntime, ...]
    projections: tuple[HpcProjectionContributor, ...]
    workers: tuple[HpcWorkerContributor, ...]


def build_hpc_plugin_runtime_surfaces(
    *,
    workspace_application: HpcWorkspaceToolApplication,
    route_application: HpcCapabilityRouteApplication,
    projection_application: HpcProjectionApplication,
    worker_application: HpcWorkerApplication,
) -> HpcPluginRuntimeSurfaces:
    return HpcPluginRuntimeSurfaces(
        tools=build_hpc_workspace_tool_runtimes(workspace_application),
        capability_routes=build_hpc_capability_route_runtimes(route_application),
        projections=(HpcProjectionContributor(projection_application),),
        workers=(HpcWorkerContributor(worker_application),),
    )


__all__ = ["HpcPluginRuntimeSurfaces", "build_hpc_plugin_runtime_surfaces"]
