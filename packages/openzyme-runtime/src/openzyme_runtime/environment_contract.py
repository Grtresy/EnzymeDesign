from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import hashlib
import json
import math
import re


_SAFE_PATH_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z0-9_]+)*$")
_VALUE_KINDS = frozenset(
    {
        "boolean",
        "credential",
        "integer",
        "json_object",
        "number",
        "optional_integer",
        "optional_number",
        "path",
        "private_string",
        "string",
        "string_list",
    }
)
_IDENTITY_MODES = frozenset(
    {"credential_presence", "path_identity", "private_digest", "value"}
)


def canonical_digest(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")
    return "sha256:" + hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class EnvironmentFieldDescriptor:
    """One environment-backed setting owned and consumed by a resolver.

    Instances carry field truth.  This type only supplies common resolution and
    credential-safe projection mechanics.
    """

    setting_path: str
    environment_names: tuple[str, ...]
    value_kind: str
    safe_generic_default: object
    identity_mode: str = "value"
    empty_uses_fallback: bool = True
    strip_value: bool = False
    list_normalization: str = "preserve"
    accepted_values: tuple[str, ...] = ()
    minimum: int | float | None = None
    maximum: int | float | None = None
    candidate_identity: bool = True

    def __post_init__(self) -> None:
        if _SAFE_PATH_PATTERN.fullmatch(self.setting_path) is None:
            raise ValueError("setting_path must be a stable dotted identifier")
        if not self.environment_names or any(
            not name or name != name.upper() for name in self.environment_names
        ):
            raise ValueError("environment_names must be non-empty uppercase names")
        if len(set(self.environment_names)) != len(self.environment_names):
            raise ValueError("environment_names must be unique")
        if self.value_kind not in _VALUE_KINDS:
            raise ValueError("value_kind is unsupported")
        if self.identity_mode not in _IDENTITY_MODES:
            raise ValueError("identity_mode is unsupported")
        if self.list_normalization not in {"preserve", "sorted_unique"}:
            raise ValueError("list_normalization is unsupported")
        if type(self.candidate_identity) is not bool:
            raise ValueError("candidate_identity must be a boolean")
        if self.accepted_values != tuple(sorted(set(self.accepted_values))):
            raise ValueError("accepted_values must be sorted and unique")
        if (
            self.minimum is not None
            and self.maximum is not None
            and self.minimum > self.maximum
        ):
            raise ValueError("minimum cannot exceed maximum")
        json.dumps(self.safe_generic_default, allow_nan=False)

    def raw_value(self, environ: Mapping[str, str]) -> str | None:
        for name in self.environment_names:
            value = environ.get(name)
            if value is None:
                continue
            if self.empty_uses_fallback and value == "":
                continue
            return value
        return None

    def resolve(self, environ: Mapping[str, str]) -> object:
        raw = self.raw_value(environ)
        if raw is None:
            return self.safe_generic_default
        prepared = raw.strip() if self.strip_value else raw
        if self.value_kind in {"credential", "path", "private_string", "string"}:
            value: object = prepared
        elif self.value_kind == "boolean":
            value = prepared.strip().lower() in {"1", "true", "yes", "on", "local"}
        elif self.value_kind == "integer":
            value = int(prepared)
        elif self.value_kind == "optional_integer":
            value = None if prepared == "" else int(prepared)
        elif self.value_kind == "number":
            value = float(prepared)
        elif self.value_kind == "optional_number":
            value = None if prepared == "" else float(prepared)
        elif self.value_kind == "json_object":
            value = json.loads(prepared)
            if not isinstance(value, dict):
                raise ValueError("Expected a JSON object.")
        elif self.value_kind == "string_list":
            values = tuple(item.strip() for item in prepared.split(",") if item.strip())
            value = (
                tuple(sorted(set(values)))
                if self.list_normalization == "sorted_unique"
                else values
            )
        else:  # pragma: no cover - constructor closes value_kind
            raise AssertionError("unreachable value kind")
        if self.accepted_values and value not in self.accepted_values:
            allowed = ", ".join(self.accepted_values)
            raise ValueError(f"{self.environment_names[0]} must be one of: {allowed}")
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            if self.minimum is not None and value < self.minimum:
                raise ValueError(
                    f"{self.environment_names[0]} must be at least {self.minimum}"
                )
            if self.maximum is not None and value > self.maximum:
                raise ValueError(
                    f"{self.environment_names[0]} must be at most {self.maximum}"
                )
        return value

    def identity_projection(self, environ: Mapping[str, str]) -> object:
        raw = self.raw_value(environ)
        if self.identity_mode == "credential_presence":
            return {"present": raw not in {None, ""}}
        if self.identity_mode == "path_identity":
            return {"configured": raw not in {None, ""}}
        try:
            value = self.resolve(environ)
        except (TypeError, ValueError, json.JSONDecodeError):
            return {
                "resolution": "invalid",
                "input_digest": canonical_digest(raw),
            }
        if isinstance(value, float) and not math.isfinite(value):
            return {
                "resolution": "invalid",
                "input_digest": canonical_digest(raw),
            }
        if self.identity_mode == "private_digest":
            return {"value_digest": canonical_digest(value)}
        if isinstance(value, tuple):
            return list(value)
        return value

    def public_metadata(self) -> dict[str, object]:
        metadata: dict[str, object] = {
            "setting_path": self.setting_path,
            "environment_names": list(self.environment_names),
            "value_kind": self.value_kind,
            "safe_generic_default": self.safe_generic_default,
            "empty_uses_fallback": self.empty_uses_fallback,
            "strip_value": self.strip_value,
            "identity_projection": self.identity_mode,
            "candidate_identity": self.candidate_identity,
        }
        if self.accepted_values:
            metadata["accepted_values"] = list(self.accepted_values)
        if self.minimum is not None:
            metadata["minimum"] = self.minimum
        if self.maximum is not None:
            metadata["maximum"] = self.maximum
        if self.value_kind == "string_list":
            metadata["list_normalization"] = self.list_normalization
        return metadata


def field_map(
    fields: tuple[EnvironmentFieldDescriptor, ...],
) -> dict[str, EnvironmentFieldDescriptor]:
    mapping = {field.setting_path: field for field in fields}
    if len(mapping) != len(fields):
        raise ValueError("environment field setting paths must be unique")
    return mapping


def credential_safe_source_projection(
    fields: tuple[EnvironmentFieldDescriptor, ...],
    environ: Mapping[str, str],
) -> dict[str, object]:
    return {
        field.setting_path: field.identity_projection(environ)
        for field in sorted(fields, key=lambda item: item.setting_path)
        if field.identity_mode != "path_identity"
    }


__all__ = [
    "EnvironmentFieldDescriptor",
    "canonical_digest",
    "credential_safe_source_projection",
    "field_map",
]
