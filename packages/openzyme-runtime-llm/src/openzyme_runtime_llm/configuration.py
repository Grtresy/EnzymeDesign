from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from types import MappingProxyType
from typing import Any

from openzyme_contracts import canonical_sha256_digest
from openzyme_contracts import require_identifier


LLM_ADAPTER_CONFIGURATION_SCHEMA = "openzyme_llm_adapter_configuration@1"
LLM_ADAPTER_CONFIGURATION_SCHEMA_DIGEST = canonical_sha256_digest(
    {
        "schema": LLM_ADAPTER_CONFIGURATION_SCHEMA,
        "fields": [
            "provider_id",
            "model",
            "base_url",
            "credential_slot",
            "timeout_seconds",
            "max_retries",
            "context_window_units",
            "default_output_units",
            "provider_options",
        ],
        "closed": True,
        "ambient_provider_selection": False,
    }
)


@dataclass(frozen=True, slots=True)
class LlmAdapterConfiguration:
    """Explicit configuration for the already-selected LLM Adapter.

    The credential value is deliberately absent.  A composition root resolves
    ``credential_slot`` through its credential material port and injects the
    resulting secret only when constructing the provider backend.
    """

    provider_id: str
    model: str
    base_url: str | None
    credential_slot: str
    timeout_seconds: float
    max_retries: int
    context_window_units: int
    default_output_units: int
    provider_options: Mapping[str, Any]

    def __post_init__(self) -> None:
        require_identifier(self.provider_id, field_name="provider_id")
        require_identifier(self.credential_slot, field_name="credential_slot")
        if (
            not isinstance(self.model, str)
            or not self.model.strip()
            or self.model != self.model.strip()
            or len(self.model) > 512
        ):
            raise ValueError("model must be one non-empty bounded model identity")
        if self.base_url is not None and (
            not isinstance(self.base_url, str)
            or not self.base_url.startswith(("https://", "http://"))
            or len(self.base_url) > 2_048
            or "@" in self.base_url
        ):
            raise ValueError("base_url must be a bounded credential-free HTTP URL")
        if (
            not isinstance(self.timeout_seconds, int | float)
            or isinstance(self.timeout_seconds, bool)
            or not 0 < float(self.timeout_seconds) <= 3_600
        ):
            raise ValueError("timeout_seconds must be within (0, 3600]")
        if (
            not isinstance(self.max_retries, int)
            or isinstance(self.max_retries, bool)
            or not 0 <= self.max_retries <= 8
        ):
            raise ValueError("max_retries must be an integer within [0, 8]")
        for field_name in ("context_window_units", "default_output_units"):
            value = getattr(self, field_name)
            if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
                raise ValueError(f"{field_name} must be a positive integer")
        if self.default_output_units >= self.context_window_units:
            raise ValueError("default_output_units must be smaller than context window")
        options = dict(self.provider_options)
        if len(options) > 64 or any(
            not isinstance(key, str)
            or not key
            or len(key) > 128
            or key.casefold() in {"api_key", "authorization", "credential", "token"}
            for key in options
        ):
            raise ValueError("provider_options must be bounded and credential-free")
        canonical_sha256_digest({"provider_options": options})
        object.__setattr__(self, "provider_options", MappingProxyType(options))

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "LlmAdapterConfiguration":
        expected = {
            "schema_version",
            "provider_id",
            "model",
            "base_url",
            "credential_slot",
            "timeout_seconds",
            "max_retries",
            "context_window_units",
            "default_output_units",
            "provider_options",
        }
        if set(value) != expected:
            raise ValueError("LLM Adapter configuration fields are closed")
        if value["schema_version"] != LLM_ADAPTER_CONFIGURATION_SCHEMA:
            raise ValueError("unsupported LLM Adapter configuration schema")
        return cls(
            provider_id=value["provider_id"],
            model=value["model"],
            base_url=value["base_url"],
            credential_slot=value["credential_slot"],
            timeout_seconds=value["timeout_seconds"],
            max_retries=value["max_retries"],
            context_window_units=value["context_window_units"],
            default_output_units=value["default_output_units"],
            provider_options=value["provider_options"],
        )

    @property
    def configuration_digest(self) -> str:
        return canonical_sha256_digest(self.safe_projection())

    def safe_projection(self) -> dict[str, Any]:
        return {
            "schema_version": LLM_ADAPTER_CONFIGURATION_SCHEMA,
            "provider_id": self.provider_id,
            "model": self.model,
            "base_url": self.base_url,
            "credential_slot": self.credential_slot,
            "timeout_seconds": float(self.timeout_seconds),
            "max_retries": self.max_retries,
            "context_window_units": self.context_window_units,
            "default_output_units": self.default_output_units,
            "provider_options": dict(self.provider_options),
        }


__all__ = [
    "LLM_ADAPTER_CONFIGURATION_SCHEMA",
    "LLM_ADAPTER_CONFIGURATION_SCHEMA_DIGEST",
    "LlmAdapterConfiguration",
]
