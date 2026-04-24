from __future__ import annotations

import json
from typing import Any

from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult

DEFAULT_PAGE_LIMIT = 30
MAX_PAGE_LIMIT = 50
LARGE_JSON_CHARS = 20_000
FULL_JSON_CHARS = 100_000
PREVIEW_JSON_CHARS = 1_200


def _json_chars(value: Any) -> int:
    return len(json.dumps(value, sort_keys=True, ensure_ascii=False))


def _preview(value: Any) -> Any:
    if isinstance(value, list):
        return [_preview(item) for item in value[:3]]
    if isinstance(value, dict):
        preview: dict[str, Any] = {}
        for index, (key, item) in enumerate(value.items()):
            if index >= 8:
                break
            preview[key] = _preview(item)
        return preview
    if isinstance(value, str) and len(value) > PREVIEW_JSON_CHARS:
        return value[:PREVIEW_JSON_CHARS] + "..."
    return value


def _type_name(value: Any) -> str:
    if isinstance(value, list):
        return "list"
    if isinstance(value, dict):
        return "dict"
    if isinstance(value, str):
        return "string"
    if value is None:
        return "null"
    return type(value).__name__


def _read_hint(path: str) -> str:
    return f'artifact.get with path="{path}", offset=0, limit={DEFAULT_PAGE_LIMIT}'


def _omitted_field(path: str, value: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "path": path,
        "type": _type_name(value),
        "json_chars": _json_chars(value),
        "preview": _preview(value),
        "read_hint": _read_hint(path),
    }
    if isinstance(value, (list, dict, str)):
        payload["item_count"] = len(value)
    return payload


def _is_large(path: str, value: Any) -> bool:
    if path in {"output_payload.evidence_items", "output_payload.source_refs", "documents"}:
        return True
    if isinstance(value, list) and len(value) > DEFAULT_PAGE_LIMIT:
        return True
    return isinstance(value, (dict, list, str)) and _json_chars(value) > LARGE_JSON_CHARS


def _split_path(path: str) -> list[str]:
    return [part for part in path.split(".") if part]


def _resolve_path(root: dict[str, Any], path: str) -> tuple[bool, Any]:
    current: Any = root
    for part in _split_path(path):
        if isinstance(current, dict) and part in current:
            current = current[part]
            continue
        if isinstance(current, list):
            try:
                current = current[int(part)]
            except (ValueError, IndexError):
                return False, None
            continue
        return False, None
    return True, current


def _clamped_limit(arguments: dict[str, Any]) -> int:
    limit = int(arguments.get("limit", DEFAULT_PAGE_LIMIT))
    return max(0, min(MAX_PAGE_LIMIT, limit))


def _output_ref_from_artifact(artifact: Any) -> str | None:
    metadata = dict(artifact.metadata or {})
    output_ref = metadata.get("output_ref")
    if output_ref is not None:
        return str(output_ref)
    prefix = "engine-document://"
    if artifact.storage_uri.startswith(prefix):
        return artifact.storage_uri[len(prefix) :]
    return None


def _artifact_resource(context: SessionRuntimeContext, artifact: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"artifact": artifact.to_dict()}
    invocation = None
    if artifact.invocation_id is not None:
        invocation = context.repositories.invocations.get(artifact.invocation_id)
        if invocation is not None:
            payload["invocation"] = invocation.to_dict()
            if invocation.output_ref is not None:
                payload["output_document_id"] = invocation.output_ref
        summary = context.repositories.research_summaries.get_by_invocation(artifact.session_id, artifact.invocation_id)
        if summary is not None:
            payload["canonical_summary"] = summary.to_dict()
    output_ref = _output_ref_from_artifact(artifact)
    if output_ref is not None:
        output_document = context.repositories.engine_documents.get(output_ref)
        if output_document is not None:
            payload["output_document"] = {
                "document_id": output_document.document_id,
                "session_id": output_document.session_id,
                "invocation_id": output_document.invocation_id,
                "document_kind": output_document.document_kind,
                "created_at": output_document.created_at,
                "updated_at": output_document.updated_at,
            }
            payload["output_payload"] = output_document.payload
    if artifact.invocation_id is not None:
        payload["documents"] = [
            document.to_dict()
            for document in context.repositories.engine_documents.list_by_invocation(
                artifact.session_id,
                artifact.invocation_id,
            )
        ]
    return payload


def _default_payload(root: dict[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "artifact": root["artifact"],
        "omitted_fields": [],
    }
    for key in ("invocation", "output_document_id", "output_document", "canonical_summary"):
        if key in root:
            payload[key] = root[key]
    output_payload = root.get("output_payload")
    if isinstance(output_payload, dict):
        counts: dict[str, int] = {}
        for field in ("evidence_items", "source_refs", "unresolved_gaps", "artifacts", "raw_notes", "recent_turns"):
            value = output_payload.get(field)
            if isinstance(value, list):
                counts[field] = len(value)
        payload["output_payload"] = {
            "status": output_payload.get("status"),
            "completion_reason": output_payload.get("completion_reason"),
            "research_brief": output_payload.get("research_brief"),
            "summary": output_payload.get("summary"),
            "clarification_question": output_payload.get("clarification_question"),
        }
        payload["counts"] = counts
        payload["summary_preview"] = _preview(output_payload.get("summary"))
        for field in ("evidence_items", "source_refs", "unresolved_gaps", "artifacts", "raw_notes", "recent_turns"):
            if field in output_payload and _is_large(f"output_payload.{field}", output_payload[field]):
                payload["omitted_fields"].append(_omitted_field(f"output_payload.{field}", output_payload[field]))
    if "documents" in root:
        documents: list[dict[str, Any]] = []
        for index, document in enumerate(root["documents"]):
            safe_document = dict(document)
            doc_payload = safe_document.get("payload")
            safe_document["payload"] = _preview(doc_payload)
            if _is_large(f"documents.{index}.payload", doc_payload):
                payload["omitted_fields"].append(_omitted_field(f"documents.{index}.payload", doc_payload))
            documents.append(safe_document)
        payload["documents"] = documents
    return payload


def _path_payload(*, root: dict[str, Any], path: str, offset: int, limit: int, include_full: bool) -> tuple[bool, dict[str, Any]]:
    exists, value = _resolve_path(root, path)
    if not exists:
        return False, {
            "error": f"path {path!r} does not exist",
            "available_top_level_paths": sorted(root.keys()),
        }
    if isinstance(value, list):
        page = value[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(value) else None
        return True, {
            "path": path,
            "type": "list",
            "offset": offset,
            "limit": limit,
            "item_count": len(value),
            "items": page,
            "next_offset": next_offset,
        }
    json_chars = _json_chars(value)
    if isinstance(value, dict) and json_chars > LARGE_JSON_CHARS and (
        not include_full or json_chars > FULL_JSON_CHARS
    ):
        keys = list(value.keys())
        page_keys = keys[offset : offset + limit]
        next_offset = offset + len(page_keys) if offset + len(page_keys) < len(keys) else None
        return True, {
            "path": path,
            "type": "dict",
            "offset": offset,
            "limit": limit,
            "item_count": len(keys),
            "json_chars": json_chars,
            "keys": [
                {
                    "key": key,
                    "path": f"{path}.{key}",
                    "type": _type_name(value[key]),
                    "json_chars": _json_chars(value[key]),
                    "preview": _preview(value[key]),
                }
                for key in page_keys
            ],
            "next_offset": next_offset,
            "preview": _preview(value),
            "read_hint": (
                f'artifact.get with path="{path}.<key>"'
                if json_chars > FULL_JSON_CHARS
                else f'artifact.get with path="{path}", include_full=true'
            ),
        }
    if isinstance(value, str) and json_chars > LARGE_JSON_CHARS and (
        not include_full or json_chars > FULL_JSON_CHARS
    ):
        return True, {
            "path": path,
            "type": "string",
            "json_chars": json_chars,
            "item_count": len(value),
            "preview": _preview(value),
            "read_hint": (
                f'artifact.get with path="{path}", include_full=true'
                if json_chars <= FULL_JSON_CHARS
                else "field exceeds the full-read safety limit; request a narrower path"
            ),
        }
    return True, {
        "path": path,
        "type": _type_name(value),
        "json_chars": json_chars,
        "value": value,
    }


def register_artifact_tools(registry: ToolRegistry) -> None:
    def list_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        task_id = invocation.arguments.get("task_id")
        invocation_id = invocation.arguments.get("invocation_id")
        if task_id is not None:
            artifacts = context.repositories.artifacts.list_by_task(session_id, str(task_id))
        elif invocation_id is not None:
            artifacts = context.repositories.artifacts.list_by_invocation(session_id, str(invocation_id))
        else:
            artifacts = context.repositories.artifacts.list_by_session(session_id)
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps([artifact.to_dict() for artifact in artifacts], sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def get_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        artifact_id = str(invocation.arguments["artifact_id"])
        artifact = context.repositories.artifacts.get(artifact_id)
        if artifact is None:
            return ToolResult(
                call_id=invocation.call_id,
                tool_name=invocation.tool_name,
                ok=False,
                content=f"artifact {artifact_id!r} does not exist",
                task_id=invocation.task_id,
                lane_id=invocation.lane_id,
            )
        root = _artifact_resource(context, artifact)
        path = invocation.arguments.get("path")
        if path is None:
            payload = _default_payload(root)
            ok = True
        else:
            offset = max(0, int(invocation.arguments.get("offset", 0)))
            limit = _clamped_limit(invocation.arguments)
            include_full = bool(invocation.arguments.get("include_full", False))
            ok, payload = _path_payload(
                root=root,
                path=str(path),
                offset=offset,
                limit=limit,
                include_full=include_full,
            )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=ok,
            content=json.dumps(payload, sort_keys=True),
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
        )

    registry.register("artifact.list", list_handler)
    registry.register("artifact.get", get_handler)


__all__ = ["register_artifact_tools"]
