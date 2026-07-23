from __future__ import annotations

import argparse
import json
import sys
from typing import Any
from typing import TextIO

from .client import HostApiClient
from .client import HostApiError
from .client import SessionProtocol
from .config import HostCliConfig
from .renderers import render_json
from .renderers import render_v3_command_result
from .renderers import render_v3_runtime_health
from .renderers import render_v3_workspace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openzyme", description="OpenZyme V3 Host CLI")
    parser.add_argument("--host", dest="base_url", help="Host API base URL")
    parser.add_argument("--project-id", help="Default project ID")
    parser.add_argument("--session-id", help="Default V3 session ID")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default=None,
        help="Output format",
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)

    sessions = subparsers.add_parser("sessions", help="Session commands")
    session_sub = sessions.add_subparsers(dest="sessions_command", required=True)
    session_create = session_sub.add_parser("create", help="Create a V3 session")
    session_create.add_argument("--project-id", dest="command_project_id", help="Project ID override")
    session_create.add_argument("--session-id", dest="command_session_id", help="Session ID override")
    session_create.add_argument("--objective", required=True, help="Session objective")
    session_create.add_argument("--title", help="Session title")
    session_show = session_sub.add_parser("show", help="Show V3 workspace")
    session_show.add_argument("--session-id", dest="command_session_id", help="Session ID override")
    session_message = session_sub.add_parser("message", help="Send a message to a V3 session")
    session_message.add_argument("--session-id", dest="command_session_id", help="Session ID override")
    session_message.add_argument("--message", required=True, help="User message")
    session_message.add_argument("--task-id", help="Focused task ID")
    session_message.add_argument("--lane-id", help="Focused lane ID")

    tasks = subparsers.add_parser("tasks", help="Task board commands")
    task_sub = tasks.add_subparsers(dest="tasks_command", required=True)
    task_create = task_sub.add_parser("create", help="Create a V3 task")
    task_create.add_argument("--session-id", dest="command_session_id", help="Session ID override")
    task_create.add_argument("--task-id", help="Task ID override")
    task_create.add_argument("--subject", required=True)
    task_create.add_argument("--description", default="")
    task_create.add_argument("--priority", default="normal")
    task_create.add_argument("--kind", default="general")
    task_create.add_argument("--lane-id")
    task_update = task_sub.add_parser("update", help="Update a V3 task")
    task_update.add_argument("--task-id", required=True)
    task_update.add_argument("--status")
    task_update.add_argument("--subject")
    task_update.add_argument("--description")
    task_update.add_argument("--priority")
    task_update.add_argument("--lane-id")

    lanes = subparsers.add_parser("lanes", help="Lane commands")
    lane_sub = lanes.add_subparsers(dest="lanes_command", required=True)
    lane_create = lane_sub.add_parser("create", help="Create a V3 lane")
    lane_create.add_argument("--session-id", dest="command_session_id", help="Session ID override")
    lane_create.add_argument("--lane-id")
    lane_create.add_argument("--name", required=True)
    lane_create.add_argument("--cwd", default=".")
    lane_create.add_argument("--branch-name")
    lane_claim = lane_sub.add_parser("claim", help="Claim a V3 lane")
    lane_claim.add_argument("--lane-id", required=True)
    lane_keep = lane_sub.add_parser("keep", help="Release/keep a V3 lane for later")
    lane_keep.add_argument("--lane-id", required=True)
    lane_remove = lane_sub.add_parser("remove", help="Remove a V3 lane")
    lane_remove.add_argument("--lane-id", required=True)

    approvals = subparsers.add_parser("approvals", help="Approval commands")
    approval_sub = approvals.add_subparsers(dest="approvals_command", required=True)
    approval_resolve = approval_sub.add_parser("resolve", help="Resolve a V3 approval")
    approval_resolve.add_argument("--approval-id", required=True)
    approval_resolve.add_argument("--decision", choices=("approved", "rejected"), required=True)

    runtime = subparsers.add_parser("runtime", help="Runtime commands")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_sub.add_parser("health", help="Show public V3 runtime health")

    scientific = subparsers.add_parser(
        "scientific",
        help="Scientific attempt authority and selected-chain commands",
    )
    scientific_sub = scientific.add_subparsers(
        dest="scientific_command",
        required=True,
    )
    scientific_inspect = scientific_sub.add_parser(
        "inspect",
        help="Inspect safe attempt authority, occurrence, selection, and closure state",
    )
    scientific_inspect.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_authorize = scientific_sub.add_parser(
        "authorize",
        help="Grant a durable bounded attempt envelope",
    )
    scientific_authorize.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_authorize.add_argument("--payload-json", required=True)
    scientific_authorize.add_argument("--idempotency-key", required=True)
    scientific_execute = scientific_sub.add_parser(
        "command",
        help="Execute one actor-bound selected-chain command",
    )
    scientific_execute.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_execute.add_argument(
        "--command",
        required=True,
        choices=(
            "attempt.create",
            "scientific.selection.begin",
            "scientific.operation.disposition",
            "scientific.effect.adopt",
            "scientific.artifact.materialize",
            "scientific.selection.seal",
            "scientific.attempt.close",
        ),
    )
    scientific_execute.add_argument("--arguments-json", required=True)
    scientific_execute.add_argument("--idempotency-key", required=True)
    scientific_finalize_admission = scientific_sub.add_parser(
        "finalize-admission",
        help="Host-finalize an admission request after its writer turn retires",
    )
    scientific_finalize_admission.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_finalize_admission.add_argument(
        "--admission-request-id",
        required=True,
    )
    scientific_finalize = scientific_sub.add_parser(
        "finalize",
        help="Host-finalize a closure request after all attempt writers retire",
    )
    scientific_finalize.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_finalize.add_argument("--closure-request-id", required=True)

    return parser


def _resolve_config(args: argparse.Namespace) -> HostCliConfig:
    env_config = HostCliConfig.from_env()
    return HostCliConfig(
        base_url=args.base_url or env_config.base_url,
        project_id=getattr(args, "project_id", None) or env_config.project_id,
        output_format=args.format or env_config.output_format,
        auth_token=env_config.auth_token,
    )


def _require_value(value: str | None, flag_name: str) -> str:
    if value:
        return value
    raise ValueError(f"{flag_name} is required (flag or environment default)")


def _format_output(output_format: str, payload: Any, text_renderer) -> str:
    return render_json(payload) if output_format == "json" else text_renderer(payload)


def run_cli(
    argv: list[str] | None = None,
    *,
    session: SessionProtocol | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    config = _resolve_config(args)
    client = HostApiClient(
        config.base_url,
        auth_token=config.auth_token,
        session=session,
    )
    try:
        if args.resource == "sessions":
            if args.sessions_command == "create":
                project_id = _require_value(
                    getattr(args, "command_project_id", None) or args.project_id or config.project_id,
                    "--project-id",
                )
                payload = client.create_v3_session(
                    project_id=project_id,
                    objective=args.objective,
                    title=args.title,
                    session_id=getattr(args, "command_session_id", None) or args.session_id,
                )
                stdout.write(_format_output(config.output_format, payload, render_v3_command_result) + "\n")
                return 0
            session_id = _require_value(
                getattr(args, "command_session_id", None) or args.session_id,
                "--session-id",
            )
            if args.sessions_command == "show":
                payload = client.get_v3_workspace(session_id)
                stdout.write(_format_output(config.output_format, payload, render_v3_workspace) + "\n")
                return 0
            if args.sessions_command == "message":
                payload = client.post_v3_message(
                    session_id,
                    message=args.message,
                    task_id=args.task_id,
                    lane_id=args.lane_id,
                )
                stdout.write(_format_output(config.output_format, payload, render_v3_command_result) + "\n")
                return 0

        if args.resource == "tasks":
            if args.tasks_command == "create":
                session_id = _require_value(
                    getattr(args, "command_session_id", None) or args.session_id,
                    "--session-id",
                )
                payload_body = {
                    "session_id": session_id,
                    "subject": args.subject,
                    "description": args.description,
                    "priority": args.priority,
                    "kind": args.kind,
                }
                if args.task_id:
                    payload_body["task_id"] = args.task_id
                if args.lane_id:
                    payload_body["lane_id"] = args.lane_id
                payload = client.create_v3_task(payload_body)
                stdout.write(_format_output(config.output_format, payload, render_v3_command_result) + "\n")
                return 0
            payload_body = {}
            for field in ("status", "subject", "description", "priority", "lane_id"):
                value = getattr(args, field)
                if value is not None:
                    payload_body[field] = value
            payload = client.update_v3_task(args.task_id, payload_body)
            stdout.write(_format_output(config.output_format, payload, render_v3_command_result) + "\n")
            return 0

        if args.resource == "lanes":
            if args.lanes_command == "create":
                session_id = _require_value(
                    getattr(args, "command_session_id", None) or args.session_id,
                    "--session-id",
                )
                payload_body = {
                    "session_id": session_id,
                    "name": args.name,
                    "cwd": args.cwd,
                }
                if args.lane_id:
                    payload_body["lane_id"] = args.lane_id
                if args.branch_name:
                    payload_body["branch_name"] = args.branch_name
                payload = client.create_v3_lane(payload_body)
            elif args.lanes_command == "claim":
                payload = client.claim_v3_lane(args.lane_id)
            elif args.lanes_command == "keep":
                payload = client.keep_v3_lane(args.lane_id)
            else:
                payload = client.remove_v3_lane(args.lane_id)
            stdout.write(_format_output(config.output_format, payload, render_v3_command_result) + "\n")
            return 0

        if args.resource == "approvals":
            payload = client.resolve_v3_approval(args.approval_id, args.decision)
            stdout.write(_format_output(config.output_format, payload, render_v3_command_result) + "\n")
            return 0
        if args.resource == "runtime":
            payload = client.get_v3_runtime_health()
            stdout.write(
                _format_output(config.output_format, payload, render_v3_runtime_health)
                + "\n"
            )
            return 0
        if args.resource == "scientific":
            session_id = _require_value(
                getattr(args, "command_session_id", None) or args.session_id,
                "--session-id",
            )
            if args.scientific_command == "inspect":
                payload = client.get_v3_scientific_attempts(session_id)
            elif args.scientific_command == "authorize":
                request_payload = json.loads(args.payload_json)
                if not isinstance(request_payload, dict):
                    raise ValueError("--payload-json must decode to an object")
                payload = client.grant_v3_scientific_attempt_authorization(
                    session_id,
                    request_payload,
                    idempotency_key=args.idempotency_key,
                )
            elif args.scientific_command == "command":
                arguments = json.loads(args.arguments_json)
                if not isinstance(arguments, dict):
                    raise ValueError("--arguments-json must decode to an object")
                payload = client.execute_v3_scientific_attempt_command(
                    session_id,
                    command=args.command,
                    arguments=arguments,
                    idempotency_key=args.idempotency_key,
                )
            elif args.scientific_command == "finalize-admission":
                payload = client.finalize_v3_scientific_attempt_admission(
                    session_id,
                    admission_request_id=args.admission_request_id,
                )
            else:
                payload = client.finalize_v3_scientific_attempt_closure(
                    session_id,
                    closure_request_id=args.closure_request_id,
                )
            stdout.write(render_json(payload) + "\n")
            return 0
        raise ValueError(f"unsupported resource: {args.resource}")
    except (HostApiError, json.JSONDecodeError, ValueError) as exc:
        stderr.write(f"{exc}\n")
        return 2
    finally:
        client.close()


def main() -> None:
    raise SystemExit(run_cli())
