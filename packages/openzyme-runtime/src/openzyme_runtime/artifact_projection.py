from __future__ import annotations

import hashlib
import json
import re
from typing import Any


PRIVATE_ARTIFACT_KEYS = {
    "storage_uri",
    "local_path",
    "host_path",
    "sandbox_host_path",
    "source_storage_uri",
    "source_uri",
    "intermediate_storage_uri",
    "runner_path",
    "runner_config",
    "ssh_config",
}

ARTIFACT_LIST_METADATA_SUMMARY_SCHEMA_ID = "artifact_list_metadata_summary@1"
ARTIFACT_LIST_RECORD_SUMMARY_SCHEMA_ID = "artifact_list_record_summary@1"
ARTIFACT_LIST_METADATA_MAX_PROJECTED_CHARS = 4_096
ARTIFACT_LIST_METADATA_MAX_SUMMARY_CHARS = 4_096
ARTIFACT_LIST_METADATA_MAX_NESTED_CHARS = 2_048
ARTIFACT_LIST_METADATA_MAX_SCALAR_CHARS = 512
ARTIFACT_LIST_METADATA_MAX_INLINE_LIST_ITEMS = 12
ARTIFACT_LIST_METADATA_MAX_INLINE_LIST_CHARS = 1_200
ARTIFACT_LIST_METADATA_MAX_DICT_FIELDS = 32
ARTIFACT_LIST_METADATA_MAX_DEPTH = 4
ARTIFACT_LIST_METADATA_MAX_OMITTED_FIELDS = 8
ARTIFACT_LIST_METADATA_MAX_PATH_CHARS = 320
ARTIFACT_LIST_RECORD_MAX_SCALAR_CHARS = 512
ARTIFACT_LIST_RECORD_MAX_SUMMARY_CHARS = 2_048
ARTIFACT_LIST_ITEM_MAX_JSON_CHARS = 20_000
ARTIFACT_GET_DEFAULT_COLLECTION_PAGE_LIMIT = 30
ARTIFACT_GET_DEFAULT_STRING_PAGE_LIMIT = 12_000

_SAFE_METADATA_PATH_SEGMENT = re.compile(r"^[A-Za-z0-9_-]+$")
_OMITTED = object()
_PRIMARY_IDENTITY_METADATA_KEYS = {
    "content_digest",
    "cutover_eligible",
    "external_id",
    "format",
    "output_format",
    "provider",
    "schema_id",
    "sealed_digest",
    "semantic_type",
    "source",
    "status",
    "validation_status",
    "version",
}

_COLLECTION_IDENTITY_METADATA_KEYS = {
    "accessions",
}


def _canonical_json(value: Any) -> str | None:
    try:
        return json.dumps(
            value,
            # artifact.list uses this exact representation for both budgeting
            # and its final ToolResult content. ASCII escaping also guarantees
            # that lone surrogate code points remain encodable UTF-8 JSON.
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (RecursionError, TypeError, ValueError):
        return None


def _canonical_digest(serialized: str | None) -> str | None:
    if serialized is None:
        return None
    try:
        encoded = serialized.encode("utf-8")
    except UnicodeEncodeError:
        return None
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def serialize_artifact_projection(value: Any) -> str:
    """Serialize an artifact projection with the canonical budget representation."""

    serialized = _canonical_json(value)
    if serialized is None:
        raise ValueError("artifact projection is not canonically JSON serializable")
    return serialized


def _metadata_type(value: Any) -> str:
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, list):
        return "list"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, (int, float)):
        return "number"
    return "unsupported"


def _metadata_item_count(value: Any) -> int | None:
    if isinstance(value, (dict, list, str)):
        return len(value)
    return None


def _metadata_key_priority(key: str, value: Any) -> tuple[int, str, str]:
    normalized = key.lower()
    if (
        normalized in _PRIMARY_IDENTITY_METADATA_KEYS
        or "contract" in normalized
    ):
        return 0, normalized, key
    if (
        normalized in _COLLECTION_IDENTITY_METADATA_KEYS
        or normalized.endswith(("_digests", "_ids", "_manifest"))
    ):
        return 1, normalized, key
    if value is None or isinstance(value, (bool, int, float, str)):
        if normalized.endswith(
            (
                "_count",
                "_counts",
                "_digest",
                "_id",
                "_version",
            )
        ):
            return 2, normalized, key
        return 3, normalized, key
    return 4, normalized, key


def _artifact_get_hint(
    *,
    artifact_id: str | None,
    path: str,
    value: Any = None,
) -> str | None:
    if not artifact_id:
        return None
    limit = (
        ARTIFACT_GET_DEFAULT_STRING_PAGE_LIMIT
        if isinstance(value, str)
        else ARTIFACT_GET_DEFAULT_COLLECTION_PAGE_LIMIT
    )
    return (
        "artifact.get with "
        f"artifact_id={json.dumps(artifact_id, ensure_ascii=True)}, "
        f"path={json.dumps(path, ensure_ascii=True)}, offset=0, limit={limit}"
    )


class _ArtifactListMetadataState:
    def __init__(self, *, artifact_id: str | None) -> None:
        self.artifact_id = artifact_id
        self.omitted_field_count = 0
        self.omitted_fields: list[dict[str, Any]] = []

    def omit(
        self,
        *,
        path: str,
        value: Any,
        reason: str,
        omitted_child_count: int | None = None,
        field_key: str | None = None,
        exact_path_available: bool = True,
    ) -> None:
        self.omitted_field_count += 1
        if len(self.omitted_fields) >= ARTIFACT_LIST_METADATA_MAX_OMITTED_FIELDS:
            return
        serialized = _canonical_json(value)
        read_hint = _artifact_get_hint(
            artifact_id=self.artifact_id,
            path=path,
            # A root-only hint addresses the parent dictionary, not the
            # omitted child value. Keep its collection page size at 30 even
            # when that child happens to be a large string.
            value=value if exact_path_available else {},
        )
        record: dict[str, Any] = {
            "path": path,
            "type": _metadata_type(value),
            "reason": reason,
            "json_chars": None if serialized is None else len(serialized),
            "content_digest": _canonical_digest(serialized),
            "read_scope": "exact_pageable" if exact_path_available else "root_only",
            "exact_path_available": exact_path_available,
        }
        if read_hint is not None:
            record["read_hint"] = read_hint
        item_count = _metadata_item_count(value)
        if item_count is not None:
            record["item_count"] = item_count
        if omitted_child_count is not None:
            record["omitted_child_count"] = omitted_child_count
        if field_key is not None:
            record["field_key_chars"] = len(field_key)
            record["field_key_digest"] = _canonical_digest(
                _canonical_json(field_key)
            )
        self.omitted_fields.append(record)


def _metadata_child_path(path: str, key: str) -> str | None:
    if not _SAFE_METADATA_PATH_SEGMENT.fullmatch(key):
        return None
    child_path = f"{path}.{key}"
    if len(child_path) > ARTIFACT_LIST_METADATA_MAX_PATH_CHARS:
        return None
    return child_path


def _project_metadata_value(
    value: Any,
    *,
    path: str,
    depth: int,
    state: _ArtifactListMetadataState,
) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        serialized = _canonical_json(value)
        if serialized is None or len(serialized) > ARTIFACT_LIST_METADATA_MAX_SCALAR_CHARS:
            state.omit(path=path, value=value, reason="scalar_size_limit")
            return _OMITTED
        return value
    if isinstance(value, list):
        serialized = _canonical_json(value)
        if (
            serialized is None
            or len(value) > ARTIFACT_LIST_METADATA_MAX_INLINE_LIST_ITEMS
            or len(serialized) > ARTIFACT_LIST_METADATA_MAX_INLINE_LIST_CHARS
        ):
            state.omit(path=path, value=value, reason="inline_list_limit")
            return _OMITTED
        return value
    if not isinstance(value, dict):
        state.omit(path=path, value=value, reason="unsupported_value")
        return _OMITTED
    if len(value) > ARTIFACT_LIST_METADATA_MAX_DICT_FIELDS:
        state.omit(path=path, value=value, reason="inline_dict_field_limit")
        return _OMITTED
    if depth >= ARTIFACT_LIST_METADATA_MAX_DEPTH:
        state.omit(path=path, value=value, reason="depth_limit")
        return _OMITTED
    return _project_metadata_dict(
        value,
        path=path,
        depth=depth + 1,
        max_chars=ARTIFACT_LIST_METADATA_MAX_NESTED_CHARS,
        state=state,
    )


def _project_metadata_dict(
    metadata: dict[str, Any],
    *,
    path: str,
    depth: int,
    max_chars: int,
    state: _ArtifactListMetadataState,
) -> dict[str, Any]:
    ordered_keys = sorted(
        metadata,
        key=lambda key: _metadata_key_priority(str(key), metadata[key]),
    )
    selected_keys = ordered_keys[:ARTIFACT_LIST_METADATA_MAX_DICT_FIELDS]
    projected: dict[str, Any] = {}
    for raw_key in selected_keys:
        key = str(raw_key)
        child_path = _metadata_child_path(path, key)
        if child_path is None:
            state.omit(
                path=path,
                value=metadata[raw_key],
                reason="unaddressable_field_key",
                field_key=key,
                exact_path_available=False,
            )
            continue
        child = _project_metadata_value(
            metadata[raw_key],
            path=child_path,
            depth=depth,
            state=state,
        )
        if child is _OMITTED:
            continue
        candidate = {**projected, key: child}
        serialized = _canonical_json(candidate)
        if serialized is None or len(serialized) > max_chars:
            state.omit(
                path=child_path,
                value=metadata[raw_key],
                reason="projected_metadata_budget",
            )
            continue
        projected[key] = child
    remainder_count = len(ordered_keys) - len(selected_keys)
    if remainder_count > 0:
        state.omit(
            path=path,
            value=metadata,
            reason="field_count_limit",
            omitted_child_count=remainder_count,
            exact_path_available=False,
        )
    return projected


def _bounded_metadata_for_artifact_list(
    metadata: Any,
    *,
    artifact_id: str | None,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    root_path = "artifact.metadata"
    state = _ArtifactListMetadataState(artifact_id=artifact_id)
    sanitization_failed = False
    try:
        sanitized = sanitize_private_artifact_fields(metadata)
    except RecursionError:
        sanitization_failed = True
        sanitized = None
        state.omit(
            path=root_path,
            value=metadata,
            reason="metadata_recursion_limit",
        )
    original_serialized = None if sanitization_failed else _canonical_json(sanitized)
    if metadata is None:
        projected: dict[str, Any] | None = None
        original_field_count = 0
    elif sanitization_failed:
        projected = {}
        original_field_count = 0
    elif isinstance(sanitized, dict):
        projected = _project_metadata_dict(
            sanitized,
            path=root_path,
            depth=0,
            max_chars=ARTIFACT_LIST_METADATA_MAX_PROJECTED_CHARS,
            state=state,
        )
        original_field_count = len(sanitized)
    else:
        state.omit(
            path=root_path,
            value=sanitized,
            reason="metadata_not_object",
        )
        projected = {}
        original_field_count = 0
    projected_serialized = _canonical_json(projected)
    root_read_hint = _artifact_get_hint(
        artifact_id=artifact_id,
        path=root_path,
        value=sanitized,
    )
    summary: dict[str, Any] = {
        "schema_id": ARTIFACT_LIST_METADATA_SUMMARY_SCHEMA_ID,
        "original_top_level_field_count": original_field_count,
        "retained_top_level_field_count": (
            0 if projected is None else len(projected)
        ),
        "original_json_chars": (
            None if original_serialized is None else len(original_serialized)
        ),
        "projected_json_chars": (
            None if projected_serialized is None else len(projected_serialized)
        ),
        "metadata_digest": _canonical_digest(original_serialized),
        "omitted_field_count": state.omitted_field_count,
        "omitted_fields": state.omitted_fields,
        "omitted_fields_truncated": (
            state.omitted_field_count > len(state.omitted_fields)
        ),
        "read_scope": "exact_pageable",
    }
    if root_read_hint is not None:
        summary["read_hint"] = root_read_hint
    _bound_omitted_summary(
        summary,
        max_chars=ARTIFACT_LIST_METADATA_MAX_SUMMARY_CHARS,
    )
    return projected, summary


def _bound_omitted_summary(summary: dict[str, Any], *, max_chars: int) -> None:
    omitted_fields = summary.get("omitted_fields")
    if not isinstance(omitted_fields, list):
        return
    while True:
        summary["omitted_fields_returned_count"] = len(omitted_fields)
        serialized = _canonical_json(summary)
        if serialized is not None and len(serialized) <= max_chars:
            break
        if not omitted_fields:
            # All remaining fields are fixed-size counters/digests plus a
            # bounded artifact id. Reaching this branch signals a programming
            # error instead of silently emitting an unbounded summary.
            raise ValueError("artifact list omission summary exceeded its hard JSON budget")
        omitted_fields.pop()
        summary["omitted_fields_truncated"] = True


def _bounded_record_for_artifact_list(
    payload: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any] | None, str | None]:
    sanitized_payload = sanitize_private_artifact_fields(payload)
    raw_artifact_id = sanitized_payload.get("artifact_id")
    artifact_id_serialized = _canonical_json(raw_artifact_id)
    artifact_id = (
        str(raw_artifact_id)
        if isinstance(raw_artifact_id, str)
        and artifact_id_serialized is not None
        and len(artifact_id_serialized) <= ARTIFACT_LIST_RECORD_MAX_SCALAR_CHARS
        else None
    )
    projected: dict[str, Any] = {}
    omitted_fields: list[dict[str, Any]] = []
    omitted_field_count = 0
    for key in sorted(sanitized_payload):
        value = sanitized_payload[key]
        serialized = _canonical_json(value)
        if (
            value is None
            or isinstance(value, (bool, int, float, str))
            and serialized is not None
            and len(serialized) <= ARTIFACT_LIST_RECORD_MAX_SCALAR_CHARS
        ):
            projected[key] = value
            continue
        omitted_field_count += 1
        record: dict[str, Any] = {
            "path": f"artifact.{key}",
            "type": _metadata_type(value),
            "reason": "record_scalar_size_limit",
            "json_chars": None if serialized is None else len(serialized),
            "content_digest": _canonical_digest(serialized),
            "read_scope": "exact_pageable" if artifact_id is not None else "unavailable",
            "exact_path_available": artifact_id is not None,
        }
        read_hint = _artifact_get_hint(
            artifact_id=artifact_id,
            path=f"artifact.{key}",
            value=value,
        )
        if read_hint is not None:
            record["read_hint"] = read_hint
        omitted_fields.append(record)
    if not omitted_fields:
        return projected, None, artifact_id
    summary: dict[str, Any] = {
        "schema_id": ARTIFACT_LIST_RECORD_SUMMARY_SCHEMA_ID,
        "omitted_field_count": omitted_field_count,
        "omitted_fields": omitted_fields,
        "omitted_fields_truncated": False,
    }
    _bound_omitted_summary(
        summary,
        max_chars=ARTIFACT_LIST_RECORD_MAX_SUMMARY_CHARS,
    )
    return projected, summary, artifact_id


def sanitize_private_artifact_fields(value: Any) -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for key, item in value.items():
            key_text = str(key)
            if key_text.lower() in PRIVATE_ARTIFACT_KEYS:
                continue
            sanitized[key_text] = sanitize_private_artifact_fields(item)
        return sanitized
    if isinstance(value, list):
        return [sanitize_private_artifact_fields(item) for item in value]
    if isinstance(value, tuple):
        return [sanitize_private_artifact_fields(item) for item in value]
    return value


def project_artifact_for_agent(artifact: Any) -> dict[str, Any]:
    payload = dict(artifact.to_dict())
    payload.pop("storage_uri", None)
    return sanitize_private_artifact_fields(payload)


def project_artifact_list_item_for_agent(artifact: Any) -> dict[str, Any]:
    payload = dict(artifact.to_dict())
    payload.pop("storage_uri", None)
    metadata = payload.pop("metadata", None)
    bounded_payload, record_summary, artifact_id = _bounded_record_for_artifact_list(
        payload
    )
    projected_metadata, metadata_summary = _bounded_metadata_for_artifact_list(
        metadata,
        artifact_id=artifact_id,
    )
    bounded_payload["metadata"] = projected_metadata
    bounded_payload["metadata_summary"] = metadata_summary
    if record_summary is not None:
        bounded_payload["record_summary"] = record_summary
    serialized = serialize_artifact_projection(bounded_payload)
    if len(serialized) > ARTIFACT_LIST_ITEM_MAX_JSON_CHARS:
        # The independent metadata/summary/record caps normally make this
        # unreachable. Keep a final local fail-closed guard so an unexpected
        # catalog field can never invalidate the list-level hard budget.
        bounded_payload["metadata"] = {}
        metadata_summary["omitted_fields"] = []
        metadata_summary["omitted_fields_truncated"] = True
        metadata_summary["omitted_fields_returned_count"] = 0
        bounded_payload["item_truncated_by_budget"] = True
        serialized = serialize_artifact_projection(bounded_payload)
    if len(serialized) > ARTIFACT_LIST_ITEM_MAX_JSON_CHARS:
        raise ValueError("bounded artifact list item exceeded its hard JSON budget")
    return bounded_payload


def project_artifact_list_for_agent(artifacts: Any) -> list[dict[str, Any]]:
    return [project_artifact_list_item_for_agent(artifact) for artifact in artifacts]


def project_artifacts_for_agent(artifacts: Any) -> list[dict[str, Any]]:
    return [project_artifact_for_agent(artifact) for artifact in artifacts]


__all__ = [
    "PRIVATE_ARTIFACT_KEYS",
    "project_artifact_for_agent",
    "project_artifact_list_for_agent",
    "project_artifact_list_item_for_agent",
    "project_artifacts_for_agent",
    "sanitize_private_artifact_fields",
    "serialize_artifact_projection",
]
