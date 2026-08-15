from __future__ import annotations

import argparse
from io import BytesIO
import hashlib
from pathlib import Path
import subprocess

import pytest

from openzyme_core import DurableLfsObjectStore
from openzyme_core import RepositoryIdentityMismatchError
from openzyme_host_api.repository_admin_cli import _read_only_audit
from openzyme_host_api.repository_restore_rehearsal import (
    capture_repository_service_state,
)
from openzyme_host_api.repository_restore_rehearsal import (
    rehearse_repository_service_restore,
)
from openzyme_host_api.repository_service_preflight import (
    RepositoryServicePreflightError,
)
from openzyme_host_api.repository_service_preflight import (
    preflight_repository_service,
)

from .repository_test_support import build_repository_test_fixture


def _file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_read_only_audit_does_not_migrate_or_mutate_database(tmp_path: Path) -> None:
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin="https://localhost:8443",
    )
    database = Path(fixture.provider.database_path)
    before = _file_digest(database)

    result = _read_only_audit(
        argparse.Namespace(
            database_path=database, binding_id=fixture.binding.binding_id
        )
    )

    assert result["query_only"] is True
    assert result["bindings"] == [
        {
            "project_id": "openzyme",
            "binding_id": fixture.binding.binding_id,
            "binding_version": 1,
            "repository_id": fixture.binding.repository_id,
            "default_base_commit": fixture.binding.default_base_commit,
            "canonical_digest": fixture.binding.canonical_digest,
            "lifecycle_status": "active",
            "session_pin_count": 1,
            "mapping_receipt_count": 0,
            "credential_record_count": 1,
            "private_namespace_count": 1,
        }
    ]
    assert _file_digest(database) == before


def test_preflight_rejects_inventory_and_hook_drift(tmp_path: Path) -> None:
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin="https://localhost:8443",
    )
    inventory = fixture.settings.binding_inventory_file.read_bytes()
    fixture.settings.binding_inventory_file.write_bytes(b"\xff")
    with pytest.raises(RepositoryServicePreflightError, match="valid UTF-8 JSON"):
        preflight_repository_service(
            settings=fixture.settings,
            provider=fixture.provider,
            roots=fixture.roots,
        )

    fixture.settings.binding_inventory_file.write_text("{}", encoding="utf-8")
    with pytest.raises(RepositoryServicePreflightError, match="closed schema"):
        preflight_repository_service(
            settings=fixture.settings,
            provider=fixture.provider,
            roots=fixture.roots,
        )

    fixture.settings.binding_inventory_file.write_bytes(inventory)
    hook = (
        fixture.roots.repository_path(fixture.binding.repository_id)
        / "hooks"
        / "pre-receive"
    )
    hook.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    with pytest.raises(RepositoryIdentityMismatchError, match="drifted"):
        preflight_repository_service(
            settings=fixture.settings,
            provider=fixture.provider,
            roots=fixture.roots,
        )


def test_restart_and_backup_restore_preserve_repository_universe(
    tmp_path: Path,
) -> None:
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin="https://localhost:8443",
    )
    content = b"durable repository rehearsal object\n"
    oid = hashlib.sha256(content).hexdigest()
    DurableLfsObjectStore(fixture.roots).put(
        fixture.binding.repository_id,
        oid,
        size=len(content),
        source=BytesIO(content),
    )
    private_ref = "refs/openzyme/private/rehearsal/checkpoint"
    subprocess.run(
        (
            str(fixture.settings.git_executable),
            "--git-dir",
            str(fixture.roots.repository_path(fixture.binding.repository_id)),
            "update-ref",
            private_ref,
            fixture.binding.default_base_commit,
        ),
        check=True,
    )
    before = capture_repository_service_state(
        provider=fixture.provider,
        roots=fixture.roots,
    )

    receipt = rehearse_repository_service_restore(
        settings=fixture.settings,
        database_path=Path(fixture.provider.database_path),
        boundary=fixture.dependencies.root_boundary,
        receipt_id="repository_restore_test_001",
        created_at="2026-08-15T19:00:00+00:00",
        created_by="operator:c1-test",
    )

    assert receipt["source_state_digest"] == before["state_digest"]
    assert receipt["restarted_state_digest"] == before["state_digest"]
    assert receipt["restored_state_digest"] == before["state_digest"]
    assert receipt["failure_domain_separated"] is False
    assert receipt["production_disaster_recovery_proven"] is False
    assert receipt["status"] == "passed_for_local_development"


def test_restore_rehearsal_rejects_nonquiescent_lfs_incoming(
    tmp_path: Path,
) -> None:
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin="https://localhost:8443",
    )
    incoming = (
        fixture.settings.lfs_object_root / fixture.binding.repository_id / "incoming"
    )
    incoming.mkdir(mode=0o700, parents=True)
    (incoming / "partial-upload").write_bytes(b"partial")

    with pytest.raises(RuntimeError, match="not quiescent"):
        rehearse_repository_service_restore(
            settings=fixture.settings,
            database_path=Path(fixture.provider.database_path),
            boundary=fixture.dependencies.root_boundary,
            receipt_id="repository_restore_test_nonquiescent",
            created_at="2026-08-15T19:01:00+00:00",
            created_by="operator:c1-test",
        )
