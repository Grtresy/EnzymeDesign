from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import call


WORKSPACE_INPUT_ROOT = Path("/workspace/input")
WORKSPACE_OUTPUT_ROOT = Path("/workspace/output")
COMPAT_INPUT_ROOT = Path("/openzyme/input")
COMPAT_OUTPUT_ROOT = Path("/openzyme/output")


def get(artifact_id: str) -> dict[str, Any]:
    return dict(call("artifacts.get", {"artifact_id": artifact_id}))


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


def register(path: str, *, kind: str = "result", format: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = _resolve_output_path(path)
    return dict(
        call(
            "artifacts.register",
            {
                "path": str(resolved),
                "kind": kind,
                "format": format,
                "metadata": dict(metadata or {}),
            },
        )
    )


def register_many(paths: list[str], *, kind: str = "result", format: str | None = None, metadata: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    for path in paths:
        resolved = _resolve_output_path(path)
        items.append({"path": str(resolved), "kind": kind, "format": format, "metadata": dict(metadata or {})})
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


__all__ = ["get", "materialize", "register", "register_many", "snapshot_code"]
