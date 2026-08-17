from __future__ import annotations

from collections.abc import Mapping
from typing import Any


AGENT_TRACE_PROJECTION_SCHEMA_VERSION = "v1"
AGENT_TRACE_PUBLIC_KEYS = frozenset(
    {
        "trace_id",
        "actor_ref",
        "actor_kind",
        "display_name",
        "role",
        "call_index",
        "created_at",
        "response_text",
        "tool_calls",
        "step_id",
        "tool_catalog_digest",
        "restore_context_digest",
        "projection_schema_version",
        "agent_step",
    }
)
AGENT_STEP_PUBLIC_KEYS = (
    "step_id",
    "session_id",
    "agent_id",
    "actor_kind",
    "role",
    "call_index",
    "task_id",
    "lane_id",
    "correlation_id",
    "signal_id",
    "wakeup_reason",
    "restore_context_digest",
    "tool_catalog_digest",
    "created_at",
)
TOOL_CALL_PUBLIC_KEYS = frozenset(
    {
        "call_id",
        "tool_name",
        "task_id",
        "lane_id",
        "args_public",
    }
)

_REDACTED = "[redacted]"
_SENSITIVE_KEY_FRAGMENTS = (
    "secret",
    "token",
    "password",
    "credential",
    "private_key",
    "api_key",
)
_PRIVATE_KEY_FRAGMENTS = (
    "storage_uri",
    "source_storage_uri",
    "intermediate_storage_uri",
    "local_path",
    "remote_path",
    "host_path",
    "runner_config",
    "runner_path",
    "ssh",
    "config",
)
_PRIVATE_EXACT_KEYS = {"code", "content", "pipeline_code", "source_code"}
_PRIVATE_STRING_PREFIXES = (
    "arti" + "fact://",
    "storage://",
    "s3://",
    "file://",
)
_PRIVATE_PATH_PREFIXES = (
    "/home/",
    "/tmp/",
    "/var/",
    "/mnt/",
    "/data/",
    "~",
)


def sanitize_public_tool_args(value: Any, *, key: str = "") -> Any:
    key_lower = key.lower()
    if key_lower in _PRIVATE_EXACT_KEYS:
        return _REDACTED
    if any(fragment in key_lower for fragment in _SENSITIVE_KEY_FRAGMENTS):
        return _REDACTED
    if any(fragment in key_lower for fragment in _PRIVATE_KEY_FRAGMENTS):
        return _REDACTED
    if isinstance(value, Mapping):
        return {
            str(item_key): sanitize_public_tool_args(item, key=str(item_key))
            for item_key, item in value.items()
        }
    if isinstance(value, list | tuple):
        return [sanitize_public_tool_args(item) for item in value[:20]]
    if isinstance(value, str):
        if value.startswith(_PRIVATE_STRING_PREFIXES):
            return _REDACTED
        if value.startswith(_PRIVATE_PATH_PREFIXES):
            return _REDACTED
        if len(value) > 1200:
            return value[:1200] + "... [truncated]"
    return value


def _mapping_from(value: Any) -> Mapping[str, Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return value
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        mapped = to_dict()
        if isinstance(mapped, Mapping):
            return mapped
    return None


def project_public_agent_step(value: Any) -> dict[str, Any] | None:
    source = _mapping_from(value)
    if source is None:
        return None
    projected = {
        key: source.get(key)
        for key in AGENT_STEP_PUBLIC_KEYS
        if key in source
    }
    return projected or None


def project_public_tool_call(value: Any) -> dict[str, Any] | None:
    source = _mapping_from(value)
    if source is None:
        return None
    return {
        "call_id": source.get("call_id"),
        "tool_name": source.get("tool_name"),
        "task_id": source.get("task_id"),
        "lane_id": source.get("lane_id"),
        "args_public": sanitize_public_tool_args(source.get("args_public") or {}),
    }


def project_public_llm_trace_step(
    payload: Mapping[str, Any],
    *,
    trace_id: str | None = None,
    created_at: str | None = None,
) -> dict[str, Any]:
    agent_step = project_public_agent_step(payload.get("agent_step"))
    if agent_step is None:
        step_source = {
            key: payload.get(key)
            for key in AGENT_STEP_PUBLIC_KEYS
            if key in payload
        }
        agent_step = project_public_agent_step(step_source)
    tool_calls = payload.get("tool_calls")
    tool_calls = tool_calls if isinstance(tool_calls, list | tuple) else ()

    projected: dict[str, Any] = {
        "trace_id": payload.get("trace_id") or trace_id,
        "actor_ref": payload.get("actor_ref") or "harness",
        "actor_kind": (
            payload.get("actor_kind")
            or (None if agent_step is None else agent_step.get("actor_kind"))
            or "master"
        ),
        "display_name": payload.get("display_name") or "OpenZyme",
        "role": (
            payload.get("role")
            or (None if agent_step is None else agent_step.get("role"))
            or "master"
        ),
        "call_index": payload.get("call_index")
        if payload.get("call_index") is not None
        else (None if agent_step is None else agent_step.get("call_index")),
        "created_at": payload.get("created_at") or created_at,
        "response_text": payload.get("response_text") or "",
        "tool_calls": [
            item
            for item in (
                project_public_tool_call(tool_call)
                for tool_call in tool_calls
            )
            if item is not None
        ],
        "projection_schema_version": AGENT_TRACE_PROJECTION_SCHEMA_VERSION,
    }

    step_id = payload.get("step_id") or (
        None if agent_step is None else agent_step.get("step_id")
    )
    if step_id is not None:
        projected["step_id"] = step_id
    tool_catalog_digest = payload.get("tool_catalog_digest") or (
        None if agent_step is None else agent_step.get("tool_catalog_digest")
    )
    if tool_catalog_digest is not None:
        projected["tool_catalog_digest"] = tool_catalog_digest
    restore_context_digest = payload.get("restore_context_digest") or (
        None if agent_step is None else agent_step.get("restore_context_digest")
    )
    if restore_context_digest is not None:
        projected["restore_context_digest"] = restore_context_digest
    if agent_step is not None:
        projected["agent_step"] = agent_step
    return {
        key: value
        for key, value in projected.items()
        if key in AGENT_TRACE_PUBLIC_KEYS
    }
