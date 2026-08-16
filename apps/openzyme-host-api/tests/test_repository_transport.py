from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

from fastapi import Request
from fastapi.testclient import TestClient
import pytest

from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import DurableLfsObjectStore
from openzyme_core import GitLfsGarbageCollector
from openzyme_core import GitLfsPrivateReachabilityFinalizer
from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_domain import GitObjectFormat
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import RepositoryRefNamespacePolicy
from openzyme_domain import Session
from openzyme_host_api.repository_transport import RepositoryTransportDependencies
from openzyme_host_api.repository_transport import _git_backend_response
from openzyme_host_api.repository_transport import _settle_git_request_task
from openzyme_host_api.repository_transport import create_repository_transport_app
from openzyme_runtime import RepositoryServiceSettings
from openzyme_runtime import OpenZymeSettings
from openzyme_runtime import RuntimeFoundation
from openzyme_host_api import HostApiDependencies
from openzyme_host_api import create_app

from .repository_test_support import build_repository_test_fixture


def _settings(root: Path) -> RepositoryServiceSettings:
    git_root = root / "git"
    lfs_root = root / "lfs"
    backup_root = root / "backup"
    for path in (git_root, lfs_root, backup_root):
        path.mkdir(parents=True)
        path.chmod(0o700)
    key = root / "repository-token.key"
    key.write_bytes(b"repository-transport-test-key" * 3)
    key.chmod(0o600)
    openssl = shutil.which("openssl")
    if openssl is None:
        raise RuntimeError("repository transport tests require openssl")
    tls_key = root / "localhost.key"
    tls_certificate = root / "localhost.crt"
    subprocess.run(
        (
            openssl,
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-nodes",
            "-keyout",
            str(tls_key),
            "-out",
            str(tls_certificate),
            "-days",
            "1",
            "-subj",
            "/CN=localhost",
            "-addext",
            "subjectAltName=DNS:localhost,IP:127.0.0.1",
        ),
        check=True,
        capture_output=True,
    )
    tls_key.chmod(0o600)
    git_lfs = shutil.which("git-lfs")
    if git_lfs is None:
        raise RuntimeError("repository transport tests require git-lfs")
    return RepositoryServiceSettings(
        https_origin="https://localhost:8443",
        bare_repository_root=git_root,
        lfs_object_root=lfs_root,
        backup_root=backup_root,
        credential_signing_key_file=key,
        tls_certificate_file=tls_certificate,
        tls_private_key_file=tls_key,
        binding_inventory_file=root / "bindings.json",
        git_executable=Path("/usr/bin/git"),
        git_lfs_executable=Path(git_lfs),
        git_http_backend=Path("/usr/lib/git-core/git-http-backend"),
        credential_ttl_seconds=600,
    )


def _source(root: Path) -> tuple[Path, str]:
    source = root / "source"
    source.mkdir()
    subprocess.run(
        ("/usr/bin/git", "init", str(source)), check=True, capture_output=True
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "config", "user.name", "C1 Test"),
        check=True,
    )
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "config", "user.email", "c1@test"),
        check=True,
    )
    (source / "README.md").write_text("repository transport\n", encoding="utf-8")
    subprocess.run(("/usr/bin/git", "-C", str(source), "add", "README.md"), check=True)
    subprocess.run(
        ("/usr/bin/git", "-C", str(source), "commit", "-m", "seed"),
        check=True,
        capture_output=True,
    )
    commit = subprocess.run(
        ("/usr/bin/git", "-C", str(source), "rev-parse", "HEAD"),
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    return source, commit


def _binding(commit: str) -> ProjectRepositoryBinding:
    return ProjectRepositoryBinding.create(
        binding_id="binding_transport_v1",
        project_id="openzyme",
        binding_version=1,
        repository_id="repo_openzyme",
        internal_git_service_id="git_openzyme_local",
        internal_git_endpoint="https://localhost:8443/repositories/repo_openzyme.git",
        lfs_service_id="lfs_openzyme_local",
        lfs_endpoint="https://localhost:8443/repositories/repo_openzyme.git/info/lfs",
        upstream_identity="github_grtresy_enzymedesign",
        upstream_url="git@github.com:Grtresy/EnzymeDesign.git",
        object_format=GitObjectFormat.SHA1,
        default_base_ref="refs/heads/dev",
        default_base_commit=commit,
        ref_namespace_policy=RepositoryRefNamespacePolicy(
            private_prefix="refs/openzyme/private",
            publication_prefix="refs/openzyme/publications",
            historical_prefix="refs/openzyme/historical",
        ),
        repository_policy_version="repository-policy-v1",
        repository_policy_digest=f"sha256:{'1' * 64}",
        created_at="2026-08-15T18:00:00+00:00",
        created_by="operator:c1",
    )


def _transport_fixture(tmp_path: Path):
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin="https://localhost:8443",
    )
    return fixture.dependencies, fixture.binding, fixture.credential.token


def test_git_v2_discovery_requires_repository_bearer_and_forwards_protocol(
    tmp_path: Path,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    path = f"/repositories/{binding.repository_id}.git/info/refs"
    with TestClient(create_repository_transport_app(dependencies)) as client:
        unauthorized = client.get(
            path,
            params={"service": "git-upload-pack"},
            headers={"Git-Protocol": "version=2"},
        )
        response = client.get(
            path,
            params={"service": "git-upload-pack"},
            headers={
                "Authorization": f"Bearer {token}",
                "Git-Protocol": "version=2",
            },
        )

    assert unauthorized.status_code == 401
    assert unauthorized.headers["www-authenticate"] == "Bearer"
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-git-upload-pack-advertisement"
    )
    assert b"version 2" in response.content
    assert (
        str(dependencies.settings.bare_repository_root).encode() not in response.content
    )


def test_git_smart_http_streams_request_and_response_without_body_buffering(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)

    async def reject_buffered_body(request: Request) -> bytes:
        del request
        raise AssertionError("Git smart HTTP must not call Request.body()")

    monkeypatch.setattr(Request, "body", reject_buffered_body)
    path = f"/repositories/{binding.repository_id}.git/git-upload-pack"
    body = b"0014command=ls-refs\n00010009peel\n0000"
    with TestClient(create_repository_transport_app(dependencies)) as client:
        response = client.post(
            path,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/x-git-upload-pack-request",
                "Git-Protocol": "version=2",
            },
            content=body,
        )

    assert response.status_code == 200
    assert response.headers["content-type"].startswith(
        "application/x-git-upload-pack-result"
    )
    assert "content-length" not in response.headers
    assert response.content.endswith(b"0000")


def test_git_backend_cleanup_does_not_swallow_unexpected_cancellation() -> None:
    async def wait_forever() -> None:
        await asyncio.Event().wait()

    async def exercise_cleanup() -> None:
        owned = asyncio.create_task(wait_forever())
        assert owned.cancel()
        await _settle_git_request_task(
            owned,
            cancellation_requested_by_cleanup=True,
        )

        already_cancelling = asyncio.create_task(wait_forever())
        assert already_cancelling.cancel()
        with pytest.raises(asyncio.CancelledError):
            await _settle_git_request_task(
                already_cancelling,
                cancellation_requested_by_cleanup=False,
            )

        pending = asyncio.create_task(wait_forever())
        cleanup = asyncio.create_task(
            _settle_git_request_task(
                pending,
                cancellation_requested_by_cleanup=True,
            )
        )
        await asyncio.sleep(0)
        assert cleanup.cancel()
        with pytest.raises(asyncio.CancelledError):
            await cleanup
        assert pending.cancelled()

    asyncio.run(exercise_cleanup())


def test_git_backend_response_closes_a_request_stream_the_backend_no_longer_reads(
    tmp_path: Path,
) -> None:
    executable = tmp_path / "early-response-cgi"
    executable.write_text(
        "#!/usr/bin/python3\n"
        "import sys\n"
        "sys.stdout.buffer.write("
        "b'Status: 200 OK\\r\\n'"
        "b'Content-Type: application/x-git-receive-pack-result\\r\\n'"
        "b'\\r\\n0000')\n"
        "sys.stdout.buffer.flush()\n",
        encoding="utf-8",
    )
    executable.chmod(0o700)

    request_stream_started = asyncio.Event()

    async def receive() -> dict[str, object]:
        request_stream_started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")

    async def exercise_response() -> bytes:
        request = Request(
            {
                "type": "http",
                "method": "POST",
                "path": "/repositories/repo.git/git-receive-pack",
                "headers": (),
            },
            receive=receive,
        )
        response = await _git_backend_response(
            executable=executable,
            environment={"LANG": "C", "LC_ALL": "C"},
            repository_id="repo",
            request=request,
        )
        chunks = [chunk async for chunk in response.body_iterator]
        assert request_stream_started.is_set()
        return b"".join(chunks)

    body = asyncio.run(asyncio.wait_for(exercise_response(), timeout=2))

    assert body == b"0000"


def test_repository_git_subprocesses_ignore_hostile_ambient_git_environment(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    hostile_environment = {
        "GIT_ALTERNATE_OBJECT_DIRECTORIES": "/ambient/objects",
        "GIT_CONFIG_COUNT": "1",
        "GIT_CONFIG_KEY_0": "core.repositoryformatversion",
        "GIT_CONFIG_PARAMETERS": "'core.bare=false'",
        "GIT_CONFIG_VALUE_0": "999",
        "GIT_DIR": "/ambient/repository.git",
        "GIT_EXEC_PATH": "/ambient/git-exec-path",
        "GIT_OBJECT_DIRECTORY": "/ambient/object-directory",
        "GIT_WORK_TREE": "/ambient/worktree",
    }
    for name, value in hostile_environment.items():
        monkeypatch.setenv(name, value)

    path = f"/repositories/{binding.repository_id}.git/info/refs"
    with TestClient(create_repository_transport_app(dependencies)) as client:
        response = client.get(
            path,
            params={"service": "git-upload-pack"},
            headers={
                "Authorization": f"Bearer {token}",
                "Git-Protocol": "version=2",
            },
        )

    assert response.status_code == 200
    assert b"version 2" in response.content


def test_repository_transport_maps_malformed_bearer_to_401(tmp_path: Path) -> None:
    dependencies, binding, _ = _transport_fixture(tmp_path)
    path = f"/repositories/{binding.repository_id}.git/info/refs"
    with TestClient(create_repository_transport_app(dependencies)) as client:
        response = client.get(
            path,
            params={"service": "git-upload-pack"},
            headers={"Authorization": "Bearer ozrepo1.%.%"},
        )

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Bearer"
    assert response.json()["code"] == "repository_credential_rejected"


def test_repository_health_is_public_safe_and_reexecutes_preflight(
    tmp_path: Path,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    del token
    app = create_repository_transport_app(dependencies)
    with TestClient(app, base_url="https://testserver") as client:
        ready = client.get("/health")
        dependencies.settings.bare_repository_root.chmod(0o755)
        drifted = client.get("/health")

    assert ready.status_code == 200
    payload = ready.json()
    assert payload["schema_version"] == "repository_transport_health@1"
    assert payload["https_listener"] == {"status": "responding"}
    assert payload["git_smart_http"] == {
        "status": "ready",
        "protocol_version": "2",
    }
    assert payload["git_lfs_batch"] == {
        "status": "ready",
        "api_version": "2",
        "transfer": "basic",
    }
    assert payload["ref_acl_hook"]["status"] == "ready"
    assert payload["active_binding_count"] == 1
    serialized = json.dumps(payload, sort_keys=True)
    assert str(dependencies.settings.bare_repository_root) not in serialized
    assert str(dependencies.settings.lfs_object_root) not in serialized
    assert binding.internal_git_endpoint not in serialized
    assert binding.upstream_url not in serialized
    assert drifted.status_code == 503
    assert drifted.json() == {
        "message": "repository service preflight failed",
        "code": "repository_service_preflight_failed",
    }


def test_repository_health_does_not_hide_unexpected_preflight_failure(
    tmp_path: Path,
    monkeypatch,
) -> None:
    dependencies, _, _ = _transport_fixture(tmp_path)
    app = create_repository_transport_app(dependencies)

    def unexpected_failure(self: RepositoryTransportDependencies) -> None:
        del self
        raise RuntimeError("unexpected preflight implementation failure")

    with TestClient(app, base_url="https://testserver") as client:
        monkeypatch.setattr(
            RepositoryTransportDependencies,
            "preflight",
            unexpected_failure,
        )
        with pytest.raises(
            RuntimeError,
            match="unexpected preflight implementation failure",
        ):
            client.get("/health")


def test_lfs_batch_basic_upload_verify_download_and_restart(tmp_path: Path) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    base = f"/repositories/{binding.repository_id}.git/info/lfs"
    content = b"OpenZyme durable LFS transport\n"
    oid = hashlib.sha256(content).hexdigest()
    auth = {"Authorization": f"Bearer {token}"}
    batch_payload = {
        "operation": "upload",
        "transfers": ["basic"],
        "hash_algo": "sha256",
        "objects": [{"oid": oid, "size": len(content)}],
    }
    with TestClient(create_repository_transport_app(dependencies)) as client:
        batch = client.post(f"{base}/objects/batch", headers=auth, json=batch_payload)
        actions = batch.json()["objects"][0]["actions"]
        upload = client.put(
            f"{base}/objects/{oid}",
            headers={
                **actions["upload"]["header"],
                "Content-Length": str(len(content)),
            },
            content=content,
        )
        verify = client.post(
            f"{base}/objects/{oid}/verify",
            headers=actions["verify"]["header"],
            json={"oid": oid, "size": len(content)},
        )

    assert batch.status_code == 200
    assert set(actions) == {"upload", "verify"}
    assert actions["upload"]["href"] == f"{binding.lfs_endpoint}/objects/{oid}"
    assert upload.status_code == 200
    assert verify.status_code == 200

    with TestClient(create_repository_transport_app(dependencies)) as restarted:
        download_batch = restarted.post(
            f"{base}/objects/batch",
            headers=auth,
            json={
                "operation": "download",
                "transfers": ["basic"],
                "objects": [{"oid": oid, "size": len(content)}],
            },
        )
        download = restarted.get(f"{base}/objects/{oid}", headers=auth)

    assert download_batch.status_code == 200
    assert download_batch.json()["objects"][0]["actions"]["download"]
    assert download.status_code == 200
    assert download.content == content


def test_lfs_rejects_wrong_repository_missing_object_and_tampered_bytes(
    tmp_path: Path,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    base = f"/repositories/{binding.repository_id}.git/info/lfs"
    auth = {"Authorization": f"Bearer {token}"}
    missing_oid = "2" * 64
    with TestClient(create_repository_transport_app(dependencies)) as client:
        foreign = client.post(
            "/repositories/foreign.git/info/lfs/objects/batch",
            headers=auth,
            json={
                "operation": "download",
                "objects": [{"oid": missing_oid, "size": 1}],
            },
        )
        missing = client.post(
            f"{base}/objects/batch",
            headers=auth,
            json={
                "operation": "download",
                "objects": [{"oid": missing_oid, "size": 1}],
            },
        )
        reserve_tampered = client.post(
            f"{base}/objects/batch",
            headers=auth,
            json={
                "operation": "upload",
                "objects": [{"oid": missing_oid, "size": 5}],
            },
        )
        upload_headers = reserve_tampered.json()["objects"][0]["actions"][
            "upload"
        ]["header"]
        tampered = client.put(
            f"{base}/objects/{missing_oid}",
            headers={**upload_headers, "Content-Length": "5"},
            content=b"wrong",
        )

    assert foreign.status_code == 401
    assert missing.status_code == 200
    assert missing.json()["objects"][0]["error"]["code"] == 404
    assert tampered.status_code == 422


def test_lfs_upload_requires_batch_reservation_and_deduplicates_exact_oid(
    tmp_path: Path,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    base = f"/repositories/{binding.repository_id}.git/info/lfs"
    content = b"deduplicated LFS bytes\n"
    oid = hashlib.sha256(content).hexdigest()
    auth = {"Authorization": f"Bearer {token}"}
    payload = {
        "operation": "upload",
        "objects": [{"oid": oid, "size": len(content)}],
    }

    with TestClient(create_repository_transport_app(dependencies)) as client:
        direct = client.put(
            f"{base}/objects/{oid}",
            headers={**auth, "Content-Length": str(len(content))},
            content=content,
        )
        reserved = client.post(
            f"{base}/objects/batch",
            headers=auth,
            json=payload,
        )
        actions = reserved.json()["objects"][0]["actions"]
        uploaded = client.put(
            f"{base}/objects/{oid}",
            headers={
                **actions["upload"]["header"],
                "Content-Length": str(len(content)),
            },
            content=content,
        )
        deduplicated = client.post(
            f"{base}/objects/batch",
            headers=auth,
            json=payload,
        )

    assert direct.status_code == 400
    assert uploaded.status_code == 200
    assert "actions" not in deduplicated.json()["objects"][0]
    with dependencies.repository_provider.read() as scope:
        assert scope.connection.execute(
            "SELECT COUNT(*) FROM git_lfs_object_records WHERE oid = ?",
            (oid,),
        ).fetchone()[0] == 1
        assert scope.connection.execute(
            "SELECT COUNT(*) FROM git_lfs_workspace_object_links WHERE oid = ?",
            (oid,),
        ).fetchone()[0] == 1


def test_lfs_object_quota_failure_is_bounded_and_performs_no_fallback(
    tmp_path: Path,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    base = f"/repositories/{binding.repository_id}.git/info/lfs"
    oversized = 64 * 1024 * 1024 + 1

    with TestClient(create_repository_transport_app(dependencies)) as client:
        response = client.post(
            f"{base}/objects/batch",
            headers={"Authorization": f"Bearer {token}"},
            json={
                "operation": "upload",
                "objects": [{"oid": "7" * 64, "size": oversized}],
            },
        )

    assert response.status_code == 200
    error = response.json()["objects"][0]["error"]
    assert error == {
        "code": 507,
        "message": (
            "Git LFS object quota 67108864 bytes would be exceeded by "
            "67108865 bytes"
        ),
        "openzyme_code": "git_lfs_quota_exceeded",
        "quota_scope": "object",
        "limit_bytes": 64 * 1024 * 1024,
        "requested_bytes": oversized,
        "fallback_performed": False,
    }
    with dependencies.repository_provider.read() as scope:
        assert scope.connection.execute(
            "SELECT COUNT(*) FROM git_lfs_quota_reservations WHERE oid = ?",
            ("7" * 64,),
        ).fetchone()[0] == 0


def test_lfs_gc_requires_retired_generation_receipt_and_exact_dry_run(
    tmp_path: Path,
) -> None:
    dependencies, binding, token = _transport_fixture(tmp_path)
    base = f"/repositories/{binding.repository_id}.git/info/lfs"
    content = b"private unreachable object\n"
    oid = hashlib.sha256(content).hexdigest()
    auth = {"Authorization": f"Bearer {token}"}
    with TestClient(create_repository_transport_app(dependencies)) as client:
        batch = client.post(
            f"{base}/objects/batch",
            headers=auth,
            json={
                "operation": "upload",
                "objects": [{"oid": oid, "size": len(content)}],
            },
        )
        upload_headers = batch.json()["objects"][0]["actions"]["upload"][
            "header"
        ]
        uploaded = client.put(
            f"{base}/objects/{oid}",
            headers={
                **upload_headers,
                "Content-Length": str(len(content)),
            },
            content=content,
        )
    assert uploaded.status_code == 200

    retired_at = "2030-01-01T00:00:00+00:00"
    with dependencies.repository_provider.connection_scope() as scope:
        namespace = scope.connection.execute(
            """
            SELECT namespace_id FROM repository_private_namespace_records
            WHERE session_id = ? AND agent_member_id = ?
              AND workspace_generation = 1
            """,
            ("sess_repository_test", "agent:executor"),
        ).fetchone()
        assert namespace is not None
        hold = scope.connection.execute(
            """
            SELECT hold_id FROM repository_private_namespace_holds
            WHERE namespace_id = ? AND released_at IS NULL
            """,
            (namespace["namespace_id"],),
        ).fetchone()
        assert hold is not None
        finalizer = GitLfsPrivateReachabilityFinalizer(
            repositories=scope.repositories,
            git_reader=dependencies.roots(),
            object_store=DurableLfsObjectStore(dependencies.roots()),
        )
        retention = RepositoryPrivateNamespaceRetentionService(
            scope.connection,
            dependencies.roots(),
            reachability_finalizer=finalizer,
        )
        retention.close_namespace(
            namespace["namespace_id"],
            closed_at="2029-12-31T23:59:58+00:00",
        )
        retention.release_hold(
            hold["hold_id"],
            released_at="2029-12-31T23:59:59+00:00",
        )
        retention.retire_namespace(
            namespace["namespace_id"],
            binding=binding,
            retired_at=retired_at,
            retention_owner_ref="operator:c5-gc-test",
        )

    with dependencies.repository_provider.write() as scope:
        collector = GitLfsGarbageCollector(
            repositories=scope.repositories,
            object_store=DurableLfsObjectStore(dependencies.roots()),
        )
        candidate = collector.dry_run(
            binding_id=binding.binding_id,
            binding_version=binding.binding_version,
            created_at="2030-01-02T00:00:00+00:00",
        )
        assert candidate.candidate_oids == (oid,)
        deletion_digest = collector.delete_exact_candidates(
            candidate_receipt_id=candidate.receipt_id,
            expected_receipt_digest=candidate.receipt_digest,
            created_by="operator:c5-gc-test",
            observed_at="2030-01-02T00:00:01+00:00",
        )

    assert deletion_digest.startswith("sha256:")
    assert not DurableLfsObjectStore(dependencies.roots()).object_path(
        binding.repository_id,
        oid,
    ).exists()
    with dependencies.repository_provider.read() as scope:
        row = scope.connection.execute(
            """
            SELECT deleted_at, deletion_receipt_id
            FROM git_lfs_object_records WHERE oid = ?
            """,
            (oid,),
        ).fetchone()
        assert row is not None
        assert row["deleted_at"] == "2030-01-02T00:00:01+00:00"
        assert row["deletion_receipt_id"] is not None


def test_v3_session_creation_pins_binding_and_projects_only_safe_identity(
    tmp_path: Path,
) -> None:
    transport, binding, _ = _transport_fixture(tmp_path)
    settings = replace(
        OpenZymeSettings.from_env({}),
        repository_service=transport.settings,
    )
    dependencies = HostApiDependencies(
        foundation=RuntimeFoundation(settings=settings),
        v3_repository_provider=transport.repository_provider,
        v3_background_runtime_enabled=False,
        v3_durable_work_enabled=True,
        v3_repository_root_boundary=transport.root_boundary,
    )
    with TestClient(create_app(dependencies)) as client:
        response = client.post(
            "/v3/sessions",
            json={
                "project_id": binding.project_id,
                "session_id": "sess_v3_repository_pin",
                "title": "Repository pin",
                "objective": "Pin exact repository identity before workspace work.",
            },
        )

    assert response.status_code == 200
    repository_projection = response.json()["workspace"]["repository_binding"]
    assert repository_projection["status"] == "pinned"
    assert repository_projection["binding_id"] == binding.binding_id
    assert repository_projection["binding_version"] == binding.binding_version
    assert repository_projection["resolved_base_commit"] == binding.default_base_commit
    serialized = str(repository_projection)
    assert binding.internal_git_endpoint not in serialized
    assert binding.upstream_url not in serialized
    assert str(transport.settings.bare_repository_root) not in serialized


def test_v3_session_creation_without_active_binding_fails_without_partial_row(
    tmp_path: Path,
) -> None:
    transport, _, _ = _transport_fixture(tmp_path)
    settings = replace(
        OpenZymeSettings.from_env({}),
        repository_service=transport.settings,
    )
    dependencies = HostApiDependencies(
        foundation=RuntimeFoundation(settings=settings),
        v3_repository_provider=transport.repository_provider,
        v3_background_runtime_enabled=False,
        v3_durable_work_enabled=True,
        v3_repository_root_boundary=transport.root_boundary,
    )
    with TestClient(create_app(dependencies)) as client:
        response = client.post(
            "/v3/sessions",
            json={
                "project_id": "unconfigured_project",
                "session_id": "sess_no_repository_binding",
                "objective": "Must not use ambient checkout state.",
            },
        )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "repository_binding_required"
    with transport.repository_provider.read() as scope:
        assert scope.repositories.sessions.get("sess_no_repository_binding") is None


def test_v3_product_session_path_requires_repository_service_configuration(
    tmp_path: Path,
) -> None:
    provider = SQLiteRepositoryProvider(str(tmp_path / "control-plane.sqlite3"))
    settings = OpenZymeSettings.from_env({})
    dependencies = HostApiDependencies(
        foundation=RuntimeFoundation(settings=settings),
        v3_repository_provider=provider,
        v3_background_runtime_enabled=False,
        v3_durable_work_enabled=True,
    )
    with provider.write() as scope:
        scope.repositories.sessions.save(
            Session.create(
                "sess_legacy_unpinned_product",
                "openzyme",
                "Legacy unpinned",
                "Remain blocked without an exact repository mapping",
            )
        )
    with TestClient(create_app(dependencies)) as client:
        response = client.post(
            "/v3/sessions",
            json={
                "project_id": "openzyme",
                "session_id": "sess_repository_service_missing",
                "objective": "Fail without repository service.",
            },
        )
        restore = client.get("/v3/sessions/sess_legacy_unpinned_product/workspace")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "repository_binding_required"
    assert restore.status_code == 409
    assert restore.json()["error"]["code"] == "repository_binding_required"
