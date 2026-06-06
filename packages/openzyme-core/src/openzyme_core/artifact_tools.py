from __future__ import annotations

import difflib
import hashlib
import json
from pathlib import Path
import re
from typing import Any
from uuid import uuid4

from openzyme_domain import ArtifactKind
from openzyme_domain import SessionArtifactRecord
from openzyme_domain.control_plane import utc_now_iso

from .artifact_projection import project_artifact_for_agent
from .artifact_projection import project_artifacts_for_agent
from .artifact_projection import sanitize_private_artifact_fields
from .harness import SessionRuntimeContext
from .harness import ToolInvocation
from .harness import ToolRegistry
from .harness import ToolResult

DEFAULT_PAGE_LIMIT = 30
MAX_PAGE_LIMIT = 50
LARGE_JSON_CHARS = 20_000
FULL_JSON_CHARS = 100_000
PREVIEW_JSON_CHARS = 1_200
DEFAULT_TEXT_LIMIT = 12_000
MAX_TEXT_LIMIT = 50_000
DEFAULT_PREVIEW_LINES = 40
MAX_PREVIEW_LINES = 200
MAX_RANGE_LINES = 500
MAX_TEXT_FILE_BYTES = 2_000_000
MAX_CREATE_TEXT_BYTES = 500_000
MAX_DIFF_CHARS = 50_000

TEXT_EXTENSIONS = {
    ".csv",
    ".fa",
    ".faa",
    ".fasta",
    ".json",
    ".jsonl",
    ".log",
    ".md",
    ".pdb",
    ".pdbqt",
    ".py",
    ".txt",
    ".xml",
    ".yaml",
    ".yml",
}
BINARY_EXTENSIONS = {
    ".bin",
    ".gz",
    ".h5",
    ".hdf5",
    ".npy",
    ".npz",
    ".parquet",
    ".pdf",
    ".png",
    ".zip",
}
TEXT_FORMATS = {
    "csv",
    "fa",
    "faa",
    "fasta",
    "json",
    "jsonl",
    "log",
    "markdown",
    "md",
    "pdb",
    "pdbqt",
    "python",
    "py",
    "text",
    "txt",
    "yaml",
}

SAFE_TEXT_FILENAME_PATTERN = re.compile(r"^[A-Za-z0-9._-]+$")


def _new_artifact_id() -> str:
    return f"art_{uuid4().hex[:12]}"


def _artifact_text_root() -> Path:
    root = Path("/tmp/openzyme-session-artifacts")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _sha256_digest(content: str) -> str:
    return f"sha256:{hashlib.sha256(content.encode('utf-8')).hexdigest()}"


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


def _clamped_offset(arguments: dict[str, Any]) -> int:
    return max(0, int(arguments.get("offset", 0)))


def _output_ref_from_artifact(artifact: Any) -> str | None:
    metadata = dict(artifact.metadata or {})
    output_ref = metadata.get("output_ref")
    if output_ref is not None:
        return str(output_ref)
    prefix = "engine-document://"
    if artifact.storage_uri.startswith(prefix):
        return artifact.storage_uri[len(prefix) :]
    return None


def _artifact_error(
    invocation: ToolInvocation,
    *,
    content: str | dict[str, Any],
    error_code: str,
    hint: str | None = None,
) -> ToolResult:
    return ToolResult(
        call_id=invocation.call_id,
        tool_name=invocation.tool_name,
        ok=False,
        content=json.dumps(content, sort_keys=True) if isinstance(content, dict) else content,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        status=error_code,
        error_code=error_code,
        hint=hint,
    )


def _validate_pipeline_source_filename(filename: str) -> str | None:
    candidate = Path(filename).name
    if candidate != filename or not SAFE_TEXT_FILENAME_PATTERN.fullmatch(candidate):
        return None
    if Path(candidate).suffix.lower() != ".py":
        return None
    return candidate


def _validate_text_content(content: Any) -> tuple[str | None, dict[str, Any] | None]:
    if not isinstance(content, str):
        return None, {
            "error": "content must be a UTF-8 string",
            "error_code": "invalid_text_content",
            "hint": "Pass the complete patched source text as a JSON string.",
        }
    try:
        encoded = content.encode("utf-8")
    except UnicodeEncodeError:
        return None, {
            "error": "content is not valid UTF-8 text",
            "error_code": "artifact_not_utf8",
            "hint": "Use valid UTF-8 source text.",
        }
    if len(encoded) > MAX_CREATE_TEXT_BYTES:
        return None, {
            "error": "text artifact content exceeds the write limit",
            "error_code": "artifact_content_too_large",
            "size_bytes": len(encoded),
            "max_size_bytes": MAX_CREATE_TEXT_BYTES,
            "hint": "Create a smaller source artifact or split generated data into result artifacts.",
        }
    return content, None


def _is_pipeline_source_artifact(artifact: Any) -> bool:
    metadata = dict(artifact.metadata or {})
    return (
        artifact.kind is ArtifactKind.CODE
        and _artifact_format(artifact) == "python"
        and metadata.get("semantic_type") == "pipeline_source"
    )


def _pipeline_source_error(invocation: ToolInvocation, artifact: Any) -> ToolResult:
    return _artifact_error(
        invocation,
        content={
            "artifact": project_artifact_for_agent(artifact),
            "error": "artifact is not a Python pipeline source artifact",
            "error_code": "artifact_not_pipeline_source",
            "required": {
                "kind": ArtifactKind.CODE.value,
                "format": "python",
                "metadata.semantic_type": "pipeline_source",
            },
        },
        error_code="artifact_not_pipeline_source",
        hint="Create pipeline source with artifact.create_text before patching or diffing it.",
    )


def _text_artifact_path(
    session_id: str,
    lineage_root: str,
    version: int,
    artifact_id: str,
    filename: str,
) -> tuple[Path, str]:
    relative_path = f"code/{lineage_root}/v{version}/{artifact_id}/{filename}"
    storage_path = _artifact_text_root() / session_id / relative_path
    storage_path.parent.mkdir(parents=True, exist_ok=True)
    return storage_path, relative_path


def _record_artifact_event(context: SessionRuntimeContext, artifact: SessionArtifactRecord) -> None:
    metadata = dict(artifact.metadata or {})
    context.emit(
        "artifact.recorded",
        {
            "artifact_id": artifact.artifact_id,
            "task_id": artifact.task_id,
            "lane_id": artifact.lane_id,
            "kind": artifact.kind.value,
            "format": metadata.get("format"),
            "semantic_type": metadata.get("semantic_type"),
            "version": metadata.get("version"),
            "parent_artifact_id": metadata.get("parent_artifact_id"),
            "lineage_root_artifact_id": metadata.get("lineage_root_artifact_id"),
        },
    )


def _create_pipeline_source_artifact(
    context: SessionRuntimeContext,
    invocation: ToolInvocation,
    *,
    filename: str,
    content: str,
    title: str | None = None,
    description: str | None = None,
    parent_artifact_id: str | None = None,
    lineage_root_artifact_id: str | None = None,
    version: int = 1,
    extra_metadata: dict[str, Any] | None = None,
) -> SessionArtifactRecord:
    artifact_id = _new_artifact_id()
    root_artifact_id = lineage_root_artifact_id or artifact_id
    digest = _sha256_digest(content)
    storage_path, relative_path = _text_artifact_path(
        context.snapshot.session.session_id,
        root_artifact_id,
        version,
        artifact_id,
        filename,
    )
    storage_path.write_text(content, encoding="utf-8")
    metadata = {
        **({} if extra_metadata is None else dict(extra_metadata)),
        "semantic_type": "pipeline_source",
        "format": "python",
        "content_digest": digest,
        "lineage_root_artifact_id": root_artifact_id,
        "version": version,
        "produced_by": invocation.tool_name,
    }
    if parent_artifact_id is not None:
        metadata["parent_artifact_id"] = parent_artifact_id
    artifact = SessionArtifactRecord(
        artifact_id=artifact_id,
        session_id=context.snapshot.session.session_id,
        task_id=invocation.task_id,
        lane_id=invocation.lane_id,
        invocation_id=None,
        run_id=None,
        kind=ArtifactKind.CODE,
        storage_uri=str(storage_path),
        relative_path=relative_path,
        title=title or filename,
        description=description,
        metadata=metadata,
        created_at=utc_now_iso(),
    )
    context.repositories.artifacts.save(artifact)
    _record_artifact_event(context, artifact)
    return artifact


def _source_artifact_payload(artifact: SessionArtifactRecord) -> dict[str, Any]:
    metadata = dict(artifact.metadata or {})
    return {
        "artifact": project_artifact_for_agent(artifact),
        "content_digest": metadata.get("content_digest"),
        "lineage_root_artifact_id": metadata.get("lineage_root_artifact_id"),
        "parent_artifact_id": metadata.get("parent_artifact_id"),
        "version": metadata.get("version"),
        "read_hint": f'artifact.read_text with artifact_id="{artifact.artifact_id}", offset=0',
        "diff_hint": f'artifact.diff_text with target_artifact_id="{artifact.artifact_id}"',
    }


def _get_required_argument(invocation: ToolInvocation, key: str) -> tuple[Any | None, ToolResult | None]:
    if key in invocation.arguments:
        return invocation.arguments[key], None
    return None, _artifact_error(
        invocation,
        content={
            "error": f"missing required argument {key!r}",
            "error_code": "missing_required_argument",
            "argument": key,
        },
        error_code="missing_required_argument",
        hint=f"Pass {key} when calling {invocation.tool_name}.",
    )


def _load_scoped_artifact(context: SessionRuntimeContext, invocation: ToolInvocation) -> tuple[Any | None, ToolResult | None]:
    artifact_id = str(invocation.arguments["artifact_id"])
    artifact = context.repositories.artifacts.get(artifact_id)
    session_id = context.snapshot.session.session_id
    if artifact is None or artifact.session_id != session_id:
        return None, _artifact_error(
            invocation,
            content=f"artifact {artifact_id!r} does not exist in the current session",
            error_code="artifact_not_found",
            hint="Use artifact.list to inspect artifact ids available in this session.",
        )
    return artifact, None


def _artifact_resource(context: SessionRuntimeContext, artifact: Any) -> dict[str, Any]:
    payload: dict[str, Any] = {"artifact": project_artifact_for_agent(artifact)}
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
            payload["output_payload"] = sanitize_private_artifact_fields(output_document.payload)
    if artifact.invocation_id is not None:
        payload["documents"] = [
            sanitize_private_artifact_fields(document.to_dict())
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
    output_document = root.get("output_document")
    document_kind = (
        output_document.get("document_kind")
        if isinstance(output_document, dict)
        else None
    )
    if isinstance(output_payload, dict) and document_kind == "tool_result_full":
        tool_result = output_payload.get("tool_result")
        payload["output_payload"] = {
            "status": output_payload.get("status"),
            "reason": output_payload.get("reason"),
            "token_estimate": output_payload.get("token_estimate"),
            "tool_name": output_payload.get("tool_name"),
            "call_id": output_payload.get("call_id"),
            "original_tool_ok": output_payload.get("original_tool_ok"),
            "original_status": output_payload.get("original_status"),
            "tool_result_status": (
                tool_result.get("status") if isinstance(tool_result, dict) else None
            ),
            "tool_result_summary": (
                _preview(tool_result.get("summary"))
                if isinstance(tool_result, dict)
                else None
            ),
        }
        payload["omitted_fields"].append(
            _omitted_field("output_payload.tool_result", tool_result)
        )
        return payload
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
        "value": sanitize_private_artifact_fields(value),
    }


def _clamped_text_limit(arguments: dict[str, Any]) -> int:
    limit = int(arguments.get("limit", DEFAULT_TEXT_LIMIT))
    return max(0, min(MAX_TEXT_LIMIT, limit))


def _artifact_format(artifact: Any) -> str | None:
    metadata = dict(artifact.metadata or {})
    value = metadata.get("format") or metadata.get("output_format")
    return None if value is None else str(value).lower()


def _artifact_suffix(artifact: Any) -> str:
    relative = str(artifact.relative_path or "")
    if relative:
        return Path(relative).suffix.lower()
    storage_uri = str(getattr(artifact, "storage_uri", "") or "")
    if "://" in storage_uri:
        return ""
    return Path(storage_uri).suffix.lower()


def _looks_binary_by_metadata(artifact: Any) -> bool:
    fmt = _artifact_format(artifact)
    if fmt is not None and fmt in TEXT_FORMATS:
        return False
    suffix = _artifact_suffix(artifact)
    return suffix in BINARY_EXTENSIONS


def _looks_text_by_metadata(artifact: Any) -> bool:
    if artifact.kind in {ArtifactKind.LOG, ArtifactKind.RESEARCH_DOSSIER, ArtifactKind.STRUCTURE, ArtifactKind.RESULT}:
        return True
    fmt = _artifact_format(artifact)
    if fmt is not None and fmt in TEXT_FORMATS:
        return True
    return _artifact_suffix(artifact) in TEXT_EXTENSIONS


def _storage_path(artifact: Any) -> Path | None:
    storage_uri = str(getattr(artifact, "storage_uri", "") or "")
    if not storage_uri:
        return None
    if "://" in storage_uri:
        return None
    return Path(storage_uri)


def _read_text_artifact(artifact: Any) -> tuple[str | None, dict[str, Any]]:
    if _looks_binary_by_metadata(artifact):
        return None, {
            "error": "artifact is not a text artifact",
            "error_code": "artifact_not_text",
            "hint": "Use artifact.get for catalog metadata, or a dedicated parser for binary artifacts.",
        }
    path = _storage_path(artifact)
    if path is None:
        return None, {
            "error": "artifact content is not stored as a readable Host file",
            "error_code": "artifact_content_unavailable",
            "hint": "Use artifact.get to inspect catalog metadata and linked engine output fields.",
        }
    if not path.is_file():
        return None, {
            "error": "artifact content file is missing",
            "error_code": "artifact_content_missing",
            "hint": "The catalog record exists, but the Host-private storage target is not readable.",
        }
    size_bytes = path.stat().st_size
    read_size = min(size_bytes, MAX_TEXT_FILE_BYTES)
    with path.open("rb") as handle:
        data = handle.read(read_size)
    if b"\x00" in data[:4096]:
        return None, {
            "error": "artifact appears to be binary",
            "error_code": "artifact_not_text",
            "size_bytes": size_bytes,
            "hint": "Use artifact.get for metadata; binary artifacts need a specialized reader.",
        }
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return None, {
            "error": "artifact is not valid UTF-8 text",
            "error_code": "artifact_not_text",
            "size_bytes": size_bytes,
            "hint": "Only UTF-8 text artifacts can be read by artifact.preview/read_text/range.",
        }
    return text, {
        "size_bytes": size_bytes,
        "bytes_read": read_size,
        "file_truncated": read_size < size_bytes,
        "text_hint_from_metadata": _looks_text_by_metadata(artifact),
    }


def _text_error_result(invocation: ToolInvocation, artifact: Any, meta: dict[str, Any]) -> ToolResult:
    payload = {
        "artifact": project_artifact_for_agent(artifact),
        **meta,
    }
    return _artifact_error(
        invocation,
        content=payload,
        error_code=str(meta.get("error_code") or "artifact_read_failed"),
        hint=None if meta.get("hint") is None else str(meta["hint"]),
    )


def register_artifact_tools(registry: ToolRegistry) -> None:
    def create_text_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        filename_raw, error = _get_required_argument(invocation, "filename")
        if error is not None:
            return error
        content_raw, error = _get_required_argument(invocation, "content")
        if error is not None:
            return error
        filename = _validate_pipeline_source_filename(str(filename_raw))
        if filename is None:
            return _artifact_error(
                invocation,
                content={
                    "error": "filename must be a safe Python filename ending in .py",
                    "error_code": "invalid_pipeline_source_filename",
                    "filename": str(filename_raw),
                },
                error_code="invalid_pipeline_source_filename",
                hint="Use a basename such as aox_hmm_pipeline.py; do not pass directories or Host paths.",
            )
        content, content_error = _validate_text_content(content_raw)
        if content_error is not None:
            return _artifact_error(
                invocation,
                content=content_error,
                error_code=str(content_error["error_code"]),
                hint=str(content_error.get("hint") or ""),
            )
        assert content is not None
        artifact = _create_pipeline_source_artifact(
            context,
            invocation,
            filename=filename,
            content=content,
            title=None if invocation.arguments.get("title") is None else str(invocation.arguments["title"]),
            description=None
            if invocation.arguments.get("description") is None
            else str(invocation.arguments["description"]),
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(_source_artifact_payload(artifact), sort_keys=True),
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
            status="artifact_created",
            summary=f"Created pipeline source artifact {artifact.artifact_id}.",
        )

    def patch_text_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        base_artifact_id_raw, error = _get_required_argument(invocation, "base_artifact_id")
        if error is not None:
            return error
        base_digest_raw, error = _get_required_argument(invocation, "base_content_digest")
        if error is not None:
            return error
        content_raw, error = _get_required_argument(invocation, "content")
        if error is not None:
            return error
        base_artifact_id = str(base_artifact_id_raw)
        artifact = context.repositories.artifacts.get(base_artifact_id)
        session_id = context.snapshot.session.session_id
        if artifact is None or artifact.session_id != session_id:
            return _artifact_error(
                invocation,
                content=f"artifact {base_artifact_id!r} does not exist in the current session",
                error_code="artifact_not_found",
                hint="Use artifact.list to inspect artifact ids available in this session.",
            )
        if not _is_pipeline_source_artifact(artifact):
            return _pipeline_source_error(invocation, artifact)
        metadata = dict(artifact.metadata or {})
        current_digest = metadata.get("content_digest")
        if current_digest is None:
            return _artifact_error(
                invocation,
                content={
                    "artifact": project_artifact_for_agent(artifact),
                    "error": "source artifact is missing metadata.content_digest",
                    "error_code": "artifact_digest_missing",
                },
                error_code="artifact_digest_missing",
                hint="Create a fresh pipeline source artifact with artifact.create_text.",
            )
        if str(base_digest_raw) != str(current_digest):
            return _artifact_error(
                invocation,
                content={
                    "artifact": project_artifact_for_agent(artifact),
                    "error": "base_content_digest does not match the current artifact digest",
                    "error_code": "stale_artifact_digest",
                    "expected_content_digest": current_digest,
                    "provided_content_digest": str(base_digest_raw),
                },
                error_code="stale_artifact_digest",
                hint="Read the current artifact metadata and retry the patch with the latest content_digest.",
            )
        base_text, read_meta = _read_text_artifact(artifact)
        if base_text is None:
            return _text_error_result(invocation, artifact, read_meta)
        actual_digest = _sha256_digest(base_text)
        if actual_digest != str(current_digest):
            return _artifact_error(
                invocation,
                content={
                    "artifact": project_artifact_for_agent(artifact),
                    "error": "catalog digest does not match stored artifact content",
                    "error_code": "artifact_digest_mismatch",
                    "metadata_content_digest": current_digest,
                    "actual_content_digest": actual_digest,
                },
                error_code="artifact_digest_mismatch",
                hint="The catalog record and stored content disagree; do not create a derived version.",
            )
        content, content_error = _validate_text_content(content_raw)
        if content_error is not None:
            return _artifact_error(
                invocation,
                content=content_error,
                error_code=str(content_error["error_code"]),
                hint=str(content_error.get("hint") or ""),
            )
        assert content is not None
        filename_arg = invocation.arguments.get("filename")
        default_filename = Path(str(artifact.relative_path)).name
        filename = _validate_pipeline_source_filename(str(filename_arg or default_filename))
        if filename is None:
            return _artifact_error(
                invocation,
                content={
                    "error": "filename must be a safe Python filename ending in .py",
                    "error_code": "invalid_pipeline_source_filename",
                    "filename": str(filename_arg or default_filename),
                },
                error_code="invalid_pipeline_source_filename",
                hint="Use a basename such as aox_hmm_pipeline.py; do not pass directories or Host paths.",
            )
        version = int(metadata.get("version") or 1) + 1
        lineage_root = str(metadata.get("lineage_root_artifact_id") or artifact.artifact_id)
        extra_metadata = {
            key: value
            for key, value in metadata.items()
            if key
            not in {
                "content_digest",
                "parent_artifact_id",
                "lineage_root_artifact_id",
                "version",
                "produced_by",
            }
        }
        new_artifact = _create_pipeline_source_artifact(
            context,
            invocation,
            filename=filename,
            content=content,
            title=None if invocation.arguments.get("title") is None else str(invocation.arguments["title"]),
            description=artifact.description
            if invocation.arguments.get("description") is None
            else str(invocation.arguments["description"]),
            parent_artifact_id=artifact.artifact_id,
            lineage_root_artifact_id=lineage_root,
            version=version,
            extra_metadata=extra_metadata,
        )
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(
                {
                    **_source_artifact_payload(new_artifact),
                    "base_artifact": project_artifact_for_agent(artifact),
                    "base_content_digest": current_digest,
                    "base_version": metadata.get("version"),
                },
                sort_keys=True,
            ),
            task_id=new_artifact.task_id,
            lane_id=new_artifact.lane_id,
            status="artifact_version_created",
            summary=(
                f"Created pipeline source artifact {new_artifact.artifact_id} "
                f"as version {version} from {artifact.artifact_id}."
            ),
        )

    def diff_text_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        base_artifact_id_raw, error = _get_required_argument(invocation, "base_artifact_id")
        if error is not None:
            return error
        target_artifact_id_raw, error = _get_required_argument(invocation, "target_artifact_id")
        if error is not None:
            return error
        base_artifact = context.repositories.artifacts.get(str(base_artifact_id_raw))
        target_artifact = context.repositories.artifacts.get(str(target_artifact_id_raw))
        session_id = context.snapshot.session.session_id
        if base_artifact is None or base_artifact.session_id != session_id:
            return _artifact_error(
                invocation,
                content=f"artifact {str(base_artifact_id_raw)!r} does not exist in the current session",
                error_code="artifact_not_found",
                hint="Use artifact.list to inspect artifact ids available in this session.",
            )
        if target_artifact is None or target_artifact.session_id != session_id:
            return _artifact_error(
                invocation,
                content=f"artifact {str(target_artifact_id_raw)!r} does not exist in the current session",
                error_code="artifact_not_found",
                hint="Use artifact.list to inspect artifact ids available in this session.",
            )
        if not _is_pipeline_source_artifact(base_artifact):
            return _pipeline_source_error(invocation, base_artifact)
        if not _is_pipeline_source_artifact(target_artifact):
            return _pipeline_source_error(invocation, target_artifact)
        base_text, base_meta = _read_text_artifact(base_artifact)
        if base_text is None:
            return _text_error_result(invocation, base_artifact, base_meta)
        target_text, target_meta = _read_text_artifact(target_artifact)
        if target_text is None:
            return _text_error_result(invocation, target_artifact, target_meta)
        context_lines = max(0, min(20, int(invocation.arguments.get("context_lines", 3))))
        diff_lines = list(
            difflib.unified_diff(
                base_text.splitlines(),
                target_text.splitlines(),
                fromfile=f"{base_artifact.artifact_id}:{Path(str(base_artifact.relative_path)).name}",
                tofile=f"{target_artifact.artifact_id}:{Path(str(target_artifact.relative_path)).name}",
                lineterm="",
                n=context_lines,
            )
        )
        diff_text = "\n".join(diff_lines)
        truncated = len(diff_text) > MAX_DIFF_CHARS
        if truncated:
            diff_text = diff_text[:MAX_DIFF_CHARS]
        payload = {
            "base_artifact": project_artifact_for_agent(base_artifact),
            "target_artifact": project_artifact_for_agent(target_artifact),
            "base_content_digest": dict(base_artifact.metadata or {}).get("content_digest"),
            "target_content_digest": dict(target_artifact.metadata or {}).get("content_digest"),
            "context_lines": context_lines,
            "diff": diff_text,
            "diff_line_count": len(diff_lines),
            "truncated": truncated,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=target_artifact.task_id,
            lane_id=target_artifact.lane_id,
            status="ok",
            summary=f"Diffed {base_artifact.artifact_id} against {target_artifact.artifact_id}.",
        )

    def list_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        session_id = context.snapshot.session.session_id
        task_id = invocation.arguments.get("task_id")
        invocation_id = invocation.arguments.get("invocation_id")
        kind_raw = invocation.arguments.get("kind")
        if task_id is not None:
            artifacts = context.repositories.artifacts.list_by_task(session_id, str(task_id))
        elif invocation_id is not None:
            artifacts = context.repositories.artifacts.list_by_invocation(session_id, str(invocation_id))
        else:
            artifacts = context.repositories.artifacts.list_by_session(session_id)
        if kind_raw is not None:
            try:
                kind = ArtifactKind(str(kind_raw))
            except ValueError:
                return _artifact_error(
                    invocation,
                    content={
                        "error": f"unknown artifact kind {kind_raw!r}",
                        "error_code": "invalid_artifact_kind",
                        "valid_kinds": [item.value for item in ArtifactKind],
                    },
                    error_code="invalid_artifact_kind",
                    hint="Use one of the ArtifactKind values exposed in the artifact catalog.",
                )
            artifacts = [artifact for artifact in artifacts if artifact.kind is kind]
        offset = _clamped_offset(invocation.arguments)
        limit = _clamped_limit(invocation.arguments)
        page = artifacts[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(artifacts) else None
        payload = {
            "artifacts": project_artifacts_for_agent(page),
            "total_count": len(artifacts),
            "offset": offset,
            "limit": limit,
            "next_offset": next_offset,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=invocation.task_id,
            lane_id=invocation.lane_id,
        )

    def get_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        artifact, error = _load_scoped_artifact(context, invocation)
        if error is not None:
            return error
        assert artifact is not None
        root = _artifact_resource(context, artifact)
        path = invocation.arguments.get("path")
        if path is None:
            payload = _default_payload(root)
            ok = True
        else:
            offset = _clamped_offset(invocation.arguments)
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

    def preview_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        artifact, error = _load_scoped_artifact(context, invocation)
        if error is not None:
            return error
        assert artifact is not None
        text, meta = _read_text_artifact(artifact)
        if text is None:
            return _text_error_result(invocation, artifact, meta)
        max_lines = max(1, min(MAX_PREVIEW_LINES, int(invocation.arguments.get("lines", DEFAULT_PREVIEW_LINES))))
        limit = _clamped_text_limit(invocation.arguments)
        lines = text.splitlines()
        preview_lines = lines[:max_lines]
        preview = "\n".join(preview_lines)
        truncated_by_lines = len(lines) > len(preview_lines)
        if len(preview) > limit:
            preview = preview[:limit]
            truncated_by_chars = True
        else:
            truncated_by_chars = False
        payload = {
            "artifact": project_artifact_for_agent(artifact),
            "size_bytes": meta["size_bytes"],
            "is_text": True,
            "line_count": len(lines),
            "returned_lines": len(preview_lines),
            "preview": preview,
            "truncated": bool(truncated_by_lines or truncated_by_chars or meta["file_truncated"]),
            "next_offset": len(preview) if len(preview) < len(text) else None,
            "range_hint": "artifact.range with start_line=1",
            "read_hint": "artifact.read_text with offset=0",
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
        )

    def read_text_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        artifact, error = _load_scoped_artifact(context, invocation)
        if error is not None:
            return error
        assert artifact is not None
        text, meta = _read_text_artifact(artifact)
        if text is None:
            return _text_error_result(invocation, artifact, meta)
        offset = max(0, int(invocation.arguments.get("offset", 0)))
        limit = _clamped_text_limit(invocation.arguments)
        page = text[offset : offset + limit]
        next_offset = offset + len(page) if offset + len(page) < len(text) or meta["file_truncated"] else None
        payload = {
            "artifact": project_artifact_for_agent(artifact),
            "size_bytes": meta["size_bytes"],
            "offset": offset,
            "limit": limit,
            "content": page,
            "returned_chars": len(page),
            "next_offset": next_offset,
            "truncated": next_offset is not None,
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
        )

    def range_handler(context: SessionRuntimeContext, invocation: ToolInvocation) -> ToolResult:
        artifact, error = _load_scoped_artifact(context, invocation)
        if error is not None:
            return error
        assert artifact is not None
        text, meta = _read_text_artifact(artifact)
        if text is None:
            return _text_error_result(invocation, artifact, meta)
        start_line = max(1, int(invocation.arguments.get("start_line", 1)))
        end_line_arg = invocation.arguments.get("end_line")
        end_line = start_line + DEFAULT_PAGE_LIMIT - 1 if end_line_arg is None else int(end_line_arg)
        end_line = max(start_line, min(end_line, start_line + MAX_RANGE_LINES - 1))
        lines = text.splitlines()
        selected = lines[start_line - 1 : end_line]
        payload = {
            "artifact": project_artifact_for_agent(artifact),
            "size_bytes": meta["size_bytes"],
            "start_line": start_line,
            "end_line": start_line + len(selected) - 1 if selected else start_line - 1,
            "requested_end_line": end_line,
            "line_count": len(lines),
            "content": "\n".join(selected),
            "lines": selected,
            "returned_line_count": len(selected),
            "next_start_line": start_line + len(selected) if start_line + len(selected) <= len(lines) else None,
            "truncated": bool(end_line < len(lines) or meta["file_truncated"]),
        }
        return ToolResult(
            call_id=invocation.call_id,
            tool_name=invocation.tool_name,
            ok=True,
            content=json.dumps(payload, sort_keys=True),
            task_id=artifact.task_id,
            lane_id=artifact.lane_id,
        )

    registry.register("artifact.create_text", create_text_handler)
    registry.register("artifact.patch_text", patch_text_handler)
    registry.register("artifact.diff_text", diff_text_handler)
    registry.register("artifact.list", list_handler)
    registry.register("artifact.get", get_handler)
    registry.register("artifact.preview", preview_handler)
    registry.register("artifact.read_text", read_text_handler)
    registry.register("artifact.range", range_handler)


__all__ = ["register_artifact_tools"]
