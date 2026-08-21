from __future__ import annotations

from typing import Any

from openzyme_contracts import ClockPort
from openzyme_contracts import IdGeneratorPort
from openzyme_host_api import FileWorkspaceV2HostSurface
from openzyme_host_api import HostSecurityPolicy
from openzyme_host_api import HostV2Dependencies
from openzyme_host_api import create_v2_app

from .composition import StandardDeploymentStartup
from .composition import build_standard_kernel_public_projection_provider
from .application_runtime import StandardOperationalAdapterSelection
from .application_runtime import StandardOperationalRuntimePorts
from .application_runtime import build_standard_kernel_application_runtime
from .host_gateway import StandardSessionBootstrapAuthorityPort


def build_standard_file_workspace_v2_host_surface(
    connection: Any,
    *,
    startup: StandardDeploymentStartup,
    clock: ClockPort,
) -> FileWorkspaceV2HostSurface:
    """Compose the generic Host delivery Adapter from the active Distribution."""

    active_epoch = startup.gate.active_epoch
    if active_epoch is None:
        raise RuntimeError("Standard deployment epoch is not active")
    provider = build_standard_kernel_public_projection_provider(
        connection,
        startup=startup,
        clock=clock,
    )
    return FileWorkspaceV2HostSurface.from_mounted_surfaces(
        release=active_epoch.release_identity,
        core_provider=provider,
        mounted_surfaces=startup.mounted_surfaces,
    )


def build_standard_v2_host_app(
    connection: Any,
    *,
    startup: StandardDeploymentStartup,
    clock: ClockPort,
    ids: IdGeneratorPort,
    bootstrap_authority: StandardSessionBootstrapAuthorityPort,
    security_policy: HostSecurityPolicy,
    operational_ports: StandardOperationalRuntimePorts | None = None,
    operational_selection: StandardOperationalAdapterSelection | None = None,
):  # noqa: ANN201 - FastAPI remains owned by the delivery Adapter
    """Build the real Plugin-free @2 Host from one activated Standard graph."""

    surface = build_standard_file_workspace_v2_host_surface(
        connection,
        startup=startup,
        clock=clock,
    )
    runtime = build_standard_kernel_application_runtime(
        connection,
        startup=startup,
        clock=clock,
        ids=ids,
        bootstrap_authority=bootstrap_authority,
        operational_ports=operational_ports,
        operational_selection=operational_selection,
    )
    app = create_v2_app(
        HostV2Dependencies(
            security_policy=security_policy,
            workspace_surface=surface,
            command_gateway=runtime.gateway,
            http_routes=tuple(
                contribution
                for _, contribution in startup.mounted_surfaces.http_routes
            ),
        )
    )
    app.state.openzyme_standard_runtime = runtime
    return app


__all__ = [
    "build_standard_file_workspace_v2_host_surface",
    "build_standard_v2_host_app",
]
