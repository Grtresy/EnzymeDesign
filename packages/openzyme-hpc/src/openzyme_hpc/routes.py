from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolResult
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import CapabilityRouteInvocation

from .workspace_lifecycle import ExecutorHpcWorkspaceError


HPC_REVISION_JOB_ROUTE_ID = "hpc-primary.revision-job"
HPC_WORKSPACE_ROUTE_ID = "hpc-primary.workspace-runtime"

_ROUTE_CAPABILITIES = {
    HPC_REVISION_JOB_ROUTE_ID: frozenset(
        {"openzyme.execution.revision-job", "openzyme.hpc.compute-route"}
    ),
    HPC_WORKSPACE_ROUTE_ID: frozenset(
        {"openzyme.hpc.target-inventory", "openzyme.hpc.workspace"}
    ),
}


class HpcCapabilityRouteApplication(Protocol):
    """Injected composition-root bridge; no SSH/Slurm implementation leaks here."""

    def invoke_route(
        self,
        *,
        invocation: CapabilityRouteInvocation,
    ) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class HpcCapabilityRouteRuntime:
    route_id: str
    application: HpcCapabilityRouteApplication
    owner_plugin_id: str = "openzyme.hpc"
    driver_id: str | None = None

    def __post_init__(self) -> None:
        if self.route_id not in _ROUTE_CAPABILITIES:
            raise ValueError("unknown HPC capability route")

    def invoke(self, invocation: CapabilityRouteInvocation) -> ToolResult:
        if invocation.route_id != self.route_id:
            return self._rejected(
                invocation,
                "hpc_route_identity_mismatch",
                "HPC route runtime received another route identity.",
            )
        if invocation.capability_id not in _ROUTE_CAPABILITIES[self.route_id]:
            return self._rejected(
                invocation,
                "hpc_route_capability_mismatch",
                "HPC route does not provide the requested capability.",
            )
        try:
            result = dict(self.application.invoke_route(invocation=invocation))
        except (ExecutorHpcWorkspaceError, KeyError, TypeError, ValueError) as exc:
            return self._rejected(
                invocation,
                getattr(exc, "error_code", "hpc_route_request_invalid"),
                str(exc),
            )
        payload: dict[str, JsonValue] = {
            **result,
            "route_id": self.route_id,
            "fallback_performed": False,
        }
        return ToolResult(
            call_id=invocation.context.command_id,
            tool_name=invocation.capability_id,
            ok=True,
            status="accepted",
            summary="HPC capability route accepted the exact bound occurrence.",
            payload=payload,
        )

    @staticmethod
    def _rejected(
        invocation: CapabilityRouteInvocation,
        error_code: str,
        summary: str,
    ) -> ToolResult:
        return ToolResult(
            call_id=invocation.context.command_id,
            tool_name=invocation.capability_id,
            ok=False,
            status="rejected",
            summary=summary,
            payload={"mutation_applied": False, "fallback_performed": False},
            error_code=error_code,
        )


def build_hpc_capability_route_runtimes(
    application: HpcCapabilityRouteApplication,
) -> tuple[HpcCapabilityRouteRuntime, ...]:
    return tuple(
        HpcCapabilityRouteRuntime(route_id=route_id, application=application)
        for route_id in (HPC_REVISION_JOB_ROUTE_ID, HPC_WORKSPACE_ROUTE_ID)
    )


__all__ = [
    "HPC_REVISION_JOB_ROUTE_ID",
    "HPC_WORKSPACE_ROUTE_ID",
    "HpcCapabilityRouteApplication",
    "HpcCapabilityRouteRuntime",
    "build_hpc_capability_route_runtimes",
]
