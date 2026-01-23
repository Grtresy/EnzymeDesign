from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from jsonschema import Draft202012Validator


class SchemaValidationError(ValueError):
    """Raised when JSON schema validation fails."""


def load_schema(schema_path: Path) -> dict:
    return json.loads(schema_path.read_text(encoding="utf-8"))


def validate_json(data: Any, schema: Mapping[str, Any], source: str) -> None:
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(data), key=lambda err: list(err.path))
    if errors:
        formatted = "\n".join(
            f"- {source}: {error.message} at {list(error.path)}"
            for error in errors
        )
        raise SchemaValidationError(formatted)


def validate_json_path(json_path: Path, schema_path: Path) -> None:
    data = json.loads(json_path.read_text(encoding="utf-8"))
    schema = load_schema(schema_path)
    validate_json(data, schema, str(json_path))


def build_default_instance(schema: Mapping[str, Any]) -> Any:
    if "const" in schema:
        return schema["const"]
    if "enum" in schema:
        return schema["enum"][0]

    schema_type = schema.get("type")
    if isinstance(schema_type, list) and schema_type:
        schema_type = schema_type[0]

    if schema_type == "object":
        props = schema.get("properties", {})
        required = schema.get("required", [])
        result: dict[str, Any] = {}
        for name in required:
            prop_schema = props.get(name, {})
            if "default" in prop_schema:
                result[name] = prop_schema["default"]
            else:
                result[name] = build_default_instance(prop_schema)
        return result
    if schema_type == "array":
        if "default" in schema:
            return schema["default"]
        return []
    if schema_type == "string":
        return schema.get("default", "")
    if schema_type == "integer":
        return schema.get("default", 0)
    if schema_type == "number":
        return schema.get("default", 0.0)
    if schema_type == "boolean":
        return schema.get("default", False)

    return schema.get("default")
