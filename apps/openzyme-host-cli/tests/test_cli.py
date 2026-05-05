from __future__ import annotations

from io import StringIO

from openzyme_host_cli.cli import run_cli
from openzyme_runtime import reset_settings_cache


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None]] = []

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, None))
        if url.startswith("/v3/sessions/") and url.endswith("/workspace"):
            return FakeResponse(200, build_v3_workspace())
        return FakeResponse(
            200,
            [{"project_id": "proj_001", "name": "Demo project"}] if url == "/projects" else [],
        )

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs.get("json")))
        if url.startswith("/v3/"):
            return FakeResponse(
                200,
                {
                    "session_id": "sess_001",
                    "status": "completed",
                    "outputs": ["Received: hello"],
                    "workspace": build_v3_workspace(),
                    "events": [{"event_type": "conversation.assistant_message"}],
                },
            )
        return FakeResponse(
            200,
            {
                "episode_id": "ep_001",
                "workspace": {
                    "episode_id": "ep_001",
                    "workflow": {
                        "current_phase": "design",
                        "status": "interrupted",
                        "updated_at": "2026-04-12T00:00:00+00:00",
                        "progress": {
                            "active_node": "design_review_gate",
                            "message": "Waiting for design workspace review approval",
                        },
                        "summary": {
                            "evidence_count": 2,
                            "artifact_count": 3,
                            "focused_artifact_count": 2,
                            "report_id": None,
                            "report_status": None,
                        },
                    },
                    "pending_actions": [],
                },
                "events": [],
            },
        )

    def patch(self, url: str, **kwargs):
        self.calls.append(("PATCH", url, kwargs.get("json")))
        return FakeResponse(
            200,
            {
                "task": {
                    "task_id": "task_001",
                    "session_id": "sess_001",
                    "subject": "Task",
                    "description": "",
                    "status": "in_progress",
                    "priority": "normal",
                    "kind": "general",
                    "assigned_ref": None,
                    "lane_id": None,
                    "blocked_by": [],
                    "created_at": "2026-04-20T00:00:00+00:00",
                    "updated_at": "2026-04-20T00:00:00+00:00",
                },
                "workspace": build_v3_workspace(),
                "events": [{"event_type": "task.updated"}],
            },
        )

    def close(self) -> None:
        return None


class FakeResponse:
    def __init__(self, status_code: int, payload) -> None:
        self.status_code = status_code
        self._payload = payload
        self.text = ""

    def json(self):
        return self._payload


def build_v3_workspace() -> dict[str, object]:
    return {
        "session": {
            "session_id": "sess_001",
            "project_id": "proj_001",
            "title": "V3",
            "objective": "Plan with V3",
            "status": "active",
            "created_at": "2026-04-20T00:00:00+00:00",
            "updated_at": "2026-04-20T00:00:00+00:00",
        },
        "task_board": {
            "items": [
                {
                    "task": {
                        "task_id": "task_001",
                        "subject": "Task",
                        "status": "todo",
                    },
                    "bucket": "ready",
                }
            ]
        },
        "lane_board": {"lanes": []},
        "pending_approvals": [],
        "reports": [],
    }


def test_cli_lists_projects_in_text_mode() -> None:
    stdout = StringIO()
    exit_code = run_cli(["projects", "list"], session=FakeSession(), stdout=stdout, stderr=StringIO())

    assert exit_code == 0
    assert "Projects" in stdout.getvalue()
    assert "proj_001: Demo project" in stdout.getvalue()


def test_cli_uses_env_defaults_and_wires_create_command(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_PROJECT_ID", "proj_001")
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["episodes", "create", "--objective", "Design an artifact workspace"],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/commands/create_episode",
        {"project_id": "proj_001", "objective": "Design an artifact workspace"},
    )
    assert "Episode ep_001" in stdout.getvalue()
    reset_settings_cache()


def test_cli_json_format_renders_raw_payload() -> None:
    stdout = StringIO()
    exit_code = run_cli(
        ["--format", "json", "projects", "list"],
        session=FakeSession(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert '"project_id": "proj_001"' in stdout.getvalue()


def test_cli_v3_sessions_create_and_message() -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        [
            "sessions",
            "create",
            "--project-id",
            "proj_001",
            "--session-id",
            "sess_001",
            "--objective",
            "Plan with V3",
        ],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/v3/sessions",
        {"project_id": "proj_001", "objective": "Plan with V3", "session_id": "sess_001"},
    )
    assert "Session sess_001" in stdout.getvalue()

    stdout = StringIO()
    exit_code = run_cli(
        ["sessions", "message", "--session-id", "sess_001", "--message", "hello"],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == ("POST", "/v3/sessions/sess_001/messages", {"message": "hello"})
    assert "Received: hello" in stdout.getvalue()


def test_cli_v3_task_update_uses_patch() -> None:
    stdout = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["tasks", "update", "--task-id", "task_001", "--status", "in_progress"],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == ("PATCH", "/v3/tasks/task_001", {"status": "in_progress"})
