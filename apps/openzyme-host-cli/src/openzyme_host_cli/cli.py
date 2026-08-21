from __future__ import annotations

import argparse
from pathlib import Path
import sys
from typing import TextIO

from openzyme_client import OpenZymeClientContractError

from .config import HostCliConfig
from .renderers import render_json
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
    message.add_argument("--skill-key", action="append", default=[])

    runtime = resources.add_parser("runtime", help="Runtime commands")
    runtime_commands = runtime.add_subparsers(dest="runtime_command", required=True)
    drain = runtime_commands.add_parser(
        "drain",
        help="Submit one bounded runtime drain command",
    )
    drain.add_argument("--session-id", dest="command_session_id")
    drain.add_argument("--max-signals", type=int, default=3)
    drain.add_argument("--max-steps-per-agent", type=int, default=8)
    drain.add_argument("--idempotency-key")
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
                        skill_keys=tuple(args.skill_key),
                        idempotency_key=_require_idempotency_key(
                            args.idempotency_key
                        ),
                    )
                    rendered = render_json(payload)
                else:
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
            stdout.write(rendered + "\n")
            return 0
        finally:
            client.close()
    except (OpenZymeClientContractError, OSError, ValueError) as exc:
        stderr.write(f"{exc}\n")
        return 2


def main() -> None:
    raise SystemExit(run_cli())
