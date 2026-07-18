from __future__ import annotations

from pathlib import Path
import re
from typing import Any

from .client import PipelineSdkError, call


WORKSPACE_INPUT_ROOT = Path("/workspace/input")
WORKSPACE_OUTPUT_ROOT = Path("/workspace/output")
COMPAT_INPUT_ROOT = Path("/openzyme/input")
COMPAT_OUTPUT_ROOT = Path("/openzyme/output")
_DIGEST_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


def get(artifact_id: str) -> dict[str, Any]:
    return dict(call("artifacts.get", {"artifact_id": artifact_id}))


def registered_artifact_ref(response: dict[str, Any]) -> dict[str, str]:
    """Return the canonical id/digest pair from ``artifacts.register``.

    The Host response intentionally carries both a public artifact projection and
    registration metadata.  Callers must not recursively search that envelope,
    because the same artifact can appear in more than one provenance projection.
    """

    artifact = response.get("artifact")
    if not isinstance(artifact, dict):
        raise _projection_error(
            "artifact registration response has no artifact object",
            error_code="artifact_registration_projection_invalid",
        )
    artifact_id = _required_text(artifact.get("artifact_id"), label="artifact_id")
    content_digest = _required_digest(
        response.get("content_digest"),
        label="artifact registration content_digest",
    )
    metadata = artifact.get("metadata")
    if isinstance(metadata, dict):
        metadata_digest = metadata.get("content_digest") or metadata.get(
            "sealed_digest"
        )
        if metadata_digest is not None and metadata_digest != content_digest:
            raise _projection_error(
                "artifact registration response has inconsistent content digests",
                error_code="artifact_registration_projection_invalid",
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
    """Select one provider file from the canonical transcript manifest only."""

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
    """Select one fetched runner output from the canonical ``fetch_refs`` list."""

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
    resolved = _resolve_output_path(path)
    return dict(
        call(
            "artifacts.register",
            {
                "path": str(resolved),
                "kind": kind,
                "format": format,
                "validation_profile": validation_profile,
                "metadata": dict(metadata or {}),
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
    items: list[dict[str, Any]] = []
    for path in paths:
        resolved = _resolve_output_path(path)
        items.append(
            {
                "path": str(resolved),
                "kind": kind,
                "format": format,
                "validation_profile": validation_profile,
                "metadata": dict(metadata or {}),
            }
        )
    return list(call("artifacts.register_many", {"items": items}))


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
) -> PipelineSdkError:
    return PipelineSdkError(
        message,
        error_code=error_code,
        stage="artifacts.response_selection",
        retryable=False,
        hint=(
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
