from __future__ import annotations

from io import StringIO

from openzyme_host_cli.cli import run_cli


class FakeSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str, object | None]] = []

    def get(self, url: str, **kwargs):
        self.calls.append(("GET", url, None))
        return FakeResponse(
            200,
            [{"project_id": "proj_001", "name": "Demo project"}] if url == "/projects" else [],
        )

    def post(self, url: str, **kwargs):
        self.calls.append(("POST", url, kwargs.get("json")))
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
                            "message": "Waiting for candidate review approval",
                        },
                        "summary": {
                            "evidence_count": 2,
                            "candidate_count": 2,
                            "selected_candidate_id": "cand_001",
                            "report_id": None,
                            "report_status": None,
                        },
                    },
                    "pending_actions": [],
                },
                "events": [],
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


def test_cli_lists_projects_in_text_mode() -> None:
    stdout = StringIO()
    exit_code = run_cli(["projects", "list"], session=FakeSession(), stdout=stdout, stderr=StringIO())

    assert exit_code == 0
    assert "Projects" in stdout.getvalue()
    assert "proj_001: Demo project" in stdout.getvalue()


def test_cli_uses_env_defaults_and_wires_create_command(monkeypatch) -> None:
    monkeypatch.setenv("OPENZYME_PROJECT_ID", "proj_001")
    stdout = StringIO()
    stderr = StringIO()
    session = FakeSession()

    exit_code = run_cli(
        ["episodes", "create", "--objective", "Design a candidate"],
        session=session,
        stdout=stdout,
        stderr=stderr,
    )

    assert exit_code == 0
    assert session.calls[-1] == (
        "POST",
        "/commands/create_episode",
        {"project_id": "proj_001", "objective": "Design a candidate"},
    )
    assert "Episode ep_001" in stdout.getvalue()


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
