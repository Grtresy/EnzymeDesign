from __future__ import annotations

from pathlib import Path
from typing import Any

from .models import ExecutionEvidence


def build_execution_evidence(project_root: Path, episode_id: str, state: dict[str, Any]) -> ExecutionEvidence:
    planning = state.get("planning")
    planning_state = planning if isinstance(planning, dict) else {}
    approved_revision_id = _optional_str(
        planning_state.get("approved_revision_id")
        or (state.get("plan") or {}).get("revision_id")
    )
    runs = state.get("runs")
    run_items = [dict(item) for item in runs if isinstance(item, dict)] if isinstance(runs, list) else []
    manifest_refs = [str(item.get("manifest_path")) for item in run_items if item.get("manifest_path")]
    step_state = state.get("steps")
    steps = step_state if isinstance(step_state, dict) else {}
    step_statuses: list[dict[str, str]] = []
    failure_reasons: list[str] = []
    for step_id, payload in sorted(steps.items()):
        if not isinstance(payload, dict):
            continue
        status = str(payload.get("status") or "unknown")
        step_statuses.append(
            {
                "step_id": str(step_id),
                "status": status,
                "tool": str(payload.get("tool") or ""),
            }
        )
        error = payload.get("error")
        if error:
            failure_reasons.append(str(error))
        elif status not in {"completed", "running"}:
            failure_reasons.append(f"{step_id}: {status}")
    report_payload = state.get("report")
    report_path = None
    if isinstance(report_payload, dict) and report_payload.get("path"):
        report_path = str(report_payload["path"])
    report_available = bool(report_path and (project_root / report_path).exists())
    episode_status = str(state.get("status") or "unknown")
    latest_run_id = _optional_str(run_items[-1].get("run_id")) if run_items else None
    needs_replan = episode_status == "failed" or bool(failure_reasons)
    return ExecutionEvidence(
        episode_id=episode_id,
        confirmed_revision_id=approved_revision_id,
        run_ids=[str(item.get("run_id")) for item in run_items if item.get("run_id")],
        manifest_refs=manifest_refs,
        step_statuses=step_statuses,
        failure_reasons=failure_reasons,
        report_ref=report_path,
        episode_status=episode_status,
        report_available=report_available,
        needs_replan=needs_replan,
        latest_run_id=latest_run_id,
    )


def _optional_str(value: object) -> str | None:
    if value is None:
        return None
    rendered = str(value)
    return rendered or None
