from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_extension_spi import CapabilityRequirement
from openzyme_extension_spi import HttpRouteContribution
from openzyme_extension_spi import RouteContribution
from openzyme_extension_spi import ToolContribution

from .composition import ActivatedPluginComposition
from .errors import KernelContractError


DECLARED_TOOL_CATALOG_SCHEMA_VERSION = "openzyme_declared_tool_catalog@1"
ROUTE_CATALOG_SCHEMA_VERSION = "openzyme_route_catalog@1"
HTTP_ROUTE_CATALOG_SCHEMA_VERSION = "openzyme_http_route_catalog@1"


@dataclass(frozen=True, slots=True)
class DeclaredToolEntry:
    owner_component_id: str
    runtime_id: str
    contract: ToolSpec
    requirements: tuple[CapabilityRequirement, ...] = ()
    requires_workspace: bool = False
    requires_explicit_route: bool = False

    @classmethod
    def from_contribution(cls, contribution: ToolContribution) -> DeclaredToolEntry:
        return cls(
            owner_component_id=contribution.owner_plugin_id,
            runtime_id=contribution.runtime_id,
            contract=contribution.contract,
            requirements=contribution.requirements,
            requires_workspace=contribution.requires_workspace,
            requires_explicit_route=contribution.requires_explicit_route,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_component_id": self.owner_component_id,
            "runtime_id": self.runtime_id,
            "contract": self.contract.to_dict(),
            "requirements": [item.to_dict() for item in self.requirements],
            "requires_workspace": self.requires_workspace,
            "requires_explicit_route": self.requires_explicit_route,
        }


@dataclass(frozen=True, slots=True)
class DeclaredToolCatalog:
    entries: tuple[DeclaredToolEntry, ...]
    catalog_digest: str

    def get(self, tool_name: str) -> DeclaredToolEntry | None:
        return next(
            (entry for entry in self.entries if entry.contract.tool_name == tool_name),
            None,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": DECLARED_TOOL_CATALOG_SCHEMA_VERSION,
            "entries": [entry.to_dict() for entry in self.entries],
            "catalog_digest": self.catalog_digest,
        }


@dataclass(frozen=True, slots=True)
class RouteCatalog:
    routes: tuple[RouteContribution, ...]
    catalog_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": ROUTE_CATALOG_SCHEMA_VERSION,
            "routes": [route.to_dict() for route in self.routes],
            "catalog_digest": self.catalog_digest,
        }


@dataclass(frozen=True, slots=True)
class HttpRouteCatalog:
    routes: tuple[HttpRouteContribution, ...]
    catalog_digest: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": HTTP_ROUTE_CATALOG_SCHEMA_VERSION,
            "routes": [route.to_dict() for route in self.routes],
            "catalog_digest": self.catalog_digest,
        }


def build_declared_tool_catalog(
    *,
    kernel_tools: tuple[DeclaredToolEntry, ...],
    composition: ActivatedPluginComposition,
) -> DeclaredToolCatalog:
    entries_by_name: dict[str, DeclaredToolEntry] = {}
    for entry in kernel_tools:
        tool_name = entry.contract.tool_name
        if tool_name in entries_by_name:
            raise KernelContractError(
                "tool_catalog_collision",
                "Kernel base tools contain a duplicate canonical name",
                details={"tool_name": tool_name},
            )
        entries_by_name[tool_name] = entry
    for manifest in composition.contributing_manifests:
        for contribution in manifest.tools:
            entry = DeclaredToolEntry.from_contribution(contribution)
            tool_name = entry.contract.tool_name
            previous = entries_by_name.get(tool_name)
            if previous is not None:
                raise KernelContractError(
                    "tool_catalog_collision",
                    "two components declare the same canonical tool name",
                    details={
                        "tool_name": tool_name,
                        "first_owner_component_id": previous.owner_component_id,
                        "second_owner_component_id": entry.owner_component_id,
                    },
                )
            entries_by_name[tool_name] = entry
    entries = tuple(entries_by_name[name] for name in sorted(entries_by_name))
    payload = {
        "schema_version": DECLARED_TOOL_CATALOG_SCHEMA_VERSION,
        "entries": [entry.to_dict() for entry in entries],
    }
    return DeclaredToolCatalog(
        entries=entries,
        catalog_digest=canonical_sha256_digest(payload),
    )


def build_route_catalog(
    composition: ActivatedPluginComposition,
) -> RouteCatalog:
    routes_by_id: dict[str, RouteContribution] = {}
    for manifest in composition.contributing_manifests:
        for route in manifest.routes:
            previous = routes_by_id.get(route.route_id)
            if previous is not None:
                raise KernelContractError(
                    "route_catalog_collision",
                    "two components declare the same route ID",
                    details={
                        "route_id": route.route_id,
                        "first_owner_component_id": previous.owner_component_id,
                        "second_owner_component_id": route.owner_component_id,
                    },
                )
            routes_by_id[route.route_id] = route
    routes = tuple(routes_by_id[route_id] for route_id in sorted(routes_by_id))
    payload = {
        "schema_version": ROUTE_CATALOG_SCHEMA_VERSION,
        "routes": [route.to_dict() for route in routes],
    }
    return RouteCatalog(
        routes=routes,
        catalog_digest=canonical_sha256_digest(payload),
    )


def build_http_route_catalog(
    composition: ActivatedPluginComposition,
) -> HttpRouteCatalog:
    routes_by_key: dict[str, HttpRouteContribution] = {}
    routes_by_id: dict[str, HttpRouteContribution] = {}
    for manifest in composition.contributing_manifests:
        for route in manifest.http_routes:
            previous_key = routes_by_key.get(route.route_key)
            if previous_key is not None:
                raise KernelContractError(
                    "http_route_catalog_collision",
                    "two Plugins declare the same normalized HTTP method/path",
                    details={
                        "route_key": route.route_key,
                        "first_owner_component_id": previous_key.owner_plugin_id,
                        "second_owner_component_id": route.owner_plugin_id,
                    },
                )
            previous_id = routes_by_id.get(route.route_id)
            if previous_id is not None:
                raise KernelContractError(
                    "route_id_collision",
                    "two Plugins declare the same HTTP route ID",
                    details={
                        "route_id": route.route_id,
                        "first_owner_component_id": previous_id.owner_plugin_id,
                        "second_owner_component_id": route.owner_plugin_id,
                    },
                )
            routes_by_key[route.route_key] = route
            routes_by_id[route.route_id] = route
    routes = tuple(routes_by_key[key] for key in sorted(routes_by_key))
    payload = {
        "schema_version": HTTP_ROUTE_CATALOG_SCHEMA_VERSION,
        "routes": [route.to_dict() for route in routes],
    }
    return HttpRouteCatalog(
        routes=routes,
        catalog_digest=canonical_sha256_digest(payload),
    )


__all__ = [
    "DECLARED_TOOL_CATALOG_SCHEMA_VERSION",
    "HTTP_ROUTE_CATALOG_SCHEMA_VERSION",
    "ROUTE_CATALOG_SCHEMA_VERSION",
    "DeclaredToolCatalog",
    "DeclaredToolEntry",
    "HttpRouteCatalog",
    "RouteCatalog",
    "build_declared_tool_catalog",
    "build_http_route_catalog",
    "build_route_catalog",
]
