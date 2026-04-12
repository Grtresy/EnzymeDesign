from __future__ import annotations

from contextlib import contextmanager
from contextlib import nullcontext
import os
from typing import Any
from typing import Iterator

from langsmith import trace
from langsmith import tracing_context


def tracing_enabled() -> bool:
    value = os.getenv("OPENZYME_LANGSMITH_TRACING") or os.getenv("LANGSMITH_TRACING")
    if value is None:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on", "local"}


def tracing_project_name() -> str:
    return os.getenv("OPENZYME_LANGSMITH_PROJECT") or os.getenv("LANGSMITH_PROJECT") or "openzyme-v2"


def build_trace_tags(
    *,
    action: str,
    project_id: str | None = None,
    episode_id: str | None = None,
    phase: str | None = None,
    approval_id: str | None = None,
    report_id: str | None = None,
) -> list[str]:
    tags = [f"action:{action}"]
    if project_id:
        tags.append(f"project:{project_id}")
    if episode_id:
        tags.append(f"episode:{episode_id}")
    if phase:
        tags.append(f"phase:{phase}")
    if approval_id:
        tags.append(f"approval:{approval_id}")
    if report_id:
        tags.append(f"report:{report_id}")
    return tags


def build_trace_metadata(
    *,
    action: str,
    project_id: str | None = None,
    episode_id: str | None = None,
    phase: str | None = None,
    approval_id: str | None = None,
    report_id: str | None = None,
    request_method: str | None = None,
    request_path: str | None = None,
) -> dict[str, Any]:
    metadata: dict[str, Any] = {"action": action}
    if project_id is not None:
        metadata["project_id"] = project_id
    if episode_id is not None:
        metadata["episode_id"] = episode_id
    if phase is not None:
        metadata["phase"] = phase
    if approval_id is not None:
        metadata["approval_id"] = approval_id
    if report_id is not None:
        metadata["report_id"] = report_id
    if request_method is not None:
        metadata["request_method"] = request_method
    if request_path is not None:
        metadata["request_path"] = request_path
    return metadata


@contextmanager
def host_request_trace_context(*, method: str, path: str) -> Iterator[None]:
    if not tracing_enabled():
        yield
        return
    with tracing_context(
        project_name=tracing_project_name(),
        tags=build_trace_tags(action="host_request"),
        metadata=build_trace_metadata(
            action="host_request",
            request_method=method,
            request_path=path,
        ),
        enabled=True,
    ):
        yield


@contextmanager
def workflow_trace(
    name: str,
    *,
    action: str,
    inputs: dict[str, Any] | None = None,
    project_id: str | None = None,
    episode_id: str | None = None,
    phase: str | None = None,
    approval_id: str | None = None,
    report_id: str | None = None,
    enabled: bool | None = None,
) -> Iterator[Any]:
    is_enabled = tracing_enabled() if enabled is None else enabled
    if not is_enabled:
        with nullcontext(None) as run:
            yield run
        return
    with trace(
        name,
        run_type="chain",
        project_name=tracing_project_name(),
        inputs=inputs,
        tags=build_trace_tags(
            action=action,
            project_id=project_id,
            episode_id=episode_id,
            phase=phase,
            approval_id=approval_id,
            report_id=report_id,
        ),
        metadata=build_trace_metadata(
            action=action,
            project_id=project_id,
            episode_id=episode_id,
            phase=phase,
            approval_id=approval_id,
            report_id=report_id,
        ),
    ) as run:
        yield run
