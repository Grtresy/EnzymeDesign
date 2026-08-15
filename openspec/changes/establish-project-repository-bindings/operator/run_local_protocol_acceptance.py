#!/usr/bin/env python3
"""Run the C1 native Git/LFS acceptance against the approved local service."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
from datetime import timedelta
import hashlib
import http.client
import json
import os
from pathlib import Path
import re
import socket
import ssl
import subprocess
import tempfile
import threading
import time
from typing import Any
from urllib.parse import urlsplit

import uvicorn

from openzyme_core import ActiveCapabilityLeaseAssertion
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import RepositoryCredentialBroker
from openzyme_core import RepositoryCredentialProtocol
from openzyme_core import RepositoryPrivateNamespaceHoldKind
from openzyme_core import RepositoryPrivateNamespaceRetentionService
from openzyme_core import RepositoryRootBoundary
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import private_ref_prefix
from openzyme_domain import RepositoryRefClass
from openzyme_host_api.repository_service_preflight import preflight_repository_service
from openzyme_host_api.repository_transport import RepositoryTransportDependencies
from openzyme_host_api.repository_transport import create_repository_transport_app
from openzyme_runtime import OpenZymeSettings


SCHEMA_ID = "project_repository_binding_local_protocol_acceptance@1"
REPOSITORY_ROOT = Path(__file__).resolve().parents[4]


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


def _digest_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _run(
    arguments: tuple[str, ...],
    *,
    environment: dict[str, str],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        arguments,
        cwd=cwd,
        env=environment,
        check=check,
        capture_output=True,
        text=True,
    )


@dataclass(slots=True)
class _RunningServer:
    server: uvicorn.Server
    thread: threading.Thread
    listener: socket.socket

    def stop(self) -> None:
        self.server.should_exit = True
        self.thread.join(timeout=10)
        if self.thread.is_alive():
            raise RuntimeError("repository acceptance server did not stop")
        self.listener.close()


def _start_server(
    dependencies: RepositoryTransportDependencies,
) -> _RunningServer:
    parsed = urlsplit(dependencies.settings.https_origin)
    if parsed.hostname != "localhost" or parsed.port is None:
        raise ValueError("local acceptance requires an explicit localhost HTTPS port")
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", parsed.port))
    listener.listen(128)
    server = uvicorn.Server(
        uvicorn.Config(
            create_repository_transport_app(dependencies),
            log_level="error",
            ssl_certfile=str(dependencies.settings.tls_certificate_file),
            ssl_keyfile=str(dependencies.settings.tls_private_key_file),
        )
    )
    thread = threading.Thread(
        target=server.run,
        kwargs={"sockets": [listener]},
        name="c1-local-repository-acceptance",
        daemon=True,
    )
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if not thread.is_alive():
            raise RuntimeError("repository acceptance server stopped during startup")
        if time.monotonic() >= deadline:
            raise RuntimeError("repository acceptance server did not start")
        time.sleep(0.01)
    return _RunningServer(server=server, thread=thread, listener=listener)


def _verify_dynamic_health(
    dependencies: RepositoryTransportDependencies,
) -> dict[str, Any]:
    parsed = urlsplit(dependencies.settings.https_origin)
    if parsed.hostname is None or parsed.port is None:
        raise ValueError("repository HTTPS origin requires an explicit host and port")
    context = ssl.create_default_context(
        cafile=str(dependencies.settings.tls_certificate_file)
    )
    connection = http.client.HTTPSConnection(
        parsed.hostname,
        parsed.port,
        context=context,
        timeout=10,
    )
    connection.request("GET", "/health")
    response = connection.getresponse()
    payload = json.loads(response.read())
    connection.close()
    if response.status != 200:
        raise RuntimeError("repository HTTPS health did not pass")
    expected_preflight = dependencies.preflight()
    if payload != {
        "schema_version": "repository_transport_health@1",
        "status": "ready",
        "https_listener": {"status": "responding"},
        "git_smart_http": {"status": "ready", "protocol_version": "2"},
        "git_lfs_batch": {
            "status": "ready",
            "api_version": "2",
            "transfer": "basic",
        },
        "ref_acl_hook": {
            "status": "ready",
            "digest": dependencies.roots().pre_receive_hook_digest(),
        },
        "active_binding_count": len(expected_preflight.active_bindings),
        "inventory_digest": expected_preflight.inventory_digest,
    }:
        raise RuntimeError("repository HTTPS health projection drifted")
    return payload


def _git_environment(git_lfs_executable: Path) -> dict[str, str]:
    environment = os.environ.copy()
    environment.update(
        {
            "GIT_CONFIG_NOSYSTEM": "1",
            "GIT_CONFIG_GLOBAL": "/dev/null",
            "GIT_TERMINAL_PROMPT": "0",
            "LC_ALL": "C",
            "PATH": (
                f"{git_lfs_executable.parent}:{environment.get('PATH', os.defpath)}"
            ),
        }
    )
    return environment


def _git(
    *,
    git_executable: Path,
    tls_certificate_file: Path,
    token: str,
    environment: dict[str, str],
    arguments: tuple[str, ...],
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return _run(
        (
            str(git_executable),
            "-c",
            f"http.extraHeader=Authorization: Bearer {token}",
            "-c",
            f"http.sslCAInfo={tls_certificate_file}",
            "-c",
            "protocol.version=2",
            *arguments,
        ),
        environment=environment,
        cwd=cwd,
        check=check,
    )


def _configure_clone(
    *,
    clone: Path,
    origin: str,
    git_executable: Path,
    git_lfs_executable: Path,
    tls_certificate_file: Path,
    token: str,
    environment: dict[str, str],
) -> None:
    commands = (
        ("config", "user.name", "OpenZyme C1 Local Acceptance"),
        ("config", "user.email", "c1-local-acceptance@openzyme.invalid"),
        ("config", "http.sslCAInfo", str(tls_certificate_file)),
        (
            "config",
            "--replace-all",
            f"http.{origin}/.extraHeader",
            f"Authorization: Bearer {token}",
        ),
    )
    for command in commands:
        _git(
            git_executable=git_executable,
            tls_certificate_file=tls_certificate_file,
            token=token,
            environment=environment,
            arguments=("-C", str(clone), *command),
        )
    _git(
        git_executable=git_executable,
        tls_certificate_file=tls_certificate_file,
        token=token,
        environment=environment,
        arguments=("-C", str(clone), "lfs", "install", "--local"),
    )
    configured_lfs = _git(
        git_executable=git_executable,
        tls_certificate_file=tls_certificate_file,
        token=token,
        environment=environment,
        arguments=("-C", str(clone), "lfs", "version"),
    ).stdout.strip()
    expected_lfs = _run(
        (str(git_lfs_executable), "version"),
        environment=environment,
    ).stdout.strip()
    if configured_lfs != expected_lfs:
        raise RuntimeError("native Git did not resolve the configured git-lfs binary")


def run_acceptance(args: argparse.Namespace) -> dict[str, Any]:
    if re.fullmatch(r"[a-z0-9][a-z0-9-]{0,79}", args.receipt_id) is None:
        raise ValueError("receipt id must be a lowercase Git-ref-safe identifier")
    settings = OpenZymeSettings.from_env().repository_service
    if settings is None:
        raise RuntimeError("repository service configuration is required")
    provider = SQLiteRepositoryProvider(str(args.database_path))
    boundary = RepositoryRootBoundary.production(
        host_checkout=REPOSITORY_ROOT,
        process_cwd=Path.cwd(),
    )
    roots = DurableRepositoryRootManager(settings, boundary)
    preflight = preflight_repository_service(
        settings=settings,
        provider=provider,
        roots=roots,
    )
    now = datetime.now(tz=UTC)
    lease_id = f"acceptance-only:{args.receipt_id}"
    with provider.write() as scope:
        session = scope.repositories.sessions.get(args.session_id)
        if session is None:
            raise RuntimeError(f"acceptance session {args.session_id!r} does not exist")
        pin = scope.repositories.session_repository_binding_pins.require(
            args.session_id
        )
        binding = scope.repositories.project_repository_bindings.get(pin.binding_id)
        if binding is None:
            raise RuntimeError("acceptance session pin references a missing binding")
        if binding.binding_id != args.binding_id:
            raise RuntimeError(
                "acceptance session pin does not match requested binding"
            )
        namespace_prefix = private_ref_prefix(
            binding,
            session_id=session.session_id,
            agent_member_id=args.agent_member_id,
            workspace_generation=args.workspace_generation,
        )
        retention = RepositoryPrivateNamespaceRetentionService(
            scope.connection,
            roots,
        )
        namespace_row = scope.connection.execute(
            """
            SELECT namespace_id, namespace_prefix, status
            FROM repository_private_namespace_records
            WHERE session_id = ?
              AND agent_member_id = ?
              AND workspace_generation = ?
            """,
            (
                session.session_id,
                args.agent_member_id,
                args.workspace_generation,
            ),
        ).fetchone()
        if namespace_row is None:
            namespace = retention.open_namespace(
                binding=binding,
                pin=pin,
                agent_member_id=args.agent_member_id,
                workspace_generation=args.workspace_generation,
                retention_deadline=(now + timedelta(days=30)).isoformat(),
                opened_at=now.isoformat(),
                namespace_id=f"repository-namespace-{args.receipt_id}",
            )
            namespace_id = namespace.namespace_id
        else:
            if namespace_row["status"] != "open":
                raise RuntimeError("acceptance private namespace is not open")
            if namespace_row["namespace_prefix"] != namespace_prefix:
                raise RuntimeError("acceptance private namespace prefix drifted")
            namespace_id = str(namespace_row["namespace_id"])
        hold_id = retention.add_hold(
            namespace_id,
            hold_kind=(RepositoryPrivateNamespaceHoldKind.ACTIVE_CAPABILITY_LEASE),
            owner_ref=lease_id,
            created_at=now.isoformat(),
            hold_id=f"repository-hold-{args.receipt_id}",
        )
        credential = RepositoryCredentialBroker(
            connection=scope.connection,
            signing_key_path=settings.credential_signing_key_file,
            credential_ttl_seconds=settings.credential_ttl_seconds,
        ).issue(
            binding=binding,
            pin=pin,
            lease=ActiveCapabilityLeaseAssertion(
                lease_id=lease_id,
                session_id=session.session_id,
                agent_member_id=args.agent_member_id,
                workspace_generation=args.workspace_generation,
                expires_at=(now + timedelta(minutes=15)).isoformat(),
            ),
            protocols=(
                RepositoryCredentialProtocol.GIT_READ,
                RepositoryCredentialProtocol.GIT_WRITE,
                RepositoryCredentialProtocol.LFS_READ,
                RepositoryCredentialProtocol.LFS_WRITE,
            ),
            ref_classes=(RepositoryRefClass.READ, RepositoryRefClass.PRIVATE),
            now=now,
        )

    dependencies = RepositoryTransportDependencies(
        repository_provider=provider,
        settings=settings,
        root_boundary=boundary,
    )
    environment = _git_environment(settings.git_lfs_executable)
    private_ref = f"{namespace_prefix}/{args.receipt_id}"
    lfs_content = b"OpenZyme C1 durable Git LFS local acceptance\n" * 32_768
    lfs_oid = hashlib.sha256(lfs_content).hexdigest()
    durable_lfs_object = (
        settings.lfs_object_root
        / binding.repository_id
        / "objects"
        / lfs_oid[:2]
        / lfs_oid[2:4]
        / lfs_oid
    )

    with tempfile.TemporaryDirectory(prefix="openzyme-c1-native-") as temporary:
        client_root = Path(temporary)
        clone = client_root / "writer"
        server = _start_server(dependencies)
        try:
            _verify_dynamic_health(dependencies)
            trace_environment = dict(environment)
            trace_environment["GIT_TRACE_PACKET"] = "1"
            cloned = _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=trace_environment,
                arguments=(
                    "clone",
                    binding.internal_git_endpoint,
                    str(clone),
                ),
            )
            if "version 2" not in cloned.stderr:
                raise RuntimeError("native clone did not negotiate Git protocol v2")
            _configure_clone(
                clone=clone,
                origin=settings.https_origin,
                git_executable=settings.git_executable,
                git_lfs_executable=settings.git_lfs_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
            )
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=("-C", str(clone), "lfs", "track", "*.bin"),
            )
            (clone / "c1-acceptance.bin").write_bytes(lfs_content)
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "-C",
                    str(clone),
                    "add",
                    ".gitattributes",
                    "c1-acceptance.bin",
                ),
            )
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "-C",
                    str(clone),
                    "commit",
                    "-m",
                    "test: record C1 local protocol acceptance",
                ),
            )
            commit = _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=("-C", str(clone), "rev-parse", "HEAD"),
            ).stdout.strip()
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "-C",
                    str(clone),
                    "push",
                    "origin",
                    f"HEAD:{private_ref}",
                ),
            )
            if durable_lfs_object.read_bytes() != lfs_content:
                raise RuntimeError("native Git LFS upload did not persist exact bytes")
        finally:
            server.stop()

        restarted = _start_server(dependencies)
        try:
            restored_clone = client_root / "reader-after-restart"
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "clone",
                    "--no-checkout",
                    binding.internal_git_endpoint,
                    str(restored_clone),
                ),
            )
            _configure_clone(
                clone=restored_clone,
                origin=settings.https_origin,
                git_executable=settings.git_executable,
                git_lfs_executable=settings.git_lfs_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
            )
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "-C",
                    str(restored_clone),
                    "fetch",
                    "origin",
                    private_ref,
                ),
            )
            _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "-C",
                    str(restored_clone),
                    "checkout",
                    "--detach",
                    "FETCH_HEAD",
                ),
            )
            if (restored_clone / "c1-acceptance.bin").read_bytes() != lfs_content:
                raise RuntimeError("native Git LFS download changed object bytes")

            hold_released_at = datetime.now(tz=UTC).isoformat()
            with provider.write() as scope:
                RepositoryPrivateNamespaceRetentionService(
                    scope.connection,
                    roots,
                ).release_hold(
                    hold_id,
                    released_at=hold_released_at,
                )
            blocked_ref = f"{namespace_prefix}/{args.receipt_id}-after-hold-release"
            released_hold_write = _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=(
                    "-C",
                    str(restored_clone),
                    "push",
                    "origin",
                    f"HEAD:{blocked_ref}",
                ),
                check=False,
            )
            if released_hold_write.returncode == 0:
                raise RuntimeError(
                    "repository credential remained writable after lease hold release"
                )
            if dict(roots.list_refs(binding, prefix=blocked_ref)).get(blocked_ref):
                raise RuntimeError("rejected post-release Git ref was created")

            revoked_at = datetime.now(tz=UTC).isoformat()
            with provider.write() as scope:
                RepositoryCredentialBroker(
                    connection=scope.connection,
                    signing_key_path=settings.credential_signing_key_file,
                    credential_ttl_seconds=settings.credential_ttl_seconds,
                ).revoke(
                    credential.claims.credential_id,
                    revoked_at=revoked_at,
                )
            rejected = _git(
                git_executable=settings.git_executable,
                tls_certificate_file=settings.tls_certificate_file,
                token=credential.token,
                environment=environment,
                arguments=("ls-remote", binding.internal_git_endpoint),
                check=False,
            )
            if rejected.returncode == 0:
                raise RuntimeError("revoked repository credential remained usable")
        finally:
            restarted.stop()

    roots.verify_pinned_commit(binding)
    terminal_ref = dict(roots.list_refs(binding, prefix=private_ref)).get(private_ref)
    if terminal_ref != commit:
        raise RuntimeError("durable private ref does not resolve to accepted commit")
    payload = {
        "schema_id": SCHEMA_ID,
        "receipt_id": args.receipt_id,
        "created_at": args.created_at,
        "created_by": args.operator_ref,
        "acceptance_profile": "approved_local_development",
        "binding": {
            "binding_id": binding.binding_id,
            "binding_version": binding.binding_version,
            "canonical_digest": binding.canonical_digest,
            "repository_id": binding.repository_id,
            "exact_base_commit": pin.resolved_base_commit,
        },
        "session_pin": {
            "session_id": pin.session_id,
            "binding_id": pin.binding_id,
            "binding_version": pin.binding_version,
            "resolved_base_commit": pin.resolved_base_commit,
        },
        "credential_authority": {
            "credential_id": credential.claims.credential_id,
            "lease_id": credential.claims.capability_lease_id,
            "lease_assertion_class": "c1_acceptance_only",
            "production_capability_lease_issuance_proven": False,
            "namespace_id": namespace_id,
            "active_lease_hold_id": hold_id,
            "active_lease_hold_released_at": hold_released_at,
            "revoked_at": revoked_at,
            "token_recorded": False,
        },
        "native_protocol": {
            "git": "smart_http_v2_over_https",
            "lfs": "batch_v2_basic",
            "https_origin": settings.https_origin,
            "private_ref": private_ref,
            "terminal_commit": commit,
            "lfs_oid": lfs_oid,
            "lfs_size": len(lfs_content),
            "dynamic_https_health_verified": True,
            "service_restart_verified": True,
            "released_lease_hold_write_rejected": True,
            "revoked_credential_rejected": True,
        },
        "preflight_inventory_digest": preflight.inventory_digest,
        "upstream_effects": 0,
        "status": "passed",
    }
    return {**payload, "receipt_digest": _digest_bytes(_canonical_bytes(payload))}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run a one-shot C1 local native Git/LFS acceptance. This is not a "
            "production capability-lease issuer."
        )
    )
    parser.add_argument("--database-path", type=Path, required=True)
    parser.add_argument("--binding-id", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--agent-member-id", required=True)
    parser.add_argument("--workspace-generation", type=int, required=True)
    parser.add_argument("--receipt-id", required=True)
    parser.add_argument("--created-at", required=True)
    parser.add_argument("--operator-ref", required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if not args.database_path.is_absolute():
        raise ValueError("database path must be absolute")
    if args.workspace_generation <= 0:
        raise ValueError("workspace generation must be positive")
    print(json.dumps(run_acceptance(args), sort_keys=True, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
