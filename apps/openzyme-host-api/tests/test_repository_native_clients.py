from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import hashlib
import http.client
import json
import os
from pathlib import Path
import socket
import subprocess
import ssl
import threading
import time
from typing import Literal

import pytest
import uvicorn

from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_core import private_ref_prefix
from openzyme_host_api.repository_transport import create_repository_transport_app

from .repository_test_support import RepositoryTestFixture
from .repository_test_support import build_repository_test_fixture
from .repository_test_support import issue_repository_credential


NATIVE_CLIENT_TIMEOUT_SECONDS = 30


@dataclass(slots=True)
class _RunningRepositoryServer:
    fixture: RepositoryTestFixture
    server: uvicorn.Server
    thread: threading.Thread
    listener: socket.socket
    port: int

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError("repository test server did not stop")
        self.listener.close()


def _start_server(
    fixture: RepositoryTestFixture,
    *,
    port: int = 0,
) -> _RunningRepositoryServer:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", port))
    listener.listen(128)
    selected_port = int(listener.getsockname()[1])
    expected_origin = f"https://localhost:{selected_port}"
    if fixture.settings.https_origin != expected_origin:
        listener.close()
        raise ValueError(
            "repository fixture HTTPS origin does not match bound test port"
        )
    server = uvicorn.Server(
        uvicorn.Config(
            create_repository_transport_app(fixture.dependencies),
            log_level="error",
            ssl_certfile=str(fixture.settings.tls_certificate_file),
            ssl_keyfile=str(fixture.settings.tls_private_key_file),
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="repository-native-client-test-server",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("repository test server stopped during startup")
        if time.monotonic() >= deadline:
            raise RuntimeError("repository test server did not start")
        time.sleep(0.01)
    return _RunningRepositoryServer(
        fixture=fixture,
        server=server,
        thread=thread,
        listener=listener,
        port=selected_port,
    )


def _base_environment() -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
        }
    )
    return environment


def _git(
    fixture: RepositoryTestFixture,
    token: str,
    *arguments: str,
    check: bool = True,
    trace_packet: bool = False,
) -> subprocess.CompletedProcess[str]:
    environment = _base_environment()
    if trace_packet:
        environment["GIT_TRACE_PACKET"] = "1"
    return subprocess.run(
        (
            str(fixture.settings.git_executable),
            "-c",
            f"http.extraHeader=Authorization: Bearer {token}",
            "-c",
            f"http.sslCAInfo={fixture.settings.tls_certificate_file}",
            "-c",
            "protocol.version=2",
            *arguments,
        ),
        check=check,
        capture_output=True,
        text=True,
        env=environment,
        timeout=NATIVE_CLIENT_TIMEOUT_SECONDS,
    )


def _configure_clone(
    fixture: RepositoryTestFixture,
    clone: Path,
    *,
    token: str,
) -> None:
    commands = (
        ("config", "user.name", "C1 Native Client"),
        ("config", "user.email", "c1-native@test"),
        (
            "config",
            "http.sslCAInfo",
            str(fixture.settings.tls_certificate_file),
        ),
        (
            "config",
            f"lfs.{fixture.binding.lfs_endpoint}.locksverify",
            "false",
        ),
    )
    for command in commands:
        _git(fixture, token, "-C", str(clone), *command)
    _set_clone_bearer(fixture, clone, token=token)
    _git(fixture, token, "-C", str(clone), "lfs", "install", "--local")


def _set_clone_bearer(
    fixture: RepositoryTestFixture,
    clone: Path,
    *,
    token: str,
) -> None:
    _git(
        fixture,
        token,
        "-C",
        str(clone),
        "config",
        "--replace-all",
        f"http.{fixture.settings.https_origin}/.extraHeader",
        f"Authorization: Bearer {token}",
    )


def _commit_file(
    fixture: RepositoryTestFixture,
    clone: Path,
    *,
    token: str,
    name: str,
    content: bytes,
    message: str,
) -> str:
    (clone / name).write_bytes(content)
    _git(fixture, token, "-C", str(clone), "add", name)
    _git(fixture, token, "-C", str(clone), "commit", "-m", message)
    return _git(
        fixture,
        token,
        "-C",
        str(clone),
        "rev-parse",
        "HEAD",
    ).stdout.strip()


def _clone_without_checkout(
    fixture: RepositoryTestFixture,
    *,
    token: str,
    destination: Path,
) -> None:
    _git(
        fixture,
        token,
        "clone",
        "--no-checkout",
        fixture.binding.internal_git_endpoint,
        str(destination),
    )
    _configure_clone(fixture, destination, token=token)


def _repository_request(
    fixture: RepositoryTestFixture,
    *,
    port: int,
    method: str,
    path: str,
    token: str,
    body: bytes | None = None,
) -> tuple[int, bytes]:
    connection = http.client.HTTPSConnection(
        "localhost",
        port,
        context=ssl.create_default_context(
            cafile=str(fixture.settings.tls_certificate_file)
        ),
        timeout=10,
    )
    headers = {"Authorization": f"Bearer {token}"}
    if body is not None:
        headers["Content-Length"] = str(len(body))
        headers["Content-Type"] = "application/octet-stream"
    connection.request(method, path, body=body, headers=headers)
    response = connection.getresponse()
    payload = response.read()
    status = response.status
    connection.close()
    return status, payload


def _end_write_authority(
    fixture: RepositoryTestFixture,
    *,
    transition: Literal["close_namespace", "release_hold"],
) -> None:
    claims = fixture.credential.claims
    ended_at = datetime.now(tz=UTC).isoformat()
    with fixture.provider.write() as scope:
        namespace_row = scope.connection.execute(
            """
            SELECT namespace_id
            FROM repository_private_namespace_records
            WHERE binding_id = ?
              AND binding_version = ?
              AND session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
              AND status = 'open'
            """,
            (
                claims.binding_id,
                claims.binding_version,
                claims.session_id,
                claims.agent_member_id,
                claims.workspace_generation,
            ),
        ).fetchone()
        assert namespace_row is not None
        namespace_id = str(namespace_row["namespace_id"])
        retention = RepositoryPrivateNamespaceRetentionService(
            scope.connection,
            fixture.roots,
        )
        if transition == "close_namespace":
            retention.close_namespace(namespace_id, closed_at=ended_at)
            return
        hold_row = scope.connection.execute(
            """
            SELECT hold_id
            FROM repository_private_namespace_holds
            WHERE namespace_id = ?
              AND hold_kind = 'active_capability_lease'
              AND owner_ref = ?
              AND released_at IS NULL
            """,
            (namespace_id, claims.capability_lease_id),
        ).fetchone()
        assert hold_row is not None
        retention.release_hold(
            str(hold_row["hold_id"]),
            released_at=ended_at,
        )


@pytest.mark.parametrize("transition", ("close_namespace", "release_hold"))
def test_native_issued_write_bearer_expires_with_namespace_authority(
    tmp_path: Path,
    transition: Literal["close_namespace", "release_hold"],
) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin=f"https://localhost:{port}",
    )
    server = _start_server(fixture, port=port)
    token = fixture.credential.token
    lifecycle_prefix = private_ref_prefix(
        fixture.binding,
        session_id=fixture.session.session_id,
        agent_member_id="agent:executor",
        workspace_generation=1,
    )
    private_ref = f"{lifecycle_prefix}/lifecycle"
    clone = tmp_path / "lifecycle-clone"
    lfs_path = f"/repositories/{fixture.binding.repository_id}.git/info/lfs/objects"

    try:
        _clone_without_checkout(fixture, token=token, destination=clone)
        first_commit = _commit_file(
            fixture,
            clone,
            token=token,
            name="lifecycle.txt",
            content=b"write authority open\n",
            message="create lifecycle ref",
        )
        _git(
            fixture,
            token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{private_ref}",
        )

        accepted_lfs_content = b"write authority open\n" * 1024
        accepted_lfs_oid = hashlib.sha256(accepted_lfs_content).hexdigest()
        accepted_status, _ = _repository_request(
            fixture,
            port=port,
            method="PUT",
            path=f"{lfs_path}/{accepted_lfs_oid}",
            token=token,
            body=accepted_lfs_content,
        )
        assert accepted_status == 200

        second_commit = _commit_file(
            fixture,
            clone,
            token=token,
            name="lifecycle.txt",
            content=b"write authority ended\n",
            message="attempt lifecycle fast-forward",
        )
        assert second_commit != first_commit
        _end_write_authority(fixture, transition=transition)

        rejected_push = _git(
            fixture,
            token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{private_ref}",
            check=False,
        )
        assert rejected_push.returncode != 0
        assert "terminal prompts disabled" in rejected_push.stderr
        rejected_create_ref = f"{lifecycle_prefix}/after-authority-ended"
        rejected_create = _git(
            fixture,
            token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{rejected_create_ref}",
            check=False,
        )
        assert rejected_create.returncode != 0
        assert "terminal prompts disabled" in rejected_create.stderr
        git_write_status, _ = _repository_request(
            fixture,
            port=port,
            method="GET",
            path=(
                f"/repositories/{fixture.binding.repository_id}.git/info/refs"
                "?service=git-receive-pack"
            ),
            token=token,
        )
        assert git_write_status == 401

        rejected_lfs_content = b"write authority already ended\n" * 1024
        rejected_lfs_oid = hashlib.sha256(rejected_lfs_content).hexdigest()
        rejected_status, _ = _repository_request(
            fixture,
            port=port,
            method="PUT",
            path=f"{lfs_path}/{rejected_lfs_oid}",
            token=token,
            body=rejected_lfs_content,
        )
        assert rejected_status == 401
        rejected_object = (
            fixture.settings.lfs_object_root
            / fixture.binding.repository_id
            / "objects"
            / rejected_lfs_oid[:2]
            / rejected_lfs_oid[2:4]
            / rejected_lfs_oid
        )
        assert not rejected_object.exists()

        visible = _git(
            fixture,
            token,
            "ls-remote",
            fixture.binding.internal_git_endpoint,
            private_ref,
            rejected_create_ref,
        ).stdout
        assert visible == f"{first_commit}\t{private_ref}\n"
        download_status, download_payload = _repository_request(
            fixture,
            port=port,
            method="GET",
            path=f"{lfs_path}/{accepted_lfs_oid}",
            token=token,
        )
        assert download_status == 200
        assert download_payload == accepted_lfs_content
    finally:
        server.stop()


def test_native_git_v2_acl_lfs_and_restart(tmp_path: Path) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    port = int(probe.getsockname()[1])
    probe.close()
    fixture = build_repository_test_fixture(
        tmp_path,
        https_origin=f"https://localhost:{port}",
    )
    server = _start_server(fixture, port=port)
    executor_token = fixture.credential.token
    researcher_credential = issue_repository_credential(
        fixture,
        agent_member_id="agent:researcher",
        workspace_generation=1,
        lease_id="lease_repository_test_researcher",
    )
    executor_prefix = private_ref_prefix(
        fixture.binding,
        session_id=fixture.session.session_id,
        agent_member_id="agent:executor",
        workspace_generation=1,
    )
    researcher_prefix = private_ref_prefix(
        fixture.binding,
        session_id=fixture.session.session_id,
        agent_member_id="agent:researcher",
        workspace_generation=1,
    )
    clone = tmp_path / "executor-clone"

    try:
        tls_context = ssl.create_default_context(
            cafile=str(fixture.settings.tls_certificate_file)
        )
        health_connection = http.client.HTTPSConnection(
            "localhost",
            port,
            context=tls_context,
            timeout=10,
        )
        health_connection.request("GET", "/health")
        health_response = health_connection.getresponse()
        health_payload = json.loads(health_response.read())
        health_connection.close()
        assert health_response.status == 200
        assert health_payload["https_listener"] == {"status": "responding"}
        assert health_payload["git_smart_http"]["protocol_version"] == "2"
        assert health_payload["git_lfs_batch"] == {
            "status": "ready",
            "api_version": "2",
            "transfer": "basic",
        }
        assert health_payload["active_binding_count"] == 1

        cloned = _git(
            fixture,
            executor_token,
            "clone",
            fixture.binding.internal_git_endpoint,
            str(clone),
            trace_packet=True,
        )
        assert "version 2" in cloned.stderr
        _configure_clone(fixture, clone, token=executor_token)

        first_commit = _commit_file(
            fixture,
            clone,
            token=executor_token,
            name="step.txt",
            content=b"step one\n",
            message="step one",
        )
        private_ref = f"{executor_prefix}/checkpoint"
        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{private_ref}",
        )

        multi_ref_one = f"{executor_prefix}/multi-one"
        multi_ref_two = f"{executor_prefix}/multi-two"
        multiple_updates = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{multi_ref_one}",
            f"HEAD:{multi_ref_two}",
            check=False,
        )
        assert multiple_updates.returncode != 0
        assert "one ref update is allowed per push" in multiple_updates.stderr
        multi_ref_visibility = _git(
            fixture,
            executor_token,
            "ls-remote",
            fixture.binding.internal_git_endpoint,
            multi_ref_one,
            multi_ref_two,
        ).stdout
        assert multi_ref_one not in multi_ref_visibility
        assert multi_ref_two not in multi_ref_visibility

        second_commit = _commit_file(
            fixture,
            clone,
            token=executor_token,
            name="step.txt",
            content=b"step one\nstep two\n",
            message="step two",
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{private_ref}",
        )

        researcher_ref = f"{researcher_prefix}/checkpoint"
        _set_clone_bearer(
            fixture,
            clone,
            token=researcher_credential.token,
        )
        _git(
            fixture,
            researcher_credential.token,
            "-C",
            str(clone),
            "push",
            fixture.binding.internal_git_endpoint,
            f"HEAD:{researcher_ref}",
        )
        _set_clone_bearer(fixture, clone, token=executor_token)
        visible = _git(
            fixture,
            executor_token,
            "ls-remote",
            fixture.binding.internal_git_endpoint,
        ).stdout
        assert private_ref in visible
        assert researcher_ref not in visible

        cross_agent = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{researcher_prefix}/cross-agent",
            check=False,
        )
        assert cross_agent.returncode != 0
        assert "outside the exact private namespace" in cross_agent.stderr
        publication = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            "HEAD:refs/openzyme/publications/forbidden",
            check=False,
        )
        assert publication.returncode != 0
        assert "outside the exact private namespace" in publication.stderr
        deletion = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            f":{private_ref}",
            check=False,
        )
        assert deletion.returncode != 0

        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "checkout",
            "--detach",
            fixture.binding.default_base_commit,
        )
        _commit_file(
            fixture,
            clone,
            token=executor_token,
            name="alternate.txt",
            content=b"alternate history\n",
            message="alternate history",
        )
        non_fast_forward = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "--force",
            "origin",
            f"HEAD:{private_ref}",
            check=False,
        )
        assert non_fast_forward.returncode != 0
        _git(fixture, executor_token, "-C", str(clone), "checkout", "dev")
        assert (
            _git(
                fixture,
                executor_token,
                "-C",
                str(clone),
                "rev-parse",
                "HEAD",
            ).stdout.strip()
            == second_commit
        )
        assert first_commit != second_commit

        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "lfs",
            "track",
            "*.bin",
        )
        lfs_content = b"OpenZyme native Git LFS\n" * 65_536
        lfs_commit = _commit_file(
            fixture,
            clone,
            token=executor_token,
            name="large.bin",
            content=lfs_content,
            message="add lfs object",
        )
        _git(fixture, executor_token, "-C", str(clone), "add", ".gitattributes")
        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "commit",
            "--amend",
            "--no-edit",
        )
        lfs_commit = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "rev-parse",
            "HEAD",
        ).stdout.strip()
        lfs_ref = f"{executor_prefix}/lfs-checkpoint"
        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{lfs_ref}",
        )
        pointer = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "show",
            f"{lfs_commit}:large.bin",
        ).stdout
        oid_line = next(
            line for line in pointer.splitlines() if line.startswith("oid ")
        )
        oid = oid_line.removeprefix("oid sha256:")
        durable_object = (
            fixture.settings.lfs_object_root
            / fixture.binding.repository_id
            / "objects"
            / oid[:2]
            / oid[2:4]
            / oid
        )
        assert durable_object.read_bytes() == lfs_content

        downloaded = tmp_path / "lfs-download"
        _clone_without_checkout(
            fixture,
            token=executor_token,
            destination=downloaded,
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(downloaded),
            "fetch",
            "origin",
            lfs_ref,
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(downloaded),
            "checkout",
            "--detach",
            "FETCH_HEAD",
        )
        assert (downloaded / "large.bin").read_bytes() == lfs_content

        wrong_repository = _git(
            fixture,
            executor_token,
            "ls-remote",
            f"{fixture.settings.https_origin}/repositories/foreign.git",
            check=False,
        )
        assert wrong_repository.returncode != 0
    finally:
        server.stop()

    restarted = _start_server(fixture, port=port)
    try:
        after_restart = tmp_path / "after-restart"
        _clone_without_checkout(
            fixture,
            token=executor_token,
            destination=after_restart,
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(after_restart),
            "fetch",
            "origin",
            lfs_ref,
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(after_restart),
            "checkout",
            "--detach",
            "FETCH_HEAD",
        )
        assert (after_restart / "large.bin").read_bytes() == lfs_content

        local_lfs_object = (
            after_restart / ".git" / "lfs" / "objects" / oid[:2] / oid[2:4] / oid
        )
        local_lfs_object.unlink()
        _git(
            fixture,
            executor_token,
            "-C",
            str(after_restart),
            "config",
            f"http.{fixture.settings.https_origin}/.extraHeader",
            "Authorization: Bearer invalid-token",
        )
        wrong_token = _git(
            fixture,
            "invalid-token",
            "-C",
            str(after_restart),
            "lfs",
            "fetch",
            "origin",
            lfs_commit,
            check=False,
        )
        assert wrong_token.returncode != 0

        missing_oid = "2" * 64
        missing_pointer = (
            "version https://git-lfs.github.com/spec/v1\n"
            f"oid sha256:{missing_oid}\n"
            "size 17\n"
        )
        missing_blob = subprocess.run(
            (
                str(fixture.settings.git_executable),
                "-C",
                str(clone),
                "hash-object",
                "-w",
                "--stdin",
            ),
            input=missing_pointer,
            check=True,
            capture_output=True,
            text=True,
            env=_base_environment(),
        ).stdout.strip()
        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "update-index",
            "--add",
            "--cacheinfo",
            f"100644,{missing_blob},missing.bin",
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "commit",
            "-m",
            "reference missing lfs object",
        )
        missing_commit = _git(
            fixture,
            executor_token,
            "-C",
            str(clone),
            "rev-parse",
            "HEAD",
        ).stdout.strip()
        missing_ref = f"{executor_prefix}/missing-lfs"
        _git(
            fixture,
            executor_token,
            "-c",
            "core.hooksPath=/dev/null",
            "-C",
            str(clone),
            "push",
            "origin",
            f"HEAD:{missing_ref}",
        )
        missing_clone = tmp_path / "missing-lfs"
        _clone_without_checkout(
            fixture,
            token=executor_token,
            destination=missing_clone,
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(missing_clone),
            "fetch",
            "origin",
            missing_ref,
        )
        missing_download = _git(
            fixture,
            executor_token,
            "-C",
            str(missing_clone),
            "lfs",
            "fetch",
            "origin",
            missing_commit,
            check=False,
        )
        assert missing_download.returncode != 0

        durable_object.write_bytes(b"X" * len(lfs_content))
        tampered_clone = tmp_path / "tampered-lfs"
        _clone_without_checkout(
            fixture,
            token=executor_token,
            destination=tampered_clone,
        )
        _git(
            fixture,
            executor_token,
            "-C",
            str(tampered_clone),
            "fetch",
            "origin",
            lfs_ref,
        )
        tampered_download = _git(
            fixture,
            executor_token,
            "-C",
            str(tampered_clone),
            "lfs",
            "fetch",
            "origin",
            lfs_commit,
            check=False,
        )
        assert tampered_download.returncode != 0
    finally:
        restarted.stop()
