from __future__ import annotations

from pathlib import Path

import pytest

from openzyme_host_api.repository_service_preflight import (
    RepositoryServicePreflightError,
)

from .repository_test_support import build_repository_test_fixture


def test_repository_preflight_requires_owner_only_control_plane_database(
    tmp_path: Path,
) -> None:
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin="https://localhost:8443",
    )
    database = Path(fixture.provider.database_path)

    report = fixture.dependencies.preflight()
    assert report.database["mode"] == "0600"
    assert "path" not in report.database

    database.chmod(0o644)
    with pytest.raises(RepositoryServicePreflightError, match="mode 0600"):
        fixture.dependencies.preflight()
