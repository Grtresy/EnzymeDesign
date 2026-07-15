from __future__ import annotations

import subprocess

from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_host_api.dev_web_ui import _build_v3_repository_provider
from openzyme_host_api.dev_web_ui import _register_existing_sandbox_image
from openzyme_host_api.dev_web_ui import build_parser


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


def test_web_ui_parser_exposes_only_v3_sqlite_database() -> None:
    destinations = {action.dest for action in build_parser()._actions}

    assert "sqlite_db" not in destinations
    assert "v3_sqlite_db" in destinations
    assert "configured" not in destinations
    assert "fixture_non_cutover" in destinations
    assert build_parser().parse_args([]).fixture_non_cutover is False


def test_configured_web_ui_registers_existing_sandbox_image(monkeypatch) -> None:
    repositories = _repositories()
    monkeypatch.setattr("openzyme_host_api.dev_web_ui.shutil.which", lambda binary: "/usr/bin/podman")

    def fake_run(args, **kwargs):
        del kwargs
        if args[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(args, 0, stdout="", stderr="")
        if args[:3] == ["podman", "image", "inspect"]:
            return subprocess.CompletedProcess(args, 0, stdout="sha256:configured\n", stderr="")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("openzyme_host_api.dev_web_ui.subprocess.run", fake_run)

    _register_existing_sandbox_image(repositories)

    image = repositories.sandbox_images.get_default()
    assert image is not None
    assert image.image_ref == "localhost/openzyme-pipeline-sandbox:dev"
    assert image.image_digest == "sha256:configured"


def test_configured_web_ui_does_not_build_missing_sandbox_image(monkeypatch) -> None:
    repositories = _repositories()
    monkeypatch.setattr("openzyme_host_api.dev_web_ui.shutil.which", lambda binary: "/usr/bin/podman")

    def fake_run(args, **kwargs):
        del kwargs
        if args[:3] == ["podman", "image", "exists"]:
            return subprocess.CompletedProcess(args, 1, stdout="", stderr="missing")
        raise AssertionError(f"unexpected command: {args}")

    monkeypatch.setattr("openzyme_host_api.dev_web_ui.subprocess.run", fake_run)

    _register_existing_sandbox_image(repositories)

    assert repositories.sandbox_images.get_default() is None


def test_build_v3_repository_provider_reports_legacy_sqlite_database(tmp_path) -> None:
    sqlite_db_path = tmp_path / "legacy-v3.sqlite3"
    connection = connect_sqlite(str(sqlite_db_path))
    connection.execute("CREATE TABLE legacy_state (id TEXT PRIMARY KEY)")
    connection.commit()
    connection.close()

    try:
        _build_v3_repository_provider(sqlite_db_path)
    except SystemExit as exc:
        message = str(exc)
    else:
        raise AssertionError("expected legacy V3 SQLite startup to fail")

    assert str(sqlite_db_path) in message
    assert "--v3-sqlite-db" in message
    assert "Manually delete the database file" in message
    assert sqlite_db_path.exists()

    verify = connect_sqlite(str(sqlite_db_path))
    table_names = {
        row[0]
        for row in verify.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    user_version = verify.execute("PRAGMA user_version").fetchone()[0]
    verify.close()
    assert "legacy_state" in table_names
    assert "sessions" not in table_names
    assert user_version == 0
