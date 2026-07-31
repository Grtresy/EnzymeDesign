from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any
from typing import TextIO

from .client import HostApiClient
from .client import HostApiError
from .client import SessionProtocol
from .config import HostCliConfig
from .renderers import render_json
from .renderers import render_v3_command_result
from .renderers import render_v3_runtime_command
from .renderers import render_v3_runtime_health
from .renderers import render_v3_workspace
from .receipts import PublicReceiptError
from .receipts import seal_public_response


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
    parser.add_argument(
        "--receipt-chain",
        type=Path,
        help="append each public Host response to one canonical receipt chain",
    )
    parser.add_argument(
        "--seal-response",
        type=Path,
        help="publish this command response once with its receipt binding",
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
    session_message.add_argument(
        "--skill-key",
        action="append",
        default=[],
        help="Workflow skill key; repeat for multiple exact keys",
    )
    session_events = session_sub.add_parser(
        "events",
        help="Replay the durable public event stream once",
    )
    session_events.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    session_events.add_argument("--after-cursor", type=int, default=0)

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
    approval_pending = approval_sub.add_parser(
        "pending",
        help="List pending approvals for one session",
    )
    approval_pending.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )

    runtime = subparsers.add_parser("runtime", help="Runtime commands")
    runtime_sub = runtime.add_subparsers(dest="runtime_command", required=True)
    runtime_sub.add_parser("health", help="Show public V3 runtime health")
    runtime_drain = runtime_sub.add_parser(
        "drain",
        help="Submit one bounded V3 runtime drain command",
    )
    runtime_drain.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    runtime_drain.add_argument("--max-signals", type=int, default=3)
    runtime_drain.add_argument("--max-steps-per-agent", type=int, default=8)
    runtime_drain.add_argument("--idempotency-key")
    runtime_status = runtime_sub.add_parser(
        "status",
        help="Show bounded scheduler and projection command state",
    )
    runtime_status.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    runtime_status.add_argument("--command-id", required=True)

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
    scientific_export = scientific_sub.add_parser(
        "export-evidence",
        help="Export one exact closed attempt/selection evidence receipt",
    )
    scientific_export.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_export.add_argument("--attempt-id", required=True)
    scientific_export.add_argument("--selection-id", required=True)
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
            "scientific.operation.adopt",
            "scientific.artifact.materialize",
            "scientific.selection.seal",
            "scientific.attempt.close",
        ),
    )
    scientific_execute.add_argument("--arguments-json", required=True)
    scientific_execute.add_argument("--idempotency-key", required=True)
    scientific_fault = scientific_sub.add_parser(
        "inject-aox-reference-fault",
        help="Consume the exact authority-bound AOX_ref21 byte-flip capability",
    )
    scientific_fault.add_argument(
        "--session-id",
        dest="command_session_id",
        help="Session ID override",
    )
    scientific_fault.add_argument("--attempt-id", required=True)
    scientific_fault.add_argument("--artifact-id", required=True)
    scientific_fault.add_argument("--idempotency-key", required=True)
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


def _emit_response(
    *,
    args: argparse.Namespace,
    client: HostApiClient,
    payload: object,
    rendered: str,
    stdout: TextIO,
) -> int:
    if args.seal_response is not None:
        if client.last_receipt is None:
            raise PublicReceiptError(
                "--seal-response requires --receipt-chain for the same request"
            )
        seal_public_response(
            args.seal_response,
            receipt=client.last_receipt,
            response=payload,
        )
    stdout.write(rendered + "\n")
    return 0


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
        receipt_chain=args.receipt_chain,
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
                return _emit_response(
                    args=args,
                    client=client,
                    payload=payload,
                    rendered=_format_output(
                        config.output_format,
                        payload,
                        render_v3_command_result,
                    ),
                    stdout=stdout,
                )
            session_id = _require_value(
                getattr(args, "command_session_id", None) or args.session_id,
                "--session-id",
            )
            if args.sessions_command == "show":
                payload = client.get_v3_workspace(session_id)
                renderer = render_v3_workspace
            if args.sessions_command == "message":
                payload = client.post_v3_message(
                    session_id,
                    message=args.message,
                    task_id=args.task_id,
                    lane_id=args.lane_id,
                    skill_keys=args.skill_key,
                )
                renderer = render_v3_command_result
            if args.sessions_command == "events":
                if args.after_cursor < 0:
                    raise ValueError("--after-cursor must be non-negative")
                payload = client.get_v3_events(
                    session_id,
                    after_cursor=args.after_cursor,
                )
                renderer = render_json
            return _emit_response(
                args=args,
                client=client,
                payload=payload,
                rendered=_format_output(config.output_format, payload, renderer),
                stdout=stdout,
            )

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
                return _emit_response(
                    args=args,
                    client=client,
                    payload=payload,
                    rendered=_format_output(
                        config.output_format,
                        payload,
                        render_v3_command_result,
                    ),
                    stdout=stdout,
                )
            payload_body = {}
            for field in ("status", "subject", "description", "priority", "lane_id"):
                value = getattr(args, field)
                if value is not None:
                    payload_body[field] = value
            payload = client.update_v3_task(args.task_id, payload_body)
            return _emit_response(
                args=args,
                client=client,
                payload=payload,
                rendered=_format_output(
                    config.output_format,
                    payload,
                    render_v3_command_result,
                ),
                stdout=stdout,
            )

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
            return _emit_response(
                args=args,
                client=client,
                payload=payload,
                rendered=_format_output(
                    config.output_format,
                    payload,
                    render_v3_command_result,
                ),
                stdout=stdout,
            )

        if args.resource == "approvals":
            if args.approvals_command == "pending":
                session_id = _require_value(
                    getattr(args, "command_session_id", None) or args.session_id,
                    "--session-id",
                )
                payload = client.get_v3_pending_approvals(session_id)
            else:
                payload = client.resolve_v3_approval(args.approval_id, args.decision)
            return _emit_response(
                args=args,
                client=client,
                payload=payload,
                rendered=render_json(payload),
                stdout=stdout,
            )
        if args.resource == "runtime":
            if args.runtime_command == "health":
                payload = client.get_v3_runtime_health()
                renderer = render_v3_runtime_health
            else:
                session_id = _require_value(
                    getattr(args, "command_session_id", None)
                    or args.session_id,
                    "--session-id",
                )
                if args.runtime_command == "drain":
                    if args.max_signals <= 0:
                        raise ValueError("--max-signals must be positive")
                    if args.max_steps_per_agent <= 0:
                        raise ValueError(
                            "--max-steps-per-agent must be positive"
                        )
                    payload = client.drain_v3_runtime(
                        session_id,
                        max_signals=args.max_signals,
                        max_steps_per_agent=args.max_steps_per_agent,
                        idempotency_key=args.idempotency_key,
                    )
                else:
                    payload = client.get_v3_runtime_command(
                        session_id,
                        args.command_id,
                    )
                renderer = render_v3_runtime_command
            return _emit_response(
                args=args,
                client=client,
                payload=payload,
                rendered=_format_output(config.output_format, payload, renderer),
                stdout=stdout,
            )
        if args.resource == "scientific":
            session_id = _require_value(
                getattr(args, "command_session_id", None) or args.session_id,
                "--session-id",
            )
            if args.scientific_command == "inspect":
                payload = client.get_v3_scientific_attempts(session_id)
            elif args.scientific_command == "export-evidence":
                payload = client.export_v3_closed_scientific_attempt_evidence(
                    session_id,
                    attempt_id=args.attempt_id,
                    selection_id=args.selection_id,
                )
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
            elif args.scientific_command == "inject-aox-reference-fault":
                payload = client.inject_v3_aox_reference_fault(
                    session_id,
                    attempt_id=args.attempt_id,
                    artifact_id=args.artifact_id,
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
            return _emit_response(
                args=args,
                client=client,
                payload=payload,
                rendered=render_json(payload),
                stdout=stdout,
            )
        raise ValueError(f"unsupported resource: {args.resource}")
    except (HostApiError, PublicReceiptError, json.JSONDecodeError, OSError, ValueError) as exc:
        stderr.write(f"{exc}\n")
        return 2
    finally:
        client.close()


def main() -> None:
    raise SystemExit(run_cli())
