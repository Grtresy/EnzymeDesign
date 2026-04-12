from __future__ import annotations

from io import StringIO
from pathlib import Path

from fastapi.testclient import TestClient

from openzyme_host_api.app import HostApiDependencies
from openzyme_host_api.app import create_app
from openzyme_host_api.demo import build_demo_foundation
from openzyme_graph.supervisor import build_v2_supervisor_graph
from openzyme_host_cli.cli import run_cli


def _build_session(tmp_path: Path) -> TestClient:
    foundation = build_demo_foundation(sqlite_db_path=tmp_path / "cli-demo.sqlite3")
    app = create_app(
        HostApiDependencies(
            foundation=foundation,
            graph_builder=build_v2_supervisor_graph,
        )
    )
    return TestClient(app)


def test_cli_create_approve_and_read_report(tmp_path: Path) -> None:
    stdout = StringIO()
    stderr = StringIO()
    session = _build_session(tmp_path)

    try:
        exit_code = run_cli(
            [
                "--project-id",
                "proj_001",
                "episodes",
                "create",
                "--objective",
                "Design a thermostable enzyme demo candidate",
            ],
            session=session,
            stdout=stdout,
            stderr=stderr,
        )
        assert exit_code == 0
        created_output = stdout.getvalue()
        assert "Phase: design" in created_output
        episode_id = created_output.splitlines()[0].split()[-1]

        stdout.seek(0)
        stdout.truncate(0)
        exit_code = run_cli(
            ["--episode-id", episode_id, "episodes", "approve"],
            session=session,
            stdout=stdout,
            stderr=stderr,
        )
        assert exit_code == 0
        assert "Phase: execution" in stdout.getvalue()

        stdout.seek(0)
        stdout.truncate(0)
        exit_code = run_cli(
            ["--episode-id", episode_id, "episodes", "approve"],
            session=session,
            stdout=stdout,
            stderr=stderr,
        )
        assert exit_code == 0
        assert "Report:" in stdout.getvalue()

        stdout.seek(0)
        stdout.truncate(0)
        exit_code = run_cli(
            ["--episode-id", episode_id, "episodes", "reports"],
            session=session,
            stdout=stdout,
            stderr=stderr,
        )
        assert exit_code == 0
        assert "Reports" in stdout.getvalue()
        assert "status=ready" in stdout.getvalue()
    finally:
        session.close()
