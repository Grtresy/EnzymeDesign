from __future__ import annotations

from typing import Any

from .client import call


def wait(run_id: str, *, timeout_seconds: int | None = None) -> dict[str, Any]:
    return dict(call("run.wait", {"run_id": run_id, "timeout_seconds": timeout_seconds}))


def fetch_artifacts(run_id: str) -> list[dict[str, Any]]:
    return list(call("run.fetch_artifacts", {"run_id": run_id}))


__all__ = ["fetch_artifacts", "wait"]
