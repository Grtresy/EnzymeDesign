from __future__ import annotations

import subprocess

from openzyme_core import CoreRepositories
from openzyme_core import apply_sqlite_migrations
from openzyme_core import connect_sqlite
from openzyme_host_api.dev_web_ui import _register_existing_sandbox_image


def _repositories() -> CoreRepositories:
    connection = connect_sqlite(":memory:")
    apply_sqlite_migrations(connection)
    return CoreRepositories.from_connection(connection)


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
