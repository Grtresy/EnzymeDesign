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
from .renderers import render_command_result
from .renderers import render_episode_list
from .renderers import render_json
from .renderers import render_projects
from .renderers import render_records
from .renderers import render_workspace


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="openzyme", description="Thin V2 OpenZyme Host CLI")
    parser.add_argument("--host", dest="base_url", help="Host API base URL")
    parser.add_argument("--project-id", help="Default project ID")
    parser.add_argument("--episode-id", help="Default episode ID")
    parser.add_argument(
        "--format",
        choices=("text", "json"),
        default=None,
        help="Output format",
    )

    subparsers = parser.add_subparsers(dest="resource", required=True)

    projects = subparsers.add_parser("projects", help="Project queries")
    project_sub = projects.add_subparsers(dest="projects_command", required=True)
    project_sub.add_parser("list", help="List projects")
    project_episodes = project_sub.add_parser("episodes", help="List episodes for a project")
    project_episodes.add_argument("--project-id", dest="command_project_id", help="Project ID override")

    episodes = subparsers.add_parser("episodes", help="Episode commands and queries")
    episode_sub = episodes.add_subparsers(dest="episodes_command", required=True)

    create = episode_sub.add_parser("create", help="Create and auto-run an episode")
    create.add_argument("--project-id", dest="command_project_id", help="Project ID override")
    create.add_argument("--objective", required=True, help="Episode objective")

    show = episode_sub.add_parser("show", help="Show workspace summary")
    show.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")

    resume = episode_sub.add_parser("resume", help="Resume an interrupted episode")
    resume.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")
    resume.add_argument(
        "--resume-json",
        default='{"approved": true}',
        help="JSON payload to send to /commands/resume_episode",
    )

    approve = episode_sub.add_parser("approve", help="Approve the pending action for an episode")
    approve.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")
    approve.add_argument("--approval-id", help="Approval ID override")

    reject = episode_sub.add_parser("reject", help="Reject the pending action for an episode")
    reject.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")
    reject.add_argument("--approval-id", help="Approval ID override")

    runs = episode_sub.add_parser("runs", help="List run records")
    runs.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")

    artifacts = episode_sub.add_parser("artifacts", help="List artifact records")
    artifacts.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")

    reports = episode_sub.add_parser("reports", help="List report records")
    reports.add_argument("--episode-id", dest="command_episode_id", help="Episode ID override")

    return parser


def _resolve_config(args: argparse.Namespace) -> HostCliConfig:
    env_config = HostCliConfig.from_env()
    return HostCliConfig(
        base_url=args.base_url or env_config.base_url,
        project_id=getattr(args, "project_id", None) or env_config.project_id,
        episode_id=getattr(args, "episode_id", None) or env_config.episode_id,
        output_format=args.format or env_config.output_format,
    )


def _require_value(value: str | None, flag_name: str) -> str:
    if value:
        return value
    raise ValueError(f"{flag_name} is required (flag or environment default)")


def _resolve_approval_id(client: HostApiClient, episode_id: str, explicit_approval_id: str | None) -> str:
    if explicit_approval_id:
        return explicit_approval_id
    pending = client.get_pending_actions(episode_id)
    if not pending:
        raise ValueError(f"episode {episode_id!r} has no pending approvals")
    return str(pending[0]["approval_id"])


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
    client = HostApiClient(config.base_url, session=session)
    try:
        if args.resource == "projects":
            if args.projects_command == "list":
                payload = client.list_projects()
                stdout.write(_format_output(config.output_format, payload, render_projects) + "\n")
                return 0
            project_id = _require_value(
                getattr(args, "command_project_id", None) or args.project_id or config.project_id,
                "--project-id",
            )
            payload = client.list_project_episodes(project_id)
            stdout.write(_format_output(config.output_format, payload, render_episode_list) + "\n")
            return 0

        episode_id = (
            _require_value(
                getattr(args, "command_episode_id", None) or args.episode_id or config.episode_id,
                "--episode-id",
            )
            if args.episodes_command not in {"create"}
            else None
        )

        if args.episodes_command == "create":
            project_id = _require_value(
                getattr(args, "command_project_id", None) or args.project_id or config.project_id,
                "--project-id",
            )
            payload = client.create_episode(project_id, args.objective)
            stdout.write(_format_output(config.output_format, payload, render_command_result) + "\n")
            return 0
        if args.episodes_command == "show":
            payload = client.get_workspace(str(episode_id))
            stdout.write(_format_output(config.output_format, payload, render_workspace) + "\n")
            return 0
        if args.episodes_command == "resume":
            resume_payload = json.loads(args.resume_json)
            payload = client.resume_episode(str(episode_id), resume_payload)
            stdout.write(_format_output(config.output_format, payload, render_command_result) + "\n")
            return 0
        if args.episodes_command in {"approve", "reject"}:
            decision = "approved" if args.episodes_command == "approve" else "rejected"
            approval_id = _resolve_approval_id(client, str(episode_id), args.approval_id)
            payload = client.resolve_approval(str(episode_id), approval_id, decision)
            stdout.write(_format_output(config.output_format, payload, render_command_result) + "\n")
            return 0
        if args.episodes_command == "runs":
            payload = client.get_runs(str(episode_id))
            stdout.write(
                _format_output(
                    config.output_format,
                    payload,
                    lambda rows: render_records("Runs", rows, ("run_id", "status", "execution_mode")),
                )
                + "\n"
            )
            return 0
        if args.episodes_command == "artifacts":
            payload = client.get_artifacts(str(episode_id))
            stdout.write(
                _format_output(
                    config.output_format,
                    payload,
                    lambda rows: render_records("Artifacts", rows, ("artifact_id", "kind", "storage_uri")),
                )
                + "\n"
            )
            return 0
        if args.episodes_command == "reports":
            payload = client.get_reports(str(episode_id))
            stdout.write(
                _format_output(
                    config.output_format,
                    payload,
                    lambda rows: render_records("Reports", rows, ("report_id", "status", "artifact_id")),
                )
                + "\n"
            )
            return 0
        raise ValueError(f"unsupported command: {args.episodes_command}")
    except (HostApiError, ValueError, json.JSONDecodeError) as exc:
        stderr.write(f"{exc}\n")
        return 2
    finally:
        client.close()


def main() -> None:
    raise SystemExit(run_cli())
