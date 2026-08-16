from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC
from datetime import datetime
import logging
import os
from pathlib import Path
import tempfile
from typing import Annotated
from typing import Any
from typing import AsyncIterator
from typing import Literal

from fastapi import FastAPI
from fastapi import Header
from fastapi import HTTPException
from fastapi import Request
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.responses import Response
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from pydantic import ConfigDict
from pydantic import Field

from openzyme_core import DurableLfsObjectStore
from openzyme_core import DurableRepositoryRootManager
from openzyme_core import GitLfsPolicyError
from openzyme_core import GitLfsQuotaExceededError
from openzyme_core import GitLfsRepositoryError
from openzyme_core import LfsObjectMismatchError
from openzyme_core import RepositoryCredentialBroker
from openzyme_core import RepositoryCredentialClaims
from openzyme_core import RepositoryCredentialError
from openzyme_core import RepositoryCredentialProtocol
from openzyme_core import RepositoryCredentialRejectedError
from openzyme_core import RepositoryProvisionCredentialBroker
from openzyme_core import RepositoryProvisionCredentialClaims
from openzyme_core import RepositoryRootBoundary
from openzyme_core import RepositoryStorageError
from openzyme_core import SQLiteRepositoryProvider
from openzyme_core import private_ref_prefix
from openzyme_runtime import RepositoryServiceSettings
from openzyme_domain import ProjectRepositoryBinding
from openzyme_domain import GitLfsBindingPolicy
from openzyme_domain import GitLfsObjectReadReceipt
from openzyme_domain import canonical_lfs_digest
from openzyme_domain import RepositoryBindingLifecycleStatus
from openzyme_domain import RepositoryRefClass

from .repository_service_preflight import RepositoryServicePreflightReport
from .repository_service_preflight import RepositoryServicePreflightError
from .repository_service_preflight import preflight_repository_service


LOGGER = logging.getLogger(__name__)
LFS_JSON_MEDIA_TYPE = "application/vnd.git-lfs+json"
_GIT_STREAM_CHUNK_BYTES = 64 * 1024
_GIT_CGI_HEADER_LIMIT_BYTES = 64 * 1024
_GIT_STDERR_LIMIT_BYTES = 64 * 1024
_LFS_UPLOAD_SESSION_HEADER = "X-OpenZyme-Lfs-Upload-Session"


class RepositoryTransportError(RuntimeError):
    error_code = "repository_transport_error"


class RepositoryTransportRequestError(ValueError):
    error_code = "repository_transport_request_invalid"


class LfsObjectRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oid: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


class LfsRefRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=4096)


class LfsBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["download", "upload"]
    transfers: list[str] = Field(default_factory=lambda: ["basic"], max_length=8)
    objects: list[LfsObjectRequest] = Field(max_length=10_000)
    ref: LfsRefRequest | None = None
    hash_algo: Literal["sha256"] | None = None


class LfsVerifyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    oid: str = Field(pattern=r"^[0-9a-f]{64}$")
    size: int = Field(ge=0)


@dataclass(frozen=True, slots=True)
class AuthenticatedRepositoryRequest:
    token: str
    claims: RepositoryCredentialClaims | RepositoryProvisionCredentialClaims
    binding: ProjectRepositoryBinding


@dataclass(slots=True)
class RepositoryTransportDependencies:
    repository_provider: SQLiteRepositoryProvider
    settings: RepositoryServiceSettings
    root_boundary: RepositoryRootBoundary

    def roots(self) -> DurableRepositoryRootManager:
        return DurableRepositoryRootManager(
            self.settings,
            self.root_boundary,
        )

    def preflight(self) -> RepositoryServicePreflightReport:
        roots = self.roots()
        return preflight_repository_service(
            settings=self.settings,
            provider=self.repository_provider,
            roots=roots,
        )

    def authenticate(
        self,
        authorization: str | None,
        *,
        repository_id: str,
        protocol: RepositoryCredentialProtocol,
    ) -> AuthenticatedRepositoryRequest:
        scheme, separator, token = (authorization or "").partition(" ")
        if separator != " " or scheme.lower() != "bearer" or not token.strip():
            raise RepositoryCredentialRejectedError(
                "repository Bearer authentication is required"
            )
        resolved_token = token.strip()
        with self.repository_provider.read() as scope:
            repositories = scope.repositories
            broker = RepositoryCredentialBroker(
                connection=repositories.sessions.connection,
                signing_key_path=self.settings.credential_signing_key_file,
                credential_ttl_seconds=self.settings.credential_ttl_seconds,
            )
            if resolved_token.startswith("ozprovision1."):
                claims = RepositoryProvisionCredentialBroker(
                    connection=repositories.sessions.connection,
                    signing_key_path=self.settings.credential_signing_key_file,
                    credential_ttl_seconds=self.settings.credential_ttl_seconds,
                ).authenticate(
                    resolved_token,
                    protocol=protocol,
                    repository_id=repository_id,
                    now=datetime.now(tz=UTC),
                )
            else:
                claims = broker.authenticate(
                    resolved_token,
                    protocol=protocol,
                    repository_id=repository_id,
                    now=datetime.now(tz=UTC),
                )
            binding = repositories.project_repository_bindings.get(claims.binding_id)
            if binding is None:
                raise RepositoryCredentialRejectedError(
                    "repository credential references a missing binding"
                )
            pin = repositories.session_repository_binding_pins.require(
                claims.session_id
            )
            lifecycle = repositories.project_repository_bindings.lifecycle_status(
                binding.binding_id
            )
            if lifecycle is RepositoryBindingLifecycleStatus.RETIRED:
                raise RepositoryCredentialRejectedError(
                    "repository credential references a retired binding"
                )
            if (
                claims.binding_version != binding.binding_version
                or claims.repository_id != binding.repository_id
                or pin.binding_id != binding.binding_id
                or pin.binding_version != binding.binding_version
                or pin.repository_id != binding.repository_id
                or pin.binding_canonical_digest != binding.canonical_digest
                or pin.resolved_base_commit != binding.default_base_commit
            ):
                raise RepositoryCredentialRejectedError(
                    "repository credential scope drifted from immutable session pin"
                )
        self.roots().verify_bare_repository(binding)
        return AuthenticatedRepositoryRequest(
            token=resolved_token,
            claims=claims,
            binding=binding,
        )


def _git_protocol_for_request(
    *,
    method: str,
    git_path: str,
    service_query: str | None,
) -> RepositoryCredentialProtocol:
    if method == "GET" and git_path == "info/refs":
        if service_query == "git-upload-pack":
            return RepositoryCredentialProtocol.GIT_READ
        if service_query == "git-receive-pack":
            return RepositoryCredentialProtocol.GIT_WRITE
    if method == "POST" and git_path == "git-upload-pack":
        return RepositoryCredentialProtocol.GIT_READ
    if method == "POST" and git_path == "git-receive-pack":
        return RepositoryCredentialProtocol.GIT_WRITE
    raise RepositoryTransportRequestError("unsupported Git smart HTTP request")


async def _read_cgi_response_headers(
    stream: asyncio.StreamReader,
) -> tuple[int, dict[str, str], bytes]:
    buffered = bytearray()
    while True:
        chunk = await stream.read(_GIT_STREAM_CHUNK_BYTES)
        if not chunk:
            raise RepositoryTransportError("Git HTTP backend returned no CGI headers")
        buffered.extend(chunk)
        candidates = tuple(
            (position, separator)
            for separator in (b"\r\n\r\n", b"\n\n")
            if (position := buffered.find(separator)) >= 0
        )
        if candidates:
            header_end, separator = min(candidates, key=lambda item: item[0])
            if header_end > _GIT_CGI_HEADER_LIMIT_BYTES:
                raise RepositoryTransportError(
                    "Git HTTP backend CGI headers exceed the bounded limit"
                )
            header_bytes = bytes(buffered[:header_end])
            body = bytes(buffered[header_end + len(separator) :])
            break
        if len(buffered) > _GIT_CGI_HEADER_LIMIT_BYTES:
            raise RepositoryTransportError(
                "Git HTTP backend CGI headers exceed the bounded limit"
            )

    status_code = 200
    headers: dict[str, str] = {}
    for raw_line in header_bytes.replace(b"\r\n", b"\n").split(b"\n"):
        name, found, value = raw_line.partition(b":")
        if not found:
            raise RepositoryTransportError(
                "Git HTTP backend returned malformed headers"
            )
        try:
            decoded_name = name.decode("ascii").strip()
            decoded_value = value.decode("latin-1").strip()
        except UnicodeDecodeError as exc:
            raise RepositoryTransportError(
                "Git HTTP backend returned invalid CGI header encoding"
            ) from exc
        if decoded_name.lower() == "status":
            status_token = decoded_value.split(" ", 1)[0]
            if len(status_token) != 3 or not status_token.isdigit():
                raise RepositoryTransportError(
                    "Git HTTP backend returned an invalid CGI status"
                )
            status_code = int(status_token)
        else:
            headers[decoded_name] = decoded_value
    return status_code, headers, body


async def _pump_git_request_body(
    request: Request,
    stream: asyncio.StreamWriter,
) -> None:
    try:
        async for chunk in request.stream():
            if chunk:
                stream.write(chunk)
                await stream.drain()
    finally:
        stream.close()
        await stream.wait_closed()


async def _drain_bounded_git_stderr(
    stream: asyncio.StreamReader,
) -> tuple[bytes, bool]:
    buffered = bytearray()
    truncated = False
    while chunk := await stream.read(_GIT_STREAM_CHUNK_BYTES):
        remaining = _GIT_STDERR_LIMIT_BYTES - len(buffered)
        if remaining > 0:
            buffered.extend(chunk[:remaining])
        if len(chunk) > remaining:
            truncated = True
    return bytes(buffered), truncated


def _log_git_backend_failure(
    *,
    repository_id: str,
    returncode: int,
    stderr: bytes,
    truncated: bool,
) -> None:
    suffix = " [truncated]" if truncated else ""
    LOGGER.error(
        "git-http-backend failed for repository %s with exit %s: %s%s",
        repository_id,
        returncode,
        stderr.decode("utf-8", errors="replace"),
        suffix,
    )


async def _abort_git_backend(
    process: asyncio.subprocess.Process,
    request_task: asyncio.Task[None],
    stderr_task: asyncio.Task[tuple[bytes, bool]],
) -> tuple[int, bytes, bool]:
    if process.returncode is None:
        process.kill()
    cancellation_requested_by_cleanup = False
    if not request_task.done() and request_task.cancelling() == 0:
        cancellation_requested_by_cleanup = request_task.cancel()
    returncode = await process.wait()
    stderr, truncated = await stderr_task
    await _settle_git_request_task(
        request_task,
        cancellation_requested_by_cleanup=cancellation_requested_by_cleanup,
    )
    return returncode, stderr, truncated


async def _settle_git_request_task(
    request_task: asyncio.Task[None],
    *,
    cancellation_requested_by_cleanup: bool,
) -> None:
    cleanup_task = asyncio.current_task()
    if cleanup_task is None:
        raise RuntimeError("Git backend cleanup must run inside an asyncio task")
    cleanup_cancellation_count = cleanup_task.cancelling()
    try:
        await request_task
    except asyncio.CancelledError:
        if cleanup_task.cancelling() != cleanup_cancellation_count:
            raise
        if not cancellation_requested_by_cleanup or not request_task.cancelled():
            raise


async def _finish_git_request_after_backend_response(
    request_task: asyncio.Task[None],
) -> None:
    cancellation_requested_by_response_completion = False
    if not request_task.done() and request_task.cancelling() == 0:
        cancellation_requested_by_response_completion = request_task.cancel()
    await _settle_git_request_task(
        request_task,
        cancellation_requested_by_cleanup=(
            cancellation_requested_by_response_completion
        ),
    )


async def _git_backend_response(
    *,
    executable: Path,
    environment: dict[str, str],
    repository_id: str,
    request: Request,
) -> StreamingResponse:
    try:
        process = await asyncio.create_subprocess_exec(
            str(executable),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment,
            limit=_GIT_STREAM_CHUNK_BYTES,
        )
    except OSError as exc:
        raise RepositoryTransportError("Git HTTP backend could not start") from exc
    if process.stdin is None or process.stdout is None or process.stderr is None:
        process.kill()
        await process.wait()
        raise RepositoryTransportError("Git HTTP backend pipes were not created")

    request_task = asyncio.create_task(
        _pump_git_request_body(request, process.stdin),
        name=f"repository-git-request-{repository_id}",
    )
    stderr_task = asyncio.create_task(
        _drain_bounded_git_stderr(process.stderr),
        name=f"repository-git-stderr-{repository_id}",
    )
    try:
        status_code, headers, first_body = await _read_cgi_response_headers(
            process.stdout
        )
    except (RepositoryTransportError, asyncio.CancelledError):
        returncode, stderr, truncated = await _abort_git_backend(
            process,
            request_task,
            stderr_task,
        )
        _log_git_backend_failure(
            repository_id=repository_id,
            returncode=returncode,
            stderr=stderr,
            truncated=truncated,
        )
        raise

    async def response_body() -> AsyncIterator[bytes]:
        backend_settled = False
        try:
            if first_body:
                yield first_body
            while chunk := await process.stdout.read(_GIT_STREAM_CHUNK_BYTES):
                yield chunk
            await _finish_git_request_after_backend_response(request_task)
            returncode = await process.wait()
            stderr, truncated = await stderr_task
            backend_settled = True
            if returncode != 0:
                _log_git_backend_failure(
                    repository_id=repository_id,
                    returncode=returncode,
                    stderr=stderr,
                    truncated=truncated,
                )
                raise RepositoryTransportError("Git HTTP backend failed")
        finally:
            if not backend_settled:
                await _abort_git_backend(process, request_task, stderr_task)

    return StreamingResponse(
        response_body(),
        status_code=status_code,
        headers=headers,
    )


def _git_environment(
    dependencies: RepositoryTransportDependencies,
    authenticated: AuthenticatedRepositoryRequest,
    *,
    request: Request,
    git_path: str,
) -> dict[str, str]:
    settings = dependencies.settings
    binding = authenticated.binding
    claims = authenticated.claims
    environment = {
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_PROJECT_ROOT": str(settings.bare_repository_root),
        "GIT_HTTP_EXPORT_ALL": "1",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": os.defpath,
        "PATH_INFO": f"/{binding.repository_id}.git/{git_path}",
        "REQUEST_METHOD": request.method,
        "QUERY_STRING": request.url.query,
        "CONTENT_TYPE": request.headers.get("content-type", ""),
        "REMOTE_USER": claims.agent_member_id,
        "OPENZYME_REPOSITORY_ACTOR_KIND": "agent",
        "OPENZYME_REPOSITORY_ID": binding.repository_id,
        "OPENZYME_BINDING_ID": binding.binding_id,
        "OPENZYME_BINDING_VERSION": str(binding.binding_version),
        "OPENZYME_OBJECT_FORMAT": binding.object_format.value,
        "OPENZYME_PRIVATE_REF_PREFIX": private_ref_prefix(
            binding,
            session_id=claims.session_id,
            agent_member_id=claims.agent_member_id,
            workspace_generation=claims.workspace_generation,
        ),
        "OPENZYME_GIT_EXECUTABLE": str(settings.git_executable),
    }
    content_length = request.headers.get("content-length")
    if content_length is not None:
        if not content_length.isdigit():
            raise RepositoryTransportRequestError(
                "Git smart HTTP Content-Length must be a decimal byte count"
            )
        environment["CONTENT_LENGTH"] = content_length
    git_protocol = request.headers.get("git-protocol")
    if git_protocol is not None:
        environment["HTTP_GIT_PROTOCOL"] = git_protocol

    hidden: list[str] = [
        binding.ref_namespace_policy.private_prefix,
        binding.ref_namespace_policy.historical_prefix,
    ]
    if RepositoryRefClass.PRIVATE in claims.ref_classes:
        hidden.append(
            "!"
            + private_ref_prefix(
                binding,
                session_id=claims.session_id,
                agent_member_id=claims.agent_member_id,
                workspace_generation=claims.workspace_generation,
            )
        )
    environment["GIT_CONFIG_COUNT"] = str(len(hidden))
    for index, value in enumerate(hidden):
        environment[f"GIT_CONFIG_KEY_{index}"] = "uploadpack.hideRefs"
        environment[f"GIT_CONFIG_VALUE_{index}"] = value
    return environment


def _lfs_error(status_code: int, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"message": message},
        media_type=LFS_JSON_MEDIA_TYPE,
    )


def _lfs_policy(
    dependencies: RepositoryTransportDependencies,
    authenticated: AuthenticatedRepositoryRequest,
) -> GitLfsBindingPolicy:
    with dependencies.repository_provider.read() as scope:
        policy = scope.repositories.git_lfs.get_policy(
            binding_id=authenticated.binding.binding_id,
            binding_version=authenticated.binding.binding_version,
        )
    if (
        policy is None
        or policy.repository_id != authenticated.binding.repository_id
        or policy.lfs_service_id != authenticated.binding.lfs_service_id
        or policy.lfs_endpoint != authenticated.binding.lfs_endpoint
        or policy.policy_version
        != authenticated.binding.repository_policy_version
        or policy.policy_digest
        != authenticated.binding.repository_policy_digest
    ):
        raise GitLfsPolicyError(
            "repository binding has no exact immutable Git LFS policy"
        )
    return policy


def _lfs_read_receipt(
    *,
    authenticated: AuthenticatedRepositoryRequest,
    oid: str,
    size: int,
    observed_at: str,
) -> GitLfsObjectReadReceipt:
    scope_digest = authenticated.claims.claims_digest
    stable = canonical_lfs_digest(
        {
            "binding_id": authenticated.binding.binding_id,
            "binding_version": authenticated.binding.binding_version,
            "repository_id": authenticated.binding.repository_id,
            "credential_id": authenticated.claims.credential_id,
            "oid": oid,
            "size": size,
            "observed_at": observed_at,
        }
    ).split(":", 1)[1]
    return GitLfsObjectReadReceipt.create(
        receipt_id=f"lfs_read_{stable[:32]}",
        binding_id=authenticated.binding.binding_id,
        binding_version=authenticated.binding.binding_version,
        repository_id=authenticated.binding.repository_id,
        lfs_endpoint_identity=canonical_lfs_digest(
            {
                "lfs_service_id": authenticated.binding.lfs_service_id,
                "lfs_endpoint": authenticated.binding.lfs_endpoint,
                "binding_id": authenticated.binding.binding_id,
                "binding_version": authenticated.binding.binding_version,
            }
        ),
        authorization_scope_digest=scope_digest,
        oid=oid,
        declared_size=size,
        observed_size=size,
        observed_sha256=oid,
        observed_at=observed_at,
    )


def create_repository_transport_app(
    dependencies: RepositoryTransportDependencies,
) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        del app
        dependencies.preflight()
        yield

    app = FastAPI(
        title="OpenZyme Repository Transport",
        version="1.0.0",
        lifespan=lifespan,
    )

    @app.exception_handler(RepositoryCredentialError)
    async def repository_credential_error(
        request: Request,
        exc: RepositoryCredentialError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=401,
            content={"message": str(exc), "code": exc.error_code},
            headers={"WWW-Authenticate": "Bearer"},
        )

    @app.exception_handler(RepositoryTransportRequestError)
    async def repository_request_error(
        request: Request,
        exc: RepositoryTransportRequestError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=400,
            content={"message": str(exc), "code": exc.error_code},
        )

    @app.exception_handler(RepositoryTransportError)
    async def repository_transport_error(
        request: Request,
        exc: RepositoryTransportError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=500,
            content={
                "message": "repository transport failed",
                "code": "repository_transport_error",
            },
        )

    @app.exception_handler(RepositoryStorageError)
    async def repository_storage_error(
        request: Request,
        exc: RepositoryStorageError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=503,
            content={
                "message": "repository durable storage is unavailable",
                "code": "repository_storage_unavailable",
            },
        )

    @app.exception_handler(RepositoryServicePreflightError)
    async def repository_preflight_error(
        request: Request,
        exc: RepositoryServicePreflightError,
    ) -> JSONResponse:
        del request, exc
        return JSONResponse(
            status_code=503,
            content={
                "message": "repository service preflight failed",
                "code": "repository_service_preflight_failed",
            },
        )

    @app.exception_handler(LfsObjectMismatchError)
    async def lfs_object_mismatch(
        request: Request,
        exc: LfsObjectMismatchError,
    ) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=422,
            content={"message": str(exc), "code": exc.error_code},
            media_type=LFS_JSON_MEDIA_TYPE,
        )

    @app.exception_handler(GitLfsRepositoryError)
    async def git_lfs_repository_error(
        request: Request,
        exc: GitLfsRepositoryError,
    ) -> JSONResponse:
        del request
        status_code = 507 if isinstance(exc, GitLfsQuotaExceededError) else 409
        payload: dict[str, object] = {
            "message": str(exc),
            "code": exc.error_code,
            "fallback_performed": False,
        }
        if isinstance(exc, GitLfsQuotaExceededError):
            payload["quota"] = {
                "scope": exc.scope,
                "limit_bytes": exc.limit_bytes,
                "requested_bytes": exc.requested_bytes,
            }
        return JSONResponse(
            status_code=status_code,
            content=payload,
            media_type=LFS_JSON_MEDIA_TYPE,
        )

    @app.get("/health")
    def repository_health(request: Request) -> JSONResponse:
        if request.url.scheme != "https":
            raise RepositoryTransportRequestError(
                "repository health is available only over HTTPS"
            )
        try:
            report = dependencies.preflight()
        except RepositoryStorageError as exc:
            raise RepositoryServicePreflightError(
                "repository durable storage failed dynamic preflight"
            ) from exc
        return JSONResponse(
            content={
                "schema_version": "repository_transport_health@1",
                "status": "ready",
                "https_listener": {"status": "responding"},
                "git_smart_http": {
                    "status": "ready",
                    "protocol_version": "2",
                },
                "git_lfs_batch": {
                    "status": "ready",
                    "api_version": "2",
                    "transfer": "basic",
                },
                "ref_acl_hook": {
                    "status": "ready",
                    "digest": report.pre_receive_hook_digest,
                },
                "active_binding_count": len(report.active_bindings),
                "inventory_digest": report.inventory_digest,
            }
        )

    @app.post("/repositories/{repository_id}.git/info/lfs/objects/batch")
    def lfs_batch(
        repository_id: str,
        payload: LfsBatchRequest,
        authorization: Annotated[str | None, Header()] = None,
    ) -> JSONResponse:
        if payload.transfers and "basic" not in payload.transfers:
            raise RepositoryTransportRequestError(
                "repository service supports only the Git LFS basic transfer"
            )
        protocol = (
            RepositoryCredentialProtocol.LFS_READ
            if payload.operation == "download"
            else RepositoryCredentialProtocol.LFS_WRITE
        )
        authenticated = dependencies.authenticate(
            authorization,
            repository_id=repository_id,
            protocol=protocol,
        )
        policy = _lfs_policy(dependencies, authenticated)
        store = DurableLfsObjectStore(dependencies.roots())
        objects: list[dict[str, Any]] = []
        for item in payload.objects:
            projected: dict[str, Any] = {"oid": item.oid, "size": item.size}
            href = f"{authenticated.binding.lfs_endpoint}/objects/{item.oid}"
            headers = {"Authorization": f"Bearer {authenticated.token}"}
            if payload.operation == "download":
                with dependencies.repository_provider.read() as scope:
                    metadata_exists = scope.repositories.git_lfs.has_object_metadata(
                        policy=policy,
                        oid=item.oid,
                        size_bytes=item.size,
                    )
                if metadata_exists and store.has_object(
                    repository_id,
                    item.oid,
                    size=item.size,
                ):
                    store.verify(repository_id, item.oid, size=item.size)
                    projected["actions"] = {
                        "download": {"href": href, "header": headers}
                    }
                else:
                    projected["error"] = {
                        "code": 404,
                        "message": "Git LFS object does not exist",
                    }
            else:
                if not isinstance(authenticated.claims, RepositoryCredentialClaims):
                    raise RepositoryCredentialRejectedError(
                        "provision credentials cannot reserve Git LFS uploads"
                    )
                with dependencies.repository_provider.read() as scope:
                    metadata_exists = scope.repositories.git_lfs.has_object_metadata(
                        policy=policy,
                        oid=item.oid,
                        size_bytes=item.size,
                    )
                if metadata_exists:
                    store.verify(repository_id, item.oid, size=item.size)
                    with dependencies.repository_provider.write() as scope:
                        scope.repositories.git_lfs.link_workspace_object(
                            policy=policy,
                            claims=authenticated.claims,
                            oid=item.oid,
                            observed_via="upload",
                            created_at=datetime.now(tz=UTC).isoformat(),
                        )
                else:
                    try:
                        with dependencies.repository_provider.write() as scope:
                            upload_session = scope.repositories.git_lfs.reserve_upload(
                                policy=policy,
                                claims=authenticated.claims,
                                oid=item.oid,
                                size_bytes=item.size,
                                now=datetime.now(tz=UTC),
                            )
                    except GitLfsQuotaExceededError as exc:
                        projected["error"] = {
                            "code": 507,
                            "message": str(exc),
                            "openzyme_code": exc.error_code,
                            "quota_scope": exc.scope,
                            "limit_bytes": exc.limit_bytes,
                            "requested_bytes": exc.requested_bytes,
                            "fallback_performed": False,
                        }
                    else:
                        upload_headers = {
                            **headers,
                            _LFS_UPLOAD_SESSION_HEADER: (
                                upload_session.upload_session_id
                            ),
                        }
                        projected["actions"] = {
                            "upload": {"href": href, "header": upload_headers},
                            "verify": {
                                "href": f"{href}/verify",
                                "header": upload_headers,
                            },
                        }
            objects.append(projected)
        return JSONResponse(
            content={"transfer": "basic", "objects": objects},
            media_type=LFS_JSON_MEDIA_TYPE,
        )

    @app.put("/repositories/{repository_id}.git/info/lfs/objects/{oid}")
    async def lfs_upload(
        repository_id: str,
        oid: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
        upload_session_id: Annotated[
            str | None,
            Header(alias=_LFS_UPLOAD_SESSION_HEADER),
        ] = None,
    ) -> Response:
        authenticated = dependencies.authenticate(
            authorization,
            repository_id=repository_id,
            protocol=RepositoryCredentialProtocol.LFS_WRITE,
        )
        if not isinstance(authenticated.claims, RepositoryCredentialClaims):
            raise RepositoryCredentialRejectedError(
                "provision credentials cannot upload Git LFS objects"
            )
        policy = _lfs_policy(dependencies, authenticated)
        if len(oid) != 64 or any(
            character not in "0123456789abcdef" for character in oid
        ):
            raise RepositoryTransportRequestError("Git LFS oid is invalid")
        content_length = request.headers.get("content-length")
        if content_length is None or not content_length.isdigit():
            raise HTTPException(status_code=411, detail="Content-Length is required")
        expected_size = int(content_length)
        if upload_session_id is None:
            raise RepositoryTransportRequestError(
                "Git LFS upload requires the exact Batch API upload session"
            )
        with dependencies.repository_provider.read() as scope:
            upload_session = scope.repositories.git_lfs.get_upload_session(
                upload_session_id
            )
        if (
            upload_session is None
            or upload_session.status.value != "reserved"
            or upload_session.binding_id != policy.binding_id
            or upload_session.binding_version != policy.binding_version
            or upload_session.repository_id != repository_id
            or upload_session.session_id != authenticated.claims.session_id
            or upload_session.agent_member_id
            != authenticated.claims.agent_member_id
            or upload_session.workspace_generation
            != authenticated.claims.workspace_generation
            or upload_session.credential_id != authenticated.claims.credential_id
            or upload_session.oid != oid
            or upload_session.declared_size != expected_size
            or datetime.fromisoformat(upload_session.expires_at)
            <= datetime.now(tz=UTC)
        ):
            raise GitLfsRepositoryError(
                "Git LFS upload session is missing, expired, terminal, or scope-drifted"
            )
        store = DurableLfsObjectStore(dependencies.roots())
        incoming = store.repository_root(repository_id) / "incoming"
        incoming.mkdir(mode=0o700, exist_ok=True)
        with tempfile.NamedTemporaryFile(dir=incoming, delete=False) as stream:
            incoming_path = Path(stream.name)
            observed_size = 0
            async for chunk in request.stream():
                stream.write(chunk)
                observed_size += len(chunk)
                if observed_size > expected_size:
                    break
            stream.flush()
            os.fsync(stream.fileno())
        if observed_size != expected_size:
            incoming_path.unlink()
            with dependencies.repository_provider.write() as scope:
                scope.repositories.git_lfs.abort_upload(
                    upload_session_id=upload_session.upload_session_id,
                    completed_at=datetime.now(tz=UTC).isoformat(),
                )
            raise RepositoryTransportRequestError(
                "Git LFS upload byte count does not match Content-Length"
            )
        try:
            store.promote_incoming(
                repository_id,
                oid,
                size=expected_size,
                incoming_path=incoming_path,
            )
        except Exception:
            if incoming_path.exists():
                incoming_path.unlink()
            with dependencies.repository_provider.write() as scope:
                scope.repositories.git_lfs.abort_upload(
                    upload_session_id=upload_session.upload_session_id,
                    completed_at=datetime.now(tz=UTC).isoformat(),
                )
            raise
        with dependencies.repository_provider.write() as scope:
            scope.repositories.git_lfs.commit_upload(
                upload_session=upload_session,
                completed_at=datetime.now(tz=UTC).isoformat(),
            )
        return Response(status_code=200)

    @app.post("/repositories/{repository_id}.git/info/lfs/objects/{oid}/verify")
    def lfs_verify(
        repository_id: str,
        oid: str,
        payload: LfsVerifyRequest,
        authorization: Annotated[str | None, Header()] = None,
        upload_session_id: Annotated[
            str | None,
            Header(alias=_LFS_UPLOAD_SESSION_HEADER),
        ] = None,
    ) -> Response:
        authenticated = dependencies.authenticate(
            authorization,
            repository_id=repository_id,
            protocol=RepositoryCredentialProtocol.LFS_WRITE,
        )
        if not isinstance(authenticated.claims, RepositoryCredentialClaims):
            raise RepositoryCredentialRejectedError(
                "provision credentials cannot verify Git LFS uploads"
            )
        policy = _lfs_policy(dependencies, authenticated)
        if oid != payload.oid:
            raise RepositoryTransportRequestError(
                "Git LFS verify path and payload oid differ"
            )
        DurableLfsObjectStore(dependencies.roots()).verify(
            repository_id,
            oid,
            size=payload.size,
        )
        if upload_session_id is None:
            raise RepositoryTransportRequestError(
                "Git LFS verify requires the exact Batch API upload session"
            )
        with dependencies.repository_provider.read() as scope:
            upload_session = scope.repositories.git_lfs.get_upload_session(
                upload_session_id
            )
            metadata_exists = scope.repositories.git_lfs.has_object_metadata(
                policy=policy,
                oid=oid,
                size_bytes=payload.size,
            )
        if (
            upload_session is None
            or upload_session.status.value != "committed"
            or upload_session.binding_id != policy.binding_id
            or upload_session.binding_version != policy.binding_version
            or upload_session.repository_id != repository_id
            or upload_session.session_id != authenticated.claims.session_id
            or upload_session.agent_member_id
            != authenticated.claims.agent_member_id
            or upload_session.workspace_generation
            != authenticated.claims.workspace_generation
            or upload_session.credential_id != authenticated.claims.credential_id
            or upload_session.oid != oid
            or upload_session.declared_size != payload.size
            or not metadata_exists
        ):
            raise GitLfsRepositoryError(
                "Git LFS verify has no exact committed upload receipt"
            )
        return Response(status_code=200)

    @app.get("/repositories/{repository_id}.git/info/lfs/objects/{oid}")
    def lfs_download(
        repository_id: str,
        oid: str,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        authenticated = dependencies.authenticate(
            authorization,
            repository_id=repository_id,
            protocol=RepositoryCredentialProtocol.LFS_READ,
        )
        policy = _lfs_policy(dependencies, authenticated)
        if len(oid) != 64 or any(
            character not in "0123456789abcdef" for character in oid
        ):
            raise RepositoryTransportRequestError("Git LFS oid is invalid")
        store = DurableLfsObjectStore(dependencies.roots())
        path = store.object_path(repository_id, oid)
        if not path.is_file():
            return _lfs_error(404, "Git LFS object does not exist")
        with dependencies.repository_provider.read() as scope:
            if not scope.repositories.git_lfs.has_object_metadata(
                policy=policy,
                oid=oid,
                size_bytes=path.stat().st_size,
            ):
                return _lfs_error(404, "Git LFS object does not exist")
        store.verify(repository_id, oid, size=path.stat().st_size)
        observed_at = datetime.now(tz=UTC).isoformat()
        receipt = _lfs_read_receipt(
            authenticated=authenticated,
            oid=oid,
            size=path.stat().st_size,
            observed_at=observed_at,
        )
        with dependencies.repository_provider.write() as scope:
            scope.repositories.git_lfs.add_object_read_receipt(receipt)
            if isinstance(authenticated.claims, RepositoryCredentialClaims):
                scope.repositories.git_lfs.link_workspace_object(
                    policy=policy,
                    claims=authenticated.claims,
                    oid=oid,
                    observed_via="download",
                    created_at=observed_at,
                )
        return FileResponse(path, media_type="application/octet-stream")

    @app.api_route(
        "/repositories/{repository_id}.git/{git_path:path}",
        methods=["GET", "POST"],
    )
    async def git_smart_http(
        repository_id: str,
        git_path: str,
        request: Request,
        authorization: Annotated[str | None, Header()] = None,
    ) -> Response:
        protocol = _git_protocol_for_request(
            method=request.method,
            git_path=git_path,
            service_query=request.query_params.get("service"),
        )
        authenticated = dependencies.authenticate(
            authorization,
            repository_id=repository_id,
            protocol=protocol,
        )
        environment = _git_environment(
            dependencies,
            authenticated,
            request=request,
            git_path=git_path,
        )
        return await _git_backend_response(
            executable=dependencies.settings.git_http_backend,
            environment=environment,
            repository_id=repository_id,
            request=request,
        )

    return app


__all__ = [
    "AuthenticatedRepositoryRequest",
    "LFS_JSON_MEDIA_TYPE",
    "LfsBatchRequest",
    "LfsObjectRequest",
    "LfsVerifyRequest",
    "RepositoryTransportDependencies",
    "RepositoryTransportError",
    "RepositoryTransportRequestError",
    "create_repository_transport_app",
]
