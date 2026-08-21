from __future__ import annotations

from importlib.resources import files
import json
from typing import Any


FILE_WORKSPACE_PUBLIC_V2_SCHEMA_RESOURCE = "file_workspace_public_v2.schema.json"


def load_file_workspace_public_v2_json_schema() -> dict[str, Any]:
    """Load the packaged public schema without performing import-time I/O."""

    resource = files(__package__).joinpath(FILE_WORKSPACE_PUBLIC_V2_SCHEMA_RESOURCE)
    value = json.loads(resource.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("file_workspace_public@2 JSON Schema root must be an object")
    return value


__all__ = [
    "FILE_WORKSPACE_PUBLIC_V2_SCHEMA_RESOURCE",
    "load_file_workspace_public_v2_json_schema",
]
