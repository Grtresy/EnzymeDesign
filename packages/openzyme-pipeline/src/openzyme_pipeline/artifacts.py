from __future__ import annotations

from pathlib import Path
from typing import Any

from .client import call


OUTPUT_ROOT = Path("/openzyme/output")


def get(artifact_id: str) -> dict[str, Any]:
    return dict(call("artifacts.get", {"artifact_id": artifact_id}))


def register(path: str, *, kind: str = "result", format: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = OUTPUT_ROOT / resolved
    resolved = resolved.resolve()
    if OUTPUT_ROOT not in (resolved, *resolved.parents):
        raise ValueError("artifacts.register only accepts files under /openzyme/output")
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
        resolved = Path(path)
        if not resolved.is_absolute():
            resolved = OUTPUT_ROOT / resolved
        resolved = resolved.resolve()
        if OUTPUT_ROOT not in (resolved, *resolved.parents):
            raise ValueError("artifacts.register_many only accepts files under /openzyme/output")
        items.append({"path": str(resolved), "kind": kind, "format": format, "metadata": dict(metadata or {})})
    return list(call("artifacts.register_many", {"items": items}))


__all__ = ["get", "register", "register_many"]
