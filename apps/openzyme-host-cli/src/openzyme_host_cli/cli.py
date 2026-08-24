from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TextIO

from openzyme_client import OpenZymeClientContractError

from .config import HostCliConfig
from .renderers import render_json
from .renderers import render_v3_fact
from .renderers import render_v3_records
from .renderers import render_v3_workspace_v2
from .v2_client import HostApiV2Client
from .v2_client import HttpSessionProtocol
from .v2_client import load_expected_release_identity


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="openzyme",
        description="OpenZyme exact file_workspace_public@2 Host CLI",
    )
    parser.add_argument("--host", dest="base_url", help="Host API base URL")
    parser.add_argument("--project-id", help="Default project ID")
    parser.add_argument("--session-id", help="Default Session ID")
    parser.add_argument(
        "--release-identity",
        type=Path,
        help="operator-pinned exact @2 layered release identity",
    )
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default=None,
        help="Output format",
    )

    resources = parser.add_subparsers(dest="resource", required=True)
    sessions = resources.add_parser("sessions", help="Session commands")
    session_commands = sessions.add_subparsers(
        dest="sessions_command",
        required=True,
    )
    create = session_commands.add_parser("create", help="Create a Session")
    create.add_argument("--project-id", dest="command_project_id")
    create.add_argument("--session-id", dest="command_session_id")
    create.add_argument("--objective", required=True)
    create.add_argument("--title")
    create.add_argument("--idempotency-key")

    show = session_commands.add_parser("show", help="Inspect one Session workspace")
    show.add_argument("--session-id", dest="command_session_id")

    message = session_commands.add_parser("message", help="Send a user message")
    message.add_argument("--session-id", dest="command_session_id")
    message.add_argument("--message", required=True)
    message.add_argument("--task-id")
    message.add_argument("--lane-id")
    message.add_argument("--idempotency-key")
    message.add_argument("--workflow-ref", action="append", default=[])
    message.add_argument("--skill-key", action="append", default=[])

    for resource_name, help_text in (
        ("conversation", "Inspect the canonical user/assistant/tool transcript"),
        ("tasks", "Inspect the canonical Task board"),
        ("agents", "Inspect resident Agent members"),
        ("failures", "Inspect public-safe failure observations"),
        ("readiness", "Inspect resident readiness and provisioning truth"),
        ("workspace", "Inspect canonical workspace truth"),
        ("tool-exposure", "Inspect Direct/Deferred public tool exposure"),
    ):
        view = resources.add_parser(resource_name, help=help_text)
        view.add_argument("--session-id", dest="command_session_id")
    approvals = resources.add_parser(
        "approvals",
        help="Inspect or decide canonical approval truth",
    )
    approvals.add_argument("--session-id", dest="command_session_id")
    approval_commands = approvals.add_subparsers(dest="approvals_command")
    show_approvals = approval_commands.add_parser("show", help="Inspect approval truth")
    show_approvals.add_argument(
        "--session-id",
        dest="command_session_id",
        default=argparse.SUPPRESS,
    )
    decide = approval_commands.add_parser(
        "decide",
        help="Resolve one exact pending approval without running the Agent",
    )
    decide.add_argument("--approval-id", required=True)
    decide.add_argument("--decision", choices=("approved", "rejected"), required=True)
    decide.add_argument("--idempotency-key")
    decide.add_argument(
        "--session-id",
        dest="command_session_id",
        default=argparse.SUPPRESS,
    )
    protocol = resources.add_parser(
        "protocol",
        help="Inspect delegations/protocol records or inbox delivery",
    )
    protocol.add_argument("--session-id", dest="command_session_id")
    protocol.add_argument(
        "--view",
        choices=("delegations", "inbox"),
        default="delegations",
    )

    runtime = resources.add_parser("runtime", help="Runtime commands")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    show_runtime = runtime_commands.add_parser(
        "show",
        help="Inspect canonical runtime command/outcome truth",
    )
    show_runtime.add_argument("--session-id", dest="command_session_id")
    drain = runtime_commands.add_parser(
        "drain",
        help="Submit one bounded runtime drain command",
    )
    drain.add_argument("--session-id", dest="command_session_id")
    drain.add_argument("--max-signals", type=int, default=3)
    drain.add_argument("--max-steps-per-agent", type=int, default=8)
    drain.add_argument("--idempotency-key")
    status = runtime_commands.add_parser(
        "status",
        help="Poll one durable runtime command without resubmitting it",
    )
    status.add_argument("--session-id", dest="command_session_id")
    status.add_argument("--command-id", required=True)

    provisioning = resources.add_parser(
        "provisioning",
        help="Explicit workspace provisioning recovery commands",
    )
    provisioning_commands = provisioning.add_subparsers(
        dest="provisioning_command",
        required=True,
    )
    reconcile = provisioning_commands.add_parser(
        "reconcile",
        help="Admit one exact dispatch-in-doubt reconciliation request",
    )
    reconcile.add_argument("--session-id", dest="command_session_id")
    reconcile.add_argument("--expected-intent-version", type=int)
    reconcile.add_argument("--claim-seconds", type=int, default=300)
    reconcile.add_argument("--idempotency-key")
    successor = provisioning_commands.add_parser(
        "successor",
        help="Create one pending successor workspace generation",
    )
    successor.add_argument("--session-id", dest="command_session_id")
    successor.add_argument("--expected-failed-intent-version", type=int)
    successor.add_argument("--resolved-reconciliation-id")
    successor.add_argument("--idempotency-key")
    return parser


def _resolve_config(args: argparse.Namespace) -> HostCliConfig:
    environment = HostCliConfig.from_env()
    return HostCliConfig(
        base_url=args.base_url or environment.base_url,
        project_id=args.project_id or environment.project_id,
        output_format=args.format or environment.output_format,
        auth_token=environment.auth_token,
        release_identity_path=(
            args.release_identity or environment.release_identity_path
        ),
    )


def _require_value(value: str | None, flag_name: str) -> str:
    if value:
        return value
    raise OpenZymeClientContractError(
        "cli_required_argument_missing",
        f"{flag_name} is required (flag or environment default)",
    )


def _require_idempotency_key(value: str | None) -> str:
    if value:
        return value
    raise OpenZymeClientContractError(
        "cli_v2_idempotency_key_required",
        "exact @2 mutations require an explicit --idempotency-key",
    )


def run_cli(
    argv: list[str] | None = None,
    *,
    session: HttpSessionProtocol | None = None,
    stdout: TextIO | None = None,
    stderr: TextIO | None = None,
) -> int:
    args = _build_parser().parse_args(argv)
    stdout = stdout or sys.stdout
    stderr = stderr or sys.stderr
    config = _resolve_config(args)
    try:
        if config.release_identity_path is None:
            raise OpenZymeClientContractError(
                "cli_release_identity_required",
                "exact @2 mode requires one operator-pinned release identity",
            )
        release = load_expected_release_identity(config.release_identity_path)
        client = HostApiV2Client(
            config.base_url,
            expected_release=release,
            auth_token=config.auth_token,
            session=session,
        )
        try:
            if args.resource == "sessions" and args.sessions_command == "create":
                project_id = _require_value(
                    args.command_project_id or args.project_id or config.project_id,
                    "--project-id",
                )
                session_id = _require_value(
                    args.command_session_id or args.session_id,
                    "--session-id",
                )
                payload = client.create_session(
                    project_id=project_id,
                    session_id=session_id,
                    objective=args.objective,
                    title=args.title,
                    idempotency_key=_require_idempotency_key(args.idempotency_key),
                )
                rendered = render_json(payload)
            else:
                session_id = _require_value(
                    args.command_session_id or args.session_id,
                    "--session-id",
                )
                if args.resource == "sessions" and args.sessions_command == "show":
                    projection, _ = client.inspect_workspace(session_id)
                    payload = projection.to_dict()
                    rendered = (
                        render_json(payload)
                        if config.output_format == "json"
                        else render_v3_workspace_v2(payload)
                    )
                elif args.resource == "sessions":
                    payload = client.post_message(
                        session_id,
                        message=args.message,
                        task_id=args.task_id,
                        lane_id=args.lane_id,
                        workflow_refs=tuple(args.workflow_ref),
                        skill_keys=tuple(args.skill_key),
                        idempotency_key=_require_idempotency_key(
                            args.idempotency_key
                        ),
                    )
                    rendered = render_json(payload)
                elif args.resource == "runtime" and args.runtime_command == "drain":
                    if args.max_signals <= 0 or args.max_steps_per_agent <= 0:
                        raise OpenZymeClientContractError(
                            "cli_runtime_budget_invalid",
                            "runtime drain budgets must be positive",
                        )
                    payload = client.drain_runtime(
                        session_id,
                        max_signals=args.max_signals,
                        max_steps_per_agent=args.max_steps_per_agent,
                        idempotency_key=_require_idempotency_key(
                            args.idempotency_key
                        ),
                    )
                    rendered = render_json(payload)
                elif args.resource == "runtime" and args.runtime_command == "status":
                    payload = client.inspect_runtime_command(
                        session_id,
                        command_id=args.command_id,
                    )
                    rendered = render_json(payload)
                elif (
                    args.resource == "provisioning"
                    and args.provisioning_command == "reconcile"
                ):
                    payload = client.reconcile_workspace_provisioning(
                        session_id,
                        expected_intent_version=args.expected_intent_version,
                        claim_seconds=args.claim_seconds,
                        idempotency_key=_require_idempotency_key(
                            args.idempotency_key
                        ),
                    )
                    rendered = render_json(payload)
                elif (
                    args.resource == "provisioning"
                    and args.provisioning_command == "successor"
                ):
                    payload = client.create_workspace_provisioning_successor(
                        session_id,
                        expected_failed_intent_version=(
                            args.expected_failed_intent_version
                        ),
                        resolved_reconciliation_id=(
                            args.resolved_reconciliation_id
                        ),
                        idempotency_key=_require_idempotency_key(
                            args.idempotency_key
                        ),
                    )
                    rendered = render_json(payload)
                elif (
                    args.resource == "approvals"
                    and args.approvals_command == "decide"
                ):
                    payload = client.decide_approval(
                        session_id,
                        approval_id=args.approval_id,
                        decision=args.decision,
                        idempotency_key=_require_idempotency_key(
                            args.idempotency_key
                        ),
                    )
                    rendered = render_json(payload)
                else:
                    projection, _ = client.inspect_workspace(session_id)
                    core = projection.to_dict()["core"]
                    if args.resource == "conversation":
                        title = "Canonical conversation transcript"
                        records = core["conversation"]["transcript"]["messages"]
                    elif args.resource == "tasks":
                        title = "Canonical Task board"
                        records = core["tasks"]
                    elif args.resource == "agents":
                        title = "Resident Agent members"
                        records = core["agents"]
                    elif args.resource == "protocol":
                        title = (
                            "Protocol inbox"
                            if args.view == "inbox"
                            else "Delegations and protocol records"
                        )
                        records = core["protocol"][
                            "inbox" if args.view == "inbox" else "records"
                        ]
                    elif args.resource == "approvals":
                        title = "Approval truth"
                        records = core["approvals"]
                    elif args.resource == "failures":
                        title = "Public-safe failure observations"
                        records = core["failures"]["observations"]
                    else:
                        if args.resource == "readiness":
                            title = "Resident readiness and workspace provisioning"
                            fact = {
                                "resident_readiness": core["session"][
                                    "resident_readiness"
                                ],
                                "provisioning": core["workspace"]["provisioning"],
                            }
                        elif args.resource == "workspace":
                            title = "Canonical workspace truth"
                            fact = core["workspace"]
                        elif args.resource == "tool-exposure":
                            title = "Direct and Deferred tool exposure"
                            fact = {
                                "available_tool_names": core["tool_reflection"][
                                    "available_tool_names"
                                ],
                                "affordances": core["tool_reflection"]["affordances"],
                                "tool_exposure": core["tool_reflection"][
                                    "tool_exposure"
                                ],
                            }
                        else:
                            title = "Canonical runtime truth"
                            fact = core["runtime"]
                        payload = {
                            "schema_version": "openzyme_cli_projection_view@1",
                            "session_id": session_id,
                            "view": args.resource,
                            "fact": fact,
                        }
                        rendered = (
                            render_json(payload)
                            if config.output_format == "json"
                            else render_v3_fact(title, fact)
                        )
                        stdout.write(rendered + "\n")
                        return 0
                    payload = {
                        "schema_version": "openzyme_cli_projection_view@1",
                        "session_id": session_id,
                        "view": args.resource,
                        "records": records,
                    }
                    rendered = (
                        render_json(payload)
                        if config.output_format == "json"
                        else render_v3_records(title, records)
                    )
            stdout.write(rendered + "\n")
            return 0
        finally:
            client.close()
    except (OpenZymeClientContractError, OSError, ValueError) as exc:
        stderr.write(f"{exc}\n")
        return 2


def main() -> None:
    raise SystemExit(run_cli())
