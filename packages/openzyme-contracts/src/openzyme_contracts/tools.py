from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field
from typing import Any

from .identity import JsonValue
from .identity import canonical_sha256_digest
from .identity import canonical_string_tuple
from .identity import freeze_json
from .identity import json_compatible
from .identity import require_digest
from .identity import require_identifier


TOOL_SPEC_SCHEMA_VERSION = "openzyme_tool_spec@1"


@dataclass(frozen=True, slots=True)
class ToolSpec:
    tool_name: str
    description: str
    input_schema: Mapping[str, JsonValue]
    output_schema: Mapping[str, JsonValue] = field(
        default_factory=lambda: {"type": "object"}
    )
    required_authorities: tuple[str, ...] = ()
    approval_policy_id: str | None = None

    def __post_init__(self) -> None:
        require_identifier(self.tool_name, field_name="tool_name")
        if not self.description or len(self.description) > 4096:
            raise ValueError("description must be non-empty and bounded")
        frozen_input = freeze_json(self.input_schema, field_name="input_schema")
        frozen_output = freeze_json(self.output_schema, field_name="output_schema")
        if not isinstance(frozen_input, Mapping) or not isinstance(
            frozen_output, Mapping
        ):
            raise ValueError("tool schemas must be JSON objects")
        object.__setattr__(self, "input_schema", frozen_input)
        object.__setattr__(self, "output_schema", frozen_output)
        object.__setattr__(
            self,
            "required_authorities",
            canonical_string_tuple(
                self.required_authorities,
                field_name="required_authorities",
            ),
        )
        if self.approval_policy_id is not None:
            require_identifier(
                self.approval_policy_id,
                field_name="approval_policy_id",
            )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": TOOL_SPEC_SCHEMA_VERSION,
            "tool_name": self.tool_name,
            "description": self.description,
            "input_schema": json_compatible(self.input_schema),
            "output_schema": json_compatible(self.output_schema),
            "required_authorities": list(self.required_authorities),
            "approval_policy_id": self.approval_policy_id,
        }

    def to_openai_tool(self) -> dict[str, Any]:
        """Compatibility projection; provider aliasing remains Adapter-owned."""

        return {
            "type": "function",
            "function": {
                "name": self.tool_name,
                "description": self.description,
                "parameters": json_compatible(self.input_schema),
            },
        }

    @property
    def contract_digest(self) -> str:
        digest = canonical_sha256_digest(self.to_dict())
        require_digest(digest, field_name="contract_digest")
        return digest


__all__ = ["TOOL_SPEC_SCHEMA_VERSION", "ToolSpec"]
