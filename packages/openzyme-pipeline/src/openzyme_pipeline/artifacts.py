from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import stat
from typing import Any
from uuid import uuid4

from .client import PipelineSdkError, call


WORKSPACE_INPUT_ROOT = Path("/workspace/input")
WORKSPACE_OUTPUT_ROOT = Path("/workspace/output")
COMPAT_INPUT_ROOT = Path("/openzyme/input")
COMPAT_OUTPUT_ROOT = Path("/openzyme/output")
ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES = 256 * 1024
ARTIFACT_REGISTRATION_METADATA_SIDECAR_MAX_BYTES = 32 * 1024 * 1024
ARTIFACT_REGISTRATION_METADATA_SIDECAR_SCHEMA_ID = (
    "artifact_registration_metadata_sidecar@1"
)
ARTIFACT_REGISTRATION_RESPONSE_SCHEMA_ID = "artifact_registration_response@2"
ARTIFACT_REGISTRATION_METADATA_SUMMARY_SCHEMA_ID = (
    "artifact_registration_metadata_summary@1"
)
ARTIFACT_REGISTRATION_VALIDATION_SUMMARY_SCHEMA_ID = (
    "artifact_registration_validation_summary@1"
)
ARTIFACT_REGISTRATION_ARTIFACT_ID_MAX_BYTES = 256
ARTIFACT_REGISTER_MANY_MAX_ITEMS = 128
ARTIFACT_REGISTRATION_HOST_OWNED_DIGEST_FIELDS = frozenset(
    {"content_digest", "sealed_digest", "tree_digest"}
)
ARTIFACT_REGISTRATION_METADATA_WORK_ROOT = Path(
    os.environ.get("OPENZYME_SANDBOX_WORK_ROOT", "/workspace/work")
)
ARTIFACT_REGISTRATION_METADATA_SIDECAR_ROOT = (
    ARTIFACT_REGISTRATION_METADATA_WORK_ROOT
    / ".openzyme"
    / "artifact-metadata"
)
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")
# Keep these wire values identical to ``openzyme_domain.models.ArtifactKind``.
# The sandbox SDK deliberately remains dependency-free, so importing the domain
# package here would violate its execution boundary.
_ARTIFACT_KIND_VALUES = (
    "code",
    "log",
    "sequence",
    "structure",
    "report",
    "research_dossier",
    "result",
    "cache",
    "other",
)
_ARTIFACT_KIND_ALLOWLIST = frozenset(_ARTIFACT_KIND_VALUES)


def get(artifact_id: str) -> dict[str, Any]:
    return dict(call("artifacts.get", {"artifact_id": artifact_id}))


def registered_artifact_ref(response: dict[str, Any]) -> dict[str, str]:
    """Select the canonical ref from a direct ``artifacts.register`` response.

    The Host response intentionally carries both a public artifact projection and
    registration metadata.  Callers must not recursively search that envelope,
    because the same artifact can appear in more than one provenance projection.
    ``provider_file_ref`` and ``fetched_output_ref`` already return terminal
    canonical artifact-catalog refs; do not chain them through this selector.
    A catalog ref is not an ``hpc_stage_ref``: before passing its artifact to
    ``bio_tools.*``, call ``ws.stage_artifact(ref["artifact_id"], ...)`` and pass
    that exact return value unchanged.
    """

    if response.get("schema_id") != ARTIFACT_REGISTRATION_RESPONSE_SCHEMA_ID:
        if set(response) == {"artifact_id", "content_digest"} and isinstance(
            response.get("artifact_id"), str
        ) and isinstance(response.get("content_digest"), str):
            raise _projection_error(
                "artifact selector output is already a canonical artifact ref; "
                "use it directly instead of passing it to registered_artifact_ref",
                error_code="artifact_ref_already_canonical",
                hint=(
                    "provider_file_ref and fetched_output_ref return terminal "
                    "artifact-catalog refs, while registered_artifact_ref accepts only "
                    "the direct response returned by artifacts.register. A catalog ref "
                    "is not an hpc_stage_ref; call ws.stage_artifact(ref['artifact_id'], "
                    "...) before passing the exact returned stage ref to bio_tools.*."
                ),
            )
        raise _projection_error(
            "artifact registration response schema is invalid; pass only the current "
            "direct response returned by artifacts.register",
            error_code="artifact_registration_projection_invalid",
        )
    expected_keys = {
        "schema_id",
        "artifact",
        "content_digest",
        "tree_digest",
        "validation",
        "reused",
    }
    if set(response) != expected_keys or not isinstance(response.get("reused"), bool):
        raise _projection_error(
            "artifact registration response does not match its closed schema",
            error_code="artifact_registration_projection_invalid",
        )
    artifact = response.get("artifact")
    if not isinstance(artifact, dict) or set(artifact) != {"artifact_id", "metadata"}:
        raise _projection_error(
            "artifact registration response artifact does not match its closed schema",
            error_code="artifact_registration_projection_invalid",
        )
    artifact_id = _required_text(artifact.get("artifact_id"), label="artifact_id")
    if len(artifact_id.encode("utf-8")) > ARTIFACT_REGISTRATION_ARTIFACT_ID_MAX_BYTES:
        raise _projection_error(
            "artifact registration response artifact_id exceeds its bounded limit",
            error_code="artifact_registration_projection_invalid",
        )
    content_digest = _required_digest(
        response.get("content_digest"),
        label="artifact registration content_digest",
    )
    metadata = artifact.get("metadata")
    if (
        not isinstance(metadata, dict)
        or metadata.get("schema_id")
        != ARTIFACT_REGISTRATION_METADATA_SUMMARY_SCHEMA_ID
        or metadata.get("projection") != "bounded_registration_summary"
    ):
        raise _projection_error(
            "artifact registration metadata summary is invalid",
            error_code="artifact_registration_projection_invalid",
        )
    expected_metadata_keys = {
        "schema_id",
        "projection",
        "metadata_digest",
        "metadata_size_bytes",
        "metadata_field_count",
        "content_digest",
        "sealed_digest",
        "tree_digest",
    }
    if (
        set(metadata) != expected_metadata_keys
        or not isinstance(metadata.get("metadata_size_bytes"), int)
        or isinstance(metadata.get("metadata_size_bytes"), bool)
        or int(metadata["metadata_size_bytes"]) < 0
        or not isinstance(metadata.get("metadata_field_count"), int)
        or isinstance(metadata.get("metadata_field_count"), bool)
        or int(metadata["metadata_field_count"]) < 0
    ):
        raise _projection_error(
            "artifact registration metadata summary does not match its closed schema",
            error_code="artifact_registration_projection_invalid",
        )
    _required_digest(
        metadata.get("metadata_digest"),
        label="artifact registration metadata_digest",
    )
    if (
        response.get("tree_digest") is not None
        or metadata.get("tree_digest") is not None
    ):
        raise _projection_error(
            "file artifact registration response must not carry a tree digest",
            error_code="artifact_registration_projection_invalid",
        )
    if (
        metadata.get("content_digest") != content_digest
        or metadata.get("sealed_digest") != content_digest
    ):
        raise _projection_error(
            "artifact registration response has inconsistent content digests",
            error_code="artifact_registration_projection_invalid",
        )
    validation = response.get("validation")
    if (
        not isinstance(validation, dict)
        or validation.get("schema_id")
        != ARTIFACT_REGISTRATION_VALIDATION_SUMMARY_SCHEMA_ID
        or validation.get("projection") != "bounded_registration_summary"
    ):
        raise _projection_error(
            "artifact registration validation summary is invalid",
            error_code="artifact_registration_projection_invalid",
        )
    expected_validation_keys = {
        "schema_id",
        "projection",
        "status",
        "format",
        "validation_profile",
        "empty_result_reason",
        "derivation_contract_id",
        "required_columns_count",
        "required_columns_digest",
        "validation_digest",
        "validation_size_bytes",
    }
    if "required_columns" in validation:
        expected_validation_keys.add("required_columns")
    if (
        set(validation) != expected_validation_keys
        or not isinstance(validation.get("required_columns_count"), int)
        or isinstance(validation.get("required_columns_count"), bool)
        or int(validation["required_columns_count"]) < 0
        or not isinstance(validation.get("validation_size_bytes"), int)
        or isinstance(validation.get("validation_size_bytes"), bool)
        or int(validation["validation_size_bytes"]) < 0
    ):
        raise _projection_error(
            "artifact registration validation summary does not match its closed schema",
            error_code="artifact_registration_projection_invalid",
        )
    _required_digest(
        validation.get("required_columns_digest"),
        label="artifact registration required_columns_digest",
    )
    _required_digest(
        validation.get("validation_digest"),
        label="artifact registration validation_digest",
    )
    return {
        "artifact_id": artifact_id,
        "content_digest": content_digest,
    }


def provider_file_ref(
    operation_response: dict[str, Any],
    *,
    relative_path_suffix: str,
) -> dict[str, str]:
    """Return one terminal canonical ref from a provider transcript manifest.

    The returned ``artifact_id``/``content_digest`` pair is a terminal canonical
    artifact-catalog ref.  Pass it directly only to a consumer that explicitly
    accepts that pair.  Before using its artifact with ``bio_tools.*``, call
    ``ws.stage_artifact(ref["artifact_id"], ...)`` and pass the exact returned
    ``hpc_stage_ref`` unchanged.  Do not pass it through another selector.
    """

    if not relative_path_suffix.startswith("/"):
        raise PipelineSdkError(
            "relative_path_suffix must start with '/'",
            error_code="artifact_selector_argument_invalid",
            stage="artifacts.response_selection",
            retryable=False,
        )
    result_summary = operation_response.get("result_summary")
    if not isinstance(result_summary, dict):
        raise _projection_error(
            "provider operation response has no result_summary object",
            error_code="provider_file_projection_invalid",
        )
    transcript_manifest = result_summary.get("transcript_manifest")
    if not isinstance(transcript_manifest, dict):
        raise _projection_error(
            "provider result_summary has no transcript_manifest object",
            error_code="provider_file_projection_invalid",
        )
    files = transcript_manifest.get("files")
    if not isinstance(files, list):
        raise _projection_error(
            "provider transcript_manifest.files is not a list",
            error_code="provider_file_projection_invalid",
        )
    matches = [
        item
        for item in files
        if isinstance(item, dict)
        and isinstance(item.get("relative_path"), str)
        and str(item["relative_path"]).endswith(relative_path_suffix)
    ]
    if len(matches) != 1:
        raise _projection_error(
            "provider transcript manifest requires exactly one file ending with "
            f"{relative_path_suffix!r}; found {len(matches)}",
            error_code="provider_file_projection_ambiguous",
            details={
                "relative_path_suffix": relative_path_suffix,
                "match_count": len(matches),
            },
        )
    match = matches[0]
    return {
        "artifact_id": _required_text(
            match.get("artifact_id"),
            label="provider file artifact_id",
        ),
        "content_digest": _required_digest(
            match.get("content_digest"),
            label="provider file content_digest",
        ),
    }


def fetched_output_ref(
    fetch_response: dict[str, Any],
    *,
    declared_output_path: str,
) -> dict[str, str]:
    """Return one terminal canonical ref from the direct ``fetch_refs`` list.

    The returned ``artifact_id``/``content_digest`` pair is a terminal canonical
    artifact-catalog ref, not an ``hpc_stage_ref``.  Pass it directly only to a
    consumer that explicitly accepts that pair.  Before using its artifact with
    ``bio_tools.*``, call ``ws.stage_artifact(ref["artifact_id"], ...)`` and pass
    the exact returned ``hpc_stage_ref`` unchanged.  Do not rename
    ``content_digest`` or hand-write a stage descriptor, and do not pass the ref
    through another selector.
    """

    expected_path = _required_text(
        declared_output_path,
        label="declared_output_path",
    )
    fetch_refs = fetch_response.get("fetch_refs")
    if not isinstance(fetch_refs, list):
        raise _projection_error(
            "HPC fetch response has no fetch_refs list",
            error_code="hpc_fetch_projection_invalid",
        )
    matches = [
        item
        for item in fetch_refs
        if isinstance(item, dict)
        and item.get("declared_output_path") == expected_path
    ]
    if len(matches) != 1:
        raise _projection_error(
            "HPC fetch response requires exactly one canonical fetch_ref for "
            f"{expected_path!r}; found {len(matches)}",
            error_code="hpc_fetch_projection_ambiguous",
            details={
                "declared_output_path": expected_path,
                "match_count": len(matches),
            },
        )
    match = matches[0]
    return {
        "artifact_id": _required_text(
            match.get("registered_artifact_id"),
            label="fetched output registered_artifact_id",
        ),
        "content_digest": _required_digest(
            match.get("output_digest"),
            label="fetched output output_digest",
        ),
    }


def materialize(
    artifact_id: str,
    target: str | None = None,
    *,
    target_path: str | None = None,
    mode: str = "copy",
) -> str:
    if target is not None and target_path is not None:
        raise ValueError("pass either target or target_path, not both")
    if target_path is not None:
        target = target_path
    payload = {"artifact_id": artifact_id, "target": target, "mode": mode}
    result = dict(call("artifacts.materialize", payload))
    return str(result["path"])


def _resolve_output_path(path: str) -> Path:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = WORKSPACE_OUTPUT_ROOT / resolved
    resolved = resolved.resolve()
    accepted_roots = (WORKSPACE_OUTPUT_ROOT.resolve(), COMPAT_OUTPUT_ROOT.resolve())
    if not any(root in (resolved, *resolved.parents) for root in accepted_roots):
        raise ValueError("artifacts.register only accepts files under /workspace/output")
    return resolved


def register(
    path: str,
    *,
    kind: str = "result",
    format: str | None = None,
    validation_profile: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    _validate_artifact_kind(kind)
    resolved = _resolve_output_path(path)
    metadata_transport = _metadata_transport(_metadata_object(metadata))
    return dict(
        call(
            "artifacts.register",
            {
                "path": str(resolved),
                "kind": kind,
                "format": format,
                "validation_profile": validation_profile,
                **metadata_transport,
            },
        )
    )


def register_many(
    paths: list[str],
    *,
    kind: str = "result",
    format: str | None = None,
    validation_profile: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> list[dict[str, Any]]:
    _validate_artifact_kind(kind)
    if len(paths) > ARTIFACT_REGISTER_MANY_MAX_ITEMS:
        raise PipelineSdkError(
            "artifacts.register_many exceeds its bounded item limit",
            error_code="artifact_register_many_too_many_items",
            stage="artifacts.request_serialization",
            retryable=False,
            details={
                "max_items": ARTIFACT_REGISTER_MANY_MAX_ITEMS,
                "item_count": len(paths),
            },
        )
    metadata_transport = _metadata_transport(_metadata_object(metadata))
    items: list[dict[str, Any]] = []
    for path in paths:
        resolved = _resolve_output_path(path)
        items.append(
            {
                "path": str(resolved),
                "kind": kind,
                "format": format,
                "validation_profile": validation_profile,
                **metadata_transport,
            }
        )
    return list(call("artifacts.register_many", {"items": items}))


def _metadata_object(metadata: object) -> dict[str, Any]:
    if metadata is None:
        return {}
    if not isinstance(metadata, dict):
        raise PipelineSdkError(
            "artifact registration metadata must be a JSON object",
            error_code="artifact_registration_metadata_invalid",
            stage="artifacts.request_serialization",
            retryable=False,
        )
    result = dict(metadata)
    reserved_fields = sorted(
        ARTIFACT_REGISTRATION_HOST_OWNED_DIGEST_FIELDS.intersection(result)
    )
    if reserved_fields:
        raise PipelineSdkError(
            "artifact registration metadata contains Host-owned digest fields",
            error_code="artifact_registration_metadata_reserved",
            stage="artifacts.request_validation",
            retryable=False,
            details={"reserved_fields": reserved_fields},
        )
    return result


def _metadata_transport(metadata: dict[str, Any]) -> dict[str, Any]:
    try:
        payload = json.dumps(
            metadata,
            ensure_ascii=True,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (RecursionError, TypeError, ValueError) as exc:
        raise PipelineSdkError(
            "artifact registration metadata is not canonical JSON",
            error_code="artifact_registration_metadata_invalid",
            stage="artifacts.request_serialization",
            retryable=False,
        ) from exc
    if len(payload) <= ARTIFACT_REGISTRATION_METADATA_INLINE_MAX_BYTES:
        return {"metadata": metadata}
    if len(payload) > ARTIFACT_REGISTRATION_METADATA_SIDECAR_MAX_BYTES:
        raise PipelineSdkError(
            "artifact registration metadata exceeds the bounded sidecar limit",
            error_code="artifact_registration_metadata_too_large",
            stage="artifacts.request_serialization",
            retryable=False,
            hint=(
                "Register oversized evidence as a separate artifact and keep only "
                "its canonical artifact reference in catalog metadata."
            ),
            details={
                "max_bytes": ARTIFACT_REGISTRATION_METADATA_SIDECAR_MAX_BYTES,
                "size_bytes": len(payload),
            },
        )
    digest = f"sha256:{hashlib.sha256(payload).hexdigest()}"
    _write_metadata_sidecar(payload, digest=digest)
    return {
        "metadata_sidecar": {
            "schema_id": ARTIFACT_REGISTRATION_METADATA_SIDECAR_SCHEMA_ID,
            "path": (
                "/workspace/work/.openzyme/artifact-metadata/"
                f"{digest.removeprefix('sha256:')}.json"
            ),
            "content_digest": digest,
            "size_bytes": len(payload),
        }
    }


def _write_metadata_sidecar(payload: bytes, *, digest: str) -> Path:
    work_root = ARTIFACT_REGISTRATION_METADATA_WORK_ROOT
    root = work_root / ".openzyme" / "artifact-metadata"
    target_name = f"{digest.removeprefix('sha256:')}.json"
    target = root / target_name
    directory_descriptors: list[int] = []
    temporary_name: str | None = None
    try:
        work_root.mkdir(mode=0o700, parents=True, exist_ok=True)
        directory_flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            directory_flags |= os.O_CLOEXEC
        if hasattr(os, "O_DIRECTORY"):
            directory_flags |= os.O_DIRECTORY
        if hasattr(os, "O_NOFOLLOW"):
            directory_flags |= os.O_NOFOLLOW
        work_fd = os.open(work_root, directory_flags)
        directory_descriptors.append(work_fd)
        os.fchmod(work_fd, 0o700)
        parent_fd = work_fd
        for name in (".openzyme", "artifact-metadata"):
            try:
                os.mkdir(name, mode=0o700, dir_fd=parent_fd)
            except FileExistsError:
                pass
            child_fd = os.open(name, directory_flags, dir_fd=parent_fd)
            directory_descriptors.append(child_fd)
            os.fchmod(child_fd, 0o700)
            parent_fd = child_fd
        metadata_fd = directory_descriptors[-1]

        existing_flags = os.O_RDONLY
        if hasattr(os, "O_CLOEXEC"):
            existing_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            existing_flags |= os.O_NOFOLLOW
        try:
            existing_fd = os.open(target_name, existing_flags, dir_fd=metadata_fd)
        except FileNotFoundError:
            existing_fd = -1
        if existing_fd >= 0:
            with os.fdopen(existing_fd, "rb", closefd=True) as handle:
                file_stat = os.fstat(handle.fileno())
                if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != len(
                    payload
                ):
                    raise OSError(
                        "metadata sidecar digest path contains different bytes"
                    )
                existing = handle.read(len(payload) + 1)
                if existing != payload:
                    raise OSError(
                        "metadata sidecar digest path contains different bytes"
                    )
                os.fchmod(handle.fileno(), 0o600)
            return target

        temporary_name = f".metadata-{uuid4().hex}.tmp"
        create_flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        if hasattr(os, "O_CLOEXEC"):
            create_flags |= os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            create_flags |= os.O_NOFOLLOW
        descriptor = os.open(
            temporary_name,
            create_flags,
            0o600,
            dir_fd=metadata_fd,
        )
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            os.fchmod(handle.fileno(), 0o600)
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(
                temporary_name,
                target_name,
                src_dir_fd=metadata_fd,
                dst_dir_fd=metadata_fd,
                follow_symlinks=False,
            )
        except FileExistsError:
            existing_fd = os.open(target_name, existing_flags, dir_fd=metadata_fd)
            with os.fdopen(existing_fd, "rb", closefd=True) as handle:
                file_stat = os.fstat(handle.fileno())
                if not stat.S_ISREG(file_stat.st_mode) or file_stat.st_size != len(
                    payload
                ):
                    raise OSError(
                        "metadata sidecar digest path contains different bytes"
                    )
                if handle.read(len(payload) + 1) != payload:
                    raise OSError(
                        "metadata sidecar digest path contains different bytes"
                    )
                os.fchmod(handle.fileno(), 0o600)
        return target
    except OSError as exc:
        raise PipelineSdkError(
            "artifact registration metadata sidecar could not be materialized",
            error_code="artifact_registration_metadata_sidecar_write_failed",
            stage="artifacts.request_serialization",
            retryable=False,
            details={"content_digest": digest, "size_bytes": len(payload)},
        ) from exc
    finally:
        if temporary_name is not None and directory_descriptors:
            try:
                os.unlink(temporary_name, dir_fd=directory_descriptors[-1])
            except FileNotFoundError:
                pass
        for descriptor in reversed(directory_descriptors):
            os.close(descriptor)


def snapshot_code(
    paths: str | list[str] | None = None,
    *,
    entrypoint: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return dict(
        call(
            "artifacts.snapshot_code",
            {
                "paths": paths,
                "entrypoint": entrypoint,
                "metadata": dict(metadata or {}),
            },
        )
    )


def _validate_artifact_kind(kind: object) -> None:
    if isinstance(kind, str) and kind in _ARTIFACT_KIND_ALLOWLIST:
        return
    allowed_values = ", ".join(_ARTIFACT_KIND_VALUES)
    raise PipelineSdkError(
        f"artifact kind {kind!r} is invalid",
        error_code="artifact_kind_invalid",
        stage="artifacts.request_validation",
        retryable=False,
        hint=f"Use exactly one of: {allowed_values}.",
        details={"allowed_values": list(_ARTIFACT_KIND_VALUES)},
    )


def _required_text(value: object, *, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise _projection_error(
            f"{label} must be a non-empty string",
            error_code="artifact_response_projection_invalid",
        )
    return value


def _required_digest(value: object, *, label: str) -> str:
    digest = _required_text(value, label=label)
    if not _DIGEST_PATTERN.fullmatch(digest):
        raise _projection_error(
            f"{label} must be a canonical sha256 digest",
            error_code="artifact_response_projection_invalid",
        )
    return digest


def _projection_error(
    message: str,
    *,
    error_code: str,
    details: dict[str, Any] | None = None,
    hint: str | None = None,
) -> PipelineSdkError:
    return PipelineSdkError(
        message,
        error_code=error_code,
        stage="artifacts.response_selection",
        retryable=False,
        hint=hint
        or (
            "Use only the documented direct response field; do not recursively "
            "search nested provenance projections or replay the completed operation."
        ),
        details=details,
    )


__all__ = [
    "fetched_output_ref",
    "get",
    "materialize",
    "provider_file_ref",
    "register",
    "register_many",
    "registered_artifact_ref",
    "snapshot_code",
]
