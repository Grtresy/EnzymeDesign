from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from pathlib import PurePosixPath
import re
from typing import Mapping


OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID = (
    "openzyme_v3_harness_owner_constraint_registry@1"
)
OWNER_CONSTRAINT_REGISTRY_ID = "openzyme_v3_harness_owner_constraints"
OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH = Path(
    "docs/v3/architecture-qualification/owner-constraint-registry.json"
)

_TOP_LEVEL_FIELDS = frozenset({"constraints", "registry_id", "schema_id"})
_CONSTRAINT_FIELDS = frozenset(
    {
        "compatibility",
        "constraint_id",
        "consumers",
        "effect_semantics",
        "error_semantics",
        "forbidden_edges",
        "lifecycle",
        "owner",
        "owner_source",
        "owner_symbol",
        "persistence",
        "scenario_ids",
    }
)
_STABLE_ID = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")


class HarnessOwnerConstraintRegistryError(ValueError):
    code = "harness_owner_constraint_registry_invalid"


@dataclass(frozen=True, slots=True)
class ValidatedHarnessOwnerConstraintRegistry:
    payload: Mapping[str, object]
    registry_digest: str
    source_path: Path | None = None


def _canonical_document_bytes(payload: object) -> bytes:
    try:
        encoded = json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise HarnessOwnerConstraintRegistryError(
            "owner registry contains a non-JSON or non-finite value"
        ) from exc
    return encoded + b"\n"


def _strict_loads(content: bytes) -> object:
    try:
        text = content.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise HarnessOwnerConstraintRegistryError(
            "owner registry is not strict UTF-8"
        ) from exc

    def reject_constant(value: str) -> None:
        raise HarnessOwnerConstraintRegistryError(
            f"owner registry contains forbidden constant {value}"
        )

    def unique_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
        result: dict[str, object] = {}
        for key, value in pairs:
            if key in result:
                raise HarnessOwnerConstraintRegistryError(
                    f"owner registry contains duplicate key {key!r}"
                )
            result[key] = value
        return result

    try:
        return json.loads(
            text,
            object_pairs_hook=unique_object,
            parse_constant=reject_constant,
        )
    except HarnessOwnerConstraintRegistryError:
        raise
    except (json.JSONDecodeError, TypeError, ValueError) as exc:
        raise HarnessOwnerConstraintRegistryError(
            "owner registry is not strict JSON"
        ) from exc


def _closed_object(
    value: object,
    *,
    fields: frozenset[str],
    label: str,
) -> dict[str, object]:
    if not isinstance(value, dict) or set(value) != fields:
        raise HarnessOwnerConstraintRegistryError(
            f"{label} must match its exact closed field set"
        )
    return value


def _text(value: object, *, label: str, stable: bool = False) -> str:
    if not isinstance(value, str) or not value or value != value.strip():
        raise HarnessOwnerConstraintRegistryError(
            f"{label} must be non-empty trimmed text"
        )
    if stable and _STABLE_ID.fullmatch(value) is None:
        raise HarnessOwnerConstraintRegistryError(f"{label} must be a stable id")
    return value


def _sorted_texts(
    value: object,
    *,
    label: str,
    allow_empty: bool,
) -> tuple[str, ...]:
    if not isinstance(value, list):
        raise HarnessOwnerConstraintRegistryError(f"{label} must be an array")
    items = tuple(_text(item, label=f"{label}[]") for item in value)
    if not allow_empty and not items:
        raise HarnessOwnerConstraintRegistryError(f"{label} must not be empty")
    if items != tuple(sorted(set(items))):
        raise HarnessOwnerConstraintRegistryError(
            f"{label} must be sorted and unique"
        )
    return items


def _source_path(value: object, *, repo_root: Path, label: str) -> Path:
    text = _text(value, label=label)
    pure = PurePosixPath(text)
    if pure.is_absolute() or pure.as_posix() != text or ".." in pure.parts:
        raise HarnessOwnerConstraintRegistryError(
            f"{label} must be a normalized repository-relative path"
        )
    candidate = repo_root.joinpath(*pure.parts)
    if candidate.is_symlink() or not candidate.is_file():
        raise HarnessOwnerConstraintRegistryError(
            f"{label} does not resolve to a regular source file"
        )
    try:
        resolved = candidate.resolve(strict=True)
        resolved.relative_to(repo_root)
    except (OSError, RuntimeError, ValueError) as exc:
        raise HarnessOwnerConstraintRegistryError(
            f"{label} escapes the repository"
        ) from exc
    return resolved


def validate_harness_owner_constraint_registry_bytes(
    content: bytes,
    *,
    repo_root: Path,
    source_path: Path | None = None,
) -> ValidatedHarnessOwnerConstraintRegistry:
    root = repo_root.resolve(strict=True)
    payload = _closed_object(
        _strict_loads(content),
        fields=_TOP_LEVEL_FIELDS,
        label="owner registry",
    )
    if _canonical_document_bytes(payload) != content:
        raise HarnessOwnerConstraintRegistryError(
            "owner registry bytes are not canonical JSON plus one LF"
        )
    if payload["schema_id"] != OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID:
        raise HarnessOwnerConstraintRegistryError("owner registry schema is unsupported")
    if payload["registry_id"] != OWNER_CONSTRAINT_REGISTRY_ID:
        raise HarnessOwnerConstraintRegistryError("owner registry id is unsupported")
    raw_constraints = payload["constraints"]
    if not isinstance(raw_constraints, list) or not raw_constraints:
        raise HarnessOwnerConstraintRegistryError("constraints must be a non-empty array")

    ids: list[str] = []
    owners: dict[str, str] = {}
    for index, raw_constraint in enumerate(raw_constraints):
        label = f"constraints[{index}]"
        constraint = _closed_object(
            raw_constraint,
            fields=_CONSTRAINT_FIELDS,
            label=label,
        )
        constraint_id = _text(
            constraint["constraint_id"],
            label=f"{label}.constraint_id",
            stable=True,
        )
        owner = _text(
            constraint["owner"], label=f"{label}.owner", stable=True
        )
        source = _source_path(
            constraint["owner_source"], repo_root=root, label=f"{label}.owner_source"
        )
        symbol = _text(constraint["owner_symbol"], label=f"{label}.owner_symbol")
        if symbol not in source.read_text(encoding="utf-8"):
            raise HarnessOwnerConstraintRegistryError(
                f"{label}.owner_symbol is absent from its owner source"
            )
        for field in (
            "compatibility",
            "effect_semantics",
            "error_semantics",
            "lifecycle",
            "persistence",
        ):
            _text(constraint[field], label=f"{label}.{field}")
        _sorted_texts(
            constraint["consumers"], label=f"{label}.consumers", allow_empty=False
        )
        _sorted_texts(
            constraint["forbidden_edges"],
            label=f"{label}.forbidden_edges",
            allow_empty=False,
        )
        _sorted_texts(
            constraint["scenario_ids"],
            label=f"{label}.scenario_ids",
            allow_empty=False,
        )
        if owner in owners and owners[owner] != source.as_posix():
            raise HarnessOwnerConstraintRegistryError(
                f"owner {owner!r} resolves to multiple source files"
            )
        owners[owner] = source.as_posix()
        ids.append(constraint_id)
    if ids != sorted(set(ids)):
        raise HarnessOwnerConstraintRegistryError(
            "constraints must be sorted by unique constraint_id"
        )
    digest = "sha256:" + hashlib.sha256(content).hexdigest()
    return ValidatedHarnessOwnerConstraintRegistry(
        payload=payload,
        registry_digest=digest,
        source_path=source_path,
    )


def load_harness_owner_constraint_registry(
    repo_root: Path,
) -> ValidatedHarnessOwnerConstraintRegistry:
    root = repo_root.resolve(strict=True)
    source = root / OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH
    return validate_harness_owner_constraint_registry_bytes(
        source.read_bytes(), repo_root=root, source_path=source
    )


__all__ = [
    "HarnessOwnerConstraintRegistryError",
    "OWNER_CONSTRAINT_REGISTRY_ID",
    "OWNER_CONSTRAINT_REGISTRY_RELATIVE_PATH",
    "OWNER_CONSTRAINT_REGISTRY_SCHEMA_ID",
    "ValidatedHarnessOwnerConstraintRegistry",
    "load_harness_owner_constraint_registry",
    "validate_harness_owner_constraint_registry_bytes",
]
