from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Protocol

from openzyme_contracts import ToolResult
from openzyme_contracts import require_digest
from openzyme_contracts import require_identifier
from openzyme_contracts.identity import JsonValue
from openzyme_contracts.identity import freeze_json

from .manifests import DriverManifest


@dataclass(frozen=True, slots=True)
class DriverInvocationRequest:
    driver_id: str
    owning_plugin_id: str
    route_id: str
    tool_name: str
    tool_contract_digest: str
    request_contract_digest: str
    payload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        for field_name in (
            "driver_id",
            "owning_plugin_id",
            "route_id",
            "tool_name",
        ):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.tool_contract_digest,
            field_name="tool_contract_digest",
        )
        require_digest(
            self.request_contract_digest,
            field_name="request_contract_digest",
        )
        payload = freeze_json(self.payload, field_name="payload")
        if not isinstance(payload, Mapping):
            raise ValueError("payload must be a JSON object")
        object.__setattr__(self, "payload", payload)


@dataclass(frozen=True, slots=True)
class CompiledDriverWorkload:
    driver_id: str
    owning_plugin_id: str
    route_id: str
    workload_contract_digest: str
    result_contract_digest: str
    workload: Mapping[str, JsonValue]

    def __post_init__(self) -> None:
        for field_name in ("driver_id", "owning_plugin_id", "route_id"):
            require_identifier(getattr(self, field_name), field_name=field_name)
        require_digest(
            self.workload_contract_digest,
            field_name="workload_contract_digest",
        )
        require_digest(
            self.result_contract_digest,
            field_name="result_contract_digest",
        )
        workload = freeze_json(self.workload, field_name="workload")
        if not isinstance(workload, Mapping):
            raise ValueError("workload must be a JSON object")
        object.__setattr__(self, "workload", workload)


class SubordinateDriver(Protocol):
    """A Driver compiles/parses only; it never dispatches provider effects."""

    @property
    def manifest(self) -> DriverManifest: ...

    def compile(self, request: DriverInvocationRequest) -> CompiledDriverWorkload: ...

    def validate_result(
        self,
        workload: CompiledDriverWorkload,
        result: ToolResult,
    ) -> ToolResult: ...


__all__ = [
    "CompiledDriverWorkload",
    "DriverInvocationRequest",
    "SubordinateDriver",
]
