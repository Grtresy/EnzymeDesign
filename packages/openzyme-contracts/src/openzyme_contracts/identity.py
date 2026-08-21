from __future__ import annotations

from collections.abc import Mapping
from collections.abc import Sequence
from enum import StrEnum
import hashlib
import json
import math
import re
from types import MappingProxyType
from typing import Any
from typing import TypeAlias


JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | Mapping[str, "JsonValue"] | tuple["JsonValue", ...]

_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
_IDENTIFIER_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:@/+\-]*$")


class ContractValidationError(ValueError):
    """A closed implementation-free contract failed local validation."""


def require_identifier(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or not value or len(value) > 256:
        raise ContractValidationError(
            f"{field_name} must be a non-empty bounded string"
        )
    if _IDENTIFIER_PATTERN.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} contains unsupported characters")
    return value


def require_digest(value: str, *, field_name: str) -> str:
    if not isinstance(value, str) or _DIGEST_PATTERN.fullmatch(value) is None:
        raise ContractValidationError(f"{field_name} must be a canonical sha256 digest")
    return value


def canonical_string_tuple(
    values: Sequence[str],
    *,
    field_name: str,
    allow_empty: bool = True,
) -> tuple[str, ...]:
    normalized = tuple(
        require_identifier(value, field_name=field_name) for value in values
    )
    if not allow_empty and not normalized:
        raise ContractValidationError(f"{field_name} must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ContractValidationError(f"{field_name} must not contain duplicates")
    return tuple(sorted(normalized))


def freeze_json(value: Any, *, field_name: str = "value") -> JsonValue:
    if value is None or isinstance(value, (bool, int, str)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ContractValidationError(
                f"{field_name} must not contain NaN or Infinity"
            )
        return value
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key in sorted(value):
            if not isinstance(key, str):
                raise ContractValidationError(
                    f"{field_name} object keys must be strings"
                )
            frozen[key] = freeze_json(value[key], field_name=f"{field_name}.{key}")
        return MappingProxyType(frozen)
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return tuple(freeze_json(item, field_name=f"{field_name}[]") for item in value)
    raise ContractValidationError(
        f"{field_name} contains unsupported JSON value {type(value).__name__}"
    )


def json_compatible(value: Any) -> Any:
    if isinstance(value, StrEnum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): json_compatible(item) for key, item in value.items()}
    if isinstance(value, tuple):
        return [json_compatible(item) for item in value]
    if isinstance(value, list):
        return [json_compatible(item) for item in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            json_compatible(value),
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256_digest(value: Any) -> str:
    return f"sha256:{hashlib.sha256(canonical_json_bytes(value)).hexdigest()}"


__all__ = [
    "ContractValidationError",
    "JsonScalar",
    "JsonValue",
    "canonical_json_bytes",
    "canonical_sha256_digest",
    "canonical_string_tuple",
    "freeze_json",
    "json_compatible",
    "require_digest",
    "require_identifier",
]
