from __future__ import annotations

from io import StringIO

from openzyme_host_cli.cli import run_cli
from openzyme_runtime import reset_settings_cache


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None]] = []
        self.last_headers: dict[str, str] = {}

    def get(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("GET", url, None))
        if url == "/v3/runtime/health":
            return FakeResponse(
                200,
                {
                    "schema_version": "v3.runtime_health.v1",
                    "status": "degraded",
                    "deployment_profile": "local-dev",
                    "storage_profile": "single_process_sqlite",
                    "observed_at": "2026-07-16T00:00:00+00:00",
                    "components": {
                        "control_plane": {"status": "ready", "details": {}},
                        "model": {"status": "unavailable", "details": {}},
                    },
                },
            )
        if url.startswith("/v3/sessions/") and url.endswith("/workspace"):
            return FakeResponse(200, build_v3_workspace())
        return FakeResponse(200, [])

    def post(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("POST", url, kwargs.get("json")))
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

    def patch(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
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


def test_cli_uses_env_defaults_and_wires_session_create(monkeypatch) -> None:
    reset_settings_cache()
    monkeypatch.setenv("OPENZYME_PROJECT_ID", "proj_001")
    monkeypatch.setenv("OPENZYME_HOST_AUTH_TOKEN", "cli-secret-token")
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["sessions", "create", "--objective", "Design an artifact workspace"],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/v3/sessions",
        {"project_id": "proj_001", "objective": "Design an artifact workspace"},
    )
    assert "Session sess_001" in stdout.getvalue()
    assert session.last_headers["Authorization"] == "Bearer cli-secret-token"
    assert session.last_headers["Idempotency-Key"].startswith("cli-")
    reset_settings_cache()


def test_cli_json_format_renders_raw_payload() -> None:
    stdout = StringIO()
    exit_code = run_cli(
        [
            "--format",
            "json",
            "sessions",
            "create",
            "--project-id",
            "proj_001",
            "--objective",
            "Plan with V3",
        ],
        session=FakeSession(),
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert '"session_id": "sess_001"' in stdout.getvalue()


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


def test_cli_lane_claim_uses_server_owned_actor() -> None:
    session = FakeSession()

    exit_code = run_cli(
        ["lanes", "claim", "--lane-id", "lane_001"],
        session=session,
        stdout=StringIO(),
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == ("POST", "/v3/lanes/lane_001/claim", {})


def test_cli_runtime_health_renders_public_projection() -> None:
    stdout = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["runtime", "health"],
        session=session,
        stdout=stdout,
        stderr=StringIO(),
    )

    assert exit_code == 0
    assert session.calls[-1] == ("GET", "/v3/runtime/health", None)
    rendered = stdout.getvalue()
    assert "Runtime: degraded" in rendered
    assert "control_plane: ready" in rendered
    assert "model: unavailable" in rendered


class ErrorSession(FakeSession):
    def post(self, url: str, **kwargs):
        self.last_headers = dict(kwargs.get("headers") or {})
        self.calls.append(("POST", url, kwargs.get("json")))
        return FakeResponse(
            422,
            {
                "error": {
                    "code": "request_validation_error",
                    "message": "Request payload failed validation.",
                }
            },
        )


def test_cli_renders_structured_host_error() -> None:
    stderr = StringIO()

    exit_code = run_cli(
        [
            "sessions",
            "create",
            "--project-id",
            "proj_001",
            "--objective",
            "Invalid request",
        ],
        session=ErrorSession(),
        stdout=StringIO(),
        stderr=stderr,
    )

    assert exit_code == 2
    assert "request_validation_error: Request payload failed validation." in stderr.getvalue()
