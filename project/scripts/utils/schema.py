from __future__ import annotations

from pathlib import Path
from typing import Any

import jsonschema

from .io import read_json


def load_schema(schema_path: Path) -> dict:
    return read_json(schema_path)


def validate_json(data: Any, schema: dict) -> None:
    jsonschema.validate(instance=data, schema=schema)


def validate_json_path(path: Path, schema_path: Path) -> None:
    schema = load_schema(schema_path)
    data = read_json(path)
    validate_json(data, schema)

