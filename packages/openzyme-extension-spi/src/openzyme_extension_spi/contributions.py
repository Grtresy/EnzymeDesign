from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from enum import StrEnum
import re
from typing import Any

from openzyme_contracts import ToolSpec
from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import canonical_string_tuple
from openzyme_contracts.identity import freeze_json
from openzyme_contracts.identity import json_compatible


class CapabilityCardinality(StrEnum):
    SINGLE = "single"
    MULTI_ROUTE = "multi_route"


class CapabilityRequirementKind(StrEnum):
    EXTENSION = "extension"
    RESOURCE = "resource"


class HttpMethod(StrEnum):
    DELETE = "DELETE"
    GET = "GET"
    PATCH = "PATCH"
    POST = "POST"
    PUT = "PUT"


_HTTP_LITERAL_SEGMENT = re.compile(r"[A-Za-z0-9._~-]+")
_HTTP_PARAMETER_SEGMENT = re.compile(r"\{[A-Za-z_][A-Za-z0-9_]*\}")


def normalize_http_route_path(value: str) -> str:
    if (
        not isinstance(value, str)
        or not value.startswith("/")
        or len(value) > 512
        or any(character in value for character in ("\x00", "\\", "?", "#", "%"))
    ):
        raise ValueError("HTTP route path must be one bounded absolute template")
    normalized = value if value == "/" else value.rstrip("/")
    segments = normalized.split("/")[1:]
    if any(
        not segment
        or (
            _HTTP_LITERAL_SEGMENT.fullmatch(segment) is None
            and _HTTP_PARAMETER_SEGMENT.fullmatch(segment) is None
        )
        for segment in segments
    ):
        raise ValueError("HTTP route path contains a non-canonical segment")
    parameters = [segment for segment in segments if segment.startswith("{")]
    if len(set(parameters)) != len(parameters):
        raise ValueError("HTTP route path repeats a parameter name")
    return normalized


@dataclass(frozen=True, slots=True)
class CapabilityProvision:
    capability_id: str
    contract_version: str
    operations: tuple[str, ...] = ()
    cardinality: CapabilityCardinality = CapabilityCardinality.SINGLE

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, field_name="capability_id")
        require_identifier(self.contract_version, field_name="contract_version")
        object.__setattr__(
            self,
            "operations",
            canonical_string_tuple(self.operations, field_name="operations"),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "contract_version": self.contract_version,
            "operations": list(self.operations),
            "cardinality": self.cardinality.value,
        }


@dataclass(frozen=True, slots=True)
class CapabilityRequirement:
    capability_id: str
    contract_spec: str
    kind: CapabilityRequirementKind = CapabilityRequirementKind.EXTENSION
    operations: tuple[str, ...] = ()
    version_spec: str | None = None
    same_target_as: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.capability_id, field_name="capability_id")
        if not self.contract_spec or len(self.contract_spec) > 128:
            raise ValueError("contract_spec must be non-empty and bounded")
        if self.version_spec is not None and (
            not self.version_spec or len(self.version_spec) > 128
        ):
            raise ValueError("version_spec must be non-empty and bounded")
        object.__setattr__(
            self,
            "operations",
            canonical_string_tuple(self.operations, field_name="operations"),
        )
        if self.same_target_as is not None:
            require_identifier(self.same_target_as, field_name="same_target_as")

    def to_dict(self) -> dict[str, Any]:
        return {
            "capability_id": self.capability_id,
            "contract_spec": self.contract_spec,
            "kind": self.kind.value,
            "operations": list(self.operations),
            "version_spec": self.version_spec,
            "same_target_as": self.same_target_as,
        }


@dataclass(frozen=True, slots=True)
class ToolContribution:
    owner_plugin_id: str
    runtime_id: str
    contract: ToolSpec
    requirements: tuple[CapabilityRequirement, ...] = ()
    requires_workspace: bool = False
    requires_explicit_route: bool = False

    def __post_init__(self) -> None:
        require_identifier(self.owner_plugin_id, field_name="owner_plugin_id")
        require_identifier(self.runtime_id, field_name="runtime_id")
        if "." not in self.contract.tool_name:
            raise ValueError("Plugin tool names must be canonical dotted names")
        requirement_ids = [item.capability_id for item in self.requirements]
        if len(set(requirement_ids)) != len(requirement_ids):
            raise ValueError("tool requirements must have unique capability IDs")
        object.__setattr__(
            self,
            "requirements",
            tuple(sorted(self.requirements, key=lambda item: item.capability_id)),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "owner_plugin_id": self.owner_plugin_id,
            "runtime_id": self.runtime_id,
            "contract": self.contract.to_dict(),
            "requirements": [item.to_dict() for item in self.requirements],
            "requires_workspace": self.requires_workspace,
            "requires_explicit_route": self.requires_explicit_route,
        }

    @property
    def contribution_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class QualificationSpec:
    qualification_spec_id: str
    owner_plugin_id: str
    capability_id: str
    contract_version: str
    version_argv: tuple[str, ...]
    smoke_argv: tuple[str, ...]
    expected_result_schema: Mapping[str, JsonValue]
    required_resource_capabilities: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        for field_name in (
            "qualification_spec_id",
            "owner_plugin_id",
            "capability_id",
            "contract_version",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        if not self.version_argv or not self.smoke_argv:
            raise ValueError("qualification argv values must not be empty")
        if any(not value or "\x00" in value for value in self.version_argv):
            raise ValueError("version_argv contains an invalid value")
        if any(not value or "\x00" in value for value in self.smoke_argv):
            raise ValueError("smoke_argv contains an invalid value")
        object.__setattr__(self, "version_argv", tuple(self.version_argv))
        object.__setattr__(self, "smoke_argv", tuple(self.smoke_argv))
        frozen_schema = freeze_json(
            self.expected_result_schema,
            field_name="expected_result_schema",
        )
        if not isinstance(frozen_schema, Mapping):
            raise ValueError("expected_result_schema must be a JSON object")
        object.__setattr__(self, "expected_result_schema", frozen_schema)
        object.__setattr__(
            self,
            "required_resource_capabilities",
            canonical_string_tuple(
                self.required_resource_capabilities,
                field_name="required_resource_capabilities",
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "qualification_spec_id": self.qualification_spec_id,
            "owner_plugin_id": self.owner_plugin_id,
            "capability_id": self.capability_id,
            "contract_version": self.contract_version,
            "version_argv": list(self.version_argv),
            "smoke_argv": list(self.smoke_argv),
            "expected_result_schema": json_compatible(self.expected_result_schema),
            "required_resource_capabilities": list(self.required_resource_capabilities),
        }

    @property
    def expected_operations(self) -> tuple[str, ...]:
        """Return the closed operation values that a smoke result may prove."""

        required = self.expected_result_schema.get("required")
        properties = self.expected_result_schema.get("properties")
        if (
            not isinstance(required, tuple)
            or "operations" not in required
            or not isinstance(properties, Mapping)
        ):
            return ()
        operations = properties.get("operations")
        if not isinstance(operations, Mapping):
            return ()
        items = operations.get("items")
        if not isinstance(items, Mapping):
            return ()
        if "const" in items:
            values = (items["const"],)
        else:
            enum_values = items.get("enum")
            if not isinstance(enum_values, tuple):
                return ()
            values = enum_values
        if any(not isinstance(value, str) for value in values):
            return ()
        return canonical_string_tuple(values, field_name="expected_operations")

    @property
    def qualification_spec_digest(self) -> str:
        return canonical_sha256_digest(self.to_dict())


@dataclass(frozen=True, slots=True)
class RouteContribution:
    route_id: str
    owner_component_id: str
    capability_ids: tuple[str, ...]
    route_kind: str
    route_contract_digest: str
    target_id: str | None = None
    driver_id: str | None = None

    def __post_init__(self) -> None:
        for field_name in ("route_id", "owner_component_id", "route_kind"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        object.__setattr__(
            self,
            "capability_ids",
            canonical_string_tuple(
                self.capability_ids,
                field_name="capability_ids",
                allow_empty=False,
            ),
        )
        require_digest(
            self.route_contract_digest,
            field_name="route_contract_digest",
        )
        if self.target_id is not None:
            require_identifier(self.target_id, field_name="target_id")
        if self.driver_id is not None:
            require_identifier(self.driver_id, field_name="driver_id")

    def to_dict(self) -> dict[str, Any]:
        return {
            "route_id": self.route_id,
            "owner_component_id": self.owner_component_id,
            "capability_ids": list(self.capability_ids),
            "route_kind": self.route_kind,
            "route_contract_digest": self.route_contract_digest,
            "target_id": self.target_id,
            "driver_id": self.driver_id,
        }


@dataclass(frozen=True, slots=True)
class HttpRouteContribution:
    route_id: str
    owner_plugin_id: str
    method: HttpMethod
    path: str
    contract_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.route_id, field_name="route_id")
        require_identifier(self.owner_plugin_id, field_name="owner_plugin_id")
        object.__setattr__(self, "path", normalize_http_route_path(self.path))
        require_digest(self.contract_digest, field_name="contract_digest")

    @property
    def route_key(self) -> str:
        return f"{self.method.value} {self.path}"

    def to_dict(self) -> dict[str, str]:
        return {
            "route_id": self.route_id,
            "owner_plugin_id": self.owner_plugin_id,
            "method": self.method.value,
            "path": self.path,
            "contract_digest": self.contract_digest,
        }


@dataclass(frozen=True, slots=True)
class NamedContribution:
    contribution_id: str
    contract_digest: str

    def __post_init__(self) -> None:
        require_identifier(self.contribution_id, field_name="contribution_id")
        require_digest(self.contract_digest, field_name="contract_digest")

    def to_dict(self) -> dict[str, str]:
        return {
            "contribution_id": self.contribution_id,
            "contract_digest": self.contract_digest,
        }


__all__ = [
    "CapabilityCardinality",
    "CapabilityProvision",
    "CapabilityRequirement",
    "CapabilityRequirementKind",
    "HttpMethod",
    "HttpRouteContribution",
    "NamedContribution",
    "QualificationSpec",
    "RouteContribution",
    "ToolContribution",
    "normalize_http_route_path",
]
