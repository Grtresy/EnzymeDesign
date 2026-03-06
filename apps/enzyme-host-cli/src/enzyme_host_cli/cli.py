from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from .execution import ExecutionAdapter
from .memory_client import MemoryClient
from .plan_runtime import PlanValidationError
from .plan_runtime import load_confirmed_plan
from .plan_runtime import load_plan_payload
from .plan_runtime import select_steps
from .reporting import build_report
from .reporting import format_status
from .reporting import report_path
from .workspace import CliState
from .workspace import ProjectContext
from .workspace import WorkspaceError
from .workspace import allocate_episode_id
from .workspace import init_project
from .workspace import load_project_context
from .workspace import read_cli_state
from .workspace import resolve_episode_id
from .workspace import set_current_episode
from .workspace import set_last_run
from .workspace import write_cli_state


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="enzyme")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init", help="Initialize a new enzyme project")
    init_cmd.add_argument("name")

    episode_cmd = subparsers.add_parser("new-episode", help="Create a new episode")
    episode_cmd.add_argument("goal")

    plan_cmd = subparsers.add_parser("plan", help="Manage the confirmed episode plan")
    plan_subparsers = plan_cmd.add_subparsers(dest="plan_command", required=True)

    plan_import = plan_subparsers.add_parser("import", help="Import a structured plan")
    plan_import.add_argument("plan_file", type=Path)

    plan_confirm = plan_subparsers.add_parser("confirm", help="Confirm a structured plan")
    plan_confirm.add_argument("plan_file", nargs="?", type=Path, default=None)

    run_cmd = subparsers.add_parser("run", help="Execute the confirmed plan")
    run_cmd.add_argument("--step", default=None)
    run_cmd.add_argument(
        "--resume",
        action="store_true",
        help="Resume from the first step whose status is not completed. Steps left as running after a crash are retried.",
    )
    run_cmd.add_argument(
        "--force",
        action="store_true",
        help="Allow rerunning a completed step when used with --step.",
    )

    subparsers.add_parser("status", help="Summarize the active episode")

    logs_cmd = subparsers.add_parser("logs", help="Show stored log references for a run")
    logs_cmd.add_argument("run_id")

    subparsers.add_parser("report", help="Materialize the current episode report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    try:
        if args.command == "init":
            return _cmd_init(args.name)
        context = load_project_context(Path.cwd())
        memory = MemoryClient(context)
        if args.command == "new-episode":
            return _cmd_new_episode(context, memory, args.goal)
        if args.command == "plan":
            return _cmd_plan(context, memory, args)
        if args.command == "run":
            return _cmd_run(context, memory, args.step, args.resume, args.force)
        if args.command == "status":
            return _cmd_status(context, memory)
        if args.command == "logs":
            return _cmd_logs(memory, args.run_id)
        if args.command == "report":
            return _cmd_report(context, memory)
    except (WorkspaceError, PlanValidationError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    raise ValueError(f"Unknown command: {args.command}")


def _cmd_init(name: str) -> int:
    context = init_project(Path.cwd(), name)
    print(f"Initialized project {context.config.project_name} at {context.root}")
    return 0


def _cmd_new_episode(context: ProjectContext, memory: MemoryClient, goal: str) -> int:
    episode_id = allocate_episode_id(context.root)
    memory.create_episode(episode_id, goal)
    set_current_episode(context.root, episode_id)
    print(f"Created episode {episode_id}")
    return 0


def _cmd_plan(context: ProjectContext, memory: MemoryClient, args: argparse.Namespace) -> int:
    episode_id = resolve_episode_id(context.root)
    if args.plan_command == "import":
        plan = load_plan_payload(args.plan_file)
        memory.confirm_plan(
            episode_id,
            plan,
            source_path=args.plan_file,
            imported_at=_now_for_cli(),
        )
        print(f"Imported plan for episode {episode_id} from {args.plan_file}")
        return 0
    if args.plan_command == "confirm":
        plan_file = args.plan_file or (context.root / "episodes" / episode_id / "plan.yaml")
        plan = load_plan_payload(plan_file)
        memory.confirm_plan(episode_id, plan, source_path=plan_file)
        print(f"Confirmed plan for episode {episode_id}")
        return 0
    raise ValueError(f"Unknown plan command: {args.plan_command}")


def _cmd_run(
    context: ProjectContext,
    memory: MemoryClient,
    step_id: str | None,
    resume: bool,
    force: bool,
) -> int:
    episode_id = resolve_episode_id(context.root)
    state = memory.load_state(episode_id)
    plan_steps = load_confirmed_plan(memory, episode_id)
    selected = select_steps(plan_steps, state, step_id=step_id, resume=resume, force=force)
    if not selected:
        print("No steps selected. The plan is already complete.")
        return 0

    adapter = ExecutionAdapter()
    all_step_ids = [step.step_id for step in plan_steps]
    for step in selected:
        print(f"Running {step.step_id} ({step.tool})")
        memory.update_state(
            episode_id,
            lambda current: _mark_step_started(current, step.step_id, step.tool),
        )
        result = adapter.run_step(context.root, step)
        memory.write_run_manifest(episode_id, result.run_id, result.manifest_payload)
        set_last_run(context.root, result.run_id)
        memory.update_state(
            episode_id,
            lambda current: _mark_step_finished(
                current,
                episode_id,
                step.step_id,
                step.tool,
                result.run_id,
                result.status,
                all_step_ids,
            ),
        )
        print(f"Completed {step.step_id}: {result.status} ({result.run_id})")
        if result.status != "completed":
            raise RuntimeError(f"Step {step.step_id} finished with status {result.status}")
    return 0


def _cmd_status(context: ProjectContext, memory: MemoryClient) -> int:
    episode_id = resolve_episode_id(context.root)
    goal = memory.load_goal(episode_id)
    state = memory.load_state(episode_id)
    print(
        format_status(
            context.config.project_name,
            context.root,
            episode_id,
            goal,
            state,
        )
    )
    return 0


def _cmd_logs(memory: MemoryClient, run_id: str) -> int:
    try:
        manifest = memory.load_run_manifest(run_id)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Run {run_id} not found.") from exc
    lines = [
        f"Run: {run_id}",
        f"Status: {manifest.get('status', 'unknown')}",
        f"Step: {manifest.get('step_id', '-')}",
        f"Tool: {manifest.get('tool', '-')}",
    ]
    compiled = manifest.get("compiled")
    if isinstance(compiled, dict):
        runspec = compiled.get("runspec")
        if isinstance(runspec, dict):
            lines.append(f"Runspec name: {runspec.get('name', '-')}")
    for label in ("submission", "job_status", "result", "fetch"):
        payload = manifest.get(label)
        if isinstance(payload, dict) and payload:
            lines.append(f"{label}:")
            lines.extend(_format_mapping(payload))
    print("\n".join(lines))
    return 0


def _cmd_report(context: ProjectContext, memory: MemoryClient) -> int:
    episode_id = resolve_episode_id(context.root)
    goal = memory.load_goal(episode_id)
    try:
        plan = memory.load_plan(episode_id)
    except FileNotFoundError:
        plan = None
    state = memory.load_state(episode_id)
    target = report_path(context.root, episode_id)
    target.write_text(
        build_report(context.config.project_name, episode_id, goal, plan, state),
        encoding="utf-8",
    )
    memory.update_state(
        episode_id,
        lambda current: {
            **current,
            "report": {
                "path": str(target.relative_to(context.root)),
                "updated_at": _now_for_cli(),
            },
        },
    )
    print(target)
    return 0


def _mark_step_started(state: dict[str, Any], step_id: str, tool: str) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": "running",
        "started_at": _now_for_cli(),
    }
    return {
        **state,
        "status": "running",
        "steps": steps,
        "runs": runs,
    }


def _mark_step_finished(
    state: dict[str, Any],
    episode_id: str,
    step_id: str,
    tool: str,
    run_id: str,
    status: str,
    all_step_ids: list[str],
) -> dict[str, Any]:
    steps = _coerce_steps(state)
    runs = _coerce_runs(state)
    steps[step_id] = {
        **steps.get(step_id, {}),
        "tool": tool,
        "status": status,
        "run_id": run_id,
        "manifest_path": f"episodes/{episode_id}/runs/{run_id}/manifest.json",
        "updated_at": _now_for_cli(),
    }
    runs = [item for item in runs if item.get("run_id") != run_id]
    runs.append(
        {
            "run_id": run_id,
            "step_id": step_id,
            "tool": tool,
            "status": status,
            "manifest_path": steps[step_id]["manifest_path"],
        }
    )
    episode_status = "completed" if all(
        steps.get(candidate_step_id, {}).get("status") == "completed"
        for candidate_step_id in all_step_ids
    ) else ("failed" if status != "completed" else "running")
    return {
        **state,
        "status": episode_status,
        "steps": steps,
        "runs": runs,
    }


def _coerce_steps(state: dict[str, Any]) -> dict[str, dict[str, Any]]:
    raw = state.get("steps")
    if not isinstance(raw, dict):
        return {}
    return {str(key): dict(value) for key, value in raw.items() if isinstance(value, dict)}


def _coerce_runs(state: dict[str, Any]) -> list[dict[str, Any]]:
    raw = state.get("runs")
    if not isinstance(raw, list):
        return []
    return [dict(item) for item in raw if isinstance(item, dict)]


def _format_mapping(payload: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for key in sorted(payload):
        value = payload[key]
        if isinstance(value, (dict, list)):
            rendered.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
        else:
            rendered.append(f"  {key}: {value}")
    return rendered


def _now_for_cli() -> str:
    from mcp_project_memory.models import utc_now_iso

    return utc_now_iso()


if __name__ == "__main__":
    raise SystemExit(main())
