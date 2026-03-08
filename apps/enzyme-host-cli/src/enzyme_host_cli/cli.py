from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys
from typing import Any

from enzyme_host_runtime import ExecutionResult
from enzyme_host_runtime import HostRuntime
from enzyme_host_runtime import RoutedExecutionAdapter
from enzyme_host_runtime import StepExecutor
from .plan_runtime import PlanValidationError
from .reporting import format_status
from .workspace import WorkspaceError


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="enzyme")
    parser.add_argument("--verbose", action="store_true", help="Show detailed backend provenance")
    subparsers = parser.add_subparsers(dest="command", required=True)

    init_cmd = subparsers.add_parser("init", help="Initialize a new OpenZyme project")
    init_cmd.add_argument("name")

    episode_cmd = subparsers.add_parser("new-episode", help="Create a new episode")
    episode_cmd.add_argument("goal")

    workflow_cmd = subparsers.add_parser("workflow", help="Drive the agent workflow")
    workflow_subparsers = workflow_cmd.add_subparsers(dest="workflow_command", required=True)
    workflow_subparsers.add_parser("start", help="Start the active episode workflow")
    continue_cmd = workflow_subparsers.add_parser("continue", help="Continue the active episode workflow")
    continue_cmd.add_argument("--state-version", type=int)
    continue_cmd.add_argument("--resume-token")
    workflow_subparsers.add_parser("execute", help="Execute the current selected tool action")

    feedback_cmd = workflow_subparsers.add_parser("feedback", help="Submit feedback for a pending interrupt")
    feedback_cmd.add_argument("interrupt_id")
    feedback_cmd.add_argument("content")
    feedback_cmd.add_argument("--kind", default="clarification")
    feedback_cmd.add_argument("--state-version", type=int)
    feedback_cmd.add_argument("--resume-token")

    workflow_subparsers.add_parser("interrupts", help="List pending interrupts")
    workflow_subparsers.add_parser("gates", help="List approval gates")

    approve_cmd = workflow_subparsers.add_parser("approve-gate", help="Approve a pending gate")
    approve_cmd.add_argument("gate_id")
    approve_cmd.add_argument("--state-version", type=int)
    approve_cmd.add_argument("--resume-token")

    reject_cmd = workflow_subparsers.add_parser("reject-gate", help="Reject a pending gate")
    reject_cmd.add_argument("gate_id")
    reject_cmd.add_argument("--state-version", type=int)
    reject_cmd.add_argument("--resume-token")

    subparsers.add_parser("status", help="Summarize the active episode")

    logs_cmd = subparsers.add_parser("logs", help="Show stored log references for a run")
    logs_cmd.add_argument("run_id")

    subparsers.add_parser("report", help="Materialize the current episode report")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    runtime = _build_runtime()
    try:
        if args.command == "init":
            return _cmd_init(runtime, args.name)
        if args.command == "new-episode":
            return _cmd_new_episode(runtime, args.goal)
        if args.command == "workflow":
            return _cmd_workflow(runtime, args)
        if args.command == "status":
            return _cmd_status(runtime, verbose=args.verbose)
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


def _cmd_workflow(runtime: HostRuntime, args: argparse.Namespace) -> int:
    if args.workflow_command == "start":
        snapshot = runtime.start_agent_workflow(Path.cwd())
        print(_render_workflow_summary(snapshot, verbose=args.verbose))
        return 0
    if args.workflow_command == "continue":
        snapshot = runtime.continue_agent_workflow(
            Path.cwd(),
            expected_state_version=args.state_version,
            resume_token=args.resume_token,
        )
        print(_render_workflow_summary(snapshot, verbose=args.verbose))
        return 0
    if args.workflow_command == "execute":
        snapshot = runtime.execute_selected_action(Path.cwd())
        print(_render_workflow_summary(snapshot, verbose=args.verbose))
        return 0
    if args.workflow_command == "feedback":
        snapshot = runtime.submit_feedback(
            Path.cwd(),
            interrupt_id=args.interrupt_id,
            content=args.content,
            kind=args.kind,
            actor="enzyme-cli",
            expected_state_version=args.state_version,
            resume_token=args.resume_token,
        )
        print(_render_workflow_summary(snapshot, verbose=args.verbose))
        return 0
    if args.workflow_command == "interrupts":
        snapshot = runtime.get_status(Path.cwd())
        if not snapshot.pending_interrupts:
            print("No pending interrupts")
            return 0
        for item in snapshot.pending_interrupts:
            print(f"{item['interrupt_id']}: {item['kind']} [{item['status']}]")
        return 0
    if args.workflow_command == "gates":
        snapshot = runtime.get_status(Path.cwd())
        if not snapshot.approval_gates:
            print("No approval gates")
            return 0
        for item in snapshot.approval_gates:
            print(f"{item['gate_id']}: {item['risk_level']} [{item['status']}]")
        return 0
    if args.workflow_command == "approve-gate":
        snapshot = runtime.approve_gate(
            Path.cwd(),
            gate_id=args.gate_id,
            actor="enzyme-cli",
            expected_state_version=args.state_version,
            resume_token=args.resume_token,
        )
        print(_render_workflow_summary(snapshot, verbose=args.verbose))
        return 0
    if args.workflow_command == "reject-gate":
        snapshot = runtime.reject_gate(
            Path.cwd(),
            gate_id=args.gate_id,
            actor="enzyme-cli",
            expected_state_version=args.state_version,
            resume_token=args.resume_token,
        )
        print(_render_workflow_summary(snapshot, verbose=args.verbose))
        return 0
    raise ValueError(f"Unknown workflow command: {args.workflow_command}")


def _cmd_status(runtime: HostRuntime, *, verbose: bool) -> int:
    snapshot = runtime.get_status(Path.cwd())
    lines = [
        format_status(
            snapshot.project_name,
            Path(snapshot.project_root),
            snapshot.episode_id,
            snapshot.goal,
            snapshot.state,
        ),
        _render_backend_lines(snapshot.agent_backend, verbose=verbose),
    ]
    print(
        "\n".join(
            line for line in lines if line.strip()
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


def _build_runtime() -> HostRuntime:
    fake_mode = os.environ.get("ENZYME_HOST_CLI_FAKE_EXECUTOR", "").strip().lower()
    if fake_mode == "prepare_receptor_success":
        return HostRuntime(executor=RoutedExecutionAdapter([_FakePrepareReceptorExecutor()]))
    return HostRuntime()


class _FakePrepareReceptorExecutor(StepExecutor):
    def supports(self, tool: str) -> bool:
        return tool == "prepare_receptor"

    def run_step(self, project_root: Path, episode_id: str, step) -> ExecutionResult:
        return ExecutionResult(
            run_id="cli-local-run-1",
            status="completed",
            manifest_payload={
                "backend": "fake-cli-executor",
                "tool": step.tool,
                "step_id": step.step_id,
                "status": "completed",
                "result": {"status": "completed", "output": {"output_path": "data/inputs/receptor.pdbqt"}},
            },
        )


def _render_workflow_summary(snapshot, *, verbose: bool) -> str:
    agent = snapshot.agent_state
    selected_action = agent.get("selected_action") if isinstance(agent, dict) else None
    next_action = selected_action.get("title") if isinstance(selected_action, dict) else "-"
    lines = [
        f"Episode: {snapshot.episode_id}",
        f"Agent Status: {agent.get('status', 'idle') if isinstance(agent, dict) else 'idle'}",
        f"Next Action: {next_action}",
        *(_render_backend_lines(snapshot.agent_backend, verbose=verbose).splitlines()),
        f"Pending Interrupts: {len(snapshot.pending_interrupts)}",
        f"Approval Gates: {len(snapshot.approval_gates)}",
        f"Runs: {len(snapshot.runs)}",
    ]
    return "\n".join(line for line in lines if line)


def _format_mapping(payload: dict[str, Any]) -> list[str]:
    rendered: list[str] = []
    for key in sorted(payload):
        value = payload[key]
        if isinstance(value, (dict, list)):
            rendered.append(f"  {key}: {json.dumps(value, sort_keys=True)}")
        else:
            rendered.append(f"  {key}: {value}")
    return rendered


def _render_backend_lines(agent_backend: dict[str, Any], *, verbose: bool) -> str:
    if not isinstance(agent_backend, dict):
        return ""
    backend_name = str(agent_backend.get("backend") or "heuristic")
    degraded = bool(agent_backend.get("degraded"))
    fallback_used = bool(agent_backend.get("fallback_used"))
    last_error = str(agent_backend.get("last_error_summary") or "-")
    state = "degraded" if degraded else "healthy"
    if backend_name == "heuristic" and not degraded:
        state = "heuristic"
    lines = [
        f"Agent Backend: {backend_name}",
        f"Backend State: {state}",
        f"Fallback Active: {'yes' if fallback_used else 'no'}",
        f"Sidecar Error: {last_error}",
    ]
    if verbose:
        provider = str(agent_backend.get("provider") or "-")
        model = str(agent_backend.get("model") or "-")
        sidecar = agent_backend.get("sidecar")
        if isinstance(sidecar, dict) and sidecar:
            lines.append(
                f"Provider/Model: {provider} / {model} ({sidecar.get('name', '-')}"
                f" {sidecar.get('version', '-')})"
            )
        else:
            lines.append(f"Provider/Model: {provider} / {model}")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
