from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolResult
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_extension_spi import CapabilityRouteInvocation


class ProductCapabilityRouteApplication(Protocol):
    """Composition-root bridge for one exact Product Plugin route."""

    def invoke_route(
        self,
        *,
        invocation: CapabilityRouteInvocation,
        driver_id: str,
    ) -> Mapping[str, JsonValue]: ...


@dataclass(slots=True)
class ExactProductCapabilityRouteRuntime:
    """Fail-closed runtime for one manifest-declared Product Plugin route."""

    route_id: str
    owner_plugin_id: str
    driver_id: str
    capability_ids: tuple[str, ...]
    application: ProductCapabilityRouteApplication

    def __post_init__(self) -> None:
        for field_name in ("route_id", "owner_plugin_id", "driver_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        capabilities = tuple(sorted(set(self.capability_ids)))
        if not capabilities:
            raise ValueError("product capability route must provide a capability")
        for capability_id in capabilities:
            require_identifier(capability_id, field_name="capability_id")
        object.__setattr__(self, "capability_ids", capabilities)

    def invoke(self, invocation: CapabilityRouteInvocation) -> ToolResult:
        if invocation.route_id != self.route_id:
            return self._rejected(
                invocation,
                "product_route_identity_mismatch",
                "Product capability route received another route identity.",
            )
        if invocation.capability_id not in self.capability_ids:
            return self._rejected(
                invocation,
                "product_route_capability_mismatch",
                "Product capability route does not provide the requested capability.",
            )
        try:
            result = dict(
                self.application.invoke_route(
                    invocation=invocation,
                    driver_id=self.driver_id,
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            return self._rejected(
                invocation,
                getattr(exc, "error_code", "product_route_request_invalid"),
                str(exc),
            )
        result.update(
            {
                "route_id": self.route_id,
                "driver_id": self.driver_id,
                "fallback_performed": False,
                "task_finished": False,
            }
        )
        return ToolResult(
            call_id=invocation.context.command_id,
            tool_name=invocation.capability_id,
            ok=True,
            status="accepted",
            summary="The exact Product Plugin route accepted the bound invocation.",
            payload=result,
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
            payload={
                "mutation_applied": False,
                "fallback_performed": False,
                "task_finished": False,
            },
            error_code=error_code,
        )


__all__ = [
    "ExactProductCapabilityRouteRuntime",
    "ProductCapabilityRouteApplication",
]
