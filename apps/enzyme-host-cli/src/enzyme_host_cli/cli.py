from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from enzyme_host_runtime import HostRuntime
from enzyme_host_runtime import RunRequest
from .plan_runtime import PlanValidationError
from .plan_runtime import load_plan_payload
from .reporting import format_status
from .workspace import WorkspaceError


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
    runtime = HostRuntime()
    try:
        if args.command == "init":
            return _cmd_init(runtime, args.name)
        if args.command == "new-episode":
            return _cmd_new_episode(runtime, args.goal)
        if args.command == "plan":
            return _cmd_plan(runtime, args)
        if args.command == "run":
            return _cmd_run(runtime, args.step, args.resume, args.force)
        if args.command == "status":
            return _cmd_status(runtime)
        if args.command == "logs":
            return _cmd_logs(runtime, args.run_id)
        if args.command == "report":
            return _cmd_report(runtime)
    except (WorkspaceError, PlanValidationError, RuntimeError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    raise ValueError(f"Unknown command: {args.command}")


def _cmd_init(runtime: HostRuntime, name: str) -> int:
    context = runtime.init_project(Path.cwd(), name)
    print(f"Initialized project {context.config.project_name} at {context.root}")
    return 0


def _cmd_new_episode(runtime: HostRuntime, goal: str) -> int:
    snapshot = runtime.create_episode(Path.cwd(), goal)
    print(f"Created episode {snapshot.episode_id}")
    return 0


def _cmd_plan(runtime: HostRuntime, args: argparse.Namespace) -> int:
    context = runtime.load_project(Path.cwd())
    episode_id = context.cli_state.current_episode_id
    if not episode_id:
        raise WorkspaceError("No active episode. Run `enzyme new-episode` first.")
    if args.plan_command == "import":
        runtime.confirm_plan(
            Path.cwd(),
            plan_file=args.plan_file,
            imported_at=_now_for_cli(),
        )
        print(f"Imported plan for episode {episode_id} from {args.plan_file}")
        return 0
    if args.plan_command == "confirm":
        plan_file = args.plan_file or (context.root / "episodes" / episode_id / "plan.yaml")
        plan = load_plan_payload(plan_file)
        runtime.confirm_plan(Path.cwd(), plan=plan, plan_file=plan_file)
        print(f"Confirmed plan for episode {episode_id}")
        return 0
    raise ValueError(f"Unknown plan command: {args.plan_command}")


def _cmd_run(
    runtime: HostRuntime,
    step_id: str | None,
    resume: bool,
    force: bool,
) -> int:
    runs = runtime.run_plan(
        Path.cwd(),
        request=RunRequest(step_id=step_id, resume=resume, force=force),
    )
    if not runs:
        print("No steps selected. The plan is already complete.")
        return 0
    for item in runs:
        print(f"Completed {item.step_id}: {item.status} ({item.run_id})")
    return 0


def _cmd_status(runtime: HostRuntime) -> int:
    snapshot = runtime.get_status(Path.cwd())
    print(
        format_status(
            snapshot.project_name,
            Path(snapshot.project_root),
            snapshot.episode_id,
            snapshot.goal,
            snapshot.state,
        )
    )
    return 0


def _cmd_logs(runtime: HostRuntime, run_id: str) -> int:
    try:
        manifest = runtime.get_run(Path.cwd(), run_id)
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


def _cmd_report(runtime: HostRuntime) -> int:
    target = runtime.materialize_report(Path.cwd())
    print(target)
    return 0


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
